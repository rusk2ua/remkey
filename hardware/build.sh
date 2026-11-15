#!/bin/sh
# Rebuild all three remtlm boards: place, route, DRC + net check, fab files.
# Needs KiCad 7 (python3 pcbnew, kicad-cli), rsvg-convert, pymupdf, Java and freerouting.jar
# (set FREEROUTING to its path if it isn't /home/claude/freerouting.jar).
# Freerouting isn't deterministic, so a board is re-routed (up to 5 tries) until
# DRC reports no unconnected pads and no dangling tracks.
set -e
cd "$(dirname "$0")"
for b in psu tower shack; do
    n=0
    while :; do
        n=$((n + 1))
        /usr/bin/python3 gen/$b.py $b/$b.kicad_pcb
        /usr/bin/python3 gen/route.py $b/$b.kicad_pcb 60 | tee /tmp/route-$b.txt
        if grep -q "DRC: 0 unconnected" /tmp/route-$b.txt && ! grep -q track_dangling $b/$b.drc.txt; then
            break
        fi
        [ $n -lt 5 ] || { echo "$b: still incomplete after $n routing passes" >&2; exit 1; }
    done
    /usr/bin/python3 gen/fab.py $b
done
