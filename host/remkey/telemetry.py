"""Tower telemetry: parse remtlm packets, apply calibration, track link health.

Packet (see firmware/remtlm/tlm_proto.h):
    $RT,<seq>,<pa_pk_mv>,<pa_avg_mv>,<xv_pk_mv>,<lock>,<temp_c10>,<uptime_s>,<call>*HH
"""

from __future__ import annotations

import bisect
import csv
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

TEMP_NONE = -32768


@dataclass
class Packet:
    seq: int
    pa_pk_mv: int
    pa_avg_mv: int
    xv_pk_mv: int
    lock: bool
    temp_c: Optional[float]
    uptime_s: int
    call: str


def xor_checksum(body: str) -> int:
    x = 0
    for ch in body.encode("ascii", errors="replace"):
        x ^= ch
    return x


def parse_packet(line: str) -> Optional[Packet]:
    """Return a Packet, or None if the line isn't a valid remtlm packet."""
    line = line.strip()
    if not line.startswith("$RT,") or len(line) < 8 or line[-3] != "*":
        return None
    body, given = line[1:-3], line[-2:]
    try:
        if xor_checksum(body) != int(given, 16):
            return None
        f = body.split(",")
        if len(f) != 9:
            return None
        temp_c10 = int(f[6])
        return Packet(
            seq=int(f[1]),
            pa_pk_mv=int(f[2]),
            pa_avg_mv=int(f[3]),
            xv_pk_mv=int(f[4]),
            lock=f[5] == "1",
            temp_c=None if temp_c10 == TEMP_NONE else temp_c10 / 10.0,
            uptime_s=int(f[7]),
            call=f[8],
        )
    except ValueError:
        return None


def format_packet(p: Packet) -> str:
    """Inverse of parse_packet (used by tests and the bench simulator)."""
    t = TEMP_NONE if p.temp_c is None else int(round(p.temp_c * 10))
    body = (f"RT,{p.seq},{p.pa_pk_mv},{p.pa_avg_mv},{p.xv_pk_mv},{1 if p.lock else 0},"
            f"{t},{p.uptime_s},{p.call}")
    return f"${body}*{xor_checksum(body):02X}"


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
              "xv_pk_mv", "lo_lock", "temp_c", "uptime_s"]

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
                p.xv_pk_mv, int(p.lock), "" if p.temp_c is None else p.temp_c, p.uptime_s,
            ])
