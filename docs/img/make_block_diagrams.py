"""Generate the remkey and remtlm overview block diagrams (SVG, plus PNG for slides).

Regenerate from the repo root:  python docs/img/make_block_diagrams.py docs/img
PNGs need rsvg-convert (librsvg); without it only the SVGs are written.
The output is deterministic: regenerating gives no diff.
"""
import os
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

FONT = "Helvetica, Arial, sans-serif"
INK = "#1f2933"
GRAY = "#52606d"

# zone colors: (fill, stroke)
TRAVEL = ("#eaf2fb", "#3b6fb6")
NET = ("#f2f2f2", "#7b8794")
SHACK = ("#eaf6ee", "#2f8a4e")
TOWER = ("#fdf3e3", "#c27c0e")
BASE = ("#f6eefa", "#8a4fb0")


class Svg:
    def __init__(self, w, h, title):
        self.w, self.h = w, h
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" font-family="{FONT}">',
            f"<title>{escape(title)}</title>",
            "<defs>"
            '<marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            'markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker>'
            '<marker id="ahg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            'markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{GRAY}"/></marker>'
            "</defs>",
            f'<rect width="{w}" height="{h}" fill="white"/>',
        ]

    def text(self, x, y, s, size=14, weight="normal", color=INK, anchor="middle",
             style="normal", halo=False):
        h = ' stroke="white" stroke-width="5" stroke-linejoin="round" paint-order="stroke"' \
            if halo else ""
        self.parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'font-style="{style}" fill="{color}" text-anchor="{anchor}"{h}>{escape(s)}</text>')

    def lines(self, x, y, items, size=13, gap=17, **kw):
        for i, s in enumerate(items):
            self.text(x, y + i * gap, s, size=size, **kw)

    def zone(self, x, y, w, h, label, colors, sub=None, right=False):
        fill, stroke = colors
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.5" stroke-dasharray="6 4"/>')
        if right:
            self.text(x + w - 14, y + 24, label, size=15, weight="bold", color=stroke, anchor="end")
        else:
            self.text(x + 14, y + 24, label, size=15, weight="bold", color=stroke, anchor="start")
        if sub:
            self.text(x + 14, y + 42, sub, size=12, color=GRAY, anchor="start", style="italic")

    def box(self, x, y, w, h, title, body=(), colors=SHACK, num=None, title_size=15):
        _, stroke = colors
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="white" '
            f'stroke="{stroke}" stroke-width="2"/>')
        cx = x + w / 2
        titles = title.split("\n")
        for i, t in enumerate(titles):
            self.text(cx, y + 24 + i * 18, t, size=title_size, weight="bold")
        top = y + 24 + len(titles) * 18 + 4
        self.lines(cx, top, body, size=12.5, color=GRAY)
        if num is not None:
            self.badge(x + w - 2, y + 2, num, stroke)
        return (x, y, w, h)

    def badge(self, x, y, n, color):
        self.parts.append(f'<circle cx="{x}" cy="{y}" r="13" fill="{color}"/>')
        self.text(x, y + 5, str(n), size=14, weight="bold", color="white")

    def arrow(self, pts, label=None, at=0.5, dy=-8, color=INK, dash=False, both=False,
              size=12.5, lw=2, anchor="middle", seg=0):
        d = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(pts))
        mk = "ahg" if color == GRAY else "ah"
        extra = ' stroke-dasharray="7 5"' if dash else ""
        start = f' marker-start="url(#{mk})"' if both else ""
        self.parts.append(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{lw}"{extra}{start} '
            f'marker-end="url(#{mk})"/>')
        if label:
            (x0, y0), (x1, y1) = pts[seg], pts[seg + 1]
            lx, ly = x0 + (x1 - x0) * at, y0 + (y1 - y0) * at + dy
            for i, s in enumerate(label.split("\n")):
                self.text(lx, ly + i * 15, s, size=size, color=color, anchor=anchor, halo=True)

    def save(self, path):
        self.parts.append("</svg>")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.parts) + "\n")


