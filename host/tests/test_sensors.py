"""Dish elevation (ADXL355) and box environment (BME280): math, packets, the hub."""

import csv
import math
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from remkey.config import StationConfig, load_station
from remkey.sensors import (
    CHIP_BME280,
    CHIP_BMP280,
    Bme280Cal,
    Elevation,
    adxl_temp_c,
    dew_point_c,
    parse_axis,
    raw_elevation,
    sea_level_hpa,
)
from remkey.station import TelemetryHub
from remkey.telemetry import (
    EnvCalPacket,
    EnvPacket,
    Packet,
    TiltPacket,
    format_env,
    format_env_cal,
    format_packet,
    format_tilt,
    parse_any,
)

REPO = Path(__file__).resolve().parents[2]
SECRET = "0123456789abcdef0123456789abcdef"
G = 256000                                    # ADXL355 counts per g at +-2 g (nominal)

# Bosch's BMP280 datasheet worked example: dig_T1..dig_P9, adc_T 519888, adc_P 415148
# -> 25.08 C, 100653.27 Pa. Humidity constants: typical BME280 values.
BOSCH_PT = [27504, 26435, -1000, 36477, -10685, 3024, 2855, 140, -7, 15500, -14600, 6000]


def cal_bytes(h1=75, h2=362, h3=0, h4=313, h5=50, h6=30) -> bytes:
    b = bytearray(33)
    for i, v in enumerate(BOSCH_PT):
        b[2 * i:2 * i + 2] = struct.pack("<H" if i in (0, 3) else "<h", v)
    b[25] = h1
    b[26:28] = struct.pack("<h", h2)
    b[28] = h3
    b[29] = (h4 >> 4) & 0xFF
    b[30] = ((h5 & 0x0F) << 4) | (h4 & 0x0F)
    b[31] = (h5 >> 4) & 0xFF
    b[32] = h6 & 0xFF
    return bytes(b)


def tilt_counts(elev_deg: float, roll_deg: float = 0.0) -> tuple[int, int, int]:
    """x along the boresight, the plate rolled about it by roll_deg."""
    e, r = math.radians(elev_deg), math.radians(roll_deg)
    return round(G * math.sin(e)), round(G * math.cos(e) * math.sin(r)), round(G * math.cos(e) * math.cos(r))


# ----------------------------------------------------------------- math
def test_bme280_matches_bosch_worked_example():
    cal = Bme280Cal.from_bytes(CHIP_BMP280, cal_bytes())
    t, p, rh = cal.compensate(415148, 519888, 0)
    assert t == pytest.approx(25.08, abs=0.005)
    assert p == pytest.approx(1006.5327, abs=0.001)          # 100653.27 Pa
    assert rh is None                                         # BMP280: no humidity


def test_bme280_humidity_and_split_registers():
    cal = Bme280Cal.from_bytes(CHIP_BME280, cal_bytes(h4=-300, h5=-77))
    assert cal.H == (75, 362, 0, -300, -77, 30)               # 12-bit signed H4/H5 across 0xE4-0xE6
    cal = Bme280Cal.from_bytes(CHIP_BME280, cal_bytes())
    _, _, rh_lo = cal.compensate(415148, 519888, 22000)
    _, _, rh_hi = cal.compensate(415148, 519888, 32000)
    assert 0 < rh_lo < rh_hi <= 100
    _, _, rh_max = cal.compensate(415148, 519888, 65535)
    assert rh_max == 100.0                                    # clamped
    with pytest.raises(ValueError):
        Bme280Cal.from_bytes(CHIP_BME280, b"\x00" * 26)


def test_dew_point_and_sea_level():
    assert dew_point_c(25.0, 50.0) == pytest.approx(13.85, abs=0.05)
    assert dew_point_c(10.0, 100.0) == pytest.approx(10.0, abs=0.01)
    assert dew_point_c(10.0, 0.0) is None
    assert sea_level_hpa(1000.0, 15.0, 0.0) == pytest.approx(1000.0)
    assert sea_level_hpa(1000.0, 15.0, 300.0) == pytest.approx(1035.8, abs=0.5)


def test_adxl_temperature():
    assert adxl_temp_c(1885) == pytest.approx(25.0)
    assert adxl_temp_c(1885 - 181) == pytest.approx(45.0)    # -9.05 LSB per C


