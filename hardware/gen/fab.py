"""Write JLCPCB-ready Gerbers + drill (zipped), a BOM and top/bottom renders for one board.

usage: fab.py <name>        (run from hardware/, e.g. fab.py psu)
"""
import csv
import json
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

sys.path.append("/usr/lib/python3/dist-packages")
import pcbnew  # noqa: E402

name = sys.argv[1]
d = Path(name)
info = json.load(open(Path(__file__).parent.parent / "boards.json"))[name]
tag = f"{info['pn']}-rev{info['rev']}"
pcb = d / f"{name}.kicad_pcb"
fab = d / "fab"
shutil.rmtree(fab, ignore_errors=True)
(fab / "gerbers").mkdir(parents=True)
run = lambda *a: subprocess.run(a, check=True, capture_output=True)  # noqa: E731
run("kicad-cli", "pcb", "export", "gerbers", "--layers",
    "F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts", "--subtract-soldermask",
    "-o", f"{fab}/gerbers/", str(pcb))
run("kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
    "-o", f"{fab}/gerbers/", str(pcb))
with zipfile.ZipFile(fab / f"{tag}-{name}-gerbers.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted((fab / "gerbers").iterdir()):
        z.write(f, f.name)
shutil.rmtree(fab / "gerbers")

# BOM: one row per value/footprint, refs grouped
board = pcbnew.LoadBoard(str(pcb))
rows = defaultdict(list)
for fp in board.GetFootprints():
    ref = fp.GetReference()
    if ref.startswith(("W", "H")):
        continue
    rows[(fp.GetValue(), str(fp.GetFPID().GetLibItemName()))].append(ref)
key = lambda r: (r[0].rstrip("0123456789"), int("0" + r[0][len(r[0].rstrip("0123456789")):]))  # noqa: E731
with open(d / f"{name}-bom.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow([f"{info['pn']} Rev {info['rev']} ({info['date']})", info["title"], "", ""])
    w.writerow(["Qty", "Refs", "Value / part", "Footprint"])
    for (val, lib), refs in sorted(rows.items(), key=lambda kv: key(sorted(kv[1])[0:1] or [""])):
        refs = sorted(refs, key=lambda r: key([r]))
        w.writerow([len(refs), " ".join(refs), val, lib or "custom"])

# 1:1 print for checking module fit (pads, outlines, labels, board edge; A4 page)
run("kicad-cli", "pcb", "export", "pdf", "--layers", "F.Mask,F.SilkS,Edge.Cuts", "--black-and-white",
    "-o", str(fab / f"{tag}-{name}-print-1to1.pdf"), str(pcb))

subprocess.run(["python3", str(Path(__file__).parent / "letterprint.py"), name, tag], check=True)  # needs pymupdf

# renders
img = d / "img"
img.mkdir(exist_ok=True)
for side, layers in (("top", "F.Cu,F.SilkS,F.Mask,Edge.Cuts"), ("bottom", "B.Cu,B.Mask,Edge.Cuts")):
    svg = f"/tmp/{name}-{side}.svg"
    run("kicad-cli", "pcb", "export", "svg", "--layers", layers, "--page-size-mode", "2",
        "--exclude-drawing-sheet", "-o", svg, str(pcb))
    run("rsvg-convert", "-w", "1600", "-b", "white", svg, "-o", str(img / f"{name}-{side}.png"))
print(name, "ok")