def remkey(out):
    s = Svg(1600, 610, "remkey: how remote paddle CW works")
    s.text(800, 36, "remkey: remote paddle CW", size=24, weight="bold")
    s.text(800, 60, "Characters cross the internet, not key-down timing, "
           "so jitter can't chop your dits and dahs", size=14, color=GRAY, style="italic")

    ZH = 390
    s.zone(20, 80, 600, ZH, "TRAVEL END", TRAVEL, "anywhere with internet")
    s.zone(640, 80, 170, ZH, "INTERNET", NET)
    s.zone(830, 80, 580, ZH, "SHACK", SHACK, "Windows PC, IC-7610")
    s.zone(1430, 80, 150, ZH, "TOWER", TOWER)

    Y, H = 160, 160
    s.box(40, Y, 160, H, "Paddle + PTT", ["iambic paddle", "", "PTT button", "or toggle switch"],
          TRAVEL)
    s.box(240, Y, 160, H, "Client Nano", ["iambic keyer", "local sidetone,", "zero delay",
                                          "decodes each", "character you send"], TRAVEL, num=1)
    s.box(440, Y, 160, H, "Mac client", ["remkey.client", "", "keyboard CW, hotkeys",
                                         "heartbeat", "tower readouts"], TRAVEL)

    s.box(850, Y, 170, H, "Station service", ["remkey.station", "", "checks the client's",
                                              "HMAC login", "safety stops on", "link loss"],
          SHACK)
    s.box(1060, Y, 160, H, "Station Nano", ["re-sends each", "character with", "exact timing",
                                           "PTT release hold", "3 s watchdog"], SHACK, num=3)
    s.box(1260, Y, 130, H, "IC-7610", ["", "KEY jack", "(CW)", "", "SEND line", "(PTT)"], SHACK)
    s.box(1445, Y, 120, H, "10 GHz\ntransverter", ["", "and PA", "", "keyed from", "the 7610's",
                                                  "SEND line"], TOWER)

    mid = Y + 75
    s.arrow([(200, mid), (240, mid)])
    s.arrow([(400, mid), (440, mid)], "USB", dy=-10)
    s.arrow([(600, mid), (850, mid)], None)
    s.badge(725, mid - 85, 2, NET[1])
    s.lines(725, mid - 55, ["characters, PTT,", "heartbeats"], size=12.5)
    s.lines(725, mid + 24, ["TCP + JSON", "over Tailscale", "(or port-forward)"], size=12.5,
            color=GRAY)
    s.arrow([(1020, mid), (1060, mid)], "USB", dy=-10)
    s.arrow([(1220, mid - 25), (1260, mid - 25)], "opto", dy=-8, size=11.5)
    s.arrow([(1220, mid + 40), (1260, mid + 40)], "opto", dy=-8, size=11.5)
    s.arrow([(1390, mid + 40), (1445, mid + 40)])

    # return paths
    ya = Y + H + 40
    s.arrow([(1140, Y + H), (1140, ya), (320, ya), (320, Y + H)],
            "PTT confirmed: the client's PTT LED lights", at=0.5, dy=-10, color=GRAY, size=12,
            seg=1)
    yb = ya + 50
    s.arrow([(1325, Y + H), (1325, yb), (520, yb), (520, Y + H)],
            "receive audio by AnyDesk, with the radio's own sidetone (delayed)",
            at=0.5, dy=-10, color=GRAY, dash=True, size=12, seg=1)
    s.text(1120, 458, "N1MM+, rig and rotator control: unchanged, by AnyDesk", size=12,
           color=GRAY, style="italic")

    # key ideas
    ky = 500
    ideas = [
        (1, TRAVEL[1], "You hear yourself instantly.",
         "The travel Nano is a normal keyer with its own sidetone."),
        (2, NET[1], "Only characters cross the network.",
         "Jitter delays a whole character, never an element."),
        (3, SHACK[1], "The shack re-times them perfectly.",
         "About one character behind you; safety stops drop PTT at once."),
    ]
    for i, (n, col, head, sub) in enumerate(ideas):
        x = 60 + i * 520
        s.badge(x, ky + 10, n, col)
        s.text(x + 22, ky + 15, head, size=15, weight="bold", anchor="start")
        s.text(x + 22, ky + 36, sub, size=13, color=GRAY, anchor="start")
    s.text(800, 592, "Safety: link closed, no heartbeat for 3 s, or the station PC/USB hangs "
           "(Nano watchdog) → PTT off and queued CW flushed immediately", size=12.5, color=GRAY)
    path = os.path.join(out, "remkey-block-diagram.svg")
    s.save(path)
    return path


