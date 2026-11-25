# remtlm board revisions

Part numbers: **RK-3xx** for the remtlm telemetry boards (RK = remkey; the 100 and 200
series are left for any keyer boards). Revisions are letters: A, B, C...

The part number and revision live in one place, `boards.json`. The build prints them on
each board's silkscreen and uses them in the fab-file names
(`<pn>-rev<rev>-<board>-gerbers.zip`) and the BOM header.

**Rules**

- A revision is open until it's ordered. Changes before the order stay in the same letter.
- Once a revision has been ordered, it's frozen: record the order here and tag the commit
  (`RK-301-revA`). Any later change starts the next letter. Bump it in `boards.json`, rebuild,
  and add a section below.
- Firmware and host versions are separate; a board revision lists the firmware it was
  tested with once it has been built.

| Part number | Board | Current rev | Ordered | Tag |
|---|---|---|---|---|
| RK-301 | Supply box (tower base, Hammond 1590B) | A | Rev A: JLCPCB, 2026-11 | `RK-301-revA` |
| RK-302 | Tower top (Hammond 1590B) | B | Rev A: JLCPCB, 2026-11. Rev B: no | `RK-302-revA` |
| RK-303 | Shack base (USB, no box) | A | Rev A: JLCPCB, 2026-11 | `RK-303-revA` |

## RK-302 Rev B (2026-11)

Not yet ordered. Changes from Rev A:

- **Key line to the sequencer, watched on A3.** A new #20 wire hole, W16 "PTT 8", for
  MKU CON1 pin 8 (PTT out, active low), between GND 15 and PA SENSE. It also stays wired
  to the sequencer: the tower only listens.
- **R16 100k** pull-up from the line to +5 V, so an open line (sequencer unplugged or dead)
  reads about 2 V, not "keyed".
- **R14 47k / R15 22k** divider into A3, with **C5 100 nF** to GND. A3 stays under 5 V with
  up to about 15 V on the line, so pin 8 can be open collector or driven.
- Needs tower firmware remtlm 0.6.0 or later to report it. Rev A boards work with 0.6.0
  too, but A3 floats on them, so build their firmware with `PTT_SENSE 0` (on the
  arduino-cli command line: `-DPTT_SENSE=0`), or add the four parts off the board at the
  Nano's A3 socket pin.
- **Dish elevation and box air sensors (2026-11-25):** the shifter's spare channels 3 and 4
  now carry I2C: LV3/HV3 SDA (Nano A4), LV4/HV4 SCL (A5). Two new 1x4 headers on the
  3.3 V side, J2 "ELEV" (ADXL355 plate on the dish frame) and J3 "AIR" (BME280 in the
  box), pin order SDA, SCL, 3V3, GND (square pad = SDA), the same as the prototype
  sensor board. Needs tower firmware remtlm 0.7.0 or later. A Rev A board gets the
  same sensors through the prototype sensor board (docs/prototype).
- DRC: as Rev A (library-path notes only), plus single-spoke thermal-relief notes on the GND
  pads of C5 and the shifter's HV-row socket (one spoke instead of two; both connected,
  solder fine). 0 unconnected pads.


## RK-301 / RK-302 / RK-303 Rev A (2026-11)

First release. All three ordered from JLCPCB in 2026-11 and frozen. The fab files are in
the `RK-30x-revA` tags.

- Through-hole, two layers. The Nano, INA226 (RK-301), buck, AMS1117-3.3 (RK-302) and
  BSS138 shifter (RK-302) modules sit in sockets. Wires solder into sized holes
  (#16 power, #18 probes, #20 signals).
- #4-40 mounting holes: 3.2 mm unplated, with a 7.6 mm copper keep-out and a silk ring
  for the standoff, split washer and pan head. Four each on RK-301 and RK-302, three on RK-303.
- 0.5 A-hold polyfuse on the logic supply (RK-301, RK-302).
- JLCPCB order-number position marked under the Nano.
- Buck module is the fixed 5 V output type (5–28 V in), not an adjustable MP1584: no
  setting needed (2026-11-15; description and docs only, no copper change).
- Paper fit check (2026-11-15): the buck, INA226 and Nano match the full-size prints.
  The 100 mm scale bar printed true.
- Pre-release drafts (2026-11-15, commits ffa92ff to cc20196) carried "v1.0" on the
  silkscreen, had M3 holes without keep-outs, and were never ordered.
