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
    tlm_csv: str = "remkey-tlm.csv"
    # --- tower supply monitor (INA226) ---
    base_supply_v: float = 14.1      # what the supply at the tower base is set to
    cable_one_way_ft: float = 100.0  # tower base to tower top
    v_scale: float = 1.0             # trim to a DMM reading at the enclosure
    i_scale: float = 1.0             # trim to a clamp meter / DMM in series
    v_min_alert: float = 12.0        # MKU 10 G5 minimum supply; 0 = off
    v_max_alert: float = 14.3        # 0 = off
    i_max_alert: float = 0.0         # peak current above this; 0 = off until you know normal
    i_min_alert: float = 0.0         # average current below this (something lost power); 0 = off


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
    return _load(StationConfig, path)


def load_client(path: str | Path) -> ClientConfig:
    return _load(ClientConfig, path)
