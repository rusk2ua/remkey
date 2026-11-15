"""remtlm supply-box (PSU node) board for a Hammond 1590B.

Nets follow docs/img/remtlm-psu-box-schematic.svg and remtlm-e220-schematic.svg,
and the pin map in firmware/remtlm/config.h.
"""
import sys
from common import Board

b = Board(102.0, 52.0, notch=7.0)

# power in: #16 wires from the supply output (tapped ahead of the shunt) and supply (-)
b.wire("W1", 5.0, 17.0, 16, "VIN", "+14V", ly=13.6)
b.wire("W2", 5.0, 25.0, 16, "GND", "GND", ly=21.6)
b.lib("F1", "Capacitor_THT", "C_Disc_D7.5mm_W5.0mm_P5.00mm", 10.5, 12.0, {"1": "VIN", "2": "VFUSED"},
      "PTC 0.5A hold (e.g. RXEF050)")
b.text("F1 PTC 0.5A", 13.0, 8.4, 0.8)
b.buck("U1", 15.0, 36.0, {"IN+": "VFUSED", "IN-": "GND", "OUT-": "GND", "OUT+": "+5V"})

# INA226 module (CJMCU-226) in a 1x8 socket; body above the header row
ina = ["IN+", "IN-", "VBS", "ALE", "SDA", "SCL", "GND", "VCC"]
b.row("U2", 30.0, 29.0, ina,
      {"IN+": "SH_P", "IN-": "SH_N", "VBS": "SH_N", "SDA": "SDA", "SCL": "SCL", "GND": "GND", "VCC": "+5V"},
      "CJMCU-226 INA226 module (1x8 socket)", label_dy=-1.6)
b.rect(28.85, 8.0, 48.95, 30.6)
b.text("INA226 MODULE", 38.9, 14.0, 1.0)
b.text("remove R100 shunt", 38.9, 16.2, 0.8)
b.text("VBS tied to IN-", 38.9, 18.2, 0.8)
# Kelvin sense leads from the external shunt's small screws (#20)
b.wire("W3", 24.2, 18.6, 20, "SH_P", "SHUNT+", ly=16.0, size=0.8)
b.text("supply side", 24.2, 21.3, 0.8)
b.wire("W4", 24.2, 24.6, 20, "SH_N", None)
b.text("SHUNT-", 24.2, 27.3, 0.8)
b.text("tower side", 24.2, 28.6, 0.8)

# Nano, USB end towards the right-hand wall
b.nano("U3", 95.0, 18.0, {"A4": "SDA", "A5": "SCL", "5V": "+5V", "GND": "GND",
                          "D5": "DQ", "D6": "AUX", "D7": "E_TXD", "D8": "D8", "D9": "D9", "D10": "D10"})

# 5 V -> 3.3 V dividers for E220 M0, M1, RXD (1k from the Nano, 2k to GND), DS18B20 pull-up
R = "Resistor_THT"
RF = "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal"
b.lib("R1", R, RF, 41.0, 34.0, {"1": "D9", "2": "M0"}, "1k")
b.lib("R3", R, RF, 41.0, 37.0, {"1": "D10", "2": "M1"}, "1k")
b.lib("R5", R, RF, 41.0, 40.0, {"1": "D8", "2": "RXD"}, "1k")
b.lib("R2", R, RF, 28.0, 34.0, {"1": "GND", "2": "M0"}, "2k")
b.lib("R4", R, RF, 28.0, 37.0, {"1": "GND", "2": "M1"}, "2k")
b.lib("R6", R, RF, 28.0, 40.0, {"1": "GND", "2": "RXD"}, "2k")
b.lib("R7", R, RF, 28.0, 43.0, {"1": "DQ", "2": "+5V"}, "4.7k")
for ref, x, y, v in (("R2 2k", 33.1, 31.7, 0), ("R1 1k", 46.1, 31.7, 0)):
    b.text(ref, x, y, 0.8)
b.text("R4 2k  R6 2k  R7 4k7", 33.1, 45.0, 0.8)
b.text("R3 1k  R5 1k", 46.1, 42.0, 0.8)

# DS18B20 box probe: #18 wires
b.wire("W5", 30.0, 48.6, 18, "GND", None)
b.wire("W6", 34.0, 48.6, 18, "DQ", None)
b.wire("W7", 38.0, 48.6, 18, "+5V", None)
b.text("GND", 30.0, 46.5, 0.8)
b.text("DQ", 34.0, 46.5, 0.8)
b.text("5V", 38.0, 46.5, 0.8)
b.text("PROBE", 43.5, 48.6, 0.8)

# E220 ribbon: 1x7, same order as the module's own pins
e220 = ["M0", "M1", "RXD", "TXD", "AUX", "VCC", "GND"]
b.row("J1", 67.0, 48.4, e220,
      {"M0": "M0", "M1": "M1", "RXD": "RXD", "TXD": "E_TXD", "AUX": "AUX", "VCC": "+5V", "GND": "GND"},
      "E220 ribbon (1x7, 0.1in)", label_dy=-1.6)
b.text("TO E220", 59.5, 48.4, 0.8)
b.lib("C1", "Capacitor_THT", "CP_Radial_D6.3mm_P2.50mm", 84.5, 40.0, {"1": "+5V", "2": "GND"}, "100uF")
b.lib("C2", "Capacitor_THT", "C_Disc_D3.0mm_W1.6mm_P2.50mm", 84.5, 44.6, {"1": "+5V", "2": "GND"}, "100nF")
b.text("C1 100uF", 85.75, 36.2, 0.8)

for i, (x, y) in enumerate(((11.0, 4.5), (91.0, 4.5), (11.0, 47.5), (91.0, 47.5))):
    b.mount(f"H{i + 1}", x, y)

b.text("remtlm PSU box  v1.0", 58.0, 3.4, 1.2)
b.text("Hammond 1590B", 58.0, 5.6, 0.8)

b.gnd_pour()
b.save(sys.argv[1] if len(sys.argv) > 1 else "psu.kicad_pcb")
import json
json.dump({f"{k[0]}.{k[1]}": v for k, v in b.expected.items()}, open((sys.argv[1] if len(sys.argv) > 1 else "psu.kicad_pcb") + ".nets.json", "w"), indent=0)
