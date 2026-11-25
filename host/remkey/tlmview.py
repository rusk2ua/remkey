"""Bench/calibration viewer for the remtlm base Nano.

    python -m remkey.tlmview --port COM9                 raw readings
    python -m remkey.tlmview --port COM9 --config station.toml   with your calibration

Stop the station service first (it owns the port), or point this at the tower
or supply-box Nano's own USB port on the bench: each prints every packet it sends.

Dish elevation lines show the raw angle (what goes into elev_cal in station.toml)
next to the calibrated one: hold the inclinometer on the dish rim, read both, and
write the pair down.
"""

from __future__ import annotations

import argparse
import sys
import time

from .config import load_station
from .sensors import Bme280Cal, Elevation, adxl_temp_c, dew_point_c
from .telemetry import (
    SRC_BASE,
    Calibration,
    EnvCalPacket,
    EnvPacket,
    LinkStats,
    Packet,
    PowerPacket,
    ReplyAssembler,
    ReplyPart,
    TiltPacket,
    parse_any,
    parse_signal,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="remtlm telemetry viewer")
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--config", help="station.toml, for pa_cal / xv_cal")
    args = ap.parse_args(argv)

    import serial

    pa_cal = xv_cal = Calibration([])
    v_scale = i_scale = 1.0
    elev = Elevation()
    if args.config:
        cfg = load_station(args.config)
        pa_cal, xv_cal = Calibration(cfg.pa_cal), Calibration(cfg.xv_cal)
        v_scale, i_scale = cfg.v_scale, cfg.i_scale
        elev = Elevation(cfg.elev_axis, cfg.elev_cal, cfg.elev_tc_deg_per_c, cfg.elev_t_ref_c)
    env_cal: Bme280Cal | None = None

    stats = LinkStats()
    box_stats = LinkStats()
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
            if isinstance(p, TiltPacket):
                now = time.strftime("%H:%M:%S")
                if not p.ok:
                    print(f"{now}        elevation sensor (ADXL355) NOT FOUND")
                    continue
                raw = elev.raw(p.x, p.y, p.z)
                t = adxl_temp_c(p.t_raw)
                g = (p.x * p.x + p.y * p.y + p.z * p.z) ** 0.5 / 256000
                cal = f"{elev.degrees(raw, t):7.3f} deg" if elev.calibrated else "  (no elev_cal)"
                print(f"{now}        elevation raw {raw:8.4f} deg  {cal}  sensor {t:5.1f} C  {g:.3f} g"
                      + ("  MOVING" if p.moving else ""))
                continue
            if isinstance(p, EnvCalPacket):
                env_cal = Bme280Cal.from_bytes(p.chip, p.cal)
                continue
            if isinstance(p, EnvPacket):
                now = time.strftime("%H:%M:%S")
                if not p.ok:
                    print(f"{now}        box air sensor (BME280) NOT FOUND")
                elif env_cal is None or env_cal.chip != p.chip:
                    print(f"{now}        box air: waiting for the sensor's calibration (every 5 min)")
                else:
                    t, hpa, rh = env_cal.compensate(p.p_raw, p.t_raw, p.h_raw)
                    hum = "" if rh is None else f"  {rh:4.1f}% RH  dew point {dew_point_c(t, rh):5.1f} C"
                    print(f"{now}        box air {t:5.1f} C  {hpa or 0:7.1f} hPa{hum}")
                continue
            if isinstance(p, PowerPacket):
                base = p.src == SRC_BASE
                where = "BASE supply" if base else "top supply "
                extra = ""
                if base:
                    box_stats.update(p)
                    temp = "n/a" if p.temp_c is None else f"{p.temp_c:.1f}"
                    extra = f"  box {temp} C  up {p.uptime_s} s  loss {box_stats.loss_pct_5min():.1f}%"
                if not p.ok:
                    print(f"{time.strftime('%H:%M:%S')} #{p.seq:<5d} {where} monitor NOT ANSWERING{extra}")
                    continue
                q = p.scaled(v_scale, i_scale)
                print(f"{time.strftime('%H:%M:%S')} #{q.seq:<5d} {where} {q.v_avg:6.3f} V"
                      f" (min {q.v_min:6.3f} max {q.v_max:6.3f})  {q.i_avg:6.3f} A"
                      f" (min {q.i_min:6.3f} max {q.i_max:6.3f}){extra}")
                continue
            if not isinstance(p, Packet):
                sig = parse_signal(line)
                if sig is not None:
                    src, dbm = sig
                    what = {"tower": "tower signal", "psu": "BASE supply signal", "noise": "noise floor"}[src]
                    print(f"{time.strftime('%H:%M:%S')}        {what} {dbm} dBm")
                elif line:
                    print(f"   {line}")
                continue
            stats.update(p)

            def fmt(cal, mv):
                w = cal.watts(mv)
                return f"{mv:5d} mV" + (f" = {w:6.2f} W" if w is not None else "")

            temp = "/".join("n/a" if t is None else f"{t:.1f}" for t in (p.temp_c, p.temp2_c)) + " C"
            lock = {None: "lock n/a", True: "REF LOCK", False: "REF UNLOCK"}[p.lock]
            if p.ptt is not None:
                lock += f"  key {'KEYED' if p.ptt else 'off'} {p.ptt_v:.2f} V"
            print(f"{time.strftime('%H:%M:%S')} #{p.seq:<5d} PA pk {fmt(pa_cal, p.pa_pk_mv)}"
                  f"  avg {fmt(pa_cal, p.pa_avg_mv)}  XV {fmt(xv_cal, p.xv_pk_mv)}"
                  f"  {temp}  {lock}  loss {stats.loss_pct_5min():.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
