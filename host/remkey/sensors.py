"""Dish elevation (ADXL355) and box environment (BME280) from the tower's raw readings.

The tower sends raw sensor values ($RA, $RB, $RC; see telemetry.py). Everything that
turns them into degrees, C, %RH and hPa lives here, so a recalibration is an edit to
station.toml and a service restart: no reflash, no climb.

Elevation
---------
The ADXL355 measures gravity. With `axis` the sensor axis that points along the
dish's boresight, the raw elevation is

    raw = atan2(a_axis, |a_other two|)

which doesn't depend on how the sensor plate is rolled about the boresight, nor on
the sensor's scale (only on the ratio between its axes). Then the one-time
calibration (station.toml):

    elevation = offset + gain * raw - tc * (T_sensor - t_ref)

- offset and gain: a straight-line fit through [[raw, inclinometer], ...] pairs taken
  at a few angles across the range you use (one pair: offset only, gain 1);
- tc: temperature coefficient in degrees per C, fitted once from a few weeks of
  readings at the 0 degree stop (python -m remkey.elevfit), 0 until then.

BME280
------
The Bosch reference compensation in double precision (BME280 datasheet, section
8.1), from the 33 calibration bytes the tower sends in $RC.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

AXES = {"x": 0, "y": 1, "z": 2}

# ADXL355 temperature sensor, nominal (datasheet): 1885 LSB at 25 C, -9.05 LSB/C.
ADXL_T_INTERCEPT = 1885.0
ADXL_T_SLOPE = -9.05


def adxl_temp_c(t_raw: int) -> float:
    """ADXL355 die temperature from its 12-bit reading (nominal intercept and slope)."""
    return 25.0 + (t_raw - ADXL_T_INTERCEPT) / ADXL_T_SLOPE


def parse_axis(spec: str) -> tuple[int, float]:
    """"x", "-y", "+z" -> (axis index, sign). Raises ValueError for anything else."""
    s = str(spec).strip().lower()
    sign = -1.0 if s.startswith("-") else 1.0
    s = s.lstrip("+-")
    if s not in AXES:
        raise ValueError(f"elev_axis must be x, y or z, optionally with a sign (-x), not {spec!r}")
    return AXES[s], sign


def raw_elevation(x: float, y: float, z: float, axis: int, sign: float) -> float:
    """Degrees above the horizon of the given sensor axis, from one gravity reading."""
    v = (x, y, z)
    along = sign * v[axis]
    others = math.hypot(*(v[i] for i in range(3) if i != axis))
    return math.degrees(math.atan2(along, others))


class Elevation:
    """Raw angle + temperature -> calibrated elevation, from the station.toml settings."""

    def __init__(self, axis: str = "x", points: Sequence[Sequence[float]] = (),
                 tc_deg_per_c: float = 0.0, t_ref_c: float = 25.0):
        self.axis, self.sign = parse_axis(axis)
        self.points = [(float(r), float(t)) for r, t in points]
        self.tc = float(tc_deg_per_c)
        self.t_ref = float(t_ref_c)
        self.offset, self.gain = 0.0, 1.0
        n = len(self.points)
        if n == 1:
            r, t = self.points[0]
            self.offset = t - r
        elif n >= 2:
            mx = sum(r for r, _ in self.points) / n
            my = sum(t for _, t in self.points) / n
            sxx = sum((r - mx) ** 2 for r, _ in self.points)
            if sxx > 1e-9:
                self.gain = sum((r - mx) * (t - my) for r, t in self.points) / sxx
                self.offset = my - self.gain * mx
            else:                                    # all at one angle: offset only
                self.offset = my - mx

    @property
    def calibrated(self) -> bool:
        return bool(self.points)

    def residual_deg(self) -> float | None:
        """Largest misfit at the calibration points (None with fewer than 3 points)."""
        if len(self.points) < 3:
            return None
        return max(abs(self.offset + self.gain * r - t) for r, t in self.points)

    def raw(self, x: float, y: float, z: float) -> float:
        return raw_elevation(x, y, z, self.axis, self.sign)

    def degrees(self, raw_deg: float, temp_c: float | None) -> float:
        e = self.offset + self.gain * raw_deg
        if self.tc and temp_c is not None:
            e -= self.tc * (temp_c - self.t_ref)
        return e


# ---------------------------------------------------------------------------
# BME280
# ---------------------------------------------------------------------------
CHIP_BME280 = 96      # chip id 0x60
CHIP_BMP280 = 88      # chip id 0x58: no humidity


def _u16(b: bytes, i: int) -> int:
    return b[i] | (b[i + 1] << 8)


def _s16(b: bytes, i: int) -> int:
    v = _u16(b, i)
    return v - 0x10000 if v & 0x8000 else v


def _s8(v: int) -> int:
    return v - 0x100 if v & 0x80 else v


@dataclass
class Bme280Cal:
    """Trimming parameters from registers 0x88-0xA1 and 0xE1-0xE7 (33 bytes, as in $RC)."""

    chip: int
    T: tuple[int, int, int]
    P: tuple[int, ...]
    H: tuple[int, int, int, int, int, int]

    @classmethod
    def from_bytes(cls, chip: int, b: bytes) -> Bme280Cal:
        if len(b) != 33:
            raise ValueError("BME280 calibration is 33 bytes")
        T = (_u16(b, 0), _s16(b, 2), _s16(b, 4))
        P = (_u16(b, 6), *(_s16(b, 8 + 2 * i) for i in range(8)))
        H = (b[25],                                  # dig_H1, 0xA1
             _s16(b, 26),                            # dig_H2, 0xE1-0xE2
             b[28],                                  # dig_H3, 0xE3
             (_s8(b[29]) << 4) | (b[30] & 0x0F),     # dig_H4: 0xE4[7:0] = H4[11:4], 0xE5[3:0] = H4[3:0]
             (_s8(b[31]) << 4) | (b[30] >> 4),       # dig_H5: 0xE6 = H5[11:4], 0xE5[7:4] = H5[3:0]
             _s8(b[32]))                             # dig_H6, 0xE7
        return cls(chip, T, P, H)

    def compensate(self, adc_p: int, adc_t: int, adc_h: int) -> tuple[float, float | None, float | None]:
        """(temperature C, pressure hPa or None, relative humidity % or None)."""
        T1, T2, T3 = self.T
        v1 = (adc_t / 16384.0 - T1 / 1024.0) * T2
        v2 = (adc_t / 131072.0 - T1 / 8192.0) ** 2 * T3
        t_fine = v1 + v2
        temp = t_fine / 5120.0

        P1, P2, P3, P4, P5, P6, P7, P8, P9 = self.P
        v1 = t_fine / 2.0 - 64000.0
        v2 = v1 * v1 * P6 / 32768.0
        v2 = v2 + v1 * P5 * 2.0
        v2 = v2 / 4.0 + P4 * 65536.0
        v1 = (P3 * v1 * v1 / 524288.0 + P2 * v1) / 524288.0
        v1 = (1.0 + v1 / 32768.0) * P1
        pres = None
        if v1:
            p = 1048576.0 - adc_p
            p = (p - v2 / 4096.0) * 6250.0 / v1
            v1 = P9 * p * p / 2147483648.0
            v2 = p * P8 / 32768.0
            pres = (p + (v1 + v2 + P7) / 16.0) / 100.0

        rh = None
        if self.chip == CHIP_BME280:
            H1, H2, H3, H4, H5, H6 = self.H
            h = t_fine - 76800.0
            h = (adc_h - (H4 * 64.0 + H5 / 16384.0 * h)) * (
                H2 / 65536.0 * (1.0 + H6 / 67108864.0 * h * (1.0 + H3 / 67108864.0 * h)))
            h = h * (1.0 - H1 * h / 524288.0)
            rh = min(100.0, max(0.0, h))
        return temp, pres, rh


def dew_point_c(temp_c: float, rh: float) -> float | None:
    """Magnus formula (b = 17.62, c = 243.12 C); good to ~0.1 C over -45..60 C."""
    if rh is None or rh <= 0:
        return None
    b, c = 17.62, 243.12
    g = math.log(rh / 100.0) + b * temp_c / (c + temp_c)
    return c * g / (b - g)


def sea_level_hpa(p_hpa: float, temp_c: float, altitude_m: float) -> float:
    """Station pressure reduced to sea level (the barometric formula weather reports use)."""
    return p_hpa * (1.0 - 0.0065 * altitude_m / (temp_c + 0.0065 * altitude_m + 273.15)) ** -5.257
