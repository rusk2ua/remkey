"""Generate the remkey (section 1) and remtlm (section 9) schematics (SVG) with schemdraw.

Regenerate from the repo root:  pip install schemdraw && python docs/img/make_schematics.py docs/img
"""
import os
import sys

os.environ.setdefault("SOURCE_DATE_EPOCH", "0")  # no timestamp in the SVGs
import matplotlib  # noqa: E402

matplotlib.rcParams["svg.hashsalt"] = "remkey"   # stable element IDs: regenerating gives no diff
import schemdraw  # noqa: E402
import schemdraw.elements as elm  # noqa: E402

OUT = sys.argv[1]
schemdraw.config(bgcolor="white", fontsize=12, lw=1.6)
GRAY = "#555555"
NOTE = dict(fontsize=10, color=GRAY)


# ------------------------------------------------------------------ client
def client():
    d = schemdraw.Drawing(show=False)
    pins = ["5V", "GND", "A0", "D12", "D9", "D4", "D3", "D2"]  # listed bottom->top
    ic = d.add(elm.Ic(
        pins=[elm.IcPin(name=p, side="right") for p in pins],
        pinspacing=2.4, edgepadW=1.6, leadlen=0.6,
        label="Arduino\nNano\n(client)", lblsize=13))

    X = ic.absanchors["D2"].x
    SW = 4.0  # x where the parts start

    # D2 / D3 paddle (3.5 mm jack, contacts to GND, internal pull-ups)
    for pin, name, lead in (("D2", "DIT", "tip"), ("D3", "DAH", "ring")):
        p = ic.absanchors[pin]
        d.add(elm.Line().at(p).to((X + SW, p.y)).label(f"jack {lead}", loc="top", fontsize=10, color=GRAY))
        d.add(elm.Button().right().label(f"paddle {name}", loc="top"))
        d.add(elm.Line().right().length(1.0).label("sleeve", loc="top", fontsize=10, color=GRAY))
        d.add(elm.Ground())
    d.add(elm.Label().at((X + SW + 6.6, ic.absanchors["D2"].y + 1.1))
          .label("3.5 mm stereo paddle jack — internal pull-ups, contact closes to GND", **NOTE))

    # D4 PTT
    p = ic.absanchors["D4"]
    d.add(elm.Line().at(p).to((X + SW, p.y)))
    d.add(elm.Switch().right().label("PTT", loc="top"))
    d.add(elm.Line().right().length(1.0))
    d.add(elm.Ground())
    d.add(elm.Label().at((X + SW + 6.8, p.y - 0.15)).label(
        'SPST toggle: ptt_switch = "latching"\nmomentary/footswitch: "momentary"', halign="left", **NOTE))

    # D9 sidetone
    p = ic.absanchors["D9"]
    d.add(elm.Line().at(p).to((X + SW - 1.5, p.y)))
    d.add(elm.Resistor().right().label("220 Ω", loc="top"))
    d.add(elm.Line().right().length(0.5))
    d.add(elm.Buzzer().right().label("piezo", loc="top") if hasattr(elm, "Buzzer")
          else elm.Speaker().right().label("piezo", loc="top"))
    d.add(elm.Ground())
    d.add(elm.Label().at((X + SW + 6.8, p.y - 0.15)).label(
        "or: 220 Ω → 100 µF → amp/headphone in,\n10 kΩ to GND for level", halign="left", **NOTE))

    # D12 PTT-confirmed LED
    p = ic.absanchors["D12"]
    d.add(elm.Line().at(p).to((X + SW - 1.5, p.y)))
    d.add(elm.Resistor().right().label("1 kΩ", loc="top"))
    d.add(elm.Line().right().length(0.5))
    d.add(elm.LED().right().label("PTT", loc="top"))
    d.add(elm.Ground())
    d.add(elm.Label().at((X + SW + 6.8, p.y - 0.15)).label(
        "optional: lit when the STATION\nconfirms PTT is on", halign="left", **NOTE))

    # A0 speed pot (optional)
    p = ic.absanchors["A0"]
    px = X + SW + 3.6
    pot = d.add(elm.Potentiometer().up().length(1.6).at((px, p.y - 0.8)).reverse()
                .label("10 kΩ\nspeed", loc="bottom"))
    d.add(elm.Line().at(p).to((pot.tap.x, p.y)))
    d.add(elm.Line().at(pot.end).up().length(0.25))
    d.add(elm.Vdd().label("+5V"))
    d.add(elm.Line().at(pot.start).down().length(0.2))
    d.add(elm.Ground())
    d.add(elm.Label().at((X + SW + 6.8, p.y - 0.15)).label(
        "optional: set USE_SPEED_POT 1", halign="left", **NOTE))

    # GND / 5V pins
    p = ic.absanchors["GND"]
    d.add(elm.Line().at(p).right().length(1.0))
    d.add(elm.Ground())
    p = ic.absanchors["5V"]
    d.add(elm.Line().at(p).right().length(1.0))
    d.add(elm.Label().label("+5V (pot only)", loc="right", halign="left", **NOTE))

    d.add(elm.Label().at((ic.absanchors["5V"].x - 5.2, ic.absanchors["5V"].y - 1.6)).label(
        "Powered and connected to the Mac by USB.   On-board LED (D13) flashes with every element sent.",
        halign="left", **NOTE))
    d.save(f"{OUT}/client-nano-schematic.svg")


