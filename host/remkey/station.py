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
from typing import Optional

from . import protocol as P
from .config import StationConfig, load_station
from .serial_link import FakeLink, KeyerLink, SerialLink

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


class StationService:
    def __init__(self, cfg: StationConfig, link: KeyerLink):
        self.cfg = cfg
        self.link = link
        self.session: Optional[Session] = None
        self.ptt = False
        self.wpm = 18
        self.server: Optional[asyncio.base_events.Server] = None
        self._hb_task: Optional[asyncio.Task] = None
        link.set_handler(self._on_keyer_line)

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
            await asyncio.sleep(1.0)

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
        why = "client disconnected"
        try:
            while True:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=self.cfg.heartbeat_timeout_s)
                except asyncio.TimeoutError:
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
        else:
            await sess.send({"t": "err", "msg": f"unknown type {t!r}"})


async def _amain(cfg: StationConfig, dry_run: bool) -> None:
    loop = asyncio.get_running_loop()
    link: KeyerLink = FakeLink() if dry_run else SerialLink(cfg.keyer_port, cfg.keyer_baud, loop)
    svc = StationService(cfg, link)
    await svc.start()
    try:
        await asyncio.Event().wait()
    finally:
        await svc.stop()
        link.close()


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
