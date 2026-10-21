# remkey — remote paddle CW for the IC-7610 (or any rig with a KEY jack)

[![CI](https://github.com/rusk2ua/remkey/actions/workflows/ci.yml/badge.svg)](https://github.com/rusk2ua/remkey/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> **Status:** the software is complete and tested in CI (simulation, end-to-end network tests, and firmware builds for every Nano image), but it has **not yet been run on real hardware**. Sections 7 and 9 have the first-power-up checklists. Reports from real stations are very welcome.

Send CW with your own paddle from anywhere, with an instant local sidetone, and have the shack re-key it with perfect timing. Remote PTT (the TRANSMIT button) included.

remkey is built for a station where:

- A Windows PC in the shack already runs N1MM+, rig control and rotator control, and you reach it with AnyDesk.
- The 7610 drives a tower-mounted 10 GHz transverter through its SEND line, so PTT is manual and keying is CW.
- You travel with a Mac and want to use a real paddle.

It is two Arduino Nanos running the same sketch, plus a small Python bridge. An optional second pair of Nanos (**remtlm**, section 9) brings tower-top PA power, temperatures, reference lock and Kuhne transverter status into the radio room over a LoRa link.

**Quick start:** wire and flash the Nanos (sections 1–3), run the station service on the shack PC (section 4), pick a network path (section 5), and run the client on your Mac (section 6). Do the bench test (section 7) before connecting anything to the tower.

```
  TRAVEL END (Mac)                                         SHACK (Windows PC)
 ┌───────────────────────┐                              ┌──────────────────────────┐
 │ paddle ─┐             │                              │                          │
 │ PTT btn ┼─► CLIENT    │ USB  remkey.client   TCP/JSON │ remkey.station   USB      │
 │ speaker◄┘   Nano      ├────► (Python)  ─────────────────► (Python)  ──────► STATION │
 │  (local sidetone,     │      keyboard CW,  internet   │  auth, heartbeat,  Nano  │
 │   decodes paddle      │      hotkeys       (port-fwd  │  safety-off on     │     │
 │   to characters)      │                     or AnyDesk│  link loss         │     │
 └───────────────────────┘                     tunnel)   │       opto ─► KEY jack   │
                                                         │       opto ─► PTT/SEND   │
                                                         │  N1MM+ / SO2R+ untouched │
                                                         └──────────────────────────┘
```

## Why it works this way

Sending raw key-down/key-up events across the internet doesn't work: network jitter stretches and chops your dits and dahs. remkey splits the job instead:

1. **At your end,** the client Nano is a normal iambic keyer with its own sidetone. You hear yourself with zero latency. It decodes each character you send and reports it over USB, for example `K:C`.
2. **Characters** cross the network, not element timing.
3. **At the shack,** the station Nano re-sends each character with exact timing on an optocoupler across the 7610's KEY line.

The radio transmits each character roughly one character-time after you send it. That's under a second at 15–20 WPM, which doesn't matter on 10 GHz. You still hear the radio's real sidetone in the remote audio stream (delayed), so you can confirm what actually went out.

Anything the decoder doesn't recognise, such as SK or a fumbled character, is passed through as a raw element pattern like `{...-.-}`. The station sends it element-for-element, so nothing is lost or "corrected."

## Contents

```
firmware/remkey/remkey.ino     Nano sketch (both roles)
firmware/remkey/config.h       role, pins, defaults
firmware/platformio.ini        optional PlatformIO/VS Code build
firmware/remtlm/               tower telemetry over LoRa (tower + base roles), section 9
host/remkey/station.py         shack service (Windows)
host/remkey/client.py          travel client (macOS; Linux works too)
host/remkey/protocol.py        network protocol, CW text sanitiser
host/remkey/telemetry.py       remtlm packet parsing, calibration, link statistics
host/remkey/tlmview.py         bench viewer for calibrating the PA power sense
host/*.example.toml            config templates
host/tests/                    pytest: protocol, end-to-end over localhost, telemetry
tests/firmware_sim/            g++ simulation of the sketch (timing, decoder, watchdog)
.github/workflows/ci.yml       CI: Python on Linux/Windows/macOS, simulation, firmware builds
CHANGELOG.md                   per-component versions and changes
CONTRIBUTING.md, SECURITY.md   how to run the checks; security model and reporting
```

---

## 1. Hardware

### Parts

| Qty | Part | Notes |
|---|---|---|
| 2 | Arduino Nano (ATmega328P) | Clones are fine. CH340 USB chips need no driver on current macOS or Windows. |
| 2 | PC817 (or 4N25/4N35) optocoupler | Station only: one for KEY, one for PTT |
| 2 | 470 Ω resistor | Opto LED current, about 8 mA |
| 1 | 3.5 mm stereo jack | Client paddle input |
| 1 | Momentary pushbutton or footswitch | Client PTT |
| 1 | Piezo sounder or small speaker + 100 µF cap | Client sidetone; or feed a headphone amp |
| 1 | 220 Ω resistor | Sidetone series resistor |
| 1 | 10 kΩ pot (optional) | Client speed knob. Set `USE_SPEED_POT 1`. |
| — | Cables to the 7610 KEY jack and PTT line | Station |

### Client Nano (travel keyer)

```
Paddle jack tip  (dit) ──── D2        (internal pull-up; contact to GND)
Paddle jack ring (dah) ──── D3
Paddle jack sleeve ──────── GND
PTT button ──────────────── D4 ── button ── GND
D9 ── 220 Ω ── piezo(+)     piezo(−) ── GND
     (or D9 ── 220 Ω ── 100 µF ── small amp/headphone input; 10 k to GND for level)
Optional speed pot: ends to 5V/GND, wiper ── A0
LED on D13 lights when the STATION confirms PTT is on
```

Swap paddles in `config.h` (`SWAP_PADDLES`) instead of rewiring.

### Station Nano (shack)

```
            ┌──────────── PC817 #1 ─────────────┐
D10 ─ 470Ω ─┤1 anode               collector  4 ├── KEY line (tip) ──► 7610 KEY
GND ────────┤2 cathode             emitter    3 ├── KEY ground (sleeve)
            └───────────────────────────────────┘
            ┌──────────── PC817 #2 ─────────────┐
D11 ─ 470Ω ─┤1 anode               collector  4 ├── PTT/SEND-in line ──► 7610
GND ────────┤2 cathode             emitter    3 ├── chassis ground
            └───────────────────────────────────┘
```

The optocouplers keep the Nano and PC USB ground galvanically separate from the radio, which matters on a station with a tower.

**KEY connection.** Both the SO2R+ and the remkey optocoupler are open-collector closures to ground, so they can safely share one line. Either:

- Y-cable the opto output in parallel with the SO2R+ keying output on the rear KEY jack (simplest; N1MM+ keeps working), or
- use the 7610's other key jack, configured for a straight key / external keyer.

Collector goes to the key line (tip), emitter to ground (sleeve). If keying does nothing, reverse it.

**PTT connection.** The opto has to put the *radio* into transmit, just like your TRANSMIT button. Your DC injector stays on the radio's SEND output and keeps working unchanged. Use an input that forces TX:

- **ACC socket SEND line:** on many Icom rigs this pin is bidirectional (it goes low on TX, and grounding it forces TX). Check the IC-7610 full manual's ACC pinout before wiring.
- **Front MIC connector PTT pin:** always a TX input. Check the manual for the pin number.

Do **not** wire the opto to the SEND output that drives your DC injector. That would key the transverter without the radio being in transmit.

---

## 2. Radio settings (IC-7610)

- **Break-in: OFF while operating remotely.** Then nothing goes up the IF cable unless PTT is on, which matches how you already operate (TRANSMIT first, then key). It also means stray keying with PTT off produces sidetone only.
- The jack the opto keys must be set for a **straight key / external keyer**, not paddles. The station Nano is the keyer.
- Keep the 7610's USB audio codec streaming to the shack PC so you can hear receive audio (and the radio's sidetone) through AnyDesk. See section 6.

---

## 3. Firmware

Build with the Arduino IDE (board **Arduino Nano**; processor "ATmega328P", or "Old Bootloader" for most clones) or with PlatformIO in VS Code.

**Arduino IDE.** Open `firmware/remkey/remkey.ino`. In `config.h`, set

```c
#define REMKEY_ROLE ROLE_CLIENT     // for the travel Nano
#define REMKEY_ROLE ROLE_STATION    // for the shack Nano
```

and upload each.

**PlatformIO:**

```
cd firmware
pio run -e client  -t upload --upload-port /dev/cu.usbserial-110
pio run -e station -t upload --upload-port COM7
```

**Check it.** Open a serial monitor at 115200 baud with line ending set to newline. You should see `V:remkey 0.1.0 client` (or `station`). Type `?` to get a status line. On the client, send a few characters with the paddle and you'll see `K:` lines. On the station, `T:CQ` keys the opto and `P:1` / `P:0` drive PTT.

Station watchdog: with PTT on or text queued, if the Nano hears nothing from the PC for 3 s it drops PTT, flushes text and prints `!:WDOG`. The service sends a heartbeat every second, so this only fires if the service or PC hangs.

The serial command set is documented at the top of `remkey.ino`.

---

## 4. Shack PC: station service (Windows)

1. Install Python 3.11+ from python.org (tick "Add to PATH").
2. Install remkey:
   ```
   cd remkey\host
   py -m pip install -e .
   ```
3. Configure:
   ```
   py -m remkey.genkey                  (copy the output)
   copy station.example.toml station.toml
   ```
   Edit `station.toml`: paste the secret and set `keyer_port` to the station Nano's COM port (Device Manager → Ports; *not* the SO2R+ or 7610 port).
4. Test without hardware:
   ```
   py -m remkey.station --config station.toml --dry-run
   ```
5. Run for real:
   ```
   py -m remkey.station --config station.toml
   ```
6. To start it automatically, create a Task Scheduler task "At log on" running `py -m remkey.station --config C:\path\station.toml` with "Start in" set to the `host` folder.

The service logs to the console and `remkey-station.log`. It accepts one client at a time.

---

## 5. Getting from the road to the shack

The client makes one outbound TCP connection. Pick either option; both work with the same software.

### Option A: router port-forward (free)

- On the Spectrum router, forward **TCP 7373** to the shack PC's LAN IP. Give the PC a DHCP reservation first.
- Windows Defender Firewall: allow inbound TCP 7373 for `python.exe`. Windows usually prompts on first run.
- In `station.toml`, set `listen_host = "0.0.0.0"`.
- In `client.toml`, set `station_host` to your public IP. Check it from the shack PC over AnyDesk if it ever changes.

**Security model:** a challenge-response HMAC with your secret (a fresh nonce every connection, so it can't be replayed), one client at a time, and a CW text whitelist. Traffic isn't encrypted. CW text isn't secret, and the risky operation is PTT, which needs the secret. Use a long generated secret.

### Option B: AnyDesk TCP tunnel (nothing exposed on the router)

This requires an AnyDesk plan that includes TCP tunneling.

1. In `station.toml`, set `listen_host = "127.0.0.1"`.
2. In AnyDesk on the Mac, open the shack PC's entry and choose **TCP tunnel → forward**: local port 7373 → `127.0.0.1:7373` on the remote side.
3. In `client.toml`, set `station_host = "127.0.0.1"`. The tunnel exists only while the AnyDesk session is open.

---

## 6. Mac: client

1. Install Python 3.11+ (`brew install python`), then:
   ```
   cd remkey/host
   python3 -m pip install -e .
   cp client.example.toml client.toml
   ```
   Paste the same secret, and set `station_host`, `station_port` and `keyer_port` (`ls /dev/cu.usbserial-* /dev/cu.usbmodem*`).
2. Run it in a terminal window:
   ```
   python3 -m remkey.client --config client.toml
   ```
   Without the travel Nano you still get keyboard CW: add `--dry-run`.

### Hotkeys

| Key | Action |
|---|---|
| PTT button on the keyer, or **Ctrl-T** | Toggle station PTT (the LED lights when the station confirms) |
| **Esc** | Abort queued text and any tune carrier |
| **Ctrl-U** | Tune carrier (`tune_ms`, capped by the station). Needs PTT on. |
| **Ctrl-F / Ctrl-S** | Speed +1 / −1 WPM, both ends |
| **Ctrl-G** | Status: link, PTT, WPM, round-trip time (plus tower telemetry if fitted) |
| **Ctrl-P** | Tower: PA power, transverter power, temperatures, 10 MHz reference lock |
| **Ctrl-K** | Tower: Kuhne MKU 10 G5 status (`s`) and firmware version (`v`) |
| **Ctrl-Q / Ctrl-C** | Quit. PTT is dropped first. |
| Typing | Sent as CW. Enter sends a space. `<SK>`, `<AR>`, `<BT>`, `<KN>` send prosigns. |

### A typical 10 GHz QSO

1. In AnyDesk, set the frequency and point the dish with GH Everyware as usual.
2. Press the PTT button. Wait for the LED (station confirmed), then wait for the tower sequencer as you would locally.
3. Send with the paddle. Your local sidetone paces you; the remote audio lets you confirm.
4. Press the PTT button again to receive. Any queued text is flushed the moment PTT drops.

### Audio

The receive audio path is independent of remkey. The zero-setup option is AnyDesk's own audio transmission: on the shack PC, set the 7610's USB audio CODEC output to play through the default playback device (Sound → Recording → USB Audio CODEC → Properties → Listen → "Listen to this device"). Before relying on it, confirm the radio's CW sidetone is present in that stream: key the rig locally with BK-IN off and listen.

### Safety layers

Every one of these drops PTT and flushes queued text:

| Event | Where |
|---|---|
| Client quits | client sends PTT off |
| TCP connection closes or errors | station service |
| No heartbeat from the client for 3 s (dead hotel Wi-Fi, laptop sleeps) | station service |
| Station service or PC hangs, USB unplugged | station Nano watchdog (3 s) |
| Tune carrier | capped by the service (`max_tune_ms`) and the firmware (30 s hard cap) |

Paddle characters sent while the link is down are **dropped**, not buffered, so stale CW never goes out minutes later.

---

## 7. Bench test before connecting to the tower

1. Station Nano on the PC, opto outputs to a multimeter (continuity) or LEDs, not the radio yet.
2. Run the service, connect the client on the same LAN (`station_host` = the PC's LAN IP), and check:
   - PTT button → PTT opto closes, client LED on.
   - Paddle → KEY opto follows about one character behind; local sidetone is immediate.
   - Kill the client's Wi-Fi with PTT on → PTT opens within 3 s.
   - Stop the service with PTT on → the Nano opens PTT within 3 s (`!:WDOG`).
3. Connect to the 7610 into a dummy load at the IF with the transverter disabled. Check KEY polarity and PTT.
4. Test from your phone's hotspot over the port-forward or tunnel.

---

## 8. Development

```
cd host && python3 -m pip install -e ".[test]" ruff && ruff check . && python3 -m pytest -q
tests/firmware_sim/run.sh       # needs g++; runs the sketch against a mock Arduino
```

GitHub Actions runs all of this on every push and pull request, plus an `arduino-cli` build of all four firmware images. The resulting `.hex` files are attached to each CI run as artifacts. See CONTRIBUTING.md.

The firmware simulation checks:

- PARIS at 20 WPM takes exactly 46 units with 22 units of key-down.
- Raw patterns and word spacing.
- Iambic A/B squeeze behaviour.
- Paddle decode of `CQ TEST K2UA`, and unknown patterns.
- Tune timing and the 30 s cap.
- The watchdog, with and without heartbeats.
- PTT button debounce.
- That the client paddle never drives the KEY output.

Every firmware image builds with no warnings in the project's own files (`arduino-cli`, board Arduino Nano, `--warnings all`):

| Image | Flash | Static RAM |
|---|---|---|
| remkey client / station | 7.9 KB of 30 KB | 541 B of 2 KB |
| remtlm tower | 15.2 KB | 774 B |
| remtlm base | 7.3 KB | 446 B |

Library versions used in CI: EByte LoRa E220 library 1.0.8, OneWire 2.3.8, DallasTemperature 4.0.6.

## 9. Tower telemetry (remtlm)

A second pair of Nanos brings tower-top readings into the radio room over a LoRa link. It's set up for a **Kuhne MKU 10 G5** transverter and an external PA:

- **PA power sense** (0–5 V), peak and average, sampled every 5 ms so CW dits aren't missed
- **MKU MON** output (CON1 pin 9), the transverter's own power monitor
- **10 MHz reference lock** from the MKU's LD output (CON1 pin 16); any unlock during a reporting interval is reported
- **Two DS18B20 probes**: PA heatsink and MKU case
- **The MKU's serial status**: the `v` (firmware) reply once after boot, then the `s` (status) reply every minute, relayed verbatim

```
 TOWER TOP (13.8 V supply)                                  RADIO ROOM
┌──────────────────────────────────────────┐            ┌──────────────────────────────┐
│ PA sense ─────────► A0 ┐                  │  927.125   │ E220 ─► BASE Nano ─USB─► PC   │
│ MKU pin 9 MON ────► A1 │                  │    MHz     │  validates packets   station  │
│ MKU pin 16 LD ────► A2 ├─ TOWER ─► E220 ~~~~~~~~~~~~~~►│                      service  │
│ DS18B20 ×2 ───────► D5 │   Nano           │    LoRa    │  ─► client: Ctrl-P, Ctrl-K,   │
│ MKU pins 11/12 ◄──► D11/D12 (via shifter)│            │     alerts, TX peak summary   │
└──────────────────────────────────────────┘            └──────────────────────────────┘
```

There is no conductor between the tower and the house, so the link adds no lightning path. Everything ends up in the same station service and Mac client as remkey.

**The transverter link is read-only.** The tower only ever sends `s` and `v`, which read status, never the configuration commands (`IR`/`IT`/`RR`/`RT`/`D1`–`D4`). A garbled byte can't retune the IF or change the sequencer.

### Frequency and legality

- The link runs on **927.125 MHz** (E220-900T22D channel 77, set by `LORA_CHANNEL` in `firmware/remtlm/config.h`). That's the top of the US 902–928 MHz band and about 24 MHz clear of 902–903 weak-signal work.
- Packets are plain ASCII with no encryption, and every packet carries your callsign. That keeps the link legal whether you treat it as a Part 15 device or as a Part 97 station.
- Transmit power defaults to 17 dBm, which is plenty for 200 ft through block. Raise it with `LORA_TX_POWER` if the link is marginal.

### Parts

| Qty | Part | Notes |
|---|---|---|
| 2 | Ebyte E220-900T22D | Both ends must be the **900** version |
| 2 | 915 MHz antenna (SMA) | A whip is fine; a small yagi at the house end if needed |
| 2 | Arduino Nano | |
| 6+6 | 1 kΩ and 2 kΩ resistors | 5 V → 3.3 V dividers on E220 M0, M1 and RXD, at each end |
| 2 | 100 µF electrolytic | Across the E220 VCC/GND pins (TX current peaks) |
| 1 | 5 V buck module (MP1584 or similar) + 1 A fuse | Tower: 13.8 V → 5 V |
| 1 | AMS1117-3.3 module (or any 3.3 V LDO) | Tower: low-voltage side of the level shifter |
| 1 | 4-channel BSS138 level-shifter module | Tower: Nano ↔ MKU serial (3.3 V) |
| 2 | DS18B20 waterproof probes + one 4.7 kΩ resistor | Tower: both on one bus |
| 2 | 10 kΩ + 22 kΩ resistors, 100 nF caps | Tower: input dividers for A0 and A1 |
| 1 | 100 kΩ resistor | Tower: pull-down on A2 (LD) |
| — | 2.54 mm female header/jumper wires | Tower: to MKU CON1 |
| 1 | Weatherproof box with cable glands | Tower |

### Wiring: E220 to Nano (same at both ends)

The E220's logic is 3.3 V and not every pin is 5 V tolerant, so the three Nano outputs go through dividers.

```
E220 pin   Nano
M0   ◄──── 2k ──┬── 1k ──── D9        (each divider: Nano ─1k─┬─ E220 pin
M1   ◄──── 2k ──┼── 1k ──── D10                               └─2k─ GND)
RXD  ◄──── 2k ──┼── 1k ──── D8
            GND ┘
TXD  ─────────────────────► D7
AUX  ─────────────────────► D6
VCC  ── 5 V ── 100 µF ── GND
GND  ── GND
```

### Wiring: tower Nano to the MKU 10 G5 and PA

```
13.8 V ── 1 A fuse ── buck (5.0 V) ──► Nano 5V pin (not VIN), E220 VCC, DS18B20s, shifter HV
                     5.0 V ── AMS1117-3.3 ──► shifter LV

PA sense      ── 10k ──┬── A0       MKU CON1 pin 9 (MON) ── 10k ──┬── A1
                       ├─ 22k ─ GND                                ├─ 22k ─ GND
                       └─ 100nF ─ GND                              └─ 100nF ─ GND

MKU CON1 pin 16 (LD) ─────────┬── A2        LD is 3.3 V via 330 Ω when locked; the
                              └─ 100k ─ GND  pull-down holds A2 low otherwise

MKU CON1 pin 11 (TXD) ── shifter LV1 ═ HV1 ── D11
MKU CON1 pin 12 (RXD) ── shifter LV2 ═ HV2 ── D12
MKU CON1 pin 15 (GND) ── GND                (common ground with the Nano)

DS18B20 #1 and #2: red 5V, black GND, both yellow ── D5; one 4.7k from D5 to 5V
```

**Notes:**

- **Why analog for LD:** a 5 V Nano needs about 3.0 V to read a digital high, and LD gives only 3.3 V through 330 Ω. That's too close, so A2 compares against 1.65 V instead.
- **LD tracks the external 10 MHz reference:** it's high only while the MKU is locked to an *external* 10 MHz reference. If you run without one, set `LOCK_MONITOR 0` so it doesn't alarm.
- **Probes:**
  - Clamp one DS18B20 under a heatsink screw near the PA device and the other on the MKU housing, both with thermal compound.
  - The MKU is rated for +55 °C case and disables transmit above +65 °C. The default alert for probe 2 is 50 °C.
  - Probe order on the bus is fixed by each probe's serial number, not by wiring. Warm one in your hand while watching `tlmview` to see which is which. Then set `temp_names` in `station.toml`, or swap the probes.
- **ADC reference:** measure the buck's 5 V rail with a DMM and enter it as `VREF_MV`. The ADC uses that rail as its reference.
- **Command terminator:** if the MKU doesn't answer `s`, it may want a line terminator. Set `XV_CMD_SUFFIX "\r"` in `config.h`.

### Wiring: base Nano (radio room)

Only the E220 block above, plus USB to the shack PC. Put the module and its antenna where it has the best view of the tower, for example a window. A USB extension cable is fine.

### Build and check

1. In the Arduino IDE, install **EByte LoRa E220 library** (Renzo Mischianti), **OneWire** and **DallasTemperature**. CI builds with versions 1.0.8, 2.3.8 and 4.0.6.
2. Open `firmware/remtlm/remtlm.ino`, set `REMTLM_ROLE` in `config.h`, and upload the TOWER image to one Nano and the BASE image to the other. Alternatively, run `pio run -e tower` / `-e base` from `firmware/remtlm`.
3. At boot, each Nano prints `V:remtlm 0.2.0 tower|base`, then `C:ok ch=77 freq_khz=927125`. The first boot also prints `C:written`, since it writes the settings to the module once.
   - `C:ERR read config` means the Nano can't talk to the module: check the M0, M1 and AUX wiring and the module's power.
4. The tower also prints `I:temperature probes=2`.
5. The tower echoes every packet on its own USB port, so you can watch it on the bench:
   - `$RT,...` readings
   - `$RK,...` transverter replies; the first, about 5 s after boot, is the `v` reply
6. The base Nano prints only valid packets.

### Shack configuration

In `station.toml`, set `tlm_port` to the base Nano's COM port. Then:

- **Ctrl-P** in the client prints the tower readings. **Ctrl-G** includes them.
- **Ctrl-K** prints the MKU's latest `s` status and its firmware version.
- **Alerts** print on their own lines (`!!` = warning, `--` = cleared):
  - 10 MHz reference unlock
  - either probe at or above its limit (`temp_warn_c`, `temp2_warn_c`)
  - no packets for `tlm_stale_s`
- **TX summary:** when you drop PTT, the client prints `last TX: PA peak … W`.
- **CSV log:** every reading is also logged to `remkey-tlm.csv`, which gives you temperature history for both probes. The station log records each transverter reply.

### Calibrating the PA power sense

Detector outputs aren't linear in power (Kuhne says the same of MON), so remkey uses a table you measure:

1. Put a power meter (through a suitable attenuator) on the PA output. On the bench before installation is easiest.
2. Run `python -m remkey.tlmview --port <tower Nano port>` and key a carrier (Ctrl-U tune, or locally) at several drive levels.
3. For each level, note the meter's watts and the `PA pk` mV reading.
4. Enter the pairs in `station.toml` as `pa_cal = [[mV, W], ...]`. Four or five points spanning low to full power are plenty.
5. Do the same with the MKU's output for `xv_cal` if you want MON in watts too.

Until a table is entered, readings are shown in mV.

### Parsing the MKU status

The manual lists what `s` reports (sequencer delays, frequency settings, reference PLL state) but not the reply's exact format, so it is relayed and displayed as-is. Once you've captured a real reply (Ctrl-K, `tlmview`, or the station log), its fields can be parsed so that, for example, a reference-PLL problem raises an alert from the serial status as well as from LD.

## Protocol reference

- Network protocol: JSON lines over TCP, documented in `host/remkey/protocol.py`.
- Serial protocol: newline-terminated commands at 115200 baud, documented at the top of `firmware/remkey/remkey.ino`.
- Telemetry packets: `$RT,...` readings and `$RK,...` transverter replies, documented in `firmware/remtlm/tlm_proto.h`.

## License

MIT. © 2026 Rus Healy, K2UA.
