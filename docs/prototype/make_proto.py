"""Hole-by-hole wiring diagrams for the remtlm prototype on ElectroCookie mini boards.

ElectroCookie mini solderable breadboard: rows 1-17; in each row A-E are joined and
F-J are joined (separately). Coordinates below use the board's own printed labels.
Regenerate:  python3 docs/prototype/make_proto.py docs/prototype
"""
import sys
from xml.sax.saxutils import escape

U = 26                     # px per 0.1 in
COLX = {c: i for i, c in enumerate("ABCDE")} | {c: i + 7 for i, c in enumerate("FGHIJ")}
COL = {"nano": "#1f5fbf", "5v": "#c62828", "gnd": "#222222", "14v": "#e67e00", "sense": "#7b1fa2",
       "jump": "#8a8a8a", "probe": "#c9a400", "part": "#2e7d32", "pin": "#555555"}


class Drawing:
    def __init__(self, title, subtitle, width=1640):
        self.title, self.subtitle, self.w = title, subtitle, width
        self.x0, self.y0 = 420, 140
        self.el, self.callouts = [], []

    def xy(self, hole):
        c, r = hole[0], int(hole[1:])
        return self.x0 + COLX[c] * U, self.y0 + (r - 1) * U

    def board(self):
        x0, y0 = self.x0 - 40, self.y0 - 50
        w, h = 11 * U + 80, 16 * U + 100
        self.el.append(f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="14" fill="#1d3f7a"/>')
        for c, i in COLX.items():
            x = self.x0 + i * U
            self.el.append(f'<text x="{x}" y="{self.y0 - 22}" class="lab">{c}</text>')
            self.el.append(f'<text x="{x}" y="{self.y0 + 16 * U + 34}" class="lab">{c}</text>')
        for r in range(1, 18):
            y = self.y0 + (r - 1) * U
            self.el.append(f'<text x="{self.x0 - 24}" y="{y + 5}" class="lab">{r}</text>')
            self.el.append(f'<text x="{self.x0 + 11 * U + 24}" y="{y + 5}" class="lab">{r}</text>')
            for half in ("ABCDE", "FGHIJ"):
                xa, xb = self.x0 + COLX[half[0]] * U, self.x0 + COLX[half[-1]] * U
                self.el.append(f'<line x1="{xa}" y1="{y}" x2="{xb}" y2="{y}" stroke="#d8b65a" stroke-width="7" opacity="0.35"/>')
            for c in COLX:
                x = self.x0 + COLX[c] * U
                self.el.append(f'<circle cx="{x}" cy="{y}" r="6" fill="#e9c46a" stroke="#b8902e"/>')

    def pin(self, hole, text, color=COL["pin"], side="l"):
        x, y = self.xy(hole)
        self.el.append(f'<rect x="{x - 8}" y="{y - 8}" width="16" height="16" fill="{color}"/>')
        if text:
            tx = x - 14 if side == "l" else x + 14
            anchor = "end" if side == "l" else "start"
            self.el.append(f'<text x="{tx}" y="{y + 4}" class="sm" fill="#fff" text-anchor="{anchor}">{escape(text)}</text>')

    def module(self, holes, text, color="#3d3d3d"):
        xs = [self.xy(h)[0] for h in holes]
        ys = [self.xy(h)[1] for h in holes]
        self.el.append(f'<rect x="{min(xs) - 12}" y="{min(ys) - 12}" width="{max(xs) - min(xs) + 24}" '
                       f'height="{max(ys) - min(ys) + 24}" rx="4" fill="{color}" opacity="0.85"/>')
        for h in holes:
            x, y = self.xy(h)
            self.el.append(f'<circle cx="{x}" cy="{y}" r="5" fill="#ccc"/>')
        self.el.append(f'<text x="{(min(xs) + max(xs)) / 2}" y="{max(ys) + 30}" class="sm" fill="#fff" text-anchor="middle">{escape(text)}</text>')

    def resistor(self, a, b, text, color=COL["part"], standing=False):
        (x1, y1), (x2, y2) = self.xy(a), self.xy(b)
        self.el.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#ddd" stroke-width="3"/>')
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        vertical = abs(y2 - y1) > abs(x2 - x1)
        bw, bh = (12, 30) if vertical else (30, 12)
        if standing:
            bw, bh = 16, 16
        self.el.append(f'<rect x="{mx - bw / 2}" y="{my - bh / 2}" width="{bw}" height="{bh}" rx="3" fill="{color}" stroke="#fff"/>')
        for x, y in ((x1, y1), (x2, y2)):
            self.el.append(f'<circle cx="{x}" cy="{y}" r="4" fill="#ddd"/>')
        if text:
            if vertical:
                self.el.append(f'<text x="{mx + 9}" y="{my + 4}" class="tiny" fill="#fff">{escape(text)}</text>')
            else:
                self.el.append(f'<text x="{mx}" y="{my - 10}" class="tiny" fill="#fff" text-anchor="middle">{escape(text)}</text>')

    def cap(self, a, b, text, polar=False):
        (x1, y1), (x2, y2) = self.xy(a), self.xy(b)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        self.el.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#ddd" stroke-width="3"/>')
        r = 15 if polar else 9
        self.el.append(f'<circle cx="{mx}" cy="{my}" r="{r}" fill="{"#203a8a" if polar else "#d08a2a"}" stroke="#fff"/>')
        if polar:
            self.el.append(f'<text x="{x1 + 9}" y="{y1 + 4}" class="tiny" fill="#fff">+</text>')
        self.el.append(f'<text x="{mx + r + 4}" y="{my + 4}" class="tiny" fill="#fff">{escape(text)}</text>')

    def jumper(self, a, b, color=COL["jump"]):
        (x1, y1), (x2, y2) = self.xy(a), self.xy(b)
        self.el.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="4"/>')
        for x, y in ((x1, y1), (x2, y2)):
            self.el.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{color}"/>')

    def wire(self, hole, text, color, side="r", lane=0.0):
        """A wire leaving the board to a callout at the margin. lane is a half-row offset:
        a wire that has to cross occupied holes runs between rows (lane=-0.5) so it
        can't be read as a connection. Callout labels are kept at least 22 px apart."""
        x, y = self.xy(hole)
        right = side == "r"
        edge = self.x0 + 11 * U + 50 if right else self.x0 - 60
        ex = edge + (40 if right else -40)
        ty = y + lane * U
        used = self.__dict__.setdefault("_used", {"r": [], "l": []})[side]
        ly = ty
        while any(abs(ly - u) < 22 for u in used):
            ly += 6
        used.append(ly)
        step = 0.5 * U if right else -0.5 * U
        pts = [(x, y)]
        if lane:
            pts.append((x + step, ty))
        pts += [(edge, ty), (ex, ly)]
        self.el.append('<polyline points="' + " ".join(f"{a},{b}" for a, b in pts)
                       + f'" fill="none" stroke="{color}" stroke-width="3.5"/>')
        self.el.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{color}"/>')
        if text:
            anchor = "start" if right else "end"
            tx = ex + 8 if right else ex - 8
            self.el.append(f'<text x="{tx}" y="{ly + 5}" class="sm" fill="{color}" text-anchor="{anchor}">{escape(text)}</text>')

    def note(self, lines, x=None, y=None):
        x = x if x is not None else self.x0 + 11 * U + 340
        y = y if y is not None else self.y0
        for i, ln in enumerate(lines):
            self.el.append(f'<text x="{x}" y="{y + i * 22}" class="note">{escape(ln)}</text>')

    def svg(self):
        h = self.y0 + 17 * U + 120
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{h}" viewBox="0 0 {self.w} {h}" '
                f'font-family="DejaVu Sans, Arial, sans-serif">'
                '<style>.lab{font-size:13px;fill:#cfd8e6;text-anchor:middle}.sm{font-size:13px}.tiny{font-size:11px}'
                '.note{font-size:14px;fill:#222}.t{font-size:22px;font-weight:bold;fill:#111}.st{font-size:14px;fill:#444}</style>'
                f'<rect width="{self.w}" height="{h}" fill="#fafaf7"/>'
                f'<text x="24" y="36" class="t">{escape(self.title)}</text>'
                f'<text x="24" y="60" class="st">{escape(self.subtitle)}</text>')
        return head + "".join(self.el) + "</svg>"