def remtlm(out):
    s = Svg(1600, 760, "remtlm: how tower telemetry works")
    s.text(800, 36, "remtlm: tower telemetry over LoRa", size=24, weight="bold")
    s.text(800, 60, "Two boxes on the tower report by radio to a receiver in the shack: "
           "no wire between the tower and the house", size=14, color=GRAY, style="italic")

    # tower top
    s.zone(20, 80, 640, 330, "TOWER-TOP BOX", TOWER, "on the back of the dish")
    s.box(40, 135, 230, 260, "Sensors", [
        "PA output power (peak, avg)",
        "MKU power monitor",
        "10 MHz reference lock",
        "key line to the sequencer",
        "MKU serial status (read-only)",
        "PA and MKU temperatures",
        "dish elevation (ADXL355)",
        "box air: temp, humidity,",
        "pressure (BME280)",
        "supply voltage (optional)",
    ], TOWER)
    s.box(310, 160, 170, 210, "Tower Nano", ["samples every 5 ms", "so CW dits aren't",
                                            "missed", "", "a report every 2 s,", "0.5 s on the air",
                                            "elevation 5×/s", "while the dish moves"], TOWER, num=1)
    s.box(520, 215, 120, 100, "E220", ["LoRa radio", "17 dBm"], TOWER)
    s.arrow([(270, 265), (310, 265)])
    s.arrow([(480, 265), (520, 265)])

    # tower base
    s.zone(20, 440, 640, 230, "SUPPLY BOX AT THE TOWER BASE", BASE, right=True)
    s.box(40, 495, 230, 150, "14 V supply", ["shunt + INA226:", "voltage and current", "going up the tower",
                                            "", "box temperature"], BASE)
    s.box(310, 495, 170, 150, "PSU Nano", ["min, avg, peak", "per interval", "",
                                          "answers in its own", "slot after each", "tower report"],
          BASE, num=2)
    s.box(520, 520, 120, 100, "E220", ["LoRa radio"], BASE)
    s.arrow([(270, 570), (310, 570)])
    s.arrow([(480, 570), (520, 570)])
    # power up the tower
    s.arrow([(155, 495), (155, 395)], color=GRAY)
    s.text(165, 430, "14 V up the tower cable", size=12, color=GRAY, anchor="start", halo=True)

    # link
    s.zone(680, 80, 190, 590, "RADIO LINK", NET)
    s.arrow([(640, 265), (900, 300)], None, lw=2.5)
    s.arrow([(640, 570), (900, 330)], None, lw=2.5)
    s.lines(775, 145, ["927.125 MHz", "one channel", "9.6 kbps"], size=13, weight="bold")
    s.lines(775, 580, ["checksummed", "text packets", "", "no lightning path", "into the house"],
            size=12.5, color=GRAY)

    # radio room
    s.zone(890, 80, 690, 590, "RADIO ROOM", SHACK, "shack PC")
    s.box(905, 255, 110, 120, "E220", ["LoRa radio"], SHACK)
    s.box(1050, 240, 160, 150, "Base Nano", ["checks every", "packet", "adds signal",
                                           "strength"], SHACK)
    s.box(1250, 215, 180, 200, "Station service", ["same program as", "remkey keying", "",
                                                  "calibration", "alerts", "history + CSV log"],
          SHACK, num=3)
    s.arrow([(1015, 315), (1050, 315)])
    s.arrow([(1210, 315), (1250, 315)], "USB", dy=-10)

    # outputs
    ox = 1462
    s.box(ox, 110, 110, 95, "Mac client", ["Ctrl-P, K, V", "alerts"], SHACK, title_size=14)
    s.box(ox, 268, 110, 95, "Dashboard", ["browser, Wi-Fi", "or Tailscale"], SHACK, title_size=14)
    s.box(ox, 425, 110, 95, "Cloud copy", ["optional", "read-only"], SHACK, title_size=14)
    s.arrow([(1430, 270), (1448, 270), (1448, 157), (ox, 157)])
    s.arrow([(1430, 315), (ox, 315)])
    s.arrow([(1430, 360), (1448, 360), (1448, 472), (ox, 472)])

    s.lines(1235, 470, [
        "Separate USB port from the remkey station Nano:",
        "a telemetry fault can't affect keying.",
        "Nothing in remtlm can key the radio",
        "or reconfigure the transverter.",
    ], size=12.5, color=GRAY, style="italic")
    s.lines(1235, 570, [
        "Alerts include: reference unlock, over-temperature,",
        "low or high supply, MKU keyed but no PA output,",
        "key line stuck, humidity or condensation, box lost",
    ], size=12.5, color=GRAY)

    ky = 708
    ideas = [
        (1, TOWER[1], "The tower reports what the rig can't see",
         "power, lock, keying, temperatures, elevation"),
        (2, BASE[1], "The supply box reports on its own",
         "voltage, current and cable drop, even with the top box down"),
        (3, SHACK[1], "One program shows it everywhere",
         "client hotkeys, live dashboard, cloud summary"),
    ]
    for i, (n, col, head, sub) in enumerate(ideas):
        x = 60 + i * 520
        s.badge(x, ky, n, col)
        s.text(x + 22, ky + 5, head, size=15, weight="bold", anchor="start")
        s.text(x + 22, ky + 26, sub, size=13, color=GRAY, anchor="start")
    path = os.path.join(out, "remtlm-block-diagram.svg")
    s.save(path)
    return path


def png(svg):
    exe = shutil.which("rsvg-convert")
    if not exe:
        print("rsvg-convert not found: skipping", svg.replace(".svg", ".png"))
        return
    subprocess.run([exe, "-z", "2", "-o", svg[:-4] + ".png", svg], check=True)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for f in (remkey(out), remtlm(out)):
        png(f)
        print("wrote", f)
