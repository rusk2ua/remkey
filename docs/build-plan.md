# Build plan

A phased path from parts on the bench to a hardened remote station. Each phase ends
with something working that can be tested on its own, and nothing touches the tower
or goes on the air until the safety behaviour has been proven on the bench.

The telemetry work (phases 5–7, and 5S for the supply box at the tower base) needs no
radio connection, so it can run in parallel with phases 1–4. Phase 5S can go first:
the supply box works on its own, before the tower-top box exists.

Tick the boxes as you go (edit this file on GitHub, or locally and push).

---

## Before you start: order parts

The E220 modules usually ship from China and are the slowest item, so order early.

- [x] 2× Ebyte E220-900T22D (the **900** version): arrived
- [x] 2× 915 MHz SMA antennas: homemade from UT-141 semi-rigid (λ/4 at 927.125 MHz ≈ 81 mm)
- [x] 2× PC817 optocouplers: 2-channel board; remove all four `302` resistors (README section 1)
- [ ] 2× DS18B20 waterproof probes
- [ ] 1× BSS138 4-channel level shifter
- [ ] 1× AMS1117-3.3 module
- [ ] 1× MP1584 (or similar) 5 V buck module and a 1 A fuse
- [ ] 1× INA226 module (e.g. CJMCU-226): supply box at the tower base
- [x] 1× 20 A / 75 mV panel-meter shunt (3.75 mΩ): ordered
- [ ] Supply box: 3rd Nano, 3rd E220 + antenna, 1× DS18B20, 5 V buck + 1 A fuse
- [ ] Optional later: a 2nd INA226 + shunt for the tower-top box (measured cable drop)
- [ ] Weatherproof box with cable glands
- [ ] 4× Nanos, resistors (1 k, 2 k, 4.7 k, 10 k, 22 k, 100 k, 470 Ω), 100 nF and 100 µF caps (likely on hand)

---

## Phase 0: No new hardware

Prove the software path and audio before soldering anything.

- [x] Install the station service on the shack PC; run it with `--dry-run`
- [x] Install the client on a Mac; run it with `--dry-run`
- [x] Connect them over the house LAN; the station log shows typed CW and PTT commands
- [x] Set up Tailscale with NordVPN on the shack PC ([remote-access-tailscale-nordvpn.md](remote-access-tailscale-nordvpn.md))
- [x] Connect from the phone hotspot (Tailscale; or router port-forward / AnyDesk tunnel)
- [x] Set up AnyDesk audio from the 7610's USB codec (see README, Audio)
- [ ] Set up DVI capture of the 7610's screen (capture card and OBS installed; DVI-to-HDMI cable on order)
- [ ] **Sidetone test:** BK-IN off, key locally, confirm the radio's sidetone is in the USB audio stream
- [ ] Add N1MM+ RF power preset macros (`{CAT1HEX ...}`)

**Done when:** you can see the radio's screen and hear its receiver remotely, and the
client and station talk to each other from outside the house.

---

## Phase 1: Station Nano on the bench

- [x] Flash the STATION image
- [x] Wire the two optocouplers to LEDs or a meter (**not** the radio)
- [x] Serial monitor: `V`, `?`, `T:CQ`, `P:1` / `P:0`, `U:2000` all behave
- [x] Run the station service against the Nano; send keyboard CW from the client over the LAN
- [x] Safety test: kill the client's Wi-Fi with PTT on → PTT drops within 3 s
- [x] Safety test: stop the station service with PTT on → PTT drops within 3 s (`!:WDOG`)
- [x] Safety test: unplug the station Nano's USB with PTT on → PTT drops at once
- [x] Safety test: unplug the client Nano's USB with PTT on → PTT released gracefully; the paddle works again when plugged back in

**Done when:** every safety test drops PTT within 3 seconds, every time.

---

## Phase 2: Client Nano and paddle