E220 = ["M0", "M1", "RXD", "TXD", "AUX", "VCC", "GND"]          # rows 2..8, as soldered


RIBBON = ["purple", "blue", "green", "yellow", "orange", "red", "gold"]   # M0 .. GND


def e220_board():
    d = Drawing("Shack E220 board (as built)",
                "E220 pins in E10-E16 (M0 at E10), ribbon header in C10-C16. Add the two capacitors.")
    d.board()
    d.module([f"E{r}" for r in range(10, 17)], "", "#2b2b2b")
    x, y = d.xy("H9")
    d.el.append(f'<text x="{x}" y="{y + 4}" class="sm" fill="#fff" text-anchor="middle">E220 above, antenna -&gt;</text>')
    for i, n in enumerate(E220):
        d.pin(f"C{i + 10}", "", "#777")
        x, y = d.xy(f"A{i + 10}")
        d.el.append(f'<text x="{x - 60}" y="{y + 5}" class="sm" fill="#222" text-anchor="end">{n}  ({RIBBON[i]})</text>')
    d.cap("A15", "A16", "", polar=True)
    d.cap("B15", "B16", "")
    x, y = d.xy("A17")
    d.el.append(f'<text x="{x - 60}" y="{y + 14}" class="sm" fill="#203a8a" text-anchor="end">100 uF A15(+)-A16</text>')
    d.el.append(f'<text x="{x - 60}" y="{y + 34}" class="sm" fill="#a0601a" text-anchor="end">100 nF B15-B16</text>')
    d.note(["Rows 10-16, top to bottom: M0, M1, RXD, TXD, AUX,",
            "VCC, GND (M0 is the pin at the end next to the",
            "module's four small holes).",
            "",
            "Row 15 = VCC (+5 V), row 16 = GND.",
            "100 uF electrolytic: + lead in A15, - lead in A16.",
            "100 nF ceramic: B15 to B16.",
            "",
            "Ribbon colors (as plugged into C10-C16):",
            "purple M0, blue M1, green RXD, yellow TXD,",
            "orange AUX, red VCC, gold GND.",
            "Check with a meter: red should read the E220's",
            "VCC pin, gold its GND pin.",
            "",
            "The other end of the ribbon goes to A2-A8 on the",
            "interface board: purple in A2 ... gold in A8.",
            "",
            "Build the supply box's E220 board the same way."])
    return d