def test_raw_elevation_ignores_roll_and_scale():
    for e in (-1.5, 0.0, 0.25, 5.0, 19.0):
        for roll in (0.0, 7.0, -30.0):
            x, y, z = tilt_counts(e, roll)
            assert raw_elevation(x, y, z, 0, 1.0) == pytest.approx(e, abs=0.0005)
            assert raw_elevation(x * 1.07, y * 1.07, z * 1.07, 0, 1.0) == pytest.approx(e, abs=0.0005)
    x, y, z = tilt_counts(5.0)
    assert raw_elevation(-x, y, z, 0, -1.0) == pytest.approx(5.0, abs=0.0005)   # axis "-x"
    assert raw_elevation(y, x, z, 1, 1.0) == pytest.approx(5.0, abs=0.0005)     # axis "y"
    assert parse_axis("-Y") == (1, -1.0) and parse_axis("+z") == (2, 1.0)
    with pytest.raises(ValueError):
        parse_axis("w")


def test_elevation_calibration_fit_and_temperature():
    assert not Elevation().calibrated and Elevation().degrees(3.0, 40.0) == 3.0
    one = Elevation(points=[[0.37, 0.0]])
    assert one.calibrated and one.degrees(5.37, None) == pytest.approx(5.0)
    # sensor reads 2% steep with a 0.4 deg mounting offset; inclinometer pairs at 0, 5, 10, 20 deg
    pts = [[0.4 + 1.02 * t, t] for t in (0.0, 5.0, 10.0, 20.0)]
    m = Elevation(points=pts)
    assert m.gain == pytest.approx(1 / 1.02) and m.residual_deg() == pytest.approx(0.0, abs=1e-9)
    assert m.degrees(0.4 + 1.02 * 7.5, None) == pytest.approx(7.5)
    # temperature: 0.01 deg per C, referred to 20 C
    mt = Elevation(points=pts, tc_deg_per_c=0.01, t_ref_c=20.0)
    assert mt.degrees(0.4, 20.0) == pytest.approx(0.0)
    assert mt.degrees(0.4 + 0.3 * 1.02, 50.0) == pytest.approx(0.0)       # drift taken out
    assert Elevation(points=[[1.0, 0.5], [1.0, 0.5]]).degrees(2.0, None) == pytest.approx(1.5)


# ----------------------------------------------------------------- packets
def test_sensor_packets_round_trip():
    t = TiltPacket(12, 4466, -1200, 255961, 1840, True, False, "K2UA")
    assert format_tilt(t) == "$RA,12,4466,-1200,255961,1840,1,0,K2UA*53"   # same as the firmware
    assert parse_any(format_tilt(t)) == t
    e = EnvPacket(3, 415148, 519888, 27000, 96, True, "K2UA")
    assert format_env(e) == "$RB,3,415148,519888,27000,96,1,K2UA*61"
    assert parse_any(format_env(e)) == e
    c = EnvCalPacket(96, cal_bytes(), "K2UA")
    assert parse_any(format_env_cal(c)) == c
    assert parse_any("$RA,1,2,K2UA*00") is None
    bad = format_tilt(t)[:-2] + "00"
    assert parse_any(bad) is None


