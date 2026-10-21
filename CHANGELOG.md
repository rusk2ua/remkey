# Changelog

Versions are per component: the Python host package (`host/`), the remkey keyer
firmware and the remtlm telemetry firmware each carry their own version.

## 2026-10-21

### Host package 0.2.0
- Tower telemetry: `$RT` readings and `$RK` transverter replies from the remtlm base
  Nano, calibration tables (mV to watts), link-loss statistics, CSV log.
- Client: Ctrl-P (tower readings), Ctrl-K (Kuhne MKU 10 G5 status and version),
  alerts for reference unlock, over-temperature and telemetry loss, peak PA power
  summary after each transmission.
- `python -m remkey.tlmview` bench viewer for calibration.

### remtlm firmware 0.2.0
- Kuhne MKU 10 G5 support: read-only serial polling (`v` at boot, `s` every
  minute), LD reference-lock on an analog input, second DS18B20 for the case.

### remtlm firmware 0.1.0
- Tower telemetry over an E220-900T22D LoRa link on 927.125 MHz: PA and
  transverter power sense (peak and average), lock input, DS18B20 temperature.

### Host package 0.1.0 / remkey firmware 0.1.0
- Remote paddle CW: client Nano decodes the paddle with local sidetone, station
  Nano re-keys with exact timing; PTT button; HMAC-authenticated TCP link;
  heartbeat and Nano watchdog safety-offs; keyboard CW and prosigns.
