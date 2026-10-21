"""Bench/calibration viewer for the remtlm base Nano.

    python -m remkey.tlmview --port COM9                 raw readings
    python -m remkey.tlmview --port COM9 --config station.toml   with your calibration

Stop the station service first (it owns the port), or point this at the tower
Nano's own USB port on the bench: the tower prints every packet on USB too.
"""

from __future__ import annotations

import argparse
import sys
import time

from .config import load_station
from .telemetry import Calibration, LinkStats, Packet, ReplyAssembler, ReplyPart, parse_any


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="remtlm telemetry viewer")
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--config", help="station.toml, for pa_cal / xv_cal")
    args = ap.parse_args(argv)

    import serial

    pa_cal = xv_cal = Calibration([])
    if args.config:
        cfg = load_station(args.config)
        pa_cal, xv_cal = Calibration(cfg.pa_cal), Calibration(cfg.xv_cal)

    stats = LinkStats()
    replies = ReplyAssembler()
    with serial.Serial(args.port, args.baud, timeout=1) as ser:
        print(f"listening on {args.port} (Ctrl-C to stop)")
        while True:
            try:
                raw = ser.readline()
            except KeyboardInterrupt:
                break
            if not raw:
                continue
            line = raw.decode("ascii", errors="replace").strip()
            p = parse_any(line)
            if isinstance(p, ReplyPart):
                done = replies.add(p)
                if done:
                    cmd, text = done
                    print(f"{time.strftime('%H:%M:%S')} transverter '{cmd}':")
                    for ln in text.splitlines():
                        print(f"      {ln}")
                continue
            if not isinstance(p, Packet):
                if line:
                    print(f"   {line}")
                continue
            stats.update(p)

            def fmt(cal, mv):
                w = cal.watts(mv)
                return f"{mv:5d} mV" + (f" = {w:6.2f} W" if w is not None else "")

            temp = "/".join("n/a" if t is None else f"{t:.1f}" for t in (p.temp_c, p.temp2_c)) + " C"
            lock = {None: "lock n/a", True: "REF LOCK", False: "REF UNLOCK"}[p.lock]
            print(f"{time.strftime('%H:%M:%S')} #{p.seq:<5d} PA pk {fmt(pa_cal, p.pa_pk_mv)}"
                  f"  avg {fmt(pa_cal, p.pa_avg_mv)}  XV {fmt(xv_cal, p.xv_pk_mv)}"
                  f"  {temp}  {lock}  loss {stats.loss_pct_5min():.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
