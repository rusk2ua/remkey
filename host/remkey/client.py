"""remkey client: runs on your Mac with the travel keyer plugged in.

    python -m remkey.client --config client.toml

Paddle characters from the travel Nano and anything you type are forwarded to
the station. The PTT button on the Nano (or Ctrl-T) toggles the rig's PTT.

Hotkeys (terminal):
    Ctrl-T  toggle PTT            Esc     abort queued text / tune
    Ctrl-U  tune carrier (needs PTT on; press Esc to stop early)
    Ctrl-F  faster (+1 WPM)       Ctrl-S  slower (-1 WPM)
    Ctrl-G  status / RTT          Ctrl-P  tower PA power, temperatures, ref lock
    Ctrl-K  transverter (Kuhne) status and firmware version
    Ctrl-Q or Ctrl-C  quit
    Any other printable key is sent as CW; Enter sends a space.
    Type <SK>, <AR>, <BT>, <KN> for prosigns.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
import time
from typing import Optional

from . import protocol as P
from .config import ClientConfig, load_client
from .serial_link import FakeLink, KeyerLink, SerialLink

log = logging.getLogger("remkey.client")

CTRL = {chr(i + 1): chr(ord("A") + i) for i in range(26)}  # '\x14' -> 'T'
ESC = "\x1b"

HOTKEY_HELP = (
    "Ctrl-T PTT | Ctrl-U tune | Esc abort | Ctrl-F/Ctrl-S speed | Ctrl-G status | Ctrl-P PA | Ctrl-K XV | Ctrl-Q quit"
)


class Console:
    """Prints CW inline and events on their own lines."""

    def __init__(self, out=None):
        self.out = out or sys.stdout
        self.col = 0

    def cw(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()
        self.col += len(text)

    def event(self, msg: str) -> None:
        if self.col:
            self.out.write("\n")
            self.col = 0
        self.out.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.out.flush()


class ClientApp:
    def __init__(self, cfg: ClientConfig, link: KeyerLink, console: Optional[Console] = None):
        self.cfg = cfg
        self.link = link
        self.console = console or Console()
        self.wpm = cfg.wpm
        self.station_ptt = False
        self.connected = False
        self.rtt_ms: Optional[float] = None
        self.quit = asyncio.Event()
        self._writer: Optional[asyncio.StreamWriter] = None
        self._typed = ""     # buffer for <PROSIGN> typing
        self.tlm: Optional[dict] = None
        self._tx_peak: Optional[tuple] = None   # (watts or None, mV) peak during this PTT
        link.set_handler(self.on_keyer_line)

    # ------------------------------------------------------------ outbound
    def _send(self, msg: dict) -> bool:
        if not self.connected or self._writer is None:
            return False
        try:
            self._writer.write(P.encode(msg))
            return True
        except (ConnectionError, RuntimeError):
            return False

    def send_cw(self, text: str, echo_local: bool = False) -> None:
        text = P.sanitize_cw(text)
        if not text:
            return
        if not self._send({"t": "cw", "text": text}):
            self.console.event(f"NOT SENT (no station link): {text!r}")
            return
        if echo_local:
            self.link.send("T:" + text)
        self.console.cw(text)

    def toggle_ptt(self) -> None:
        want = not self.station_ptt
        if not self._send({"t": "ptt", "on": want}):
            self.console.event("PTT ignored: no station link")
            return
        self.console.event(f"PTT -> {'ON' if want else 'off'} (requested)")

    def set_wpm(self, v: int, tell_keyer: bool = True) -> None:
        self.wpm = max(5, min(50, v))
        if tell_keyer:
            self.link.send(f"W:{self.wpm}")
        self._send({"t": "wpm", "v": self.wpm})
        self.console.event(f"{self.wpm} WPM")

    def abort(self) -> None:
        self.link.send("X")
        self._send({"t": "abort"})
        self.console.event("abort")

    def tune(self) -> None:
        if not self.station_ptt:
            self.console.event("tune needs PTT on (Ctrl-T or the PTT button first)")
            return
        if self._send({"t": "tune", "ms": self.cfg.tune_ms}):
            self.console.event(f"tune {self.cfg.tune_ms / 1000:.1f} s (Esc to stop)")

    def status(self) -> None:
        rtt = f"{self.rtt_ms:.0f} ms" if self.rtt_ms is not None else "n/a"
        link = "connected" if self.connected else "DISCONNECTED"
        self.console.event(
            f"station {link} | PTT {'ON' if self.station_ptt else 'off'} | {self.wpm} WPM | RTT {rtt}"
        )
        if self.tlm:
            self.console.event(self.tlm_line(self.tlm))

    @staticmethod
    def _power(w, mv) -> str:
        return f"{w:.1f} W" if isinstance(w, (int, float)) else f"{mv} mV"

    def tlm_line(self, m: dict) -> str:
        names = m.get("temp_names") or ["probe 1", "probe 2"]
        parts = [
            f"PA peak {self._power(m.get('pa_pk_w'), m.get('pa_pk_mv'))}"
            f" avg {self._power(m.get('pa_avg_w'), m.get('pa_avg_mv'))}",
            f"XV {self._power(m.get('xv_pk_w'), m.get('xv_pk_mv'))}",
        ]
        for name, temp in zip(names, (m.get("temp_c"), m.get("temp2_c"))):
            if isinstance(temp, (int, float)):
                parts.append(f"{name} {temp:.1f} C")
        lock = m.get("lock")
        if lock is not None:
            parts.append("ref locked" if lock else "ref UNLOCKED")
        parts.append(f"link loss {m.get('loss_pct', 0)}%")
        if m.get("stale"):
            parts.append(f"STALE ({m.get('age_s')} s old)")
        return "tower: " + " | ".join(parts)

    def show_tlm(self) -> None:
        if not self._send({"t": "tlmq"}):
            if self.tlm:
                self.console.event(self.tlm_line(self.tlm) + " (cached)")
            else:
                self.console.event("no tower telemetry yet")

    # ------------------------------------------------------------ keyer events
    def on_keyer_line(self, line: str) -> None:
        if line.startswith("K:"):
            ch = line[2:]
            if self.connected:
                # paddle chars are already heard on the local sidetone: no echo
                self.send_cw(ch if ch else " ")
            else:
                self.console.event(f"paddle {ch!r} dropped: no station link")
        elif line == "B:P":
            self.toggle_ptt()
        elif line.startswith("W:"):
            try:
                self.set_wpm(int(line[2:]), tell_keyer=False)
            except ValueError:
                pass
        elif line.startswith("V:"):
            self.console.event(f"travel keyer: {line[2:]}")
        elif line.startswith("E:"):
            self.console.event(f"travel keyer error: {line}")

    # ------------------------------------------------------------ keyboard
    def on_key(self, ch: str) -> None:
        if ch == ESC:
            self._typed = ""
            self.abort()
            return
        if ch in CTRL and ch not in ("\r", "\n", "\t", "\x7f", "\x08"):
            key = CTRL[ch]
            if key == "T":
                self.toggle_ptt()
            elif key == "U":
                self.tune()
            elif key == "F":
                self.set_wpm(self.wpm + 1)
            elif key == "S":
                self.set_wpm(self.wpm - 1)
            elif key == "G":
                self.status()
            elif key == "P":
                self.show_tlm()
            elif key == "K":
                if not self._send({"t": "xvq"}):
                    self.console.event("transverter status needs the station link")
            elif key in ("Q", "C"):
                self.quit.set()
            return
        if ch in ("\r", "\n"):
            ch = " "
        if ch in ("\x7f", "\x08"):
            return  # can't unsend
        # hold <...> sequences until closed so prosigns go out as one unit
        if self._typed or ch == "<":
            self._typed += ch
            if ch == ">" or len(self._typed) > 5:
                text, self._typed = self._typed, ""
                self.send_cw(text, echo_local=self.cfg.echo_typed)
            return
        self.send_cw(ch, echo_local=self.cfg.echo_typed)

    # ------------------------------------------------------------ network
    async def _session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        hello = P.decode(await asyncio.wait_for(reader.readline(), timeout=10))
        if hello.get("t") == "err":
            raise ConnectionError(hello.get("msg"))
        if hello.get("t") != "hello":
            raise ConnectionError("unexpected greeting")
        writer.write(P.encode({"t": "auth", "mac": P.compute_mac(self.cfg.secret, hello["nonce"])}))
        await writer.drain()
        ok = P.decode(await asyncio.wait_for(reader.readline(), timeout=10))
        if ok.get("t") != "ok":
            raise ConnectionError(ok.get("msg", "auth rejected"))

        self._writer = writer
        self.connected = True
        self.console.event(f"connected to station {self.cfg.station_host}:{self.cfg.station_port}")
        self._send({"t": "wpm", "v": self.wpm})
        hb = asyncio.create_task(self._heartbeat())
        try:
            while not self.quit.is_set():
                line = await reader.readline()
                if not line:
                    raise ConnectionError("station closed the connection")
                self._on_station(P.decode(line))
        finally:
            hb.cancel()

    async def _heartbeat(self) -> None:
        while True:
            self._send({"t": "hb", "ts": time.monotonic()})
            if self._writer:
                try:
                    await self._writer.drain()
                except (ConnectionError, RuntimeError):
                    return
            await asyncio.sleep(self.cfg.heartbeat_s)

    def _on_station(self, msg: dict) -> None:
        t = msg.get("t")
        if t == "state":
            was = self.station_ptt
            self.station_ptt = bool(msg.get("ptt"))
            self.link.send(f"L:{1 if self.station_ptt else 0}")
            if was != self.station_ptt:
                self.console.event(f"STATION PTT {'ON' if self.station_ptt else 'off'}")
                if self.station_ptt:
                    self._tx_peak = None
                else:
                    self._report_tx()
        elif t == "hb":
            ts = msg.get("ts")
            if isinstance(ts, (int, float)):
                self.rtt_ms = (time.monotonic() - ts) * 1000
        elif t == "drained":
            pass
        elif t == "tlm":
            self.tlm = msg
            if self.station_ptt:
                w, mv = msg.get("pa_pk_w"), msg.get("pa_pk_mv", 0)
                if self._tx_peak is None or mv > self._tx_peak[1]:
                    self._tx_peak = (w, mv)
            if "age_s" in msg:          # reply to Ctrl-P
                self.console.event(self.tlm_line(msg))
        elif t == "xvstat":
            if msg.get("query"):
                if msg.get("version"):
                    self.console.event("transverter firmware: " + msg["version"].replace("\n", " / "))
                if msg.get("text"):
                    self.console.event(f"transverter status ({msg.get('age_s')} s old):")
                    for ln in msg["text"].splitlines():
                        self.console.event("   " + ln)
                else:
                    self.console.event("no transverter status received yet")
        elif t == "alert":
            mark = "!!" if msg.get("level") == "warn" else "--"
            self.console.event(f"{mark} {msg.get('msg')}")
        elif t == "wdog":
            self.console.event(f"SAFETY STOP: {msg.get('why')}")
        elif t in ("log", "err"):
            self.console.event(f"station: {msg.get('msg')}")

    def _report_tx(self) -> None:
        if self._tx_peak is not None:
            w, mv = self._tx_peak
            self.console.event(f"last TX: PA peak {self._power(w, mv)}")
        self._tx_peak = None

    def _on_disconnect(self) -> None:
        self.connected = False
        self._writer = None
        if self.station_ptt:
            self.console.event("link lost - station drops PTT on its own")
        self.station_ptt = False
        self.link.send("L:0")

    async def run(self) -> None:
        self.link.send(f"W:{self.wpm}")
        self.link.send(f"F:{self.cfg.sidetone_hz}")
        self.link.send("V")
        while not self.quit.is_set():
            writer = None
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.cfg.station_host, self.cfg.station_port, limit=P.MAX_LINE),
                    timeout=10,
                )
                sess = asyncio.create_task(self._session(reader, writer))
                quit_wait = asyncio.create_task(self.quit.wait())
                done, _ = await asyncio.wait({sess, quit_wait}, return_when=asyncio.FIRST_COMPLETED)
                quit_wait.cancel()
                if sess in done:
                    sess.result()   # re-raise the disconnect reason
                else:
                    if self.station_ptt:
                        self._send({"t": "ptt", "on": False})
                        await writer.drain()
                    sess.cancel()
            except (OSError, ConnectionError, asyncio.TimeoutError, ValueError) as exc:
                self.console.event(f"station link: {exc or type(exc).__name__}")
            finally:
                if writer is not None:
                    writer.close()
                self._on_disconnect()
            if not self.quit.is_set():
                try:
                    await asyncio.wait_for(self.quit.wait(), timeout=self.cfg.reconnect_s)
                except asyncio.TimeoutError:
                    pass


# ---------------------------------------------------------------- terminal
class RawTerminal:
    """Single-key input without echo; keeps output post-processing so print() works."""

    def __init__(self) -> None:
        import termios

        self.termios = termios
        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)

    def __enter__(self):
        t = self.termios
        attrs = t.tcgetattr(self.fd)
        attrs[0] &= ~(t.IXON | t.ICRNL)                   # iflag: let Ctrl-S/Q through, keep CR
        attrs[3] &= ~(t.ICANON | t.ECHO | t.ISIG | t.IEXTEN)  # lflag
        attrs[6][t.VMIN] = 1
        attrs[6][t.VTIME] = 0
        t.tcsetattr(self.fd, t.TCSANOW, attrs)
        return self

    def __exit__(self, *exc):
        self.termios.tcsetattr(self.fd, self.termios.TCSADRAIN, self.saved)


def _keyboard_thread(loop: asyncio.AbstractEventLoop, app: ClientApp) -> None:
    import os

    fd = sys.stdin.fileno()
    while not app.quit.is_set():
        try:
            data = os.read(fd, 32)
        except OSError:
            break
        if not data:
            break
        for ch in data.decode("utf-8", errors="ignore"):
            loop.call_soon_threadsafe(app.on_key, ch)


async def _amain(cfg: ClientConfig, dry_run: bool, keyboard: bool) -> None:
    loop = asyncio.get_running_loop()
    link: KeyerLink = FakeLink() if dry_run else SerialLink(cfg.keyer_port, cfg.keyer_baud, loop)
    app = ClientApp(cfg, link)
    app.console.event("remkey client - " + HOTKEY_HELP)
    if keyboard:
        threading.Thread(target=_keyboard_thread, args=(loop, app), daemon=True).start()
    try:
        await app.run()
    finally:
        link.send("L:0")
        link.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="remkey client")
    ap.add_argument("--config", default="client.toml")
    ap.add_argument("--dry-run", action="store_true", help="no travel Nano attached (keyboard CW only)")
    ap.add_argument("--no-keyboard", action="store_true", help="paddle only; don't capture the terminal")
    args = ap.parse_args(argv)
    cfg = load_client(args.config)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    keyboard = not args.no_keyboard and sys.stdin.isatty()
    if keyboard:
        try:
            term = RawTerminal()
        except Exception:  # noqa: BLE001  (Windows has no termios)
            keyboard = False
    if keyboard:
        with term:
            asyncio.run(_amain(cfg, args.dry_run, True))
    else:
        try:
            asyncio.run(_amain(cfg, args.dry_run, False))
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
