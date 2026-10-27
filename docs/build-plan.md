# Build plan

A phased path from parts on the bench to a hardened remote station. Each phase ends
with something working that can be tested on its own, and nothing touches the tower
or goes on the air until the safety behaviour has been proven on the bench.

The telemetry work (phases 5–7) needs no radio connection, so it can run in parallel
with phases 1–4.

Tick the boxes as you go (edit this file on GitHub, or locally and push).

---

## Before you start: order parts

The E220 modules usually ship from China and are the slowest item, so order early.

- [x] 2× Ebyte E220-900T22D (the **900** version): arrived
- [x] 2× 915 MHz SMA antennas: homemade from UT-141 semi-rigid (λ/4 at 927.125 MHz ≈ 81 mm)
- [ ] 2× PC817 optocouplers
- [ ] 2× DS18B20 waterproof probes
- [ ] 1× BSS138 4-channel level shifter
- [ ] 1× AMS1117-3.3 module
- [ ] 1× MP1584 (or similar) 5 V buck module and a 1 A fuse
- [ ] 1× INA226 module (e.g. CJMCU-226)
- [x] 1× 20 A / 75 mV panel-meter shunt (3.75 mΩ): ordered
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

- [ ] Flash the STATION image
- [ ] Wire the two optocouplers to LEDs or a meter (**not** the radio)
- [ ] Serial monitor: `V`, `?`, `T:CQ`, `P:1` / `P:0`, `U:2000` all behave
- [ ] Run the station service against the Nano; send keyboard CW from the client over the LAN
- [ ] Safety test: kill the client's Wi-Fi with PTT on → PTT drops within 3 s
- [ ] Safety test: stop the station service with PTT on → PTT drops within 3 s (`!:WDOG`)
- [ ] Safety test: unplug the Nano's USB with PTT on → PTT drops

**Done when:** every safety test drops PTT within 3 seconds, every time.

---

## Phase 2: Client Nano and paddle

- [ ] Flash the CLIENT image
- [ ] Wire the paddle jack, PTT button and sidetone (speed pot optional: `USE_SPEED_POT 1`)
- [ ] Send at 15–20 WPM: the station's on-board LED and KEY opto follow about one character behind
- [ ] Decoded text in the client matches what was sent
- [ ] Choose iambic A or B; swap paddles if needed (`config.h`)
- [ ] Deliberately fumbled characters pass through as raw patterns (`{...}`)
- [ ] PTT button toggles station PTT; the D12 PTT LED lights at both ends
- [ ] Send a word and press PTT off right after the last character: it is keyed out in full, PTT drops about 2 s after the last element
- [ ] Press PTT off, then keep sending within 2 s: PTT stays on and everything is keyed

**Done when:** a few minutes of normal sending comes out clean on the station side,
and the PTT button and LED behave.

---

## Phase 3: Connect to the 7610, nothing going up the tower

- [ ] Disconnect or disable the tower IF feed; dummy load on the 7610's output
- [ ] Choose the PTT input: ACC SEND (if the manual confirms it accepts a ground to TX) or MIC connector PTT
- [ ] PTT opto → radio goes to TX and the DC injector puts 13 V on the IF cable
- [ ] Y-cable the KEY opto alongside the SO2R+; keying polarity correct
- [ ] N1MM+ CW through the SO2R+ still works
- [ ] BK-IN set to OFF; keying with PTT off gives sidetone only

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

## Phase 5: remtlm on the bench (parallel with phases 1–4)

- [ ] Wire both E220s and Nanos; flash TOWER and BASE
- [ ] Both print `C:ok ch=77 freq_khz=927125`
- [ ] Packets arrive at the base; `tlmview` shows them
- [ ] Spectrum check (ADALM-PLUTO, TinySA or a bench analyzer): LoRa bursts at 927.125 MHz, nothing near 902–903. With a real analyzer, look for spurs and broadband noise down at 902–903 too, with the E220 keyed into a dummy load or a short antenna
- [ ] PA sense and MON inputs: a variable voltage or pot in `tlmview` tracks a meter
- [ ] Both DS18B20s read; identified by hand-warming; `temp_names` set
- [ ] MKU on the bench: LD reads locked/unlocked correctly (or `LOCK_MONITOR 0` if no external 10 MHz reference)
- [ ] MKU serial via the level shifter: `v` and `s` replies arrive (else set `XV_CMD_SUFFIX "\r"`)
- [ ] Capture an `s` reply and send it over for parsing / serial reference-PLL alert
- [ ] INA226: remove the module's R100 (or set `SHUNT_UOHM 3614`)
- [ ] Shunt: heavy leads on the bolts, IN+ / IN- on the sense screws (IN+ supply side); shunt insulated from the enclosure
- [ ] Tower prints `I:INA226 ok`; `tlmview` shows supply voltage and current
- [ ] Bench supply plus a load (power resistor or the transverter): voltage matches a DMM, current matches a meter in series; set `v_scale` / `i_scale`
- [ ] Reverse-polarity check: current reads positive with the load on the IN- side

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
- [ ] Shunt and INA226 at the enclosure entry, ahead of everything in the box
- [ ] Ctrl-V: tower voltage at receive current: ________ V at ________ A
- [ ] Ctrl-V after some transmitting: cable loop resistance ________ mΩ (#10 ≈ 200, #12 ≈ 318), supply holding ________ V at the base
- [ ] Lowest tower voltage on transmit stays above 12.0 V (MKU rating): lowest seen ________ V
- [ ] Alerts tested: unplug a probe, interrupt the 10 MHz reference, power-cycle the tower Nano, unplug the INA226

**Done when:** the link holds overnight with negligible loss, and alerts fire correctly.

---

## Phase 8: Hardening

- [ ] Station service starts automatically (Task Scheduler, "At log on")
- [ ] Shack PC power plan: never sleep; USB selective suspend off
- [ ] Two-week soak in normal use
- [ ] Review `remkey-station.log` and `remkey-tlm.csv` for drops, watchdog events, temperature trends
- [ ] Run `python -m remkey.powerstats remkey-tlm.csv --config station.toml`; set `i_max_alert`, `i_min_alert` and `v_min_alert` from its suggestions
- [ ] README updated with real-hardware notes (PTT pin used, KEY polarity, sequencer wait, wiring changes)
- [ ] Remove the "not yet run on real hardware" status note from the README
- [ ] Tag v1.0

**Done when:** two weeks of normal use with no surprises.
