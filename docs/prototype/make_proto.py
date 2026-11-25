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
        self.min_h = max(getattr(self, "min_h", 0), y + len(lines) * 22 + 20)

    def svg(self):
        h = max(self.y0 + 17 * U + 120, getattr(self, "min_h", 0))
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


# ---------------------------------------------------------------------------
# Tower-top board: everything on one board. The E220 plugs into a tall 1x7 socket
# in A1-A7 and lies flat over rows 1-8; the buck rides on foam tape under it, over
# the right half of rows 1-7. Field wiring leaves the left edge, Nano wiring the right.
# ---------------------------------------------------------------------------
class Netcheck:
    """Every hole used once; every strip (row, half) carries one net."""

    def __init__(self):
        self.holes, self.strips = {}, {}

    def use(self, hole, net, what):
        assert hole not in self.holes, f"{hole} used twice: {self.holes[hole]} and {what}"
        self.holes[hole] = what
        key = (int(hole[1:]), "L" if hole[0] in "ABCDE" else "R")
        old = self.strips.setdefault(key, net)
        assert old == net, f"strip {key}: {old} vs {net} ({what} at {hole})"


TOWER_STRIPS = {
    (1, "L"): "M0_E", (2, "L"): "M1_E", (3, "L"): "RXD_E", (4, "L"): "TXD", (5, "L"): "AUX",
    (6, "L"): "5V", (7, "L"): "GND",
    (1, "R"): "M0_N", (2, "R"): "M1_N", (3, "R"): "RXD_N", (4, "R"): "TXD", (5, "R"): "AUX",
    (6, "R"): "5V", (7, "R"): "GND",
    (8, "L"): "LD", (8, "R"): "GND", (9, "L"): "PA_SENSE", (9, "R"): "A0",
    (10, "L"): "GND", (10, "R"): "GND", (11, "L"): "MON", (11, "R"): "A1",
    (12, "L"): "PTT_LINE", (12, "R"): "A3", (13, "L"): "5V", (13, "R"): "GND",
    (14, "L"): "XV_TXD", (15, "L"): "XV_RXD", (16, "L"): "3V3", (17, "L"): "GND",
    (14, "R"): "XV_RX", (15, "R"): "XV_TX", (16, "R"): "5V", (17, "R"): "GND",
}


