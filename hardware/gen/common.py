"""Shared helpers for building the remtlm boards with KiCad 7's Python API.

Every board is described in code: outline, footprints, pad nets and labels.
The tracks come from Freerouting (route.py); GND is a pour on both layers.
Coordinates are in mm from the board's top-left corner.
"""
import sys

sys.path.append("/usr/lib/python3/dist-packages")
import pcbnew  # noqa: E402

FPLIB = "/usr/share/kicad/footprints"
OX, OY = 100.0, 50.0          # where the board sits on the KiCad page

# wire-hole sizes (drill, pad) by AWG, for wires soldered straight into the board
WIRE = {16: (1.8, 3.6), 18: (1.4, 2.8), 20: (1.2, 2.4)}


def mm(v):
    return pcbnew.FromMM(v)


def pt(x, y):
    return pcbnew.VECTOR2I(mm(OX + x), mm(OY + y))


class Board:
    def __init__(self, w, h, notch=0.0):
        self.b = pcbnew.BOARD()
        self.w, self.h = w, h
        self.nets = {}
        self.expected = {}        # (ref, pad) -> net, checked after routing
        ds = self.b.GetDesignSettings()
        nc = ds.m_NetSettings.m_DefaultNetClass
        nc.SetTrackWidth(mm(0.4))
        nc.SetClearance(mm(0.25))
        nc.SetViaDiameter(mm(0.8))
        nc.SetViaDrill(mm(0.4))
        ds.m_TrackMinWidth = mm(0.2)
        ds.m_MinClearance = mm(0.2)
        ds.m_ViasMinSize = mm(0.6)
        ds.m_MinThroughDrill = mm(0.3)
        ds.m_CopperEdgeClearance = mm(0.4)
        self._outline(w, h, notch)

    # ------------------------------------------------------------------ outline
    def _seg(self, a, b, layer=pcbnew.Edge_Cuts, width=0.1):
        s = pcbnew.PCB_SHAPE(self.b, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pt(*a))
        s.SetEnd(pt(*b))
        s.SetLayer(layer)
        s.SetWidth(mm(width))
        self.b.Add(s)

    def _outline(self, w, h, n):
        if n:
            p = [(n, 0), (w - n, 0), (w - n, n), (w, n), (w, h - n), (w - n, h - n), (w - n, h),
                 (n, h), (n, h - n), (0, h - n), (0, n), (n, n)]
        else:
            p = [(0, 0), (w, 0), (w, h), (0, h)]
        for i in range(len(p)):
            self._seg(p[i], p[(i + 1) % len(p)])

    # ------------------------------------------------------------------ nets
    def net(self, name):
        if name is None:
            return None
        if name not in self.nets:
            ni = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(ni)
            self.nets[name] = ni
        return self.nets[name]

    def _setnet(self, fp, pad, name):
        if name:
            pad.SetNet(self.net(name))
            self.expected[(fp.GetReference(), pad.GetNumber())] = name

    # ------------------------------------------------------------------ text
    def text(self, s, x, y, size=1.0, layer=pcbnew.F_SilkS, rot=0, just="c"):
        t = pcbnew.PCB_TEXT(self.b)
        t.SetText(s)
        t.SetPosition(pt(x, y))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        t.SetTextThickness(mm(max(0.15, size * 0.15)))
        if rot:
            t.SetTextAngleDegrees(rot)
        if just == "l":
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        elif just == "r":
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_RIGHT)
        self.b.Add(t)

    def rect(self, x0, y0, x1, y1, layer=pcbnew.F_SilkS, width=0.15):
        for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            self._seg(a, b, layer, width)

    # ------------------------------------------------------------------ footprints
    def _new_fp(self, ref, value):
        fp = pcbnew.FOOTPRINT(self.b)
        fp.SetReference(ref)
        fp.SetValue(value)
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        fp.Value().SetLayer(pcbnew.F_Fab)
        return fp

    def _pad(self, fp, num, x, y, drill, size, shape=pcbnew.PAD_SHAPE_CIRCLE, slot=None):
        p = pcbnew.PAD(fp)
        p.SetNumber(str(num))
        p.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        p.SetLayerSet(p.PTHMask())
        p.SetShape(shape)
        if slot:                      # (length, width) of an oblong drill along x
            p.SetDrillShape(pcbnew.PAD_DRILL_SHAPE_OBLONG)
            p.SetDrillSize(pcbnew.VECTOR2I(mm(slot[0]), mm(slot[1])))
            p.SetSize(pcbnew.VECTOR2I(mm(size[0]), mm(size[1])))
        else:
            p.SetDrillSize(pcbnew.VECTOR2I(mm(drill), mm(drill)))
            p.SetSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        fp.Add(p)
        v = pcbnew.VECTOR2I(mm(x), mm(y))
        p.SetPos0(v)
        p.SetPosition(v)
        return p

    def _place(self, fp, x, y):
        self.b.Add(fp)
        fp.SetPosition(pt(x, y))
        return fp

    def wire(self, ref, x, y, awg, net, label=None, lx=None, ly=None, size=1.0, just="c"):
        """A plated hole for a wire soldered straight into the board."""
        drill, pad = WIRE[awg]
        fp = self._new_fp(ref, f"#{awg} wire")
        p = self._pad(fp, 1, 0, 0, drill, pad)
        self._place(fp, x, y)
        self._setnet(fp, p, net)
        if label:
            self.text(label, x if lx is None else lx, (y - pad / 2 - 1.0) if ly is None else ly, size, just=just)
        return fp

    def row(self, ref, x, y, names, nets, value, pitch=2.54, square_first=True, dy=0.0, label_dy=None):
        """A single row of 0.1" holes along +x (header or socket). names label the pins."""
        fp = self._new_fp(ref, value)
        for i, name in enumerate(names):
            shape = pcbnew.PAD_SHAPE_RECT if (i == 0 and square_first) else pcbnew.PAD_SHAPE_CIRCLE
            self._pad(fp, i + 1, i * pitch, dy, 1.0, 1.7, shape)
        self._place(fp, x, y)
        for pad in fp.Pads():
            i = int(pad.GetNumber()) - 1
            self._setnet(fp, pad, nets.get(names[i]))
        if label_dy is not None:
            for i, name in enumerate(names):
                self.text(name, x + i * pitch, y + label_dy, 0.8, rot=90,
                          just="l" if label_dy < 0 else "r")
        return fp

    def lib(self, ref, lib, name, x, y, nets, value, rot=0):
        """A KiCad library footprint; nets maps pad number -> net name."""
        fp = pcbnew.FootprintLoad(f"{FPLIB}/{lib}.pretty", name)
        fp.SetReference(ref)
        fp.SetValue(value)
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        self._place(fp, x, y)
        if rot:
            fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            self._setnet(fp, pad, nets.get(pad.GetNumber()))
        return fp

    def mount(self, ref, x, y):
        """#4-40 mounting hole: 3.2 mm unplated, with a 7.6 mm copper keep-out on both
        layers (clears a 1/4 in hex standoff, #4 split washer and pan head) and a silk
        ring showing the hardware's footprint."""
        fp = self._new_fp(ref, "#4-40 mounting hole")
        p = pcbnew.PAD(fp)
        p.SetNumber("")
        p.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
        p.SetLayerSet(p.UnplatedHoleMask())
        p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        p.SetDrillSize(pcbnew.VECTOR2I(mm(3.2), mm(3.2)))
        p.SetSize(pcbnew.VECTOR2I(mm(3.2), mm(3.2)))
        fp.Add(p)
        self._place(fp, x, y)
        c = pcbnew.PCB_SHAPE(self.b, pcbnew.SHAPE_T_CIRCLE)
        c.SetCenter(pt(x, y))
        c.SetEnd(pt(x + 3.5, y))
        c.SetLayer(pcbnew.F_SilkS)
        c.SetWidth(mm(0.15))
        self.b.Add(c)
        z = pcbnew.ZONE(self.b)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowCopperPour(True)
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        ls = pcbnew.LSET()
        ls.AddLayer(pcbnew.F_Cu)
        ls.AddLayer(pcbnew.B_Cu)
        z.SetLayerSet(ls)
        ol = z.Outline()
        ol.NewOutline()
        import math
        for k in range(32):
            v = pt(x + 3.8 * math.cos(2 * math.pi * k / 32), y + 3.8 * math.sin(2 * math.pi * k / 32))
            ol.Append(v.x, v.y)
        self.b.Add(z)
        self.holes = getattr(self, "holes", []) + [(x, y)]
        return fp

    def ident(self, name, x, y, lines=2):
        """Part number, revision and date from hardware/boards.json, on the top silk."""
        import json
        import os
        info = json.load(open(os.path.join(os.path.dirname(__file__), "..", "boards.json")))[name]
        self.info = info
        self.text(f"{info['pn']}  Rev {info['rev']}", x, y, 1.2)
        self.text(f"{info['title']}  {info['date']}", x, y + 2.0, 0.8)
        return info

    def jlc_marker(self, x, y):
        """Where JLCPCB prints its order number (choose 'Specify a location' when ordering)."""
        self.text("JLCJLCJLCJLC", x, y, 0.8)

    def nano(self, ref, x_usb, y_analog, nets):
        """Arduino Nano in two 1x15 sockets, USB end pointing +x (towards x_usb).

        The analog row (D13, 3V3, AREF, A0-A7, 5V, RST, GND, VIN) sits at y_analog,
        the digital row (D12-D2, GND, RST, RX0, TX1) 15.24 mm further down."""
        a = ["D13", "3V3", "AREF", "A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "5V", "RST", "GND", "VIN"]
        d = ["D12", "D11", "D10", "D9", "D8", "D7", "D6", "D5", "D4", "D3", "D2", "GND", "RST", "RX0", "TX1"]
        fp = self._new_fp(ref, "Arduino Nano (2x15 sockets)")
        n = 0
        for row, names in ((0.0, a), (15.24, d)):
            for i, name in enumerate(names):
                n += 1
                shape = pcbnew.PAD_SHAPE_RECT if name == "TX1" else pcbnew.PAD_SHAPE_CIRCLE
                self._pad(fp, n, -2.54 * i, row, 1.0, 1.7, shape)
        self._place(fp, x_usb, y_analog)
        allnames = a + d
        for pad in fp.Pads():
            self._setnet(fp, pad, nets.get(allnames[int(pad.GetNumber()) - 1]))
        x0, x1 = x_usb - 2.54 * 14 - 3.8, x_usb + 3.8
        y0, y1 = y_analog + 7.62 - 9.0, y_analog + 7.62 + 9.0
        self.rect(x0, y0, x1, y1)
        self.text("ARDUINO NANO", (x0 + x1) / 2, y_analog + 5.2, 1.2)
        self.text("USB >", x1 - 3.6, y_analog + 10.0, 1.0)
        return fp

    def buck(self, ref, cx, cy, nets):
        """The 18.7 x 11.9 mm fixed-5 V mini buck module, standing on header pins in its corner pads.

        Pad centres 14.5 x 8.6 mm (as measured); plated slots along x take
        13.3-15.7 mm. Viewed from above with the inductor on the right:
        IN- top-left, OUT- top-right, IN+ bottom-left, OUT+ bottom-right."""
        fp = self._new_fp(ref, "mini buck module, fixed 5 V out (5-28 V in)")
        dx, dy = 7.25, 4.3
        layout = (("IN+", -dx, dy), ("IN-", -dx, -dy), ("OUT-", dx, -dy), ("OUT+", dx, dy))
        for i, (name, x, y) in enumerate(layout):
            self._pad(fp, i + 1, x, y, None, (3.4, 2.0), pcbnew.PAD_SHAPE_OVAL, slot=(2.2, 1.0))
        self._place(fp, cx, cy)
        for pad in fp.Pads():
            self._setnet(fp, pad, nets.get(layout[int(pad.GetNumber()) - 1][0]))
        self.rect(cx - 9.35, cy - 5.95, cx + 9.35, cy + 5.95)
        for name, x, y in layout:
            self.text(name, cx + x, cy + y + (2.0 if y < 0 else -2.0), 0.8)
        self.text("BUCK 5.0V", cx, cy, 1.0)
        return fp

    # ------------------------------------------------------------------ finishing
    def gnd_pour(self):
        for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
            z = pcbnew.ZONE(self.b)
            z.SetLayer(layer)
            z.SetNet(self.net("GND"))
            z.SetLocalClearance(mm(0.35))
            z.SetMinThickness(mm(0.25))
            z.SetThermalReliefGap(mm(0.4))
            z.SetThermalReliefSpokeWidth(mm(0.5))
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
            ol = z.Outline()
            ol.NewOutline()
            for x, y in ((0, 0), (self.w, 0), (self.w, self.h), (0, self.h)):
                v = pt(x, y)
                ol.Append(v.x, v.y)
            self.b.Add(z)

    def save(self, path):
        self.b.Save(path)