def ribbon_and_dividers(d):
    for i, n in enumerate(E220):
        d.pin(f"A{i + 2}", "", "#666")
        x, y = d.xy(f"A{i + 2}")
        d.el.append(f'<text x="{x - 60}" y="{y + 5}" class="sm" fill="#222" text-anchor="end">ribbon {n} ({RIBBON[i]})</text>')
    d.resistor("B2", "B8", "2k")
    d.resistor("C3", "C8", "2k")
    d.resistor("D4", "D8", "2k")
    for r in (2, 3, 4):
        d.resistor(f"E{r}", f"F{r}", "", color="#1b8a3a", standing=True)
    d.wire("J2", "Nano D9   (E220 M0)", COL["nano"])
    d.wire("J3", "Nano D10  (E220 M1)", COL["nano"])
    d.wire("J4", "Nano D8   (to E220 RXD)", COL["nano"])
    d.wire("E5", "Nano D7   (from E220 TXD)", COL["nano"], lane=-0.5)
    d.wire("E6", "Nano D6   (E220 AUX)", COL["nano"], lane=-0.5)


DIV_NOTE = ["Ribbon pins into A2-A8: purple (M0) in A2, blue A3,",
            "green A4, yellow A5, orange A6, red (VCC) A7, gold (GND) A8.",
            "",
            "Dividers, 5 V Nano -> 3.3 V E220 (M0, M1, RXD):",
            "  1k standing, across the gap: E2-F2, E3-F3, E4-F4",
            "  2k lying flat: B2-B8, C3-C8, D4-D8",
            "TXD and AUX go straight to the Nano (no divider).",
            ""]


