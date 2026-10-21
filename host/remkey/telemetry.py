"""Tower telemetry: parse remtlm packets, apply calibration, track link health.

Packets (see firmware/remtlm/tlm_proto.h):
    $RT,<seq>,<pa_pk_mv>,<pa_avg_mv>,<xv_pk_mv>,<lock>,<t1_c10>,<t2_c10>,<uptime_s>,<call>*HH
    $RP,<seq>,<v_avg>,<v_min>,<v_max>,<i_avg>,<i_min>,<i_max>,<ok>,<call>*HH   supply (mV, mA)
    $RK,<id>,<cmd>,<part>,<total>,<text>,<call>*HH     transverter serial reply, in parts
"""

from __future__ import annotations

import bisect
import csv
import math
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

TEMP_NONE = -32768
LOCK_DISABLED = 2


@dataclass
class Packet:
    seq: int
    pa_pk_mv: int
    pa_avg_mv: int
    xv_pk_mv: int
    lock: bool | None          # None = lock monitoring disabled on the tower
    temp_c: float | None       # probe 1
    temp2_c: float | None      # probe 2
    uptime_s: int
    call: str


@dataclass
class PowerPacket:
    seq: int
    v_avg: float       # volts at the tower enclosure
    v_min: float
    v_max: float
    i_avg: float       # amps through the shunt
    i_min: float
    i_max: float
    ok: bool           # False: INA226 not answering, values are 0
    call: str

    def scaled(self, v_scale: float, i_scale: float) -> PowerPacket:
        return PowerPacket(self.seq, self.v_avg * v_scale, self.v_min * v_scale, self.v_max * v_scale,
                           self.i_avg * i_scale, self.i_min * i_scale, self.i_max * i_scale,
                           self.ok, self.call)


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


def _checked_body(line: str) -> str | None:
    line = line.strip()
    if len(line) < 8 or not line.startswith("$") or line[-3] != "*":
        return None
    body, given = line[1:-3], line[-2:]
    try:
        return body if xor_checksum(body) == int(given, 16) else None
    except ValueError:
        return None


def _temp(c10: str) -> float | None:
    v = int(c10)
    return None if v == TEMP_NONE else v / 10.0


def parse_any(line: str):
    """Return a Packet, PowerPacket, ReplyPart, or None for anything else / bad checksum."""
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
        if body.startswith("RP,"):
            f = body.split(",")
            if len(f) != 10:
                return None
            mv = [int(x) / 1000.0 for x in f[2:8]]
            return PowerPacket(seq=int(f[1]), v_avg=mv[0], v_min=mv[1], v_max=mv[2],
                               i_avg=mv[3], i_min=mv[4], i_max=mv[5], ok=f[8] == "1", call=f[9])
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


def parse_packet(line: str) -> Packet | None:
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


def format_power(p: PowerPacket) -> str:
    """Inverse of parse_any for $RP (used by tests)."""
    v = [round(x * 1000) for x in (p.v_avg, p.v_min, p.v_max, p.i_avg, p.i_min, p.i_max)]
    return _seal(f"RP,{p.seq},{v[0]},{v[1]},{v[2]},{v[3]},{v[4]},{v[5]},{int(p.ok)},{p.call}")


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
        self._capture: int | None = None
        self._parts: dict[int, str] = {}
        self._total = 0
        self._cmd = ""

    def add(self, rp: ReplyPart) -> tuple[str, str] | None:
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

    def watts(self, mv: float) -> float | None:
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


# Annealed copper, ohms per foot of one conductor at 20 C (standard AWG table, solid).
# Stranded wire runs about 2% higher. Copper rises 0.393% per degree C.
AWG_OHM_PER_FT = {8: 0.0006282, 10: 0.0009989, 12: 0.001588, 14: 0.002525}
COPPER_TEMPCO = 0.00393


def loop_resistance(awg: int, one_way_ft: float, temp_c: float = 20.0) -> float:
    """Expected resistance of the + and - conductors together (2 x one_way_ft)."""
    return AWG_OHM_PER_FT[awg] * 2 * one_way_ft * (1 + COPPER_TEMPCO * (temp_c - 20.0))