- [x] Flash the CLIENT image
- [x] Wire the paddle jack, PTT button and sidetone (speed pot optional: `USE_SPEED_POT 1`)
- [x] Send at 15–20 WPM: the station's on-board LED and KEY opto follow about one character behind
- [x] Decoded text in the client matches what was sent
- [ ] Choose iambic A or B; swap paddles if needed (`config.h`)
- [ ] Deliberately fumbled characters pass through as raw patterns (`{...}`)
- [x] PTT button toggles station PTT; the D12 PTT LED lights at both ends
- [x] Send a word and press PTT off right after the last character: it is keyed out in full, PTT drops about 2 s after the last element
- [x] Press PTT off, then keep sending within 2 s: PTT stays on and everything is keyed

**Done when:** a few minutes of normal sending comes out clean on the station side,
and the PTT button and LED behave.

---

## Phase 3: Connect to the 7610, nothing going up the tower

- [ ] Disconnect or disable the tower IF feed; dummy load on the 7610's output
- [x] Choose the PTT input: SO2R+ rear RCA PTT footswitch jack
- [x] PTT opto → radio goes to TX and the DC injector puts 13 V on the IF cable
- [x] Y-cable the KEY opto alongside the SO2R+; keying polarity correct
- [x] N1MM+ CW through the SO2R+ still works
- [x] BK-IN set to OFF; keying with PTT off gives sidetone only

**Done when:** remote PTT and keying behave exactly like pressing TRANSMIT and using
the paddle at the radio, and N1MM+ is unaffected.

---

## Phase 4: On the air, remote

