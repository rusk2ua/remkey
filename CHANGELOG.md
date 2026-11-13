# Changelog

Versions are per component: the Python host package (`host/`), the remkey keyer
firmware and the remtlm telemetry firmware each carry their own version.

## 2026-11-13

### Host package 0.8.0: cloud copy of the dashboard
- The station service can push telemetry snapshots to S3 (`cloud_bucket` in
  `station.toml`): current state every 15 s, the last hour every minute, 12 hours
  every 5 minutes. Uploads run in a worker thread with short timeouts, one at a
  time; failures are logged once (then every 10 minutes) and never touch keying.
  The remote session (client address, PTT) is left out. Optional dependency:
  `pip install -e ".[cloud]"` (boto3).
- The dashboard page has a cloud mode: polls the uploaded JSON, shows how old the
  data is, read-only.
- New `cloud/`: CloudFormation template (private S3 bucket, CloudFront with an
  ACM certificate, a CloudFront Function for the password prompt and the secret
  path, Route 53 records, an IAM user that can only write `data/`) and
  `cloud/deploy.sh` to deploy it from the Mac. CI lints both.

### Host package 0.7.0: web dashboard
- The station service can serve a live telemetry page (`dash_port = 8080` in
  `station.toml`) for another computer, tablet or phone on the home network or
  Tailscale: supply box and tower-top readings, transverter status, history
  charts (15 min to 12 h, reloaded from `remkey-tlm.csv` after a restart) and the
  alert log. Plain asyncio, HTTP and Server-Sent Events: no new dependencies,
  and the page itself loads nothing from the internet.
- Buttons: add a marker (to the station log, the alert list and the Mac client),
  reset min/max and link counts, clear the alert list. Nothing on the page can
  key the radio or reach the tower.
- Answers only `dash_allow` addresses (default: private ranges and Tailscale),
  only to IP or plain machine/`*.local`/`*.ts.net` host names (DNS-rebinding
  guard), and takes button presses only with the page's own request header. If
  the dashboard can't start, keying still comes up.
- New module `host/remkey/dashboard.py`, page `host/remkey/web/dashboard.html`,
  tests `host/tests/test_dashboard.py`; README section 9 "Web dashboard".

## 2026-11-11

### remtlm firmware 0.4.0: supply box at the tower base
- New **PSU** role (`REMTLM_ROLE ROLE_PSU`, `pio run -e psu`) for a third Nano in
  the supply box at the tower base: INA226 + shunt on the supply output (voltage
  and current going up the tower, min / avg / max per interval) and one DS18B20
  for the box temperature, sent as a new `$RS` packet with its own sequence
  number and uptime. Same pins as the tower Nano for the E220, D5 and I2C.
- Both senders share channel 77. The PSU node listens and sends its `$RS` ~60 ms
  after each tower `$RT`, in the gap before the tower's next packet; with no
  tower heard for 3.5 s it sends every 2 s on its own. It only touches the
  DS18B20 bus right after its own packet, so the bus can't garble an incoming `$RT`.
- TOWER: the INA226 is now optional and off by default (`PWR_ENABLE 0`). Turn it
  on for a second INA226 at the top and a measured cable drop.
- BASE: accepts `$RS`. **Reflash the base**: 0.3.0 rejects `$RS` as a bad packet.
- INA226 reads are more robust next to SoftwareSerial (which holds interrupts off
  ~1 ms per received byte and can time out an I2C read): the INA226 counts as
  gone only after 5 failed reads in a row (`PWR_FAIL_LIMIT`), the PSU skips I2C
  while the E220's AUX is low (a packet arriving), and the tower skips it during
  an MKU serial poll.
- `TLM_MAX_LINE` 80 → 96 (worst-case `$RS` is 80 bytes with CR/LF).
- New host-side simulation of the sketch (`tests/firmware_sim/remtlm_sim.cpp`,
  mocked E220 / OneWire / INA226), run for tower, tower with INA226, base and psu
  by `tests/firmware_sim/run.sh`. CI also builds the psu and tower-with-INA226 images.

### Host package 0.6.0
- Parses `$RS`; separate link statistics, link-up and stale alerts for the
  supply box (`tower-base supply box lost`), a box temperature alert
  (`box_temp_name`, `box_temp_warn_c`), and voltage alerts labelled by where they
  were measured (`at tower base` / `tower-top`).
- Ctrl-V / the supply line show the base supply, box temperature and link loss;
  with a top INA226 as well, the top voltage and the measured cable drop. The
  cable-resistance fit uses only top-box voltage and says so when there is none.
- CSV: new `supply_at`, `box_temp_c` and `top_v_avg` columns (an old file is
  rotated aside automatically); supply-box rows are logged while the tower is silent.
- `powerstats` fits the cable only on top-box voltage; `tlmview` shows `$RS` lines.
- New schematic `docs/img/remtlm-psu-box-schematic.svg`; README section 9 and
  the build plan (new phase 5S) cover the supply box.

## 2026-10-28

