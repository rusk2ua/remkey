# remkey — remote paddle CW for the IC-7610 (or any rig with a KEY jack)

Send CW with your own paddle from anywhere, with an instant local sidetone, and have the shack re-key it with perfect timing. Remote PTT (the TRANSMIT button) included.

remkey is built for a station where:

- A Windows PC in the shack already runs N1MM+, rig control and rotator control, and you reach it with AnyDesk.
- The 7610 drives a tower-mounted 10 GHz transverter through its SEND line, so PTT is manual and keying is CW.
- You travel with a Mac and want to use a real paddle.

It is two Arduino Nanos running the same sketch, plus a small Python bridge.

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
host/remkey/station.py         shack service (Windows)
host/remkey/client.py          travel client (macOS; Linux works too)
host/remkey/protocol.py        network protocol, CW text sanitiser
host/*.example.toml            config templates
host/tests/                    pytest: protocol + end-to-end over localhost
tests/firmware_sim/            g++ simulation of the sketch (timing, decoder, watchdog)
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
| **Ctrl-G** | Status: link, PTT, WPM, round-trip time |
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
cd host && python3 -m pip install -e ".[test]" && python3 -m pytest -q
tests/firmware_sim/run.sh       # needs g++; runs the sketch against a mock Arduino
```

The firmware simulation checks:

- PARIS at 20 WPM takes exactly 46 units with 22 units of key-down.
- Raw patterns and word spacing.
- Iambic A/B squeeze behaviour.
- Paddle decode of `CQ TEST K2UA`, and unknown patterns.
- Tune timing and the 30 s cap.
- The watchdog, with and without heartbeats.
- PTT button debounce.
- That the client paddle never drives the KEY output.

The firmware has been verified in that simulation but not yet on real hardware. The first AVR build may surface board-specific warnings; please open an issue with the output.

## Protocol reference

- Network protocol: JSON lines over TCP, documented in `host/remkey/protocol.py`.
- Serial protocol: newline-terminated commands at 115200 baud, documented at the top of `firmware/remkey/remkey.ino`.

## License

MIT. © 2026 Rus Healy, K2UA.
