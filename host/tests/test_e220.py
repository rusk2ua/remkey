"""remkey.e220 against a simulated E220 module on a pseudo-terminal."""

import os
import sys
import threading

import pytest

from remkey import e220

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="needs a pty")

FACTORY = bytes([0x00, 0x00, 0x62, 0x00, 0x12, 0x03, 0x00, 0x00])   # 9600 8N1, 2.4k, 22 dBm, ch 18


class FakeE220(threading.Thread):
    """Answers C1 00 08 (read) and C0 00 08 + 8 bytes (write) like the module in mode 3."""

    def __init__(self, regs=FACTORY, mute=False):
        super().__init__(daemon=True)
        self.master, slave = os.openpty()
        self.port = os.ttyname(slave)
        self.regs = bytearray(regs)
        self.mute = mute
        self.writes = 0
        self.start()

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = os.read(self.master, n - len(buf))
            if not chunk:
                raise OSError
            buf += chunk
        return buf

    def run(self):
        try:
            while True:
                cmd = self._read(3)
                if cmd == bytes([0xC0, 0x00, 0x08]):
                    self.regs[:] = self._read(8)
                    self.regs[6:8] = b"\x00\x00"           # key bytes read back as zero
                    self.writes += 1
                elif cmd != bytes([0xC1, 0x00, 0x08]):
                    continue
                if not self.mute:
                    os.write(self.master, bytes([0xC1, 0x00, 0x08]) + bytes(self.regs))
        except OSError:
            pass


def test_encode_matches_remtlm_settings():
    regs = e220.encode(0, 0, 77, 9.6, 17)
    assert regs.hex(" ") == "00 00 64 01 4d 03 00 00"
    d = e220.decode(regs)
    assert (d["channel"], d["freq_mhz"], d["air_kbps"], d["power_dbm"]) == (77, 927.125, 9.6, 17)
    assert d["uart"] == "9600 8N1" and not d["fixed_mode"] and not d["lbt"] and not d["rssi_byte"]
    assert d["subpacket_bytes"] == 200 and d["wor_ms"] == 2000
    with pytest.raises(ValueError):
        e220.encode(0, 0, 81, 9.6, 17)


def test_read_only(capsys):
    m = FakeE220()
    assert e220.main(["--port", m.port]) == 0
    out = capsys.readouterr().out
    assert "channel    18  (868.125 MHz)" in out and m.writes == 0


def test_write_and_verify_then_idempotent(capsys):
    m = FakeE220()
    assert e220.main(["--port", m.port, "--write"]) == 0
    assert bytes(m.regs[:6]).hex(" ") == "00 00 64 01 4d 03"
    assert "written and verified" in capsys.readouterr().out
    assert e220.main(["--port", m.port, "--write"]) == 0
    assert "already set" in capsys.readouterr().out and m.writes == 1


def test_no_reply_gives_wiring_hint(capsys):
    m = FakeE220(mute=True)
    assert e220.main(["--port", m.port]) == 1
    assert "M0 and M1 tied HIGH" in capsys.readouterr().err