def shack_board():
    d = Drawing("Shack (BASE) interface board",
                "Ribbon from the E220 board -> dividers -> wires to the Nano carrier's screw terminals")
    d.board()
    ribbon_and_dividers(d)
    d.wire("E7", "Nano 5V", COL["5v"], lane=-0.5)
    d.wire("E8", "Nano GND", COL["gnd"], lane=-0.5)
    d.note(DIV_NOTE + ["Row 7 (ribbon VCC) -> Nano 5V; row 8 (ribbon GND)",
                       "-> Nano GND. The shack PC's USB powers the Nano,",
                       "and its 5V terminal powers the E220.",
                       "",
                       "Wires that cross the board run between the rows",
                       "in the drawing. Use insulated wire for those.",
                       "Blue = signal, red = +5 V, black = GND."])
    return d


def psu_interface_board():
    d = Drawing("Supply box (PSU) interface board",
                "Same as the shack board, plus the +5 V / GND buses and the DS18B20")
    d.board()
    ribbon_and_dividers(d)
    d.jumper("E7", "F7", COL["5v"])
    d.jumper("E8", "F8", COL["gnd"])
    d.wire("G6", "Nano D5   (DS18B20 DQ)", COL["nano"], lane=0.0)
    d.wire("G7", "Nano 5V", COL["5v"])
    d.wire("H7", "+5 V from the power board", COL["5v"], lane=0.25)
    d.wire("G8", "Nano GND", COL["gnd"], lane=0.25)
    d.wire("H8", "GND from the power board", COL["gnd"], lane=0.5)
    d.resistor("I6", "I7", "", color="#1b8a3a", standing=True)
    d.pin("F6", "", COL["probe"])
    d.pin("J7", "", COL["5v"])
    d.pin("I8", "", COL["gnd"])
    d.note(DIV_NOTE + ["Buses: E7-F7 makes right row 7 +5 V; E8-F8 makes",
                       "right row 8 GND.",
                       "",
                       "DS18B20 box probe: yellow (DQ) F6, red J7, black I8.",
                       "4.7k pull-up standing, I6-I7.",
                       "",
                       "The Nano is powered from its 5V terminal (not VIN).",
                       "Wires that cross the board run between the rows",
                       "in the drawing. Use insulated wire for those."])
    return d