def gauge_match(r_ohm: float, one_way_ft: float, temp_c: float = 20.0) -> tuple[int, float, str]:
    """Closest AWG for a measured loop resistance, with a plain-language verdict."""
    best = min(AWG_OHM_PER_FT, key=lambda g: abs(loop_resistance(g, one_way_ft, temp_c) - r_ohm))
    exp = loop_resistance(best, one_way_ft, temp_c)
    ratio = r_ohm / exp if exp else 0
    if ratio > 1.25 and best == max(AWG_OHM_PER_FT):
        verdict = "higher than #14 copper would give: check connectors, crimps, fuse holder"
    elif ratio > 1.15:
        verdict = f"{(ratio - 1) * 100:.0f}% above #{best}: connectors, fuse and shunt add some"
    else:
        verdict = f"consistent with #{best}"
    return best, exp, verdict


class CableFit:
    """Least-squares fit of tower voltage against current: V = Vsource - R * I.

    Uses the per-interval averages, which obey the same straight line as the
    instantaneous values. The slope is the total series resistance between the
    supply's regulation point and the shunt (both cable conductors, connectors,
    fuse); the intercept is the voltage the supply is actually holding.
    """

    def __init__(self, maxlen: int = 900, min_points: int = 20, min_span_a: float = 0.5):
        self.pts: deque[tuple[float, float]] = deque(maxlen=maxlen)
        self.min_points = min_points
        self.min_span_a = min_span_a

    def add(self, i_a: float, v_v: float) -> None:
        self.pts.append((i_a, v_v))

    def result(self) -> dict | None:
        n = len(self.pts)
        if n < self.min_points:
            return None
        xs = [p[0] for p in self.pts]
        ys = [p[1] for p in self.pts]
        lo, hi = min(xs), max(xs)
        if hi - lo < self.min_span_a:
            return None
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
        slope = sxy / sxx
        icpt = my - slope * mx
        rms = math.sqrt(sum((y - (icpt + slope * x)) ** 2 for x, y in zip(xs, ys, strict=True)) / n)
        return {"r_ohm": -slope, "v_source": icpt, "n": n, "i_lo": lo, "i_hi": hi, "rms_mv": rms * 1000}


@dataclass
class LinkStats:
    """Counts packets and gaps in the sequence number."""

    received: int = 0
    lost: int = 0
    resets: int = 0
    last_seq: int | None = None
    last_uptime: int | None = None
    last_rx: float | None = None
    recent: list = field(default_factory=list)   # (time, lost_before_this) for loss %

    def update(self, p: Packet, now: float | None = None) -> None:
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

    def age_s(self, now: float | None = None) -> float | None:
        if self.last_rx is None:
            return None
        return (time.monotonic() if now is None else now) - self.last_rx


class CsvLog:
    """Appends one row per reporting interval. Opens the file per write so it's safe to read live.

    If an existing file has a different header (an older remkey version), it is
    renamed to <name>.<timestamp>.csv and a fresh file is started.
    """

    HEADER = ["time", "seq", "pa_pk_mv", "pa_avg_mv", "pa_pk_w", "pa_avg_w",
              "xv_pk_mv", "ref_lock", "temp1_c", "temp2_c", "uptime_s",
              "v_avg", "v_min", "v_max", "i_avg", "i_min", "i_max"]

    def __init__(self, path: str):
        self.path = Path(path)
        if self.path.exists():
            with self.path.open(newline="", encoding="utf-8") as f:
                first = next(csv.reader(f), None)
            if first != self.HEADER:
                self.path.rename(self.path.with_suffix(f".{time.strftime('%Y%m%d-%H%M%S')}.csv"))
        if not self.path.exists():
            with self.path.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(self.HEADER)

    def write(self, p: Packet, pa_pk_w: float | None, pa_avg_w: float | None,
              pwr: PowerPacket | None = None) -> None:
        def f3(x):
            return f"{x:.3f}"

        power = ([f3(pwr.v_avg), f3(pwr.v_min), f3(pwr.v_max), f3(pwr.i_avg), f3(pwr.i_min),
                  f3(pwr.i_max)] if pwr is not None and pwr.ok else [""] * 6)
        with self.path.open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                time.strftime("%Y-%m-%d %H:%M:%S"), p.seq, p.pa_pk_mv, p.pa_avg_mv,
                "" if pa_pk_w is None else f"{pa_pk_w:.2f}",
                "" if pa_avg_w is None else f"{pa_avg_w:.2f}",
                p.xv_pk_mv, "" if p.lock is None else int(p.lock),
                "" if p.temp_c is None else p.temp_c,
                "" if p.temp2_c is None else p.temp2_c, p.uptime_s,
                *power,
            ])