def tower_board():
    d = Drawing("Tower-top board (TOWER): one ElectroCookie mini + the Nano carrier",
                "E220 in a tall socket at A1-A7, lying flat over rows 1-8; buck on foam tape under it. "
                "Field wires and three Nano wires leave the left edge; the other Nano wires leave the right.", width=1700)
    d.board()
    nc = Netcheck()

    def net(h):
        return TOWER_STRIPS[(int(h[1:]), "L" if h[0] in "ABCDE" else "R")]

    def two(a, b, what):
        nc.use(a, net(a), what)
        nc.use(b, net(b), what)

    # E220 socket and dividers
    for i, n in enumerate(E220):
        h = f"A{i + 1}"
        nc.use(h, net(h), f"E220 {n}")
        d.pin(h, "", "#111")
        x, y = d.xy(h)
        d.el.append(f'<text x="{x + 11}" y="{y - 7}" class="tiny" fill="#fff">{n}</text>')
    for a, b in (("B1", "B7"), ("C2", "C7"), ("D3", "D7")):
        two(a, b, "2k")
        d.resistor(a, b, "2k")
    for r in (1, 2, 3):
        two(f"E{r}", f"F{r}", "1k")
        d.resistor(f"E{r}", f"F{r}", "1k")
    for r, c in ((4, COL["nano"]), (5, COL["nano"]), (6, COL["5v"]), (7, COL["gnd"])):
        two(f"E{r}", f"F{r}", "bus jumper")
        d.jumper(f"E{r}", f"F{r}", c)
    two("I6", "I7", "100nF E220")
    d.cap("I6", "I7", "100n")
    two("J7", "J8", "jumper")
    d.jumper("J7", "J8", COL["gnd"])

    # buck pads (it sits on foam tape over F1-J7, under the E220)
    for h, lab, c in (("G6", "OUT+", COL["5v"]), ("G7", "OUT-", COL["gnd"]), ("H7", "IN-", COL["gnd"])):
        nc.use(h, net(h), f"buck {lab}")
        d.pin(h, "", c)

    # analog inputs
    two("E8", "F8", "100k LD pull-down")
    d.resistor("E8", "F8", "100k")
    two("E9", "F9", "10k PA")
    d.resistor("E9", "F9", "", standing=True)
    two("G9", "G10", "22k A0")
    d.resistor("G9", "G10", "", standing=True)
    two("H9", "H10", "100nF A0")
    d.cap("H9", "H10", "")
    two("E10", "F10", "GND jumper")
    d.jumper("E10", "F10", COL["gnd"])
    two("E11", "F11", "10k MON")
    d.resistor("E11", "F11", "", standing=True)
    two("I11", "I10", "22k A1")
    d.resistor("I11", "I10", "", standing=True)
    two("J11", "J10", "100nF A1")
    d.cap("J11", "J10", "")

    # key line to the sequencer (MKU CON1 pin 8) -> A3
    two("E12", "F12", "47k PTT")
    d.resistor("E12", "F12", "", standing=True)
    two("D12", "D13", "100k PTT pull-up")
    d.resistor("D12", "D13", "", standing=True)
    two("G12", "G13", "22k A3")
    d.resistor("G12", "G13", "", standing=True)
    two("H12", "H13", "100nF A3")
    d.cap("H12", "H13", "")
    two("I16", "I17", "100uF")
    d.cap("I16", "I17", "", polar=True)

    # BSS138 module in a socket: LV pins in D14-D17, HV pins in F14-F17; LV3/LV4 end hangs past row 17
    for r, lv, hv in ((14, "LV1", "HV1"), (15, "LV2", "HV2"), (16, "LV", "HV"), (17, "GND", "GND")):
        nc.use(f"D{r}", net(f"D{r}"), f"BSS138 {lv}")
        nc.use(f"F{r}", net(f"F{r}"), f"BSS138 {hv}")
    x0, y0 = d.xy("D14")
    x1, _ = d.xy("F14")
    y1 = d.xy("F17")[1] + 2 * U
    d.el.append(f'<rect x="{x0 - 14}" y="{y0 - 14}" width="{x1 - x0 + 28}" height="{y1 - y0 + 28}" rx="4" '
                'fill="#0b5d3b" opacity="0.8" stroke="#fff" stroke-dasharray="5,4"/>')
    for r, lv, hv in ((14, "LV1", "HV1"), (15, "LV2", "HV2"), (16, "LV", "HV"), (17, "GND", "GND")):
        d.pin(f"D{r}", "", "#0d3")
        d.pin(f"F{r}", "", "#0d3")
        x, y = d.xy(f"E{r}")
        d.el.append(f'<text x="{x}" y="{y + 4}" class="tiny" fill="#fff" text-anchor="middle">{lv}|{hv}</text>')
    d.el.append(f'<text x="{(x0 + x1) / 2}" y="{y1 + 4}" class="tiny" fill="#fff" text-anchor="middle">LV3/LV4 off board</text>')

    # links on the underside (insulated)
    def under(a, b, color):
        two(a, b, "underside link")
        (xa, ya), (xb, yb) = d.xy(a), d.xy(b)
        d.el.append(f'<line x1="{xa}" y1="{ya}" x2="{xb}" y2="{yb}" stroke="{color}" stroke-width="3" '
                    'stroke-dasharray="7,5" opacity="0.9"/>')
        for x, y in ((xa, ya), (xb, yb)):
            d.el.append(f'<circle cx="{x}" cy="{y}" r="5" fill="none" stroke="{color}" stroke-width="2"/>')
    under("G8", "D10", COL["gnd"])
    under("B17", "C10", COL["gnd"])
    under("G17", "C17", COL["gnd"])
    under("J6", "J16", COL["5v"])
    under("H16", "A13", COL["5v"])
    under("H17", "J13", COL["gnd"])

    # field wires, left edge
    left = [("A8", "MKU CON1 16  LD", COL["sense"]), ("B8", None, None),
            ("A9", "PA power sense", COL["sense"]), ("A10", "MKU CON1 15  GND", COL["gnd"]),
            ("B10", "PA GND", COL["gnd"]), ("A11", "MKU CON1 9  MON", COL["sense"]),
            ("A12", "MKU CON1 8  PTT out", COL["sense"]), ("A14", "MKU CON1 11  TXD", COL["sense"]),
            ("A15", "MKU CON1 12  RXD", COL["sense"]), ("A17", "supply GND in", COL["gnd"])]
    for h, lab, c in left:
        if lab is None:
            continue
        nc.use(h, net(h), lab)
        d.wire(h, lab, c, "l", lane=-0.5 if h[0] == "B" else 0.0)
    # Nano wires, right edge
    right = [("J1", "Nano D9   (M0)"), ("J2", "Nano D10  (M1)"), ("J3", "Nano D8   (to RXD)"),
             ("J4", "Nano D7   (from TXD)"), ("J5", "Nano D6   (AUX)"), ("I8", "Nano GND"),
             ("J9", "Nano A0   (PA)"), ("G11", "Nano A1   (MON)"), ("J12", "Nano A3   (key line)"),
             ("J14", "Nano D11  (MKU RX)"),
             ("J15", "Nano D12  (MKU TX)"), ("G16", "Nano 5V")]
    for h, lab in right:
        nc.use(h, net(h), lab)
        c = COL["5v"] if "5V" in lab else COL["gnd"] if "GND" in lab else COL["nano"]
        d.wire(h, lab, c, "r", lane=0.0 if h[0] == "J" else -0.5)
    for h, lab, lane in (("B8", "Nano A2  (LD)", 0.5), ("A16", "Nano 3V3  (shifter LV)", 0.0)):
        nc.use(h, net(h), lab)
        d.wire(h, lab, COL["nano"], "l", lane=lane)
    # probe power on the right half
    for h, lab, c, side in (("B13", "probe 1 red", COL["5v"], "l"), ("C13", "probe 2 red", COL["5v"], "l"),
                            ("I13", "probe 2 black", COL["gnd"], "r"), ("J17", "probe 1 black", COL["gnd"], "r")):
        nc.use(h, net(h), lab)
        d.wire(h, lab, c, side, lane=0.0 if h[0] in "AJ" else 0.5 if side == "r" else -0.5)

    # outlines: E220 over rows 1-8 and past the right edge; buck over F1-J7
    xa, ya = d.xy("A1")
    xj, y8 = d.xy("J8")
    d.el.append(f'<rect x="{xa - 10}" y="{ya - 30}" width="{xj - xa + 70}" height="{y8 - ya + 34}" rx="6" '
                'fill="none" stroke="#ffd54f" stroke-width="3" stroke-dasharray="10,6"/>')
    d.el.append(f'<text x="{xa - 30}" y="{ya - 64}" class="sm" fill="#b8860b">E220 outline (above, on the tall socket); SMA end -&gt;</text>')
    xf, yf = d.xy("F1")
    xj7, yj7 = d.xy("J7")
    d.el.append(f'<rect x="{xf - 12}" y="{yf - 14}" width="{xj7 - xf + 24}" height="{yj7 - yf + 28}" rx="4" '
                'fill="none" stroke="#9be7ff" stroke-width="3" stroke-dasharray="4,4"/>')
    d.el.append(f'<text x="{(xf + xj7) / 2}" y="{(yf + yj7) / 2 + 6}" class="sm" fill="#9be7ff" text-anchor="middle">buck</text>')

    d.note(["E220: tall 1x7 socket in A1-A7 (M0 in A1 ... GND in A7,",
            "  M0 = pin next to the module's four small holes). The module",
            "  lies flat over rows 1-8; only flat parts go under it.",
            "Dividers: 2k flat B1-B7, C2-C7, D3-D7; 1k flat across the",
            "  gap E1-F1, E2-F2, E3-F3. Jumpers E4-F4 (TXD), E5-F5 (AUX),",
            "  E6-F6 (+5 V), E7-F7 (GND), J7-J8 (GND). 100 nF flat I6-I7.",
            "Buck: foam tape over F1-J7, under the E220. Short wires:",
            "  OUT+ G6, OUT- G7, IN- H7. Solder everything under it",
            "  first, and leave the wire ends at J1-J5 long.",
            "+13.8 V: PTC (0.5 A) in line in the lead, heat-shrunk,",
            "  straight to the buck's IN+ pad. Supply GND -> A17.",
            "Analog: PA sense -> A9, 10k E9-F9, 22k G9-G10, 100 nF H9-H10.",
            "  MON -> A11, 10k E11-F11, 22k I11-I10, 100 nF J11-J10.",
            "  LD -> A8, 100k flat E8-F8 (row 8 is under the E220 edge).",
            "  Row 10 is GND, both halves (jumper E10-F10).",
            "Key line (MKU pin 8) -> A12: 47k E12-F12, 100k D12-D13",
            "  (pull-up), 22k G12-G13, 100 nF H12-H13, J12 -> Nano A3.",
            "  Row 13: +5 V on the left, GND on the right.",
            "DS18B20 x2: red B13, C13; black J17, I13. Both yellow",
            "  wires to the Nano's D5 terminal, with the 4.7k",
            "  between the carrier's D5 and 5V terminals.",
            "100 uF I16 (+) to I17.",
            "BSS138 shifter in a socket cut to 2 x 4: LV1 D14, LV2 D15,",
            "  LV D16, GND D17; HV1 F14 ... GND F17. Its LV3/LV4 end",
            "  hangs past row 17 (no holes there).",
            "Dashed lines: insulated wire on the underside:",
            "  G8-D10, B17-C10, G17-C17, H17-J13 (GND);",
            "  J6-J16, H16-A13 (+5 V)."],
           x=d.x0 + 11 * U + 400, y=d.y0 - 20)
    used = len(nc.holes)
    return d, used


