"""remkey station service: runs on the shack PC next to N1MM+.

    python -m remkey.station --config station.toml

Accepts one authenticated client at a time and drives the station Nano:
text -> "T:", PTT -> "P:", speed -> "W:". If the client goes quiet or
disconnects, PTT is dropped and queued text is flushed. Independently, the
Nano's own watchdog drops PTT if this service stops talking to it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from . import protocol as P
from .config import StationConfig, load_station
from .serial_link import FakeLink, KeyerLink, SerialLink
from .telemetry import Calibration, CsvLog, LinkStats, Packet, ReplyAssembler, ReplyPart, parse_any

log = logging.getLogger("remkey.station")


class Session:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.peer = writer.get_extra_info("peername")

    async def send(self, msg: dict) -> None:
        try:
            self.writer.write(P.encode(msg))
            await self.writer.drain()
        except (ConnectionError, RuntimeError):
            pass

    def send_nowait(self, msg: dict) -> None:
        try:
            self.writer.write(P.encode(msg))
        except (ConnectionError, RuntimeError):
            pass


class TelemetryHub:
    """Turns remtlm packets from the base Nano into calibrated readings and alerts."""

    def __init__(self, cfg: StationConfig, notify):
        self.cfg = cfg
        self.notify = notify                 # callable(dict): send to the client if connected
        self.pa_cal = Calibration(cfg.pa_cal)
        self.xv_cal = Calibration(cfg.xv_cal)
        self.stats = LinkStats()
        self.csv = CsvLog(cfg.tlm_csv) if cfg.tlm_csv else None
        self.latest: dict | None = None
        self.replies = ReplyAssembler()
        self.xv_replies: dict[str, dict] = {}     # "s"/"v" -> {"text", "time"}
        self.lock_ok = True
        self.hot = [False, False]
        self.stale = True
        names = list(cfg.temp_names) + ["probe 1", "probe 2"]
        self.temp_names = [str(names[0]), str(names[1])]

    def on_line(self, line: str) -> None:
        p = parse_any(line)
        if isinstance(p, ReplyPart):
            self._on_reply(p)
            return
        if not isinstance(p, Packet):
            if line.startswith(("V:", "C:")):
                log.info("telemetry base: %s", line)
            elif line.startswith("E:"):
                log.warning("telemetry base: %s", line)
            return
        self.stats.update(p)
        pa_pk_w = self.pa_cal.watts(p.pa_pk_mv)
        pa_avg_w = self.pa_cal.watts(p.pa_avg_mv)
        if self.csv:
            try:
                self.csv.write(p, pa_pk_w, pa_avg_w)
            except OSError as exc:
                log.warning("telemetry CSV: %s", exc)
        self.latest = {
            "t": "tlm",
            "seq": p.seq,
            "pa_pk_mv": p.pa_pk_mv,
            "pa_avg_mv": p.pa_avg_mv,
            "pa_pk_w": pa_pk_w,
            "pa_avg_w": pa_avg_w,
            "xv_pk_mv": p.xv_pk_mv,
            "xv_pk_w": self.xv_cal.watts(p.xv_pk_mv),
            "lock": p.lock,
            "temp_c": p.temp_c,
            "temp2_c": p.temp2_c,
            "temp_names": self.temp_names,
            "uptime_s": p.uptime_s,
            "loss_pct": round(self.stats.loss_pct_5min(), 1),
        }
        if self.stale:
            self.stale = False
            self._alert("ok", "tower telemetry link up")
        if p.lock is not None and p.lock != self.lock_ok:
            self.lock_ok = p.lock
            self._alert("ok" if p.lock else "warn",
                        "10 MHz reference locked" if p.lock else "10 MHz reference UNLOCKED")
        for i, (t, warn) in enumerate(((p.temp_c, self.cfg.temp_warn_c),
                                       (p.temp2_c, self.cfg.temp2_warn_c))):
            if t is None:
                continue
            name = self.temp_names[i]
            if not self.hot[i] and t >= warn:
                self.hot[i] = True
                self._alert("warn", f"{name} HOT: {t:.1f} C")
            elif self.hot[i] and t < warn - 3:
                self.hot[i] = False
                self._alert("ok", f"{name} back to {t:.1f} C")
        self.notify(self.latest)

    def _on_reply(self, rp: ReplyPart) -> None:
        done = self.replies.add(rp)
        if done is None:
            return
        cmd, text = done
        self.xv_replies[cmd] = {"text": text, "time": time.time()}
        log.info("transverter '%s' reply: %s", cmd, text.replace("\n", " | "))
        self.notify(self.xv_message(cmd))

    def xv_message(self, cmd: str) -> dict:
        r = self.xv_replies.get(cmd)
        if r is None:
            return {"t": "xvstat", "cmd": cmd, "text": None, "age_s": None}
        return {"t": "xvstat", "cmd": cmd, "text": r["text"], "age_s": round(time.time() - r["time"])}

    def check_stale(self) -> None:
        age = self.stats.age_s()
        if not self.stale and (age is None or age > self.cfg.tlm_stale_s):
            self.stale = True
            self._alert("warn", f"tower telemetry lost (no packet for {self.cfg.tlm_stale_s:.0f} s)")

    def snapshot(self) -> dict | None:
        if self.latest is None:
            return None
        snap = dict(self.latest)
        snap["age_s"] = round(self.stats.age_s() or 0.0, 1)
        snap["stale"] = self.stale
        return snap

    def _alert(self, level: str, msg: str) -> None:
        (log.warning if level == "warn" else log.info)("telemetry: %s", msg)
        self.notify({"t": "alert", "level": level, "msg": msg})


class StationService:
    def __init__(self, cfg: StationConfig, link: KeyerLink, tlm_link: KeyerLink | None = None):
        self.cfg = cfg
        self.link = link
        self.tlm_link = tlm_link
        self.tlm = TelemetryHub(cfg, self._notify) if tlm_link is not None else None
        self.session: Session | None = None
        self.ptt = False
        self.wpm = 18
        self.server: asyncio.base_events.Server | None = None
        self._hb_task: asyncio.Task | None = None
        link.set_handler(self._on_keyer_line)
        if tlm_link is not None:
            tlm_link.set_handler(self.tlm.on_line)

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self.link.send("G:1")          # make sure the Nano watchdog is armed
        self.link.send("P:0")
        self.link.send("X")
        self.link.send("V")
        self.server = await asyncio.start_server(
            self._handle_client, self.cfg.listen_host, self.cfg.listen_port, limit=P.MAX_LINE
        )
        self._hb_task = asyncio.create_task(self._keyer_heartbeat())
        addrs = ", ".join(str(s.getsockname()) for s in self.server.sockets)
        log.info("listening on %s", addrs)

    @property
    def port(self) -> int:
        assert self.server is not None
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self._safe_off("service stopping")
        if self._hb_task:
            self._hb_task.cancel()
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def _keyer_heartbeat(self) -> None:
        while True:
            self.link.send("H")
            if self.tlm:
                self.tlm.check_stale()
            await asyncio.sleep(1.0)

    def _notify(self, msg: dict) -> None:
        if self.session:
            self.session.send_nowait(msg)

    # ------------------------------------------------------------ safety
    def _safe_off(self, why: str) -> None:
        if self.ptt:
            log.warning("PTT off: %s", why)
        self.link.send("X")
        self.link.send("P:0")
        self.ptt = False

    # ------------------------------------------------------------ keyer events
    def _on_keyer_line(self, line: str) -> None:
        s = self.session
        if line == "D":
            if s:
                s.send_nowait({"t": "drained"})
        elif line.startswith("!:"):
            log.warning("keyer watchdog: %s", line)
            self.ptt = False
            if s:
                s.send_nowait({"t": "wdog", "why": "station keyer watchdog"})
                s.send_nowait(self._state())
        elif line.startswith("K:"):
            # someone is using a paddle plugged into the station Nano
            log.info("station paddle: %r", line[2:])
        elif line.startswith("V:"):
            log.info("keyer: %s", line[2:])
        elif line.startswith("E:"):
            log.warning("keyer error: %s", line)
            if s:
                s.send_nowait({"t": "log", "msg": f"keyer {line}"})
        else:
            log.debug("keyer: %s", line)

    def _state(self) -> dict:
        return {"t": "state", "ptt": self.ptt, "wpm": self.wpm}

    # ------------------------------------------------------------ clients
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        sess = Session(reader, writer)
        if self.session is not None:
            log.warning("rejecting %s: another client is connected", sess.peer)
            await sess.send({"t": "err", "msg": "busy: another client is connected"})
            writer.close()
            return

        nonce = P.make_nonce()
        await sess.send({"t": "hello", "v": P.PROTOCOL_VERSION, "nonce": nonce})
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            msg = P.decode(line)
        except Exception:  # noqa: BLE001  (timeout, bad JSON, oversize)
            log.warning("handshake failed from %s", sess.peer)
            writer.close()
            return
        if msg.get("t") != "auth" or not P.verify_mac(self.cfg.secret, nonce, msg.get("mac")):
            log.warning("bad auth from %s", sess.peer)
            await sess.send({"t": "err", "msg": "auth failed"})
            writer.close()
            return
        if self.session is not None:          # raced with another client during handshake
            await sess.send({"t": "err", "msg": "busy: another client is connected"})
            writer.close()
            return

        self.session = sess
        log.info("client connected: %s", sess.peer)
        await sess.send({"t": "ok"})
        await sess.send(self._state())
        if self.tlm:
            snap = self.tlm.snapshot()
            if snap:
                await sess.send(snap)
        why = "client disconnected"
        try:
            while True:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=self.cfg.heartbeat_timeout_s)
                except TimeoutError:
                    why = "heartbeat lost"
                    await sess.send({"t": "wdog", "why": "station lost heartbeat"})
                    break
                if not line:
                    break
                try:
                    msg = P.decode(line)
                except ValueError:
                    await sess.send({"t": "err", "msg": "bad message"})
                    continue
                await self._dispatch(sess, msg)
        except (ConnectionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError):
            why = "connection error"
        finally:
            self._safe_off(why)
            self.session = None
            log.info("client gone (%s): %s", why, sess.peer)
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def _dispatch(self, sess: Session, msg: dict) -> None:
        t = msg.get("t")
        if t == "hb":
            await sess.send({"t": "hb", "ts": msg.get("ts")})
        elif t == "cw":
            text = P.sanitize_cw(str(msg.get("text", "")), self.cfg.max_text_chars)
            for chunk in P.chunk_for_keyer(text):
                self.link.send("T:" + chunk)
        elif t == "ptt":
            on = bool(msg.get("on"))
            self.link.send("P:1" if on else "P:0")
            if not on:
                self.link.send("X")
            self.ptt = on
            log.info("PTT %s", "ON" if on else "off")
            await sess.send(self._state())
        elif t == "wpm":
            try:
                v = max(5, min(50, int(msg.get("v"))))
            except (TypeError, ValueError):
                return
            self.wpm = v
            self.link.send(f"W:{min(50, v + self.cfg.wpm_offset)}")
            await sess.send(self._state())
        elif t == "tune":
            try:
                ms = max(0, min(self.cfg.max_tune_ms, int(msg.get("ms"))))
            except (TypeError, ValueError):
                return
            if not self.ptt:
                await sess.send({"t": "log", "msg": "tune ignored: PTT is off"})
                return
            self.link.send(f"U:{ms}")
        elif t == "abort":
            self.link.send("X")
        elif t == "tlmq":
            snap = self.tlm.snapshot() if self.tlm else None
            await sess.send(snap or {"t": "log", "msg": "no tower telemetry"})
        elif t == "xvq":
            if not self.tlm:
                await sess.send({"t": "log", "msg": "no tower telemetry"})
            else:
                msg = self.tlm.xv_message("s")
                msg["version"] = (self.tlm.xv_replies.get("v") or {}).get("text")
                msg["query"] = True
                await sess.send(msg)
        else:
            await sess.send({"t": "err", "msg": f"unknown type {t!r}"})


async def _amain(cfg: StationConfig, dry_run: bool) -> None:
    loop = asyncio.get_running_loop()
    link: KeyerLink = FakeLink() if dry_run else SerialLink(cfg.keyer_port, cfg.keyer_baud, loop)
    tlm_link: KeyerLink | None = None
    if cfg.tlm_port and not dry_run:
        tlm_link = SerialLink(cfg.tlm_port, cfg.tlm_baud, loop)
    svc = StationService(cfg, link, tlm_link)
    await svc.start()
    try:
        await asyncio.Event().wait()
    finally:
        await svc.stop()
        link.close()
        if tlm_link:
            tlm_link.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="remkey station service")
    ap.add_argument("--config", default="station.toml")
    ap.add_argument("--dry-run", action="store_true", help="no Nano; log keyer commands only")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_station(args.config)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if cfg.log_file:
        handlers.append(logging.FileHandler(cfg.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=handlers,
    )
    try:
        asyncio.run(_amain(cfg, args.dry_run))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
