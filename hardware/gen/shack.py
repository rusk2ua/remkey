"""remtlm base (shack) board: Nano + E220 ribbon header, powered from the shack PC's USB.

Nets follow docs/img/remtlm-e220-schematic.svg and firmware/remtlm/config.h.
"""
import json
import sys
from common import Board

out = sys.argv[1] if len(sys.argv) > 1 else "shack.kicad_pcb"
b = Board(64.0, 40.0)
R, RV = "Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P2.54mm_Vertical"

b.nano("U1", 58.5, 5.5, {"5V": "+5V", "GND": "GND", "D6": "AUX", "D7": "E_TXD",
                          "D8": "D8", "D9": "D9", "D10": "D10"})
for ref, x, y, n1, n2, v in (("R1", 20.0, 28.0, "D9", "M0", "1k"), ("R2", 20.0, 32.0, "M0", "GND", "2k"),
                             ("R3", 26.0, 28.0, "D10", "M1", "1k"), ("R4", 26.0, 32.0, "M1", "GND", "2k"),
                             ("R5", 32.0, 28.0, "D8", "RXD", "1k"), ("R6", 32.0, 32.0, "RXD", "GND", "2k")):
    b.lib(ref, R, RV, x, y, {"1": n1, "2": n2}, v)
b.text("R1 R3 R5 1k", 13.6, 28.0, 0.8, just="r")
b.text("R2 R4 R6 2k", 13.6, 32.0, 0.8, just="r")
e220 = ["M0", "M1", "RXD", "TXD", "AUX", "VCC", "GND"]
b.row("J1", 36.0, 37.0, e220,
      {"M0": "M0", "M1": "M1", "RXD": "RXD", "TXD": "E_TXD", "AUX": "AUX", "VCC": "+5V", "GND": "GND"},
      "E220 ribbon (1x7, 0.1in)", label_dy=-1.6)
b.text("TO E220", 28.0, 37.0, 0.8)
b.lib("C1", "Capacitor_THT", "CP_Radial_D6.3mm_P2.50mm", 40.0, 29.0, {"1": "+5V", "2": "GND"}, "100uF")
b.lib("C2", "Capacitor_THT", "C_Disc_D3.0mm_W1.6mm_P2.50mm", 47.0, 29.0, {"1": "+5V", "2": "GND"}, "100nF")
b.text("C1 100uF  C2 100nF", 46.0, 24.2, 0.8)
for i, (x, y) in enumerate(((4.0, 4.0), (4.0, 36.0), (60.0, 36.0))):
    b.mount(f"H{i + 1}", x, y)
b.text("RK-303", 9.0, 12.0, 1.2)
b.text("Rev A", 9.0, 14.2, 1.2)
b.text("remtlm shack", 9.0, 16.4, 0.8)
b.text("2026-11", 9.0, 18.2, 0.8)
b.jlc_marker(40.0, 16.0)
b.gnd_pour()
b.save(out)
json.dump({f"{k[0]}.{k[1]}": v for k, v in b.expected.items()}, open(out + ".nets.json", "w"), indent=0)