### Station launcher
- `host/Start-remkey.bat`: starts the station service from its own folder (venv if
  present, else `py`) for a Task Scheduler "At log on" task; keeps the window
  open with the exit code if the service stops. README section 4 now uses it and
  covers switching console QuickEdit off in the registry, which closes the gap
  before remkey's own QuickEdit fix runs at logon.
- `.venv/` added to `.gitignore`; `.bat`/`.cmd` files kept with CRLF line endings.

### Host package 0.5.1
- `python -m remkey.e220`: read and decode an E220-900T22D's settings, or store
  remtlm's settings (`--write`), through any 3.3 V USB serial adapter such as an
  FT232. Wiring in README section 9. (`remkey.__version__` now matches
  `pyproject.toml`.)

## 2026-10-27

### Docs
- New `docs/remote-access-tailscale-nordvpn.md`: reach the station over Tailscale
  while NordVPN stays on the shack PC. Tested on the real station: NordVPN's
  firewall blocks inbound TCP on the Tailscale adapter, so the station listens on
  127.0.0.1 and `tailscale serve` publishes it to the tailnet. Also covers NordVPN
  settings (kill switch, Meshnet, why not to split-tunnel `tailscaled`), Mac/iPad
  limits, other station software, and a pre-trip test list. README section 5 now
  recommends Tailscale; `station.example.toml` defaults to `127.0.0.1`.

## 2026-10-26

### remkey firmware 0.4.1
- Long paddle runs now stream instead of waiting for the paddle to be released.
  A held dah paddle never leaves the 2-dit gap that ends a character, so the
  whole run used to sit in the decoder and was cut to 10 elements. Now, when a
  6th dah follows `-----`, the five go out as a `0` and the run continues, so
  the far end hears `0 0 0 ...` about one group behind, then the leftover (T, M,
  O or `{----}`) when you stop. Any other run that fills the 10-element buffer
  goes out as a raw pattern and continues, so nothing is dropped. Client Nano
  only; the station and host are unchanged. Simulation tests added.

### remkey firmware 0.4.0
- Fix: the station watchdog could fire spuriously right after a heartbeat. The
  heartbeat stamps `lastRxMs` with `millis()`, which can be a tick later than the
  loop's `now`; the unsigned `now - lastRxMs` then wrapped to ~4.29e9 and dropped
  PTT with `!:WDOG`. More serial traffic (CW text) made it much more likely. The
  comparison is now signed. Simulation regression test added.
- PTT input reports both edges: `B:P` when it closes, `B:R` when it opens, and
  `B:H` at power-up if it is already closed (instead of a phantom press).

### Host package 0.5.0
- Client: `ptt_switch = "latching"` in `client.toml` for an SPST toggle switch.
  Station PTT follows the switch; switch off is the graceful release. After a
  safety stop with the switch still ON, the client says so and waits for the
  switch to be cycled; a switch left ON at startup never keys. Default stays
  `"momentary"` (press toggles).
- Station: turns off Windows console QuickEdit at startup, so a stray click in
  the service window can no longer freeze it (and trip the Nano watchdog).
- Client: a connection timeout now prints `TimeoutError` instead of a blank
  `station link:` message.

## 2026-10-25

### remkey firmware 0.3.0
- PTT-off is a graceful release: queued CW is keyed out, then PTT is held for
  `PTT_HANG_MS` (2 s; the station service sets it with `J:<ms>`), restarted by any
  CW arriving meanwhile. `O` drops PTT immediately; the watchdog stays immediate.
- The Nano reports actual PTT output changes (`P:1` / `P:0`).
- Client: the PTT button reports a just-finished character before `B:P`.

### Host package 0.4.0
- Station: graceful release via the Nano; safety stops use `O`; `ptt_hang_ms` in
  `station.toml`; PTT state comes from the Nano's reports; Esc during a release
  drops PTT at once.
- Client: shows "releasing"; PTT pressed during a release keeps PTT on; quitting
  waits for the release (Ctrl-Q twice to force).

### remkey firmware 0.2.0
- On-board LED (D13) flashes with the CW being sent on both roles; polarity set by
  `LED_ACTIVE_LOW` (default 1).
- PTT indication moved to an optional external LED on D12.

## 2026-10-21 (later)

### remtlm firmware 0.3.0
- INA226 supply monitor on I2C: voltage at the tower enclosure and current through
  a high-side shunt, min/max/average per interval, sent as `$RP` packets.

### Host package 0.3.0
- Supply readings in the client (Ctrl-V, Ctrl-P, after-TX summary), alerts for
  low/high voltage, high/low current and INA226 failure, CSV columns.
- Cable loop resistance and supply voltage at the base, fitted from the readings,
  with a wire-gauge check.
- `python -m remkey.powerstats`: receive/transmit supply statistics from the CSV
  log and suggested alert limits.
- Default shunt is a 20 A / 75 mV panel-meter shunt (`SHUNT_UOHM 3750`, 21.8 A full scale).

### Fixes
- remkey firmware: keyer enums moved to `keyer_types.h` so the Arduino build's
  generated prototypes compile (CI failure on the client and station images).
- README: the 927 MHz link is part of the amateur station (Part 97), not Part 15.

## 2026-10-21

### Docs
- `docs/build-plan.md`: phased build checklist.

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
