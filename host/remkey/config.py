"""TOML configuration for the station service and client (Python 3.11+ tomllib)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass
class StationConfig:
    secret: str = ""
    listen_host: str = "0.0.0.0"     # 127.0.0.1 if you only use an AnyDesk tunnel
    listen_port: int = 7373
    keyer_port: str = "COM7"
    keyer_baud: int = 115200
    heartbeat_timeout_s: float = 3.0  # no client traffic this long -> PTT off, flush
    ptt_hang_ms: int = 2000           # after PTT off: finish queued CW, then hold PTT this long
    wpm_offset: int = 2               # station sends a bit faster so its buffer drains
    max_tune_ms: int = 15000
    max_text_chars: int = 512
    log_file: str = "remkey-station.log"
    # --- tower telemetry (remtlm base Nano); empty tlm_port = disabled ---
    tlm_port: str = ""
    tlm_baud: int = 115200
    pa_cal: list = field(default_factory=list)     # [[mV, watts], ...]
    xv_cal: list = field(default_factory=list)
    temp_warn_c: float = 65.0                      # probe 1 (PA heatsink)
    temp2_warn_c: float = 50.0                     # probe 2 (MKU case: 55 C max, TX off at 65)
    temp_names: list = field(default_factory=lambda: ["PA heatsink", "transverter case"])
    tlm_stale_s: float = 10.0
    # key line to the sequencer (MKU CON1 pin 8, tower firmware 0.6.0+)
    mon_tx_mv: int = 500            # MKU MON at or above this = the transverter is transmitting
    pa_tx_mv: int = 150             # PA sense below this = no PA output
    pa_silent_s: float = 3.0        # MKU transmitting, PA silent this long -> alert; 0 = off
    ptt_stuck_s: float = 120.0      # key line held keyed this long -> alert; 0 = off
    tlm_csv: str = "remkey-tlm.csv"
    # --- supply monitor (INA226 in the tower-base supply box, and/or the top box) ---
    base_supply_v: float = 14.1      # what the supply is set to (used when only the top box measures)
    cable_one_way_ft: float = 100.0  # tower base to tower top
    box_temp_name: str = "supply box"   # DS18B20 in the tower-base supply box
    box_temp_warn_c: float = 50.0       # 0 = off
    v_scale: float = 1.0             # trim to a DMM reading at the INA226
    i_scale: float = 1.0             # trim to a clamp meter / DMM in series
    v_min_alert: float = 12.0        # MKU 10 G5 minimum supply; 0 = off
    v_max_alert: float = 14.3        # 0 = off
    i_max_alert: float = 0.0         # peak current above this; 0 = off until you know normal
    i_min_alert: float = 0.0         # average current below this (something lost power); 0 = off
    # --- dish elevation (ADXL355) and box environment (BME280), tower firmware 0.7.0+ ---
    elev_axis: str = "x"             # sensor axis along the dish's boresight: x, y, z, or -x etc.
    elev_cal: list = field(default_factory=list)       # [[raw_deg, inclinometer_deg], ...]
    elev_tc_deg_per_c: float = 0.0   # temperature coefficient (python -m remkey.elevfit)
    elev_t_ref_c: float = 25.0       # sensor temperature the coefficient is referred to
    elev_min_deg: float = -2.0       # dashboard dial range
    elev_max_deg: float = 22.0
    env_rh_warn: float = 85.0        # box relative humidity alert, %; 0 = off
    env_dew_margin_c: float = 3.0    # alert when the box air is this close to its dew point; 0 = off
    env_altitude_m: float = 0.0      # > 0: also show sea-level pressure
    # --- web dashboard (telemetry monitor in a browser); dash_port = 0 turns it off ---
    dash_port: int = 0
    dash_host: str = "0.0.0.0"
    dash_allow: list = field(default_factory=list)      # CIDRs; empty = home LAN + Tailscale
    dash_hostnames: list = field(default_factory=list)  # extra names to accept in the Host header
    dash_history_h: float = 12.0                        # hours of chart history kept in memory
    # --- cloud copy of the dashboard (S3 + CloudFront, see cloud/deploy.sh); empty bucket = off ---
    cloud_bucket: str = ""
    cloud_region: str = "us-east-1"
    cloud_profile: str = "remkey-tlm"                   # credentials profile on this PC
    cloud_interval_s: float = 15.0


@dataclass
class ClientConfig:
    secret: str = ""
    station_host: str = "127.0.0.1"
    station_port: int = 7373
    keyer_port: str = "/dev/cu.usbserial-0001"
    keyer_baud: int = 115200
    wpm: int = 18
    sidetone_hz: int = 600
    tune_ms: int = 5000
    echo_typed: bool = True           # play keyboard-typed text on the local sidetone
    reconnect_s: float = 3.0
    heartbeat_s: float = 1.0
    ptt_switch: str = "momentary"     # "momentary" button (press toggles) or "latching" switch


def _load(cls, path: str | Path):
    data: dict[str, Any] = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"unknown config keys in {path}: {', '.join(sorted(unknown))}")
    cfg = cls(**data)
    if len(cfg.secret) < 16:
        raise ValueError(f"{path}: 'secret' must be at least 16 characters "
                         "(run: python -m remkey.genkey)")
    return cfg


def load_station(path: str | Path) -> StationConfig:
    cfg = _load(StationConfig, path)
    from .sensors import parse_axis
    parse_axis(cfg.elev_axis)                     # raises ValueError with a readable message
    for pt in cfg.elev_cal:
        if not (isinstance(pt, list) and len(pt) == 2 and all(isinstance(v, (int, float)) for v in pt)):
            raise ValueError(f"{path}: elev_cal entries are [raw_deg, inclinometer_deg] pairs, not {pt!r}")
    return cfg


def load_client(path: str | Path) -> ClientConfig:
    cfg = _load(ClientConfig, path)
    if cfg.ptt_switch not in ("momentary", "latching"):
        raise ValueError(f"{path}: ptt_switch must be \"momentary\" or \"latching\", "
                         f"not {cfg.ptt_switch!r}")
    return cfg
