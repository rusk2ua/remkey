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
| RK-301 | Supply box (tower base, Hammond 1590B) | A | no | |
| RK-302 | Tower top (Hammond 1590B) | A | no | |
| RK-303 | Shack base (USB, no box) | A | no | |

## RK-301 / RK-302 / RK-303 Rev A (2026-11)

First release, not yet ordered.

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
