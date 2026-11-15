"""remtlm tower-top board for a Hammond 1590B (no shunt or INA226 at the top).

Nets follow docs/img/remtlm-tower-signals-schematic.svg, the logic-supply part of
remtlm-tower-power-schematic.svg, remtlm-e220-schematic.svg, and the pin map in
firmware/remtlm/config.h.
"""
import json
import sys
from common import Board

out = sys.argv[1] if len(sys.argv) > 1 else "tower.kicad_pcb"
b = Board(102.0, 52.0, notch=7.0)
R, RV = "Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P2.54mm_Vertical"
CD = "C_Disc_D3.0mm_W1.6mm_P2.50mm"

# ---------------------------------------------------------------- power
b.wire("W1", 5.0, 17.0, 16, "VIN", "+13.8V", ly=13.6)
b.wire("W2", 5.0, 25.0, 16, "GND", "GND", ly=21.6)
b.lib("F1", "Capacitor_THT", "C_Disc_D7.5mm_W5.0mm_P5.00mm", 10.5, 12.0, {"1": "VIN", "2": "VFUSED"},
      "PTC 0.5A hold (e.g. RXEF050)")
b.text("F1 PTC 0.5A", 17.4, 12.0, 0.8, just="l")
b.buck("U1", 15.0, 36.0, {"IN+": "VFUSED", "IN-": "GND", "OUT-": "GND", "OUT+": "+5V"})
# AMS1117-3.3 module standing in a 1x3 socket: VIN, OUT, GND (as printed on the module)
b.row("U2", 26.0, 48.6, ["VIN", "OUT", "GND"], {"VIN": "+5V", "OUT": "+3V3", "GND": "GND"},
      "AMS1117-3.3 module (1x3 socket)", label_dy=-1.6)
b.text("3.3V REG", 28.54, 43.4, 0.8)

# ---------------------------------------------------------------- transverter and PA wires (#20) along the top
top = [("W3", 20.0, "XV_TXD", "TXD 11"), ("W4", 24.5, "XV_RXD", "RXD 12"), ("W5", 29.0, "LD", "LD 16"),
       ("W6", 33.5, "MON", "MON 9"), ("W7", 38.0, "GND", "GND 15"),
       ("W8", 46.0, "PA_SENSE", "PA SENSE"), ("W9", 50.5, "GND", "PA GND")]
for ref, x, net, lab in top:
    b.wire(ref, x, 4.2, 20, net, None)
    b.text(lab, x, 6.3, 0.8, rot=90, just="r")
b.text("MKU 10 G5 CON1", 29.0, 1.2, 0.8)
b.text("PA", 48.25, 1.2, 0.8)

# ---------------------------------------------------------------- BSS138 4-channel shifter
# module rotated 180 deg: LV row on top (towards the MKU wires), HV row below; LVn sits above HVn
lv = ["LV4", "LV3", "GND", "LV", "LV2", "LV1"]
hv = ["HV4", "HV3", "GND", "HV", "HV2", "HV1"]
b.row("U3", 28.0, 17.0, lv, {"LV1": "XV_TXD", "LV2": "XV_RXD", "LV": "+3V3", "GND": "GND"},
      "BSS138 4ch shifter, LV row (1x6 socket)", square_first=False, label_dy=-1.6)
b.row("U4", 28.0, 27.16, hv, {"HV1": "XV_RX", "HV2": "XV_TX", "HV": "+5V", "GND": "GND"},
      "BSS138 4ch shifter, HV row (1x6 socket)", square_first=False, label_dy=1.6)
b.rect(26.0, 15.9, 42.7, 28.3)
b.text("LEVEL SHIFTER", 34.35, 22.1, 0.8)

# ---------------------------------------------------------------- Nano, USB end towards the right-hand wall
b.nano("U5", 95.0, 18.0, {"A0": "A0", "A1": "A1", "A2": "LD", "5V": "+5V", "GND": "GND",
                          "D5": "DQ", "D6": "AUX", "D7": "E_TXD", "D8": "D8", "D9": "D9", "D10": "D10",
                          "D11": "XV_RX", "D12": "XV_TX"})

