"""Fit the dish elevation sensor's temperature coefficient from the telemetry CSV.

    python -m remkey.elevfit remkey-tlm.csv --config station.toml
    python -m remkey.elevfit remkey-tlm.csv --config station.toml --since 2026-12-01

Park the dish on its 0 degree stop and leave it there while the weather changes:
cold nights and sunny afternoons, ideally a 20 C swing or more. The station logs
the raw angle and the sensor's temperature with every tower report. This fits the
raw angle against temperature over the rows where the dish was at the stop, and
prints elev_tc_deg_per_c and elev_t_ref_c for station.toml.

It's a one-time job: the ADXL355's drift is repeatable, so the coefficient holds.
Rows count as "at the stop" when the calibrated elevation is within --window of
--at (default 0 +- 0.5 deg); moving the dish during the logging period is fine, the
other rows are simply left out.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys

from .config import load_station
from .sensors import Elevation


def fit(rows: list[dict], at: float, window: float, gain: float) -> dict | None:
    """Least squares raw = a + b * T over the rows at the stop. tc = gain * b."""
    pts = []
    for r in rows:
        try:
            e, raw, t = float(r["elev_deg"]), float(r["elev_raw_deg"]), float(r["tilt_temp_c"])
        except (KeyError, TypeError, ValueError):
            continue
        if abs(e - at) <= window:
            pts.append((t, raw))
    n = len(pts)
    if n < 10:
        return None
    mt = sum(t for t, _ in pts) / n
    mr = sum(r for _, r in pts) / n
    stt = sum((t - mt) ** 2 for t, _ in pts)
    if stt <= 0:
        return None
    b = sum((t - mt) * (r - mr) for t, r in pts) / stt
    a = mr - b * mt
    before = math.sqrt(sum((r - mr) ** 2 for _, r in pts) / n) * abs(gain)
    after = math.sqrt(sum((r - (a + b * t)) ** 2 for t, r in pts) / n) * abs(gain)
    worst_before = max(abs(r - mr) for _, r in pts) * abs(gain)
    worst_after = max(abs(r - (a + b * t)) for t, r in pts) * abs(gain)
    ts = [t for t, _ in pts]
    return {"n": n, "tc": gain * b, "t_ref": mt, "t_lo": min(ts), "t_hi": max(ts),
            "rms_before": before, "rms_after": after, "worst_before": worst_before,
            "worst_after": worst_after}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="dish elevation sensor: temperature coefficient from the CSV")
    ap.add_argument("csv", help="remkey-tlm.csv written by the station service")
    ap.add_argument("--config", help="station.toml (for the elevation calibration's gain)")
    ap.add_argument("--at", type=float, default=0.0, help="elevation of the stop, degrees (default 0)")
    ap.add_argument("--window", type=float, default=0.5, help="rows within this of --at count (default 0.5)")
    ap.add_argument("--since", help="only rows on or after this date/time (YYYY-MM-DD[ HH:MM])")
    a = ap.parse_args(argv)
    gain = 1.0
    if a.config:
        cfg = load_station(a.config)
        gain = Elevation(cfg.elev_axis, cfg.elev_cal).gain
    with open(a.csv, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if not a.since or (r.get("time") or "") >= a.since]
    res = fit(rows, a.at, a.window, gain)
    if res is None:
        print("Not enough rows at the stop with elevation and sensor temperature "
              "(need 10 or more, at different temperatures). Is the dish parked, and is "
              "the tower running remtlm 0.7.0 with the ADXL355?")
        return 1
    span = res["t_hi"] - res["t_lo"]
    print(f"{res['n']} rows at the stop, sensor {res['t_lo']:.1f} to {res['t_hi']:.1f} C ({span:.1f} C span)")
    print(f"scatter at the stop: rms {res['rms_before']:.3f} deg, worst {res['worst_before']:.3f} deg "
          "without the fit")
    print(f"                     rms {res['rms_after']:.3f} deg, worst {res['worst_after']:.3f} deg with it")
    print(f"drift: {res['tc'] * 10:+.3f} deg per 10 C")
    print()
    print("Add to station.toml, then restart the station service:")
    print(f"elev_tc_deg_per_c = {res['tc']:.5f}")
    print(f"elev_t_ref_c = {res['t_ref']:.1f}")
    if span < 15:
        print()
        print(f"Only a {span:.0f} C temperature span so far: log longer, through colder and "
              "warmer weather, for a coefficient that holds all year.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
