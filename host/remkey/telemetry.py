"""Tower telemetry: parse remtlm packets, apply calibration, track link health.

Packets (see firmware/remtlm/tlm_proto.h):
    $RT,<seq>,<pa_pk_mv>,<pa_avg_mv>,<xv_pk_mv>,<lock>,<t1_c10>,<t2_c10>,<uptime_s>,<call>*HH
    $RK,<id>,<cmd>,<part>,<total>,<text>,<call>*HH     transverter serial reply, in parts
"""

from __future__ import annotations

import bisect
import csv
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

TEMP_NONE = -32768
LOCK_DISABLED = 2


@dataclass
class Packet:
    seq: int
    pa_pk_mv: int
    pa_avg_mv: int
    xv_pk_mv: int
    lock: Optional[bool]          # None = lock monitoring disabled on the tower
    temp_c: Optional[float]       # probe 1
    temp2_c: Optional[float]      # probe 2
    uptime_s: int
    call: str


@dataclass
class ReplyPart:
    capture: int
    cmd: str
    part: int
    total: int
    text: str
    call: str


def xor_checksum(body: str) -> int:
    x = 0
    for ch in body.encode("ascii", errors="replace"):
        x ^= ch
    return x


def _checked_body(line: str) -> Optional[str]:
    line = line.strip()
    if len(line) < 8 or not line.startswith("$") or line[-3] != "*":
        return None
    body, given = line[1:-3], line[-2:]
    try:
        return body if xor_checksum(body) == int(given, 16) else None
    except ValueError:
        return None


def _temp(c10: str) -> Optional[float]:
    v = int(c10)
    return None if v == TEMP_NONE else v / 10.0


def parse_any(line: str):
    """Return a Packet, a ReplyPart, or None for anything else / bad checksum."""
    body = _checked_body(line)
    if body is None:
        return None
    try:
        if body.startswith("RT,"):
            f = body.split(",")
            if len(f) != 10:
                return None
            return Packet(
                seq=int(f[1]), pa_pk_mv=int(f[2]), pa_avg_mv=int(f[3]), xv_pk_mv=int(f[4]),
                lock=None if int(f[5]) == LOCK_DISABLED else f[5] == "1",
                temp_c=_temp(f[6]), temp2_c=_temp(f[7]), uptime_s=int(f[8]), call=f[9],
            )
        if body.startswith("RK,"):
            head = body.split(",", 5)            # RK,id,cmd,part,total,rest
            if len(head) != 6:
                return None
            text, _, call = head[5].rpartition(",")
            return ReplyPart(capture=int(head[1]), cmd=head[2], part=int(head[3]),
                             total=int(head[4]), text=text, call=call)
    except ValueError:
        return None
    return None


def parse_packet(line: str) -> Optional[Packet]:
    """Return a readings Packet, or None."""
    p = parse_any(line)
    return p if isinstance(p, Packet) else None


def _seal(body: str) -> str:
    return f"${body}*{xor_checksum(body):02X}"


def format_packet(p: Packet) -> str:
    """Inverse of parse_packet (used by tests and the bench simulator)."""
    t1 = TEMP_NONE if p.temp_c is None else int(round(p.temp_c * 10))
    t2 = TEMP_NONE if p.temp2_c is None else int(round(p.temp2_c * 10))
    lock = LOCK_DISABLED if p.lock is None else int(p.lock)
    return _seal(f"RT,{p.seq},{p.pa_pk_mv},{p.pa_avg_mv},{p.xv_pk_mv},{lock},"
                 f"{t1},{t2},{p.uptime_s},{p.call}")


def format_reply(capture: int, cmd: str, text: str, call: str = "K2UA", chunk: int = 48) -> list[str]:
    """Split a sanitised reply into $RK lines, as the tower does."""
    parts = [text[i:i + chunk] for i in range(0, len(text), chunk)] or [""]
    return [_seal(f"RK,{capture},{cmd},{i + 1},{len(parts)},{t},{call}") for i, t in enumerate(parts)]


