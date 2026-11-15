#!/bin/sh
# Rebuild all three remtlm boards: place, route, DRC + net check, fab files.
# Needs KiCad 7 (python3 pcbnew, kicad-cli), rsvg-convert, Java and freerouting.jar
# (set FREEROUTING to its path if it isn't /home/claude/freerouting.jar).
set -e
cd "$(dirname "$0")"
for b in psu tower shack; do
    /usr/bin/python3 gen/$b.py $b/$b.kicad_pcb
    /usr/bin/python3 gen/route.py $b/$b.kicad_pcb
    /usr/bin/python3 gen/fab.py $b
done