- [ ] Reconnect the tower
- [ ] Test from the house over the phone hotspot (schedule with a nearby 10 GHz station, or a local receiver)
- [ ] Determine the wait needed after PTT before keying (MKU sequencer default 50 ms, plus PA/relay)
- [ ] Real away-from-home session (hotel or a friend's internet)
- [ ] Note the RTT (Ctrl-G) on a poor connection: ________ ms

**Done when:** you've completed a QSO from away.

---

## Phase 5S: Supply box at the tower base (can go first)

The PSU Nano: INA226 and shunt on the supply output, one DS18B20, its own E220. See
README section 9, "Wiring: supply box at the tower base".

- [ ] Flash the BASE Nano with remtlm 0.4.0 or later (older base firmware rejects `$RS`)
- [ ] Flash the PSU image (`REMTLM_ROLE ROLE_PSU`, or `pio run -e psu`)
- [ ] Bench: PSU prints `C:ok ch=77 freq_khz=927125`, `I:temperature probes=1`, `I:INA226 ok`
- [ ] INA226: remove the module's R100 (or set `SHUNT_UOHM 3614`)
- [ ] Bench supply plus a load: `$RS` voltage matches a DMM, current matches a meter in series
- [ ] Reverse-polarity check: current reads positive with the load on the IN- side
- [ ] `tlmview` on the base Nano shows `BASE supply` lines every 2 s; box temperature sensible
- [ ] In the box: shunt in the supply (+) output ahead of the tower cable, on standoffs, terminals covered; IN+ supply side
- [ ] Box 5 V tapped on the supply side of the shunt (fuse → buck), not from VIN
- [ ] Station service: `-- tower-base supply box link up`; Ctrl-V shows `supply at tower base: … V | … A | supply box … C`
- [ ] Receive current at the base: ________ A at ________ V
- [ ] Transmit current at the base: ________ A peak
- [ ] `v_min_alert` set for the base voltage (e.g. 13.5) until a top INA226 exists
- [ ] Unplug the PSU Nano: `!! tower-base supply box lost` after `tlm_stale_s`
- [ ] Later, once the tower box is up: PSU prints `I:tower heard, sending in its gaps`; loss on both links stays near zero

**Done when:** Ctrl-V shows the tower's supply voltage and current from the house, and the
box's link loss stays near zero overnight.

---

## Phase 5: remtlm on the bench (parallel with phases 1–4)

- [x] Optional: check each E220 with the FT232 adapter (README section 9): `python -m remkey.e220 --port ... --write` reads back channel 77, 9.6 kbps, 17 dBm
- [ ] Wire both E220s and Nanos; flash TOWER and BASE
- [ ] Both print `C:ok ch=77 freq_khz=927125`
- [ ] Packets arrive at the base; `tlmview` shows them
- [ ] Spectrum check (ADALM-PLUTO, TinySA or a bench analyzer): LoRa bursts at 927.125 MHz, nothing near 902–903. With a real analyzer, look for spurs and broadband noise down at 902–903 too, with the E220 keyed into a dummy load or a short antenna
- [ ] PA sense and MON inputs: a variable voltage or pot in `tlmview` tracks a meter
- [ ] Both DS18B20s read; identified by hand-warming; `temp_names` set
- [ ] MKU on the bench: LD reads locked/unlocked correctly (or `LOCK_MONITOR 0` if no external 10 MHz reference)
- [ ] MKU serial via the level shifter: `v` and `s` replies arrive (else set `XV_CMD_SUFFIX "\r"`)
- [ ] Capture an `s` reply and send it over for parsing / serial reference-PLL alert
- [ ] Optional top-box INA226 (`PWR_ENABLE 1`): R100 removed, shunt wired and insulated, tower prints `I:INA226 ok`, readings match a DMM
- [ ] With the supply box running too: its `$RS` packets follow each tower `$RT` (`tlmview`), no extra loss on either link

**Done when:** `tlmview` shows sensible readings, both temperatures, lock state and the
MKU's replies, with near-zero packet loss on the bench.

---

## Phase 6: Calibration (bench, with the PA)

- [ ] Measure the buck converter's 5 V rail; set `VREF_MV`; reflash TOWER
- [ ] Power meter and attenuator on the PA output
- [ ] Record meter watts vs `tlmview` `PA pk` mV at four or five drive levels

  | Drive | Meter (W) | PA pk (mV) | MON (mV) |
  |---|---|---|---|
  | | | | |
  | | | | |
  | | | | |
  | | | | |
  | | | | |

- [ ] Enter `pa_cal` (and `xv_cal` for MON) in `station.toml`
- [ ] Ctrl-P watts agree with the meter across the range

**Done when:** Ctrl-P shows watts that agree with the meter.

---

## Phase 7: Tower installation

- [ ] Tower Nano, E220 and level shifter in the weatherproof box
- [ ] 13.8 V → fuse → buck converter; probes mounted with thermal compound (PA heatsink, MKU case)
- [ ] Cables dressed and glands sealed
- [ ] Base Nano and antenna in their final position (best view of the tower)
- [ ] Range test through the block wall: packet loss over one hour: ________ %
- [ ] Step `LORA_TX_POWER` down to the lowest setting with under ~1% loss: ________
- [ ] Long carrier: heatsink and case temperatures noted; thresholds adjusted if needed
- [ ] Optional top INA226: shunt at the enclosure entry, ahead of everything in the box
- [ ] With the top INA226, Ctrl-V: top voltage at receive current ________ V at ________ A; measured cable drop ________ V
- [ ] With the top INA226, after some transmitting: cable loop resistance ________ mΩ (#10 ≈ 200, #12 ≈ 318)
- [ ] Lowest tower voltage on transmit stays above 12.0 V (MKU rating): lowest seen ________ V (estimated from the table without a top INA226)
- [ ] Alerts tested: unplug a probe, interrupt the 10 MHz reference, power-cycle the tower Nano, unplug an INA226

**Done when:** the link holds overnight with negligible loss, and alerts fire correctly.

---

## Phase 8: Hardening

- [x] Station service starts automatically (Task Scheduler "At log on" → `host\Start-remkey.bat`)
- [ ] Console QuickEdit off for the station user (`reg add HKCU\Console /v QuickEdit /t REG_DWORD /d 0 /f`)
- [ ] Reboot test: before touching the window, a client connects and keys PTT; log lines appear without pressing Enter
- [ ] Shack PC power plan: never sleep; USB selective suspend off
- [ ] Two-week soak in normal use
- [ ] Review `remkey-station.log` and `remkey-tlm.csv` for drops, watchdog events, temperature trends
- [ ] Run `python -m remkey.powerstats remkey-tlm.csv --config station.toml`; set `i_max_alert`, `i_min_alert` and `v_min_alert` from its suggestions
- [ ] README updated with real-hardware notes (PTT pin used, KEY polarity, sequencer wait, wiring changes)
- [ ] Remove the "not yet run on real hardware" status note from the README
- [ ] Tag v1.0

**Done when:** two weeks of normal use with no surprises.