# ------------------------------------------------------------------ station
def station():
    d = schemdraw.Drawing(show=False)
    pins = ["GND", "D11", "D10"]
    ic = d.add(elm.Ic(
        pins=[elm.IcPin(name=p, side="right") for p in pins],
        pinspacing=4.0, edgepadW=2.6, leadlen=0.6,
        label="Arduino\nNano\n(station)", lblsize=13))

    X = ic.absanchors["D10"].x
    OX = X + 11.5  # opto anode x
    gnd_in_y = ic.absanchors["GND"].y
    chans = [("D10", "KEY", "1"), ("D11", "PTT", "2")]
    tops = []
    for pin, name, n in chans:
        p = ic.absanchors[pin]
        d.add(elm.Line().at(p).right().length(0.6))
        d.add(elm.Resistor().right().label("220 Ω", loc="top"))
        d.add(elm.Dot(open=True).label(f"IN{n}", loc="top", fontsize=10))
        d.add(elm.Line().right().length(1.4).label("302 bridged", loc="bottom", ofst=0.25, fontsize=9, color="#b00000"))
        d.add(elm.LED().right().length(2.2).label("ind.", loc="top", fontsize=10))
        d.add(elm.Line().to((OX - 0.45, p.y)))
        opto = d.add(elm.Optocoupler().anchor("anode").at((OX - 0.45, p.y))
                     .label(f"PC817 #{n}", loc="top", ofst=(-0.9, 0.5)))
        tops.append(opto)
        # cathode to input-side G bus
        d.add(elm.Line().at(opto.cathode).left().length(0.8))
        cx = opto.cathode.x - 0.8
        d.add(elm.Line().to((cx, gnd_in_y)))
        d.add(elm.Dot())
        # output side
        d.add(elm.Line().at(opto.collector).right().length(1.1))
        d.add(elm.Line().right().length(1.1).label("302 bridged", loc="bottom", fontsize=9, color="#b00000"))
        d.add(elm.Dot(open=True).label(f"V{n}", loc="top", fontsize=10))
        d.add(elm.Line().right().length(1.5))
        if name == "KEY":
            d.add(elm.Line().right().length(0.5).label(
                "→ 7610 KEY jack tip\n   (Y-cable with SO2R+ key out)", loc="right", halign="left"))
        else:
            d.add(elm.Line().right().length(0.5).label(
                "→ SO2R Box rear RCA PTT\n   (center pin)", loc="right", halign="left"))
        ex = opto.emitter.x + 0.8
        d.add(elm.Line().at(opto.emitter).to((ex, opto.emitter.y)))

    # input-side G bus back to Nano GND
    gx_start = ic.absanchors["GND"]
    gx_end = tops[-1].cathode.x - 0.8
    d.add(elm.Line().at(gx_start).to((gx_end, gnd_in_y)))
    d.add(elm.Dot(open=True).at((X + 4.2, gnd_in_y)).label("G (in)", loc="bottom", fontsize=10))

    # output-side G (shared emitters)
    ex = tops[0].emitter.x + 0.8
    out_g_y = gnd_in_y
    d.add(elm.Line().at((ex, tops[0].emitter.y)).to((ex, out_g_y)))
    d.add(elm.Dot().at((ex, tops[1].emitter.y)))
    d.add(elm.Line().at((ex, out_g_y)).right().length(3.7))
    d.add(elm.Dot(open=True).at((ex + 1.2, out_g_y)).label("G (out)", loc="bottom", fontsize=10))
    d.add(elm.Line().at((ex + 3.7, out_g_y)).right().length(0.5).label(
        "→ KEY sleeve + RCA shell\n   (radio-side ground)", loc="right", halign="left"))

    # isolation barrier + jumper
    bx = (tops[0].anode.x + tops[0].collector.x) / 2
    d.add(elm.Line().at((bx, tops[0].anode.y + 2.4)).to((bx, gnd_in_y - 1.2))
          .linestyle("--").color("#1f6fb2"))
    d.add(elm.Label().at((bx, gnd_in_y - 1.6)).label("isolation barrier", fontsize=10, color="#1f6fb2"))
    d.add(elm.Label().at((bx, gnd_in_y - 2.3)).label(
        "yellow G-to-G jumper: leave OFF (keeps radio ground isolated from the Nano/PC)",
        fontsize=10, color="#b00000"))

    # module outline
    lx = X + 3.4
    rx = ex + 1.9
    ty = tops[0].anode.y + 2.6
    by = gnd_in_y - 0.9
    d.add(elm.Line().at((lx, ty)).to((rx, ty)).linestyle(":").color(GRAY))
    d.add(elm.Line().at((rx, ty)).to((rx, by)).linestyle(":").color(GRAY))
    d.add(elm.Line().at((rx, by)).to((lx, by)).linestyle(":").color(GRAY))
    d.add(elm.Line().at((lx, by)).to((lx, ty)).linestyle(":").color(GRAY))
    d.add(elm.Label().at((lx + 0.2, ty + 0.4)).label(
        "2-channel PC817 board (\"817 Module 2 Channel Isolation\"), modified",
        halign="left", fontsize=10, color=GRAY))

    d.add(elm.Label().at((ic.absanchors["GND"].x - 4.6, by - 3.0)).label(
        "≈ 9 mA LED drive (≈ 3 V across the board input).  Closed output ≈ 0.1–0.2 V.  "
        "Outputs are unlimited after the 302 removal: key/PTT inputs only.",
        halign="left", **NOTE))
    d.save(f"{OUT}/station-nano-schematic.svg")




