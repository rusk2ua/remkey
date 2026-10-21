"""Summarise tower supply readings from the telemetry CSV and suggest alert limits.

    python -m remkey.powerstats remkey-tlm.csv
    python -m remkey.powerstats remkey-tlm.csv --config station.toml --since 2026-11-01

Rows are split into receive and transmit intervals by the PA power-sense peak
(pa_pk_mv above --tx-mv counts as transmit). Run it after a few days of normal
operating, including some transmitting, then copy the suggested limits into
station.toml.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys

from .config import load_station
from .telemetry import CableFit, gauge_match


def pct(values: list[float], p: float) -> float:
    """Percentile by linear interpolation (p in 0..100)."""
    xs = sorted(values)
    if not xs:
        return math.nan
    k = (len(xs) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def summarise(rows: list[dict], tx_mv: float) -> dict:
    rx, tx = [], []
    for r in rows:
        try:
            v = {k: float(r[k]) for k in ("v_avg", "v_min", "v_max", "i_avg", "i_min", "i_max")}
            v["pa"] = float(r.get("pa_pk_mv") or 0)
        except (KeyError, ValueError):
            continue                       # no supply data in this row
        (tx if v["pa"] > tx_mv else rx).append(v)
    return {"rx": rx, "tx": tx}


def describe(name: str, data: list[dict], out) -> None:
    if not data:
        print(f"{name}: no intervals", file=out)
        return
    va = [d["v_avg"] for d in data]
    ia = [d["i_avg"] for d in data]
    print(f"{name}: {len(data)} intervals", file=out)
    print(f"  voltage avg   min {min(va):6.2f}  p5 {pct(va, 5):6.2f}  median {pct(va, 50):6.2f}"
          f"  p95 {pct(va, 95):6.2f}  max {max(va):6.2f} V", file=out)
    print(f"  voltage low   lowest {min(d['v_min'] for d in data):6.2f} V", file=out)
    print(f"  current avg   min {min(ia):6.2f}  p5 {pct(ia, 5):6.2f}  median {pct(ia, 50):6.2f}"
          f"  p95 {pct(ia, 95):6.2f}  max {max(ia):6.2f} A", file=out)
    print(f"  current peak  highest {max(d['i_max'] for d in data):6.2f} A", file=out)


def suggest(groups: dict, base_v: float) -> dict:
    """Alert limits with margin around what was observed. None where there is no data."""
    rx, tx = groups["rx"], groups["tx"]
    alld = rx + tx
    s: dict = {}
    if alld:
        peak = max(d["i_max"] for d in alld)
        s["i_max_alert"] = math.ceil(peak * 1.2 * 2) / 2                    # +20%, round up to 0.5 A
        lowest = min(d["v_min"] for d in alld)
        s["v_min_alert"] = math.floor((lowest - 0.3) * 10) / 10             # 0.3 V below the lowest seen
        s["v_max_alert"] = round(base_v + 0.2, 1)                           # can't exceed the supply
    if rx:
        s["i_min_alert"] = math.floor(pct([d["i_avg"] for d in rx], 5) * 0.8 * 10) / 10   # 80% of RX p5
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="tower supply statistics and suggested alert limits")
    ap.add_argument("csv", help="remkey-tlm.csv written by the station service")
    ap.add_argument("--config", help="station.toml (for base_supply_v and cable_one_way_ft)")
    ap.add_argument("--tx-mv", type=float, default=150.0,
                    help="PA sense peak above this counts as transmitting (default 150 mV)")
    ap.add_argument("--since", help="only rows on or after this date/time (YYYY-MM-DD[ HH:MM])")
    args = ap.parse_args(argv)

    base_v, one_way_ft = 14.1, 100.0
    if args.config:
        cfg = load_station(args.config)
        base_v, one_way_ft = cfg.base_supply_v, cfg.cable_one_way_ft

    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if not args.since or r.get("time", "") >= args.since]
    groups = summarise(rows, args.tx_mv)
    out = sys.stdout
    print(f"{len(rows)} rows read; supply at the tower base set to {base_v:.2f} V\n", file=out)
    describe("RECEIVE", groups["rx"], out)
    describe("TRANSMIT", groups["tx"], out)

    fit = CableFit(maxlen=10**7)
    for d in groups["rx"] + groups["tx"]:
        fit.add(d["i_avg"], d["v_avg"])
    r = fit.result()
    print(file=out)
    if r:
        awg, exp, verdict = gauge_match(r["r_ohm"], one_way_ft)
        print(f"cable loop resistance {r['r_ohm'] * 1000:.0f} mOhm (fit over {r['n']} intervals,"
              f" {r['i_lo']:.2f}-{r['i_hi']:.2f} A, rms {r['rms_mv']:.0f} mV)", file=out)
        print(f"  {verdict}; #{awg} copper would be {exp * 1000:.0f} mOhm for 2 x {one_way_ft:.0f} ft"
              " at 20 C (+0.39% per degree C)", file=out)
        print(f"  supply holding {r['v_source']:.2f} V at the base (set to {base_v:.2f} V)", file=out)
    else:
        print("cable loop resistance: not enough current spread yet (transmit more)", file=out)

    s = suggest(groups, base_v)
    if s:
        print("\nSuggested limits for station.toml (review before using):", file=out)
        for k in ("v_min_alert", "v_max_alert", "i_max_alert", "i_min_alert"):
            if k in s:
                print(f"{k} = {s[k]:.1f}", file=out)
        if s.get("v_min_alert", 99) < 12.0:
            print("# note: below the MKU 10 G5's 12 V minimum supply rating", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
