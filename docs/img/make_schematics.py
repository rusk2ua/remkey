"""Generate remkey client and station schematics (SVG) with schemdraw.

Regenerate from the repo root:  pip install schemdraw && python docs/img/make_schematics.py docs/img
"""
import sys
import schemdraw
import schemdraw.elements as elm

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


client()
station()