# ================================================================== remtlm (section 9)

def _box(**kw):
    """An Ic that always sits upright, whatever direction the last wire went."""
    return elm.Ic(**kw).theta(0)

RED = "#b00000"


def _wire(d, *pts):
    for a, b in zip(pts, pts[1:]):
        d.add(elm.Line().at(a).to(b))


def _net(d, at, name, direction="down", length=0.6):
    """Short stub ending in a net-name label (e.g. +5V) instead of a long wire."""
    d.add(getattr(elm.Line(), direction)().at(at).length(length))
    ofs = {"down": (0, -0.35), "up": (0, 0.35), "left": (-0.2, 0), "right": (0.2, 0)}[direction]
    ha = {"down": "center", "up": "center", "left": "right", "right": "left"}[direction]
    va = {"down": "top", "up": "bottom", "left": "center", "right": "center"}[direction]
    end = d.here
    d.add(elm.Label().at((end[0] + ofs[0], end[1] + ofs[1])).label(name, fontsize=11, halign=ha, valign=va))


def _gnd_down(d, at, length=0.6):
    d.add(elm.Line().down().at(at).length(length))
    d.add(elm.Ground())


# ------------------------------------------------------------------ E220 <-> Nano
def tlm_e220():
    d = schemdraw.Drawing(show=False)
    SP = 2.8
    nano = d.add(_box(
        pins=[elm.IcPin(name=p, side="right") for p in
              ["GND", "5V", "D6", "D7", "D8", "D10", "D9"]],
        pinspacing=SP, edgepadW=1.6, leadlen=0.6,
        label="Arduino\nNano\n(tower or base)", lblsize=13))
    XE = nano.absanchors["D9"].x + 11
    e220 = d.add(_box(
        pins=[elm.IcPin(name=p, side="left") for p in
              ["GND", "VCC", "AUX", "TXD", "RXD", "M1", "M0"]],
        pinspacing=SP, edgepadW=1.6, leadlen=0.6,
        label="E220-\n900T22D", lblsize=13).anchor("M0").at((XE, nano.absanchors["D9"].y)))

    # 5 V -> 3.3 V dividers on the three Nano outputs
    for i, (np_, ep) in enumerate((("D9", "M0"), ("D10", "M1"), ("D8", "RXD"))):
        a, b = nano.absanchors[np_], e220.absanchors[ep]
        d.add(elm.Line().at(a).right().length(1.2))
        d.add(elm.Resistor().right().length(2.6).label("1 kΩ", loc="top"))
        node = d.add(elm.Dot()).center
        d.add(elm.Line().at(node).to(b))
        d.add(elm.Resistor().down().at(node).length(1.5).label("2 kΩ", loc="bottom", fontsize=10))
        d.add(elm.Ground())
    d.add(elm.Label().at((nano.absanchors["D9"].x + 6.9, nano.absanchors["D9"].y + 0.9)).label(
        "≈ 3.3 V high", fontsize=10, color=GRAY))

    # inputs from the module
    for np_, ep in (("D7", "TXD"), ("D6", "AUX")):
        _wire(d, e220.absanchors[ep], nano.absanchors[np_])
    d.add(elm.Label().at(((nano.absanchors["D7"].x + XE) / 2, nano.absanchors["D7"].y + 0.35))
          .label("module TX → Nano RX (3.3 V is a valid high)", fontsize=10, color=GRAY))
    d.add(elm.Label().at(((nano.absanchors["D6"].x + XE) / 2, nano.absanchors["D6"].y + 0.35))
          .label("AUX: high = idle", fontsize=10, color=GRAY))

    # power
    a, b = nano.absanchors["5V"], e220.absanchors["VCC"]
    _wire(d, a, b)
    cx = XE - 2.2
    d.add(elm.Dot().at((cx, b.y)))
    d.add(elm.Capacitor(polar=True).down().at((cx, b.y)).length(1.6)
          .label("100 µF", loc="bottom", fontsize=10))
    d.add(elm.Ground())
    d.add(elm.Label().at(((a.x + cx) / 2, a.y + 0.35)).label("+5 V", fontsize=11))
    _gnd_down(d, nano.absanchors["GND"])
    _gnd_down(d, e220.absanchors["GND"])

    # antenna
    top = e220.get_bbox(transform=True).ymax
    ax = e220.get_bbox(transform=True).xmax - 0.6
    d.add(elm.Line().at((ax, top)).up().length(0.6))
    d.add(elm.Antenna().label("SMA, 915 MHz whip", loc="right", fontsize=10))

    d.add(elm.Label().at((nano.get_bbox(transform=True).xmin, nano.get_bbox(transform=True).ymin - 1.6))
          .label("Identical at both ends.  Tower: +5 V from the buck converter.  "
                 "Base: +5 V from the Nano's USB, and the Nano's USB to the shack PC.",
                 halign="left", **NOTE))
    d.save(f"{OUT}/remtlm-e220-schematic.svg")