def psu_power_board():
    d = Drawing("Supply box (PSU) power board",
                "Polyfuse + fixed 5 V buck, INA226 module")
    d.board()
    ina = ["IN+", "IN-", "VBS", "ALE", "SDA", "SCL", "GND", "VCC"]
    # INA226 header in F2-F9; module body lies over the left half (rows 1-9)
    xs, ys = d.xy("A1")[0] - 14, d.xy("A1")[1] - 6
    xe, ye = d.xy("F9")[0] + 12, d.xy("F9")[1] + 12
    d.el.append(f'<rect x="{xs}" y="{ys}" width="{xe - xs}" height="{ye - ys}" rx="4" fill="#1565c0" opacity="0.55"/>')
    d.el.append(f'<text x="{(xs + xe) / 2 - 10}" y="{(ys + ye) / 2}" class="sm" fill="#fff" text-anchor="middle">INA226 module</text>')
    d.el.append(f'<text x="{(xs + xe) / 2 - 10}" y="{(ys + ye) / 2 + 18}" class="tiny" fill="#fff" text-anchor="middle">(remove its R100)</text>')
    for i, n in enumerate(ina):
        d.pin(f"F{2 + i}", "", "#0d47a1")
        x, y = d.xy(f"F{2 + i}")
        d.el.append(f'<text x="{x - 14}" y="{y + 4}" class="tiny" fill="#fff" text-anchor="end">{n}</text>')
    d.wire("J2", "SHUNT+ sense lead (supply side)", COL["sense"])
    d.wire("J3", "SHUNT- sense lead (tower side)", COL["sense"])
    d.jumper("H3", "H4", COL["jump"])
    d.wire("J6", "Nano A4  (SDA)", COL["nano"])
    d.wire("J7", "Nano A5  (SCL)", COL["nano"])
    # power, left half rows 11-17
    d.wire("A11", "+14 V tap (supply side of the shunt)", COL["14v"], "l")
    d.cap("C11", "C13", "PTC 0.5 A")
    x0, y0 = d.xy("F11")
    x1, y1 = d.xy("J16")
    d.el.append(f'<rect x="{x0 - 10}" y="{y0 - 10}" width="{x1 - x0 + 20}" height="{y1 - y0 + 20}" rx="4" '
                'fill="#333" opacity="0.6" stroke="#fff" stroke-dasharray="5,4"/>')
    d.el.append(f'<text x="{(x0 + x1) / 2}" y="{(y0 + y1) / 2 - 4}" class="sm" fill="#fff" text-anchor="middle">buck</text>')
    d.el.append(f'<text x="{(x0 + x1) / 2}" y="{(y0 + y1) / 2 + 14}" class="tiny" fill="#fff" text-anchor="middle">on foam tape</text>')
    d.wire("A13", "buck IN+", COL["14v"], "l")
    d.wire("A15", "supply GND", COL["gnd"], "l")
    d.wire("B15", "buck IN-", COL["gnd"], "l", lane=-0.5)
    d.wire("C15", "buck OUT-", COL["gnd"], "l", lane=0.5)
    d.wire("A17", "buck OUT+", COL["5v"], "l")
    # local feeds to the INA226 and out to the interface board
    d.jumper("E15", "G8", COL["gnd"])
    d.jumper("E17", "G9", COL["5v"])
    d.wire("J9", "+5 V to the interface board (H7)", COL["5v"])
    d.wire("J8", "GND to the interface board (H8)", COL["gnd"])
    d.note(["INA226: header pins in F2-F9, IN+ in F2 ... VCC in F9.",
            "The module lies over the left half, rows 1-9 (nothing",
            "else goes there). Remove its R100 shunt.",
            "  SHUNT+ / SHUNT- sense leads: J2, J3",
            "  VBS tied to IN-: jumper H3-H4",
            "  SDA J6 -> Nano A4, SCL J7 -> Nano A5",
            "  GND G8 <- E15, VCC G9 <- E17 (insulated jumpers)",
            "",
            "Power (left half):",
            "  +14 V tap -> A11, polyfuse standing C11-C13,",
            "  row 13 -> buck IN+",
            "  supply GND -> A15; buck IN- B15, OUT- C15",
            "  buck OUT+ -> A17 (row 17 = +5 V)",
            "  +5 V (J9) and GND (J8) -> interface board",
            "",
            "Buck: fixed 5 V, nothing to set. Stick it on foam tape",
            "over the empty right half, rows 11-16, and run short",
            "insulated wires from its corner pads. Don't solder its",
            "pads into the holes: rows would short IN+ to OUT+.",
            "The +14 V tap is the box's own supply only; the",
            "tower's main current never passes through here."])
    return d


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, fn in (("proto-e220-board", e220_board), ("proto-shack-interface", shack_board),
                     ("proto-psu-interface", psu_interface_board), ("proto-psu-power", psu_power_board)):
        open(f"{out}/{name}.svg", "w").write(fn().svg())
        print(name)