# ---------------------------------------------------------------- analog inputs (above the Nano)
# A0, A1: 10k in, 22k + 100nF to GND.  A2 (LD): 100k pull-down.
b.lib("R8", R, RV, 55.0, 8.5, {"1": "PA_SENSE", "2": "A0"}, "10k")
b.lib("R9", R, RV, 61.0, 8.5, {"1": "A0", "2": "GND"}, "22k")
b.lib("C3", "Capacitor_THT", CD, 67.0, 8.5, {"1": "A0", "2": "GND"}, "100nF")
b.lib("R10", R, RV, 73.0, 8.5, {"1": "MON", "2": "A1"}, "10k")
b.lib("R11", R, RV, 79.0, 8.5, {"1": "A1", "2": "GND"}, "22k")
b.lib("C4", "Capacitor_THT", CD, 85.0, 8.5, {"1": "A1", "2": "GND"}, "100nF")
b.lib("R12", R, RV, 55.0, 13.0, {"1": "LD", "2": "GND"}, "100k")
b.text("R8 10k R9 22k C3", 61.0, 5.4, 0.8)
b.text("R10 10k R11 22k C4", 79.0, 5.4, 0.8)
b.text("R12 100k", 63.0, 13.0, 0.8, just="l")

# ---------------------------------------------------------------- E220 dividers and ribbon
for ref, x, y, n1, n2, v in (("R1", 42.0, 38.0, "D9", "M0", "1k"), ("R2", 42.0, 42.0, "M0", "GND", "2k"),
                             ("R3", 48.0, 38.0, "D10", "M1", "1k"), ("R4", 48.0, 42.0, "M1", "GND", "2k"),
                             ("R5", 54.0, 38.0, "D8", "RXD", "1k"), ("R6", 54.0, 42.0, "RXD", "GND", "2k")):
    b.lib(ref, R, RV, x, y, {"1": n1, "2": n2}, v)
b.text("R1 R3 R5 1k", 49.3, 35.6, 0.8)
b.text("R2 R4 R6 2k", 49.3, 44.6, 0.8)
e220 = ["M0", "M1", "RXD", "TXD", "AUX", "VCC", "GND"]
b.row("J1", 67.0, 48.4, e220,
      {"M0": "M0", "M1": "M1", "RXD": "RXD", "TXD": "E_TXD", "AUX": "AUX", "VCC": "+5V", "GND": "GND"},
      "E220 ribbon (1x7, 0.1in)", label_dy=-1.6)
b.text("TO E220", 59.5, 48.4, 0.8)
b.lib("C1", "Capacitor_THT", "CP_Radial_D6.3mm_P2.50mm", 84.5, 40.0, {"1": "+5V", "2": "GND"}, "100uF")
b.lib("C2", "Capacitor_THT", CD, 84.5, 44.6, {"1": "+5V", "2": "GND"}, "100nF")
b.text("C1 100uF", 85.75, 36.2, 0.8)

# ---------------------------------------------------------------- DS18B20 probes (#18), one 4.7k pull-up
for ref, x, net, lab in (("W10", 35.5, "GND", "GND"), ("W11", 39.0, "DQ", "DQ"), ("W12", 42.5, "+5V", "5V"),
                         ("W13", 47.5, "GND", "GND"), ("W14", 51.0, "DQ", "DQ"), ("W15", 54.5, "+5V", "5V")):
    b.wire(ref, x, 48.8, 18, net, None)
    b.text(lab, x, 46.6, 0.8)
b.lib("R13", R, RV, 60.0, 42.0, {"1": "DQ", "2": "+5V"}, "4.7k")
b.text("R13 4k7", 61.3, 39.6, 0.8)

for i, (x, y) in enumerate(((11.0, 4.5), (91.0, 4.5), (11.0, 47.5), (91.0, 47.5))):
    b.mount(f"H{i + 1}", x, y)

b.ident("tower", 33.0, 33.6)
b.jlc_marker(77.0, 28.6)

b.gnd_pour()
b.save(out)
json.dump({f"{k[0]}.{k[1]}": v for k, v in b.expected.items()}, open(out + ".nets.json", "w"), indent=0)
