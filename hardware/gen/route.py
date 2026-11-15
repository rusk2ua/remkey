"""Route a generated board with Freerouting, pour GND, run DRC and check every pad's net.

usage: route.py board.kicad_pcb [passes]
Writes the routed board in place plus board.drc.txt.
"""
import json
import re
import subprocess
import sys

sys.path.append("/usr/lib/python3/dist-packages")
import pcbnew  # noqa: E402

import os
FREEROUTING = os.environ.get("FREEROUTING", "/home/claude/freerouting.jar")


def tokens(text):
    return re.findall(r'\(|\)|"[^"]*"|[^\s()]+', text)


def parse(tok, i=0):
    out = []
    while i < len(tok):
        t = tok[i]
        if t == "(":
            sub, i = parse(tok, i + 1)
            out.append(sub)
        elif t == ")":
            return out, i + 1
        else:
            out.append(t.strip('"'))
            i += 1
    return out, i


def find(node, key):
    for n in node:
        if isinstance(n, list) and n and n[0] == key:
            yield n


def import_ses(board, ses_path):
    tree, _ = parse(tokens(open(ses_path).read()))
    ses = tree[0]
    routes = next(find(ses, "routes"))
    res = next(find(routes, "resolution"))
    scale = {"um": 1000.0, "mm": 1.0, "mil": 1000 / 25.4}[res[1]] * float(res[2])   # units per mm
    layers = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}
    nets = board.GetNetsByName()
    n_tr = n_via = 0

    def p(x, y):
        return pcbnew.VECTOR2I(pcbnew.FromMM(float(x) / scale), pcbnew.FromMM(-float(y) / scale))

    for net in find(next(find(routes, "network_out")), "net"):
        ni = nets[net[1]]
        for w in find(net, "wire"):
            path = next(find(w, "path"))
            layer, width, xy = path[1], float(path[2]) / scale, path[3:]
            pts = [p(xy[k], xy[k + 1]) for k in range(0, len(xy) - 1, 2)]
            for a, b in zip(pts, pts[1:]):
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(a)
                t.SetEnd(b)
                t.SetWidth(pcbnew.FromMM(width))
                t.SetLayer(layers[layer])
                t.SetNet(ni)
                board.Add(t)
                n_tr += 1
        for v in find(net, "via"):
            m = re.search(r"(\d+):(\d+)_um", v[1])
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(p(v[2], v[3]))
            via.SetWidth(pcbnew.FromMM(int(m.group(1)) / 1000) if m else pcbnew.FromMM(0.8))
            via.SetDrill(pcbnew.FromMM(int(m.group(2)) / 1000) if m else pcbnew.FromMM(0.4))
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            via.SetNet(ni)
            board.Add(via)
            n_via += 1
    return n_tr, n_via


def main():
    path = sys.argv[1]
    passes = sys.argv[2] if len(sys.argv) > 2 else "40"
    board = pcbnew.LoadBoard(path)
    for t in list(board.GetTracks()):
        board.Remove(t)
    dsn, ses = path.replace(".kicad_pcb", ".dsn"), path.replace(".kicad_pcb", ".ses")
    assert pcbnew.ExportSpecctraDSN(board, dsn)
    r = subprocess.run(["java", "-jar", FREEROUTING, "-de", dsn, "-do", ses, "-mp", passes,
                        "--gui.enabled=false"], capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("freerouting failed")
    n_tr, n_via = import_ses(board, ses)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(path)

    # every pad on the net the generator meant, and nothing more
    want = json.load(open(path + ".nets.json"))
    bad = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            key = f"{fp.GetReference()}.{pad.GetNumber()}"
            got = pad.GetNetname() or None
            if want.get(key) != got:
                bad.append((key, want.get(key), got))
    drc = path.replace(".kicad_pcb", ".drc.txt")
    pcbnew.WriteDRCReport(board, drc, pcbnew.EDA_UNITS_MILLIMETRES, True)
    txt = open(drc).read()
    counts = re.findall(r"\*\* Found (\d+) ([^*]+?) \*\*", txt)
    print(f"tracks {n_tr}, vias {n_via}; net mismatches {len(bad)} {bad[:5]}")
    for c in counts:
        print("DRC:", c[0], c[1].strip())


if __name__ == "__main__":
    main()
