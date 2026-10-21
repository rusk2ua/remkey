"""Line-oriented serial link to a remkey Nano, bridged into asyncio."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Callable, Optional, Protocol

log = logging.getLogger(__name__)


class KeyerLink(Protocol):
    """What the service and client need from a keyer. FakeLink in tests implements it too."""

    def send(self, line: str) -> None: ...
    def set_handler(self, handler: Callable[[str], None]) -> None: ...
    def close(self) -> None: ...


class SerialLink:
    """Talks to the Nano over USB serial.

    A background thread reads lines and hands them to the handler on the asyncio
    loop (via call_soon_threadsafe). Writes are synchronous and lock-protected;
    they are a few bytes at 115200 baud.
    """

    def __init__(self, port: str, baud: int = 115200, loop: Optional[asyncio.AbstractEventLoop] = None):
        import serial  # pyserial; imported here so tests don't need it

        self.port = port
        self._loop = loop or asyncio.get_event_loop()
        self._handler: Callable[[str], None] = lambda line: None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ser = serial.Serial(port, baud, timeout=0.2)
        # Opening the port resets a Nano (DTR). Give the bootloader time to hand over.
        time.sleep(2.0)
        self._ser.reset_input_buffer()
        self._thread = threading.Thread(target=self._reader, name=f"keyer-{port}", daemon=True)
        self._thread.start()

    def set_handler(self, handler: Callable[[str], None]) -> None:
        self._handler = handler

    def send(self, line: str) -> None:
        data = (line + "\n").encode("ascii", errors="ignore")
        with self._lock:
            try:
                self._ser.write(data)
            except Exception as exc:  # noqa: BLE001
                log.error("keyer write failed on %s: %s", self.port, exc)

    def _reader(self) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = self._ser.read(64)
            except Exception as exc:  # noqa: BLE001
                log.error("keyer read failed on %s: %s", self.port, exc)
                time.sleep(1.0)
                continue
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("ascii", errors="replace").rstrip("\r")
                if line:
                    self._loop.call_soon_threadsafe(self._handler, line)

    def close(self) -> None:
        self._stop.set()
        try:
            self._ser.close()
        except Exception:  # noqa: BLE001
            pass


class FakeLink:
    """In-memory keyer for tests and --dry-run. Records everything sent."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._handler: Callable[[str], None] = lambda line: None

    def set_handler(self, handler: Callable[[str], None]) -> None:
        self._handler = handler

    def send(self, line: str) -> None:
        self.sent.append(line)
        if line != "H":
            log.info("[dry-run keyer] %s", line)
        if line == "V":
            self._handler("V:remkey fake")

    def inject(self, line: str) -> None:
        """Pretend the keyer sent us a line."""
        self._handler(line)

    def close(self) -> None:
        pass