# ---------------------------------------------------------------------------
# Tower sensor board: dish elevation (ADXL355) and box environment (BME280), for a
# RK-302 Rev A board. Same BSS138 4-channel module as on the RK-302: channel 1 SDA,
# channel 2 SCL. The 3.3 V side carries the two sensor headers; the 5 V side goes to
# the Nano's A4/A5. Rows 6-7 hold the module's unused channels 3 and 4.
# ---------------------------------------------------------------------------
SENSOR_STRIPS = {
    (2, "L"): "SDA_3V3", (3, "L"): "SCL_3V3", (4, "L"): "3V3", (5, "L"): "GND",
    (6, "L"): "LV3", (7, "L"): "LV4",
    (2, "R"): "SDA_5V", (3, "R"): "SCL_5V", (4, "R"): "5V", (5, "R"): "GND",
    (6, "R"): "HV3", (7, "R"): "HV4",
}
SHIFTER = (("LV1", "HV1"), ("LV2", "HV2"), ("LV", "HV"), ("GND", "GND"), ("LV3", "HV3"), ("LV4", "HV4"))


def tower_sensor_board():
    d = Drawing("Tower sensor board (dish elevation + box environment) for a RK-302 Rev A",
                "Same BSS138 4-channel shifter as on the RK-302: channel 1 = SDA, channel 2 = SCL. "
                "ADXL355 plate and BME280 on 4-wire leads; five wires to the Rev A board.",
                width=1700)
    d.board()
    nc = Netcheck()

    def net(h):
        return SENSOR_STRIPS[(int(h[1:]), "L" if h[0] in "ABCDE" else "R")]

    # shifter in two 1x6 sockets: LV row in D2-D7, HV row in F2-F7
    for i, (lv, hv) in enumerate(SHIFTER):
        r = i + 2
        nc.use(f"D{r}", net(f"D{r}"), f"BSS138 {lv}")
        nc.use(f"F{r}", net(f"F{r}"), f"BSS138 {hv}")
    x0, y0 = d.xy("D2")
    x1, y1 = d.xy("F7")
    d.el.append(f'<rect x="{x0 - 14}" y="{y0 - 14}" width="{x1 - x0 + 28}" height="{y1 - y0 + 28}" rx="4" '
                'fill="#0b5d3b" opacity="0.8" stroke="#fff" stroke-dasharray="5,4"/>')
    for i, (lv, hv) in enumerate(SHIFTER):
        r = i + 2
        d.pin(f"D{r}", "", "#0d3")
        d.pin(f"F{r}", "", "#0d3")
        x, y = d.xy(f"E{r}")
        d.el.append(f'<text x="{x}" y="{y + 4}" class="tiny" fill="#fff" text-anchor="middle">{lv}|{hv}</text>')
    d.el.append(f'<text x="{(x0 + x1) / 2}" y="{y1 + 30}" class="tiny" fill="#fff" text-anchor="middle">'
                'BSS138 4ch (ch 3, 4 unused)</text>')

    # sensor headers on the 3.3 V side: B2-B5 = ADXL355 plate, C2-C5 = BME280 (SDA, SCL, 3V3, GND)
    order = ("SDA", "SCL", "3V3", "GND")
    for col, who, color in (("B", "ADXL355", "#6a1b9a"), ("C", "BME280", "#00838f")):
        for i, n in enumerate(order):
            h = f"{col}{i + 2}"
            nc.use(h, net(h), f"{who} {n}")
            d.pin(h, "", color)
    for r, n in ((2, "SDA (3.3 V)"), (3, "SCL (3.3 V)"), (5, "GND")):
        x, y = d.xy(f"A{r}")
        d.el.append(f'<text x="{x - 48}" y="{y + 5}" class="sm" fill="#222" text-anchor="end">row {r}: {n}</text>')
    xb, yb = d.xy("A17")
    for i, (txt, color) in enumerate((("purple, B2-B5: ADXL355 plate lead", "#6a1b9a"),
                                      ("teal, C2-C5: BME280 lead", "#00838f"),
                                      ("each top to bottom: SDA, SCL, 3V3, GND", "#222"))):
        d.el.append(f'<text x="{xb - 40}" y="{yb + 80 + i * 20}" class="sm" fill="{color}">{txt}</text>')
    d.min_h = yb + 150

    # +3.3 V from the Rev A board's regulator, into row 4 left (left edge, straight in)
    nc.use("A4", net("A4"), "3V3 in")
    d.wire("A4", "Rev A: +3.3 V (AMS1117 OUT)", "#ef6c00", "l")
    # wires to the Rev A board, right edge
    for h, lab, c in (("J2", "Rev A: Nano A4  (SDA)", COL["nano"]), ("J3", "Rev A: Nano A5  (SCL)", COL["nano"]),
                      ("J4", "Rev A: +5 V", COL["5v"]), ("J5", "Rev A: GND", COL["gnd"])):
        nc.use(h, net(h), lab)
        d.wire(h, lab, c, "r")

    d.note(["Shifter: the same BSS138 4-channel module as on the RK-302,",
            "  in two 1x6 sockets: LV1 D2, LV2 D3, LV D4, GND D5, LV3 D6,",
            "  LV4 D7; HV1 F2 ... HV4 F7 (go by the labels on the module).",
            "  Channel 1 carries SDA, channel 2 SCL. Rows 6-7: unused",
            "  channels 3 and 4, nothing else in those rows.",
            "  The module's own 10k pull-ups serve as the I2C pull-ups",
            "  on both sides, so the board needs no others.",
            "",
            "3.3 V side (left half):",
            "  row 2 SDA, row 3 SCL, row 4 +3.3 V, row 5 GND.",
            "  ADXL355 plate lead in B2-B5, BME280 lead in C2-C5",
            "  (SDA, SCL, 3V3, GND from the top). +3.3 V in at A4.",
            "  Column E sits under the module: leave it empty.",
            "",
            "5 V side (right half), five wires to the Rev A board:",
            "  J2 -> Nano A4 (SDA), J3 -> Nano A5 (SCL): solder to the",
            "    Nano socket's A4 / A5 pads on the underside (Rev A",
            "    leaves them unconnected).",
            "  J4 -> +5 V and J5 -> GND: any +5 V / GND pad, e.g. the",
            "    Nano socket's 5V and GND pins.",
            "  A4 <- +3.3 V: the AMS1117 module's OUT pin (U2), or the",
            "    on-board shifter's LV pin (U3). Not the Nano's 3V3.",
            "",
            "Check with a meter before plugging in the sensors:",
            "  row 4 left = 3.3 V, row 4 right = 5 V,",
            "  rows 2 and 3 left idle at 3.3 V, right at 5 V.",
            "",
            "Sensor straps (on the breakouts, for I2C):",
            "  ADXL355: CS/SCL = SCL, MOSI/SDA = SDA, SCLK/VSSIO to GND,",
            "    MISO/ASEL to GND (address 0x1D; to 3.3 V for 0x53).",
            "    VSUPPLY and VDDIO to 3.3 V. Confirm against your",
            "    breakout's documentation.",
            "  BME280: CSB to 3.3 V (I2C mode), SDO to GND (0x76) or",
            "    3.3 V (0x77). Most breakouts strap these already.",
            "  The firmware finds either address of each."],
           x=d.x0 + 11 * U + 420, y=d.y0 - 20)
    return d, len(nc.holes)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for name, fn in (("proto-e220-board", e220_board), ("proto-shack-interface", shack_board),
                     ("proto-psu-interface", psu_interface_board), ("proto-psu-power", psu_power_board)):
        open(f"{out}/{name}.svg", "w").write(fn().svg())
        print(name)
    d, used = tower_board()
    open(f"{out}/proto-tower-board.svg", "w").write(d.svg())
    print(f"proto-tower-board ({used} holes)")
    d, used = tower_sensor_board()
    open(f"{out}/proto-tower-sensors.svg", "w").write(d.svg())
    print(f"proto-tower-sensors ({used} holes)")