# ------------------------------------------------------------------ tower power + supply monitor
def tlm_power():
    d = schemdraw.Drawing(show=False)
    # heavy +13.8 V path through the shunt
    d.add(elm.Dot(open=True).at((0, 0)).label("+13.8 V\nfrom tower cable", loc="left"))
    d.add(elm.Line().right().length(1.5))
    sh = d.add(elm.RBox().right().length(4.5)
               .label("20 A / 75 mV shunt (3.75 mΩ)", loc="top", ofst=0.7))
    d.add(elm.Line().right().length(12.5))
    load = d.add(elm.Dot()).center
    d.add(elm.Line().right().length(6.0))
    d.add(elm.Label().label("→ MKU 10 G5, PA, relays\n   (heavy wire)", loc="right", halign="left"))
    d.add(elm.Label().at((sh.start.x, 0.45)).label("bolt", fontsize=9, color=GRAY))
    d.add(elm.Label().at((sh.end.x, 0.45)).label("bolt", fontsize=9, color=GRAY))

    # INA226: Kelvin sense leads from the shunt's small screws
    s1 = (sh.start.x + 0.5, 0)
    s2 = (sh.end.x - 0.5, 0)
    SP = 1.4
    ina = d.add(_box(
        pins=[elm.IcPin(name="IN+", side="top"), elm.IcPin(name="IN−", side="top"),
              elm.IcPin(name="VBUS", side="top"),
              elm.IcPin(name="SCL", side="right"), elm.IcPin(name="SDA", side="right"),
              elm.IcPin(name="GND", side="right"), elm.IcPin(name="VCC", side="right")],
        pinspacing=SP, edgepadW=0.9, edgepadH=1.4, leadlen=0.8,
        label="INA226\n(CJMCU-226)", lblsize=12).anchor("IN+").at((s1[0], -3.0)))
    ip, im, vb = ina.absanchors["IN+"], ina.absanchors["IN−"], ina.absanchors["VBUS"]
    for s, side in ((s1, 1), (s2, -1)):
        d.add(elm.Dot().at(s))
        d.add(elm.Label().at((s[0] + 0.15 * side, -0.4)).label(
            "sense", fontsize=9, color=GRAY, halign="left" if side > 0 else "right"))
    _wire(d, s1, ip)
    yb = -1.7
    _wire(d, s2, (s2[0], yb), (im.x, yb), im)
    _wire(d, vb, (vb.x, yb))
    d.add(elm.Dot().at((im.x, yb)))
    d.add(elm.Dot().at((vb.x, yb)) if vb.x <= s2[0] else elm.Line().at((s2[0], yb)).to((vb.x, yb)))
    d.add(elm.Label().at((s2[0] + 0.4, yb)).label(
        "VBUS (if the module has one) to IN−", halign="left", fontsize=9, color=GRAY))

    # tower Nano, pins aligned row for row with the INA226
    XN = ina.absanchors["SCL"].x + 5.5
    nano = d.add(_box(
        pins=[elm.IcPin(name="A5", side="left"), elm.IcPin(name="A4", side="left"),
              elm.IcPin(name="GND", side="left"), elm.IcPin(name="5V", side="left")],
        pinspacing=SP, edgepadW=1.6, edgepadH=1.4, leadlen=0.8,
        label="tower\nNano", lblsize=13).anchor("A5").at((XN, ina.absanchors["SCL"].y)))
    for a, b in (("SCL", "A5"), ("SDA", "A4"), ("VCC", "5V")):
        _wire(d, ina.absanchors[a], nano.absanchors[b])
    pa, pb = ina.absanchors["VCC"], nano.absanchors["5V"]
    d.add(elm.Label().at(((pa.x + pb.x) / 2, pa.y + 0.3)).label("+5V", fontsize=10, color=GRAY))
    pa, pb = ina.absanchors["GND"], nano.absanchors["GND"]
    _wire(d, pa, pb)
    gx = pb.x - 1.5
    d.add(elm.Dot().at((gx, pa.y)))
    d.add(elm.Line().down().at((gx, pa.y)).length(0.4))
    d.add(elm.Ground())

    # logic supply: fuse -> buck (5.0 V) -> AMS1117-3.3
    d.add(elm.Line().at(load).down().length(0.8))
    d.add(elm.Fuse().down().length(2.0).label("1 A", loc="bottom"))
    f_end = d.here
    buck = d.add(_box(
        pins=[elm.IcPin(name="IN−", side="left"), elm.IcPin(name="IN+", side="left"),
              elm.IcPin(name="OUT−", side="right"), elm.IcPin(name="OUT+", side="right")],
        pinspacing=1.6, edgepadW=1.4, leadlen=0.6,
        label="buck\n(MP1584)\nset 5.0 V", lblsize=11).anchor("IN+").at((f_end[0] + 1.2, f_end[1] - 0.6)))
    _wire(d, f_end, (f_end[0], buck.absanchors["IN+"].y), buck.absanchors["IN+"])
    p = buck.absanchors["IN−"]
    _wire(d, p, (f_end[0], p.y))
    d.add(elm.Line().down().at((f_end[0], p.y)).length(0.4))
    d.add(elm.Ground())
    p = buck.absanchors["OUT−"]
    d.add(elm.Line().right().at(p).length(0.6))
    d.add(elm.Line().down().length(0.4))
    d.add(elm.Ground())
    o = buck.absanchors["OUT+"]
    d.add(elm.Line().right().at(o).length(1.6))
    n5 = d.add(elm.Dot()).center
    d.add(elm.Line().up().at(n5).length(0.6))
    d.add(elm.Vdd().label("+5V"))
    d.add(elm.Line().right().at(n5).length(1.2))
    ldo = d.add(_box(
        pins=[elm.IcPin(name="IN", side="left"), elm.IcPin(name="OUT", side="right"),
              elm.IcPin(name="GND", side="bottom")],
        pinspacing=1.4, edgepadW=2.2, edgepadH=0.6, leadlen=0.6,
        label="AMS1117\n-3.3", lblsize=11).anchor("IN").at(d.here))
    d.add(elm.Line().right().at(ldo.absanchors["OUT"]).length(0.8))
    d.add(elm.Line().up().length(0.6))
    d.add(elm.Vdd().label("+3.3V"))
    d.add(elm.Ground().at(ldo.absanchors["GND"]))

    # notes
    ymin = min(ina.get_bbox(transform=True).ymin, buck.get_bbox(transform=True).ymin) - 1.2
    d.add(elm.Label().at((0, ymin)).label(
        "INA226: A0/A1 address pins to GND (0x40).  Remove the module's own R100 shunt "
        "(or set SHUNT_UOHM 3614).", halign="left", fontsize=10, color=RED))
    d.add(elm.Label().at((0, ymin - 0.8)).label(
        "The whole shunt sits at +13.8 V: insulating base or standoffs, terminals covered, "
        "at the enclosure entry ahead of everything.", halign="left", fontsize=10, color=RED))
    d.add(elm.Label().at((0, ymin - 1.8)).label(
        "+5V feeds: Nano 5V pin (not VIN), E220 VCC, both DS18B20s, shifter HV, INA226 VCC.   "
        "+3.3V feeds: shifter LV only.\n"
        "Measure +5V with a DMM and enter it as VREF_MV.", halign="left", **NOTE))
    d.add(elm.Dot(open=True).at((0, ymin - 3.4)).label("tower cable (−)", loc="left"))
    d.add(elm.Line().right().length(1.0))
    d.add(elm.Ground())
    d.add(elm.Label().at((1.8, ymin - 3.4)).label(
        "one common ground: cable (−), buck, Nano, E220, INA226, MKU CON1 pin 15",
        halign="left", **NOTE))
    d.save(f"{OUT}/remtlm-tower-power-schematic.svg")

