"""Line-oriented serial link to a remkey Nano, bridged into asyncio."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger(__name__)


class KeyerLink(Protocol):
    """What the service and client need from a keyer. FakeLink in tests implements it too."""

    def send(self, line: str) -> None: ...
    def set_handler(self, handler: Callable[[str], None]) -> None: ...
    def close(self) -> None: ...


LOST = "#:LOST"     # synthetic lines the link reports itself (never sent by a Nano)
BACK = "#:BACK"


class SerialLink:
    """Talks to the Nano over USB serial.

    A background thread reads lines and hands them to the handler on the asyncio
    loop (via call_soon_threadsafe). Writes are synchronous and lock-protected;
    they are a few bytes at 115200 baud.

    If the port fails (USB unplugged), the handler gets LOST once, writes are
    dropped quietly, and the thread re-opens the port every second. When it is
    back, the handler gets BACK so the owner can re-send its settings.
    """

    def __init__(self, port: str, baud: int = 115200, loop: asyncio.AbstractEventLoop | None = None,
                 opener: Callable[..., object] | None = None, retry_s: float = 1.0,
                 boot_s: float = 2.0):
        if opener is None:
            import serial  # pyserial; imported here so tests don't need it

            opener = serial.Serial
        self.port = port
        self.baud = baud
        self._open = opener
        self._retry_s = retry_s
        self._boot_s = boot_s
        self._loop = loop or asyncio.get_event_loop()
        self._handler: Callable[[str], None] = lambda line: None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ser = self._connect()
        self.up = True
        self._thread = threading.Thread(target=self._reader, name=f"keyer-{port}", daemon=True)
        self._thread.start()

    def _connect(self):
        ser = self._open(self.port, self.baud, timeout=0.2)
        # Opening the port resets a Nano (DTR). Give the bootloader time to hand over.
        time.sleep(self._boot_s)
        ser.reset_input_buffer()
        return ser

    def set_handler(self, handler: Callable[[str], None]) -> None:
        self._handler = handler

    def _emit(self, line: str) -> None:
        self._loop.call_soon_threadsafe(self._handler, line)

    def send(self, line: str) -> None:
        if not self.up:
            return
        data = (line + "\n").encode("ascii", errors="ignore")
        with self._lock:
            try:
                self._ser.write(data)
            except Exception as exc:  # noqa: BLE001
                log.error("keyer write failed on %s: %s", self.port, exc)

    def _lost(self, exc: Exception) -> None:
        log.error("keyer on %s lost: %s", self.port, exc)
        with self._lock:
            self.up = False
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001
                pass
        self._emit(LOST)
        while not self._stop.wait(self._retry_s):
            try:
                ser = self._connect()
            except Exception:  # noqa: BLE001
                continue
            with self._lock:
                self._ser = ser
                self.up = True
            log.warning("keyer on %s is back", self.port)
            self._emit(BACK)
            return

    def _reader(self) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = self._ser.read(64)
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    return
                buf = b""
                self._lost(exc)
                continue
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("ascii", errors="replace").rstrip("\r")
                if line:
                    self._emit(line)

    def close(self) -> None:
        self._stop.set()
        try:
            self._ser.close()
        except Exception:  # noqa: BLE001
            pass


class FakeLink:
    """In-memory keyer for tests and --dry-run. Records everything sent.

    Emulates the station Nano's PTT reporting: P:1 reports "P:1"; P:0 reports
    "P:0" after the hang time (J:<ms>, default 2000; no CW is really queued);
    O reports "P:0" at once.
    """

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._handler: Callable[[str], None] = lambda line: None
        self.ptt = False
        self.hang_s = 2.0
        self._release: asyncio.TimerHandle | None = None

    def set_handler(self, handler: Callable[[str], None]) -> None:
        self._handler = handler

    def _report(self, line: str, delay: float = 0.0) -> asyncio.TimerHandle | None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._handler(line)
            return None
        return loop.call_later(delay, self._handler, line)

    def _cancel_release(self) -> None:
        if self._release is not None:
            self._release.cancel()
            self._release = None

    def _released(self) -> None:
        self._release = None
        self.ptt = False
        self._handler("P:0")

    def send(self, line: str) -> None:
        self.sent.append(line)
        if line != "H":
            log.info("[dry-run keyer] %s", line)
        if line == "V":
            self._handler("V:remkey fake")
        elif line.startswith("J:"):
            self.hang_s = int(line[2:]) / 1000.0
        elif line == "P:1":
            self._cancel_release()
            if not self.ptt:
                self.ptt = True
                self._report("P:1")
        elif line == "P:0":
            if self.ptt and self._release is None:
                try:
                    self._release = asyncio.get_running_loop().call_later(self.hang_s, self._released)
                except RuntimeError:
                    self._released()
        elif line == "O":
            self._cancel_release()
            if self.ptt:
                self.ptt = False
                self._report("P:0")

    def inject(self, line: str) -> None:
        """Pretend the keyer sent us a line."""
        self._handler(line)

    def unplug(self) -> None:
        """Pretend the USB cable was pulled: the Nano's outputs go dead."""
        self._cancel_release()
        self.ptt = False
        self._handler(LOST)

    def replug(self) -> None:
        self._handler(BACK)

    def close(self) -> None:
        pass