class ReplyAssembler:
    """Collects $RK parts into whole transverter replies.

    Returns the full text (line breaks restored) when the last part of a capture
    arrives. If any part was lost, the reply is still returned with "[...]" where
    the missing text was, rather than silently dropping it.
    """

    def __init__(self) -> None:
        self._capture: Optional[int] = None
        self._parts: dict[int, str] = {}
        self._total = 0
        self._cmd = ""

    def add(self, rp: ReplyPart) -> Optional[tuple[str, str]]:
        if rp.capture != self._capture:
            self._capture, self._parts, self._total, self._cmd = rp.capture, {}, rp.total, rp.cmd
        self._parts[rp.part] = rp.text
        if rp.part != rp.total:
            return None
        text = "".join(self._parts.get(i, "[...]") for i in range(1, self._total + 1))
        self._capture = None
        return self._cmd, text.replace("|", "\n")


class Calibration:
    """Piecewise-linear mV -> watts from measured points [[mv, watts], ...].

    Detector outputs are not linear in power, so measure several points with a
    power meter (see the README) and list them. Below the first point the result
    is the first point's watts; above the last it extrapolates the last segment.
    An empty table means "no calibration": watts is None.
    """

    def __init__(self, points: Sequence[Sequence[float]]):
        pts = sorted((float(mv), float(w)) for mv, w in points)
        self.mv = [p[0] for p in pts]
        self.w = [p[1] for p in pts]

    def __bool__(self) -> bool:
        return len(self.mv) >= 2

    def watts(self, mv: float) -> Optional[float]:
        if not self:
            return None
        if mv <= self.mv[0]:
            return self.w[0]
        i = bisect.bisect_right(self.mv, mv)
        i = min(i, len(self.mv) - 1)
        x0, x1, y0, y1 = self.mv[i - 1], self.mv[i], self.w[i - 1], self.w[i]
        if x1 == x0:
            return y1
        return max(0.0, y0 + (mv - x0) * (y1 - y0) / (x1 - x0))


@dataclass
class LinkStats:
    """Counts packets and gaps in the sequence number."""

    received: int = 0
    lost: int = 0
    resets: int = 0
    last_seq: Optional[int] = None
    last_uptime: Optional[int] = None
    last_rx: Optional[float] = None
    recent: list = field(default_factory=list)   # (time, lost_before_this) for loss %

    def update(self, p: Packet, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        gap = 0
        if self.last_uptime is not None and p.uptime_s < self.last_uptime:
            self.resets += 1                       # tower rebooted: seq restarted
        elif self.last_seq is not None:
            gap = (p.seq - self.last_seq - 1) % 65536
            if gap > 1000:                         # nonsense jump: treat as resync
                gap = 0
        self.lost += gap
        self.received += 1
        self.last_seq, self.last_uptime, self.last_rx = p.seq, p.uptime_s, now
        self.recent.append((now, gap))
        cutoff = now - 300
        while self.recent and self.recent[0][0] < cutoff:
            self.recent.pop(0)

    def loss_pct_5min(self) -> float:
        got = len(self.recent)
        lost = sum(g for _, g in self.recent)
        return 100.0 * lost / (got + lost) if got + lost else 0.0

    def age_s(self, now: Optional[float] = None) -> Optional[float]:
        if self.last_rx is None:
            return None
        return (time.monotonic() if now is None else now) - self.last_rx


class CsvLog:
    """Appends one row per packet. Opens the file per write so it's safe to read live."""

    HEADER = ["time", "seq", "pa_pk_mv", "pa_avg_mv", "pa_pk_w", "pa_avg_w",
              "xv_pk_mv", "ref_lock", "temp1_c", "temp2_c", "uptime_s"]

    def __init__(self, path: str):
        self.path = Path(path)
        if not self.path.exists():
            with self.path.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(self.HEADER)

    def write(self, p: Packet, pa_pk_w: Optional[float], pa_avg_w: Optional[float]) -> None:
        with self.path.open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                time.strftime("%Y-%m-%d %H:%M:%S"), p.seq, p.pa_pk_mv, p.pa_avg_mv,
                "" if pa_pk_w is None else f"{pa_pk_w:.2f}",
                "" if pa_avg_w is None else f"{pa_avg_w:.2f}",
                p.xv_pk_mv, "" if p.lock is None else int(p.lock),
                "" if p.temp_c is None else p.temp_c,
                "" if p.temp2_c is None else p.temp2_c, p.uptime_s,
            ])