# ------------------------------------------------------------------ tower signals
def tlm_signals():
    d = schemdraw.Drawing(show=False)
    SP = 3.0
    nano = d.add(_box(
        pins=[elm.IcPin(name=p, side="left") for p in
              ["D5", "GND", "D12", "D11", "A2", "A1", "A0"]],
        pinspacing=SP, edgepadW=1.8, leadlen=0.6,
        label="tower\nNano", lblsize=13))
    y = {p: nano.absanchors[p].y for p in ["A0", "A1", "A2", "D11", "D12", "GND", "D5"]}
    XL = nano.absanchors["A0"].x - 19.0   # source column
    mku = d.add(_box(
        pins=[elm.IcPin(name="GND", pin="15", side="right", anchorname="15"),
              elm.IcPin(name="RXD", pin="12", side="right", anchorname="12"),
              elm.IcPin(name="TXD", pin="11", side="right", anchorname="11"),
              elm.IcPin(name="LD", pin="16", side="right", anchorname="16"),
              elm.IcPin(name="MON", pin="9", side="right", anchorname="9")],
        pinspacing=SP, edgepadW=3.2, leadlen=0.8,
        label="Kuhne\nMKU 10 G5\nCON1", lblsize=12).anchor("9").at((XL, y["A1"])))

    # A0 / A1: 10k / 22k divider + 100 nF
    d.add(elm.Dot(open=True).at((XL, y["A0"])).label("PA power-sense out\n(0–5 V)", loc="left"))
    for src, pin in (((XL, y["A0"]), "A0"), (mku.absanchors["9"], "A1")):
        d.add(elm.Line().at(src).to((XL + 2.0, y[pin])))
        d.add(elm.Resistor().right().length(2.6).label("10 kΩ", loc="top"))
        node = d.add(elm.Dot()).center
        d.add(elm.Line().at(node).to(nano.absanchors[pin]))
        d.add(elm.Resistor().down().at(node).length(1.8).label("22 kΩ", loc="bottom", fontsize=10))
        d.add(elm.Ground())
        d.add(elm.Line().at(node).right().length(1.5))
        d.add(elm.Dot())
        d.add(elm.Capacitor().down().length(1.8).label("100 nF", loc="bottom", fontsize=10))
        d.add(elm.Ground())

    # A2: LD with 100k pull-down
    a = mku.absanchors["16"]
    d.add(elm.Line().at(a).to((XL + 4.6, a.y)))
    node = d.add(elm.Dot()).center
    d.add(elm.Line().at(node).to(nano.absanchors["A2"]))
    d.add(elm.Resistor().down().at(node).length(1.8).label("100 kΩ", loc="bottom", fontsize=10))
    d.add(elm.Ground())
    d.add(elm.Label().at((XL + 7.0, a.y + 0.35)).label(
        "3.3 V via 330 Ω when locked; read as analog vs 1.65 V", halign="left", fontsize=10, color=GRAY))

    # serial through the BSS138 shifter
    XS = XL + 8.0
    sh = d.add(_box(
        pins=[elm.IcPin(name="LV2", side="left"), elm.IcPin(name="LV1", side="left"),
              elm.IcPin(name="HV2", side="right"), elm.IcPin(name="HV1", side="right"),
              elm.IcPin(name="LV", side="top", pos=0.3), elm.IcPin(name="HV", side="top", pos=0.7),
              elm.IcPin(name="GND", side="bottom")],
        pinspacing=SP, edgepadW=2.6, leadlen=0.6,
        label="BSS138\nlevel shifter", lblsize=11).anchor("LV1").at((XS, y["D11"])))
    _wire(d, mku.absanchors["11"], sh.absanchors["LV1"])
    _wire(d, mku.absanchors["12"], sh.absanchors["LV2"])
    _wire(d, sh.absanchors["HV1"], nano.absanchors["D11"])
    _wire(d, sh.absanchors["HV2"], nano.absanchors["D12"])
    d.add(elm.Label().at(((sh.absanchors["HV1"].x + nano.absanchors["D11"].x) / 2, y["D11"] + 0.35))
          .label("MKU TX → Nano RX", fontsize=10, color=GRAY))
    d.add(elm.Label().at(((sh.absanchors["HV2"].x + nano.absanchors["D12"].x) / 2, y["D12"] + 0.35))
          .label("Nano TX → MKU RX", fontsize=10, color=GRAY))
    d.add(elm.Label().at(((mku.absanchors["11"].x + XS) / 2, y["D11"] + 0.35))
          .label("3.3 V, 9600 baud", fontsize=10, color=GRAY))
    _net(d, sh.absanchors["LV"], "+3.3V", "up", 0.5)
    _net(d, sh.absanchors["HV"], "+5V", "up", 0.5)
    d.add(elm.Ground().at(sh.absanchors["GND"]))

    # grounds
    d.add(elm.Line().at(mku.absanchors["15"]).right().length(1.0))
    d.add(elm.Ground())
    d.add(elm.Line().at(nano.absanchors["GND"]).left().length(1.0))
    d.add(elm.Ground())

    # DS18B20 bus on D5
    d5 = nano.absanchors["D5"]
    bus_x0 = XL + 1.0
    d.add(elm.Line().at(d5).to((bus_x0 + 2.8, d5.y)))
    pu_x = d5.x - 3.0
    d.add(elm.Dot().at((pu_x, d5.y)))
    d.add(elm.Resistor().up().at((pu_x, d5.y)).length(1.8).label("4.7 kΩ", loc="bottom", fontsize=10))
    d.add(elm.Vdd().label("+5V"))
    for i, (px, name) in enumerate(((bus_x0 + 1.0, "PA heatsink"), (bus_x0 + 7.0, "MKU case"))):
        pr = d.add(_box(
            size=(3.6, 2.2),
            pins=[elm.IcPin(name="DQ", side="top", pos=0.5),
                  elm.IcPin(name="VDD", side="bottom", pos=0.2),
                  elm.IcPin(name="GND", side="bottom", pos=0.8)],
            leadlen=0.6,
            label=f"DS18B20 #{i + 1}\n{name}", lblsize=10).anchor("DQ").at((px + 1.8, d5.y - 0.0)))
        dq = pr.absanchors["DQ"]
        d.add(elm.Dot().at((dq.x, d5.y)))
        d.add(elm.Ground().at(pr.absanchors["GND"]))
        _net(d, pr.absanchors["VDD"], "+5V", "down", 0.4)
    d.add(elm.Label().at((bus_x0 + 12.5, d5.y - 2.0)).label(
        "yellow = DQ, red = VDD, black = GND.\nBus order follows each probe's serial number:\n"
        "warm one in your hand to tell them apart.", halign="left", **NOTE))

    d.save(f"{OUT}/remtlm-tower-signals-schematic.svg")


client()
station()
tlm_e220()
tlm_power()
tlm_signals()