@pytest.mark.skipif(shutil.which("g++") is None, reason="needs g++")
def test_firmware_sensor_packets(tmp_path):
    exe = tmp_path / ("tlm_proto_test.exe" if sys.platform == "win32" else "tlm_proto_test")
    subprocess.run(["g++", "-std=c++17", "-I", str(REPO / "firmware/remtlm"),
                    str(REPO / "tests/firmware_sim/tlm_proto_test.cpp"), "-o", str(exe)], check=True)
    out = subprocess.run([str(exe)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
    pk = [parse_any(ln) for ln in out.stdout.splitlines() if ln.startswith(("$RA", "$RB", "$RC"))]
    ra = [p for p in pk if isinstance(p, TiltPacket)]
    rb = [p for p in pk if isinstance(p, EnvPacket)]
    rc = [p for p in pk if isinstance(p, EnvCalPacket)]
    assert ra[0] == TiltPacket(12, 4466, -1200, 255961, 1840, True, False, "K2UA")
    assert ra[1].ok is False
    assert rc[0].cal == cal_bytes()                           # firmware hex == these bytes
    t, p, rh = Bme280Cal.from_bytes(rc[0].chip, rc[0].cal).compensate(rb[0].p_raw, rb[0].t_raw, rb[0].h_raw)
    assert t == pytest.approx(25.08, abs=0.005) and p == pytest.approx(1006.5327, abs=0.001)
    assert rh is not None and rb[1].ok is False


# ----------------------------------------------------------------- the hub
def hub(tmp_path, **kw):
    cfg = StationConfig(secret=SECRET, log_file="", tlm_csv=str(tmp_path / "tlm.csv"), **kw)
    got = []
    h = TelemetryHub(cfg, got.append)
    return h, got


def tower_line(seq=1):
    return format_packet(Packet(seq, 100, 50, 0, True, 25.0, 24.0, 60, "K2UA", ptt=False, ptt_v=12.0))


def test_hub_elevation_and_live_push(tmp_path):
    h, _ = hub(tmp_path, elev_cal=[[0.4, 0.0], [10.6, 10.0]])
    live = []
    h.on_elev = live.append
    x, y, z = tilt_counts(5.5, roll_deg=3.0)                 # raw 5.5 -> 5.0 deg after calibration
    h.on_line(format_tilt(TiltPacket(1, x, y, z, 1885, True, False, "K2UA")))
    assert h.dish["deg"] == pytest.approx(5.0, abs=0.001) and h.dish["temp_c"] == pytest.approx(25.0)
    assert h.dish["g"] == pytest.approx(1.0, abs=0.001)
    assert live[-1]["deg"] == pytest.approx(5.0, abs=0.001) and not live[-1]["moving"]
    assert set(live[-1]) == {"deg", "raw_deg", "moving", "ts"}      # one frame, one reading
    for i in range(10):                                       # live mode: every one is pushed
        x, y, z = tilt_counts(5.5 + 0.1 * i)
        h.on_line(format_tilt(TiltPacket(2 + i, x, y, z, 1885, True, True, "K2UA")))
    assert len(live) == 11 and live[-1]["moving"] is True
    assert len(h.history.dish) <= 3                           # charts take live ones at 1 per second
    # $RT rows in the CSV carry the latest elevation
    h.on_line(tower_line())
    rows = list(csv.DictReader((tmp_path / "tlm.csv").open()))
    last_raw = 6.4                                            # the last live reading above
    assert float(rows[-1]["elev_deg"]) == pytest.approx((last_raw - 0.4) * 10 / 10.2, abs=0.01)
    assert rows[-1]["box_air_c"] == ""
    # sensor gone: alert, then back
    h.on_line(format_tilt(TiltPacket(20, 0, 0, 0, 0, False, False, "K2UA")))
    assert any("ADXL355) not answering" in a["msg"] for a in h.alerts)
    h.on_line(format_tilt(TiltPacket(21, x, y, z, 1885, True, False, "K2UA")))
    assert any("elevation sensor answering again" in a["msg"] for a in h.alerts)


def test_hub_environment_alerts(tmp_path):
    h, _ = hub(tmp_path, env_rh_warn=85.0, env_dew_margin_c=3.0, env_altitude_m=300.0)
    # a reading before the calibration has arrived: waits for it
    h.on_line(format_env(EnvPacket(1, 415148, 519888, 27000, 96, True, "K2UA")))
    assert h.env["waiting"]
    h.on_line(format_env_cal(EnvCalPacket(96, cal_bytes(), "K2UA")))
    h.on_line(format_env(EnvPacket(2, 415148, 519888, 27000, 96, True, "K2UA")))
    e = h.env
    assert not e["waiting"] and e["temp_c"] == pytest.approx(25.08, abs=0.01)
    assert e["hpa"] == pytest.approx(1006.53, abs=0.01) and e["sea_hpa"] > e["hpa"]
    assert e["dew_c"] == pytest.approx(dew_point_c(e["temp_c"], e["rh"]))
    assert not any("humidity" in a["msg"] or "CONDENSATION" in a["msg"] for a in h.alerts)
    # find a raw humidity reading that comes out above 85% RH
    cal = Bme280Cal.from_bytes(96, cal_bytes())
    wet = next(r for r in range(27000, 65535, 250) if cal.compensate(415148, 519888, r)[2] >= 98.0)
    h.on_line(format_env(EnvPacket(3, 415148, 519888, wet, 96, True, "K2UA")))
    msgs = [a["msg"] for a in h.alerts]
    assert any("humidity HIGH" in m for m in msgs) and any("near CONDENSATION" in m for m in msgs)
    h.on_line(format_env(EnvPacket(4, 415148, 519888, 27000, 96, True, "K2UA")))
    msgs = [a["msg"] for a in h.alerts]
    assert any("humidity back to" in m for m in msgs) and any("clear of its dew point" in m for m in msgs)
    h.on_line(tower_line())
    rows = list(csv.DictReader((tmp_path / "tlm.csv").open()))
    assert float(rows[-1]["box_air_c"]) == pytest.approx(25.08, abs=0.01) and rows[-1]["box_hpa"] == "1006.53"
    assert len(h.history.env) == 3
    # BMP280: no humidity, so no humidity alerts
    h.on_line(format_env_cal(EnvCalPacket(88, cal_bytes(), "K2UA")))
    h.on_line(format_env(EnvPacket(5, 415148, 519888, 0, 88, True, "K2UA")))
    assert h.env["rh"] is None and h.env["dew_c"] is None
    h.on_line(format_env(EnvPacket(6, 0, 0, 0, 0, False, "K2UA")))
    assert any("BME280) not answering" in a["msg"] for a in h.alerts)


def test_station_toml_sensor_settings(tmp_path):
    p = tmp_path / "station.toml"
    base = f'secret = "{SECRET}"\n'
    p.write_text(base + 'elev_axis = "-y"\nelev_cal = [[0.4, 0.0], [10.6, 10.0]]\n'
)
    cfg = load_station(p)
    assert cfg.elev_axis == "-y" and cfg.elev_cal[1] == [10.6, 10.0]
    p.write_text(base + 'elev_axis = "q"\n')
    with pytest.raises(ValueError, match="elev_axis"):
        load_station(p)
    p.write_text(base + 'elev_cal = [[1, 2, 3]]\n')
    with pytest.raises(ValueError, match="elev_cal"):
        load_station(p)


def test_elevfit_finds_the_temperature_coefficient(tmp_path, capsys):
    from remkey.elevfit import main

    p = tmp_path / "tlm.csv"
    hdr = "time,elev_deg,elev_raw_deg,tilt_temp_c\n"
    lines = []
    for i in range(60):                    # parked at 0: raw drifts 0.012 deg/C around 20 C, plus a 5 deg row
        t = -5.0 + i * 0.75
        raw = 0.31 + 0.012 * (t - 20.0) + (0.002 if i % 2 else -0.002)
        lines.append(f"2026-12-01 00:{i:02d}:00,{raw - 0.31:.4f},{raw:.4f},{t:.2f}")
    lines.append("2026-12-01 01:00:00,5.0000,5.3100,20.00")
    p.write_text(hdr + "\n".join(lines) + "\n")
    assert main([str(p)]) == 0
    out = capsys.readouterr().out
    assert "elev_tc_deg_per_c = 0.01200" in out and "60 rows at the stop" in out
    assert "drift: +0.120 deg per 10 C" in out
    q = tmp_path / "few.csv"
    q.write_text(hdr + "\n".join(lines[:5]) + "\n")
    assert main([str(q)]) == 1


def test_cloud_summary_shows_dish_and_box_air():
    from remkey.cloud import summary_html

    st = {"now": 0, "telemetry": True,
          "dish": {"ok": True, "deg": 4.25, "moving": True, "age_s": 1, "calibrated": True},
          "env": {"ok": True, "waiting": False, "temp_c": 12.3, "hpa": 978.4, "rh": 64.0,
                  "dew_c": 5.6, "margin_c": 6.7}}
    page = summary_html(st)
    assert "Dish elevation (10/24 GHz frame)" in page and "4.25 deg (calibrated; MOVING" in page
    assert "12.3 C, 978.4 hPa, 64% RH, dew point 5.6 C (6.7 C margin)" in page
