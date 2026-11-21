"""Assembly checklist for the tower-top prototype board (proto-tower-board.png).

Writes tower-checklist.pdf (Letter, landscape, for the bench) and tower-checklist.xlsx.
Regenerate:  python3 docs/prototype/make_checklist.py docs/prototype
Needs reportlab and openpyxl, and the DejaVu fonts.
"""
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

R = []
def s(stage, part, holes, note=""):
    R.append([False, len(R)+1, stage, part, holes, note or None])
P="1 Prep"; U="2 Under the E220"; L="3 Underside links"; B="4 Buck"; K="5 E220 socket"; M="6 Rows 8-13"; T="7 Rows 14-17"; F="8 Field wiring"; C="9 Power-up checks"
s(P,"Set the E220 on the board where the socket will go","A1-A7","Confirm the module covers rows 1-8 only and clears row 9. Rows 9 and down get standing parts.")
s(P,"Measure the buck's height plus foam tape","—","The E220 socket must hold the module 1-2 mm above that. If one 8.5 mm female header isn't enough, stack two.")
s(P,"Cut two 1x4 female sockets for the BSS138 shifter","—","Only LV1, LV2, LV, GND and HV1, HV2, HV, GND go into the board. The LV3/LV4 end hangs past row 17.")
s(U,"2k, flat (M0 divider)","B1 - B7","Everything in rows 1-8 lies flat: no part taller than a resistor lying down.")
s(U,"2k, flat (M1 divider)","C2 - C7","")
s(U,"2k, flat (RXD divider)","D3 - D7","")
s(U,"1k, flat across the gap (M0)","E1 - F1","")
s(U,"1k, flat across the gap (M1)","E2 - F2","")
s(U,"1k, flat across the gap (RXD)","E3 - F3","")
s(U,"Jumper (TXD)","E4 - F4","")
s(U,"Jumper (AUX)","E5 - F5","")
s(U,"Jumper (+5 V bus)","E6 - F6","")
s(U,"Jumper (GND bus)","E7 - F7","")
s(U,"Jumper (GND)","J7 - J8","")
s(U,"100 nF ceramic, laid flat (E220 bypass)","I6 - I7","")
s(U,"100k, flat across the gap (LD pull-down)","E8 - F8","Row 8 is under the E220's edge.")
s(U,"Wires to Nano D9, D10, D8, D7, D6","J1, J2, J3, J4, J5","Leave them long and label them: the buck covers these holes later.")
s(U,"Wire to Nano GND","I8","")
s(U,"Meter check","—","Row 1 to row 7: 2k. Row 2 to row 7: 2k. Row 3 to row 7: 2k. E1 to F1: 1k (same for rows 2, 3).")
s(L,"Insulated link, GND","G8 - D10","On the underside.")
s(L,"Insulated link, GND","B17 - C10","")
s(L,"Insulated link, GND","G17 - C17","")
s(L,"Insulated link, GND","H17 - J13","")
s(L,"Insulated link, +5 V","J6 - J16","")
s(L,"Insulated link, +5 V","H16 - A13","")
s(L,"Meter check","—","GND: row 7, row 8 right, row 10, row 13 right and row 17 all connected. +5 V: row 6, row 13 left, row 16 right connected. No continuity between +5 V and GND.")
s(B,"Short wires on the buck's pads: OUT+, OUT-, IN-","G6, G7, H7","Solder the wires to the pads first, then into the board.")
s(B,"+13.8 V lead: 0.5 A PTC spliced in, heat-shrunk, to the buck's IN+ pad","—","The PTC is off the board now; rows 12-13 hold the key-line network.")
s(B,"Stick the buck down on foam tape","over F1 - J7","Check nothing under it is shorted. +5 V (row 6) to GND (row 7): not shorted.")
s(K,"Tall 1x7 female socket","A1 - A7","M0 in A1 … GND in A7. M0 is the pin next to the module's four small holes. The module lies over the board with its SMA end past the J edge.")
s(M,"10k, standing across the gap (PA sense)","E9 - F9","")
s(M,"22k, standing (A0 to GND)","G9 - G10","")
s(M,"100 nF (A0 to GND)","H9 - H10","")
s(M,"Jumper (row 10 GND, both halves)","E10 - F10","")
s(M,"10k, standing across the gap (MON)","E11 - F11","")
s(M,"22k, standing (A1 to GND)","I11 - I10","")
s(M,"100 nF (A1 to GND)","J11 - J10","")
s(M,"47k, standing across the gap (key line)","E12 - F12","")
s(M,"100k, standing (key-line pull-up to +5 V)","D12 - D13","")
s(M,"22k, standing (A3 to GND)","G12 - G13","")
s(M,"100 nF (A3 to GND)","H12 - H13","")
s(M,"Wires to Nano A0, A1, A3","J9, G11, J12","")
s(M,"Wire to Nano A2","B8","")
s(T,"100 µF electrolytic","I16 (+) - I17","")
s(T,"BSS138 sockets: LV side","D14 - D17","LV1 D14, LV2 D15, LV D16, GND D17.")
s(T,"BSS138 sockets: HV side","F14 - F17","HV1 F14, HV2 F15, HV F16, GND F17.")
s(T,"Wires to Nano D11, D12","J14, J15","")
s(T,"Wire to Nano 5V","G16","Nano's 5V terminal, not VIN.")
s(T,"Wire to Nano 3V3","A16","Shifter LV supply.")
s(F,"MKU CON1 pin 16 (LD)","A8","")
s(F,"PA power sense","A9","")
s(F,"MKU CON1 pin 15 (GND)","A10","")
s(F,"PA GND","B10","")
s(F,"MKU CON1 pin 9 (MON)","A11","")
s(F,"MKU CON1 pin 8 (PTT out); stays wired to the sequencer too","A12","")
s(F,"MKU CON1 pin 11 (TXD)","A14","")
s(F,"MKU CON1 pin 12 (RXD)","A15","")
s(F,"Supply GND","A17","")
s(F,"DS18B20 red wires","B13, C13","Black wires: J17 and I13.")
s(F,"DS18B20 yellow wires (both) to the Nano's D5 terminal","Nano carrier","4.7k across the carrier's D5 and 5V terminals.")
s(C,"Bench supply 13.8 V, current limit about 200 mA; no E220, shifter or Nano","PTC lead and A17","")
s(C,"Check +5 V","Row 16 right, row 6, row 13 left","About 5.0 V.")
s(C,"Key-line network, A12 open","J12 to GND","About 0.65 V at J12 (2.0 V on the line).")
s(C,"Key-line network, A12 grounded","J12 to GND","Near 0 V.")
s(C,"Plug in the shifter, the E220 (antenna or dummy load on it) and the Nano","—","")
s(C,"Serial monitor at 115200","Nano USB","V:remtlm 0.6.1 tower, C:written (first boot only), C:ok ch=77, I:temperature probes=2, then $RT every 2 s ending ,0,~2040,K2UA.")
s(C,"Ground A12 briefly","A12","A $RT with ,1, within about 300 ms, then ,0, again when released.")


def pdf(path, rows):
    pdfmetrics.registerFont(TTFont("DV", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("DVB", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
    st = ParagraphStyle("c", fontName="DV", fontSize=9, leading=11)
    hd = ParagraphStyle("h", fontName="DVB", fontSize=11, leading=14, spaceBefore=6, spaceAfter=3)
    ti = ParagraphStyle("t", fontName="DVB", fontSize=15, leading=19)
    sub = ParagraphStyle("s", fontName="DV", fontSize=9, leading=12, textColor=colors.HexColor("#555555"))

    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story = [Paragraph("remtlm tower-top prototype (ElectroCookie mini): assembly checklist", ti),
             Paragraph("Hole positions as in docs/prototype/proto-tower-board.png. Firmware remtlm 0.6.1 or later.",
                       sub), Spacer(1, 6)]
    widths = [0.35 * inch, 0.35 * inch, 3.2 * inch, 1.45 * inch, 4.65 * inch]
    stages = []
    for r in rows:
        if not stages or stages[-1][0] != r[2]:
            stages.append((r[2], []))
        stages[-1][1].append(r)
    for name, rs in stages:
        data = [["", "#", "Part or wire", "Holes", "Notes and checks"]]
        for r in rs:
            data.append(["\u2611" if r[0] else "\u2610", str(r[1]), Paragraph(esc(r[3]), st),
                         Paragraph(esc(r[4]), st), Paragraph(esc(r[5]), st)])
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, 0), "DVB", 9), ("FONT", (0, 1), (1, -1), "DV", 9),
            ("FONTSIZE", (0, 1), (0, -1), 14),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aaaaaa")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(KeepTogether([Paragraph(esc(name), hd), t]))

    def foot(c, d):
        c.setFont("DV", 8)
        c.setFillColor(colors.HexColor("#777777"))
        c.drawRightString(landscape(letter)[0] - 0.5 * inch, 0.35 * inch, f"Page {d.page}")

    doc = SimpleDocTemplate(path, pagesize=landscape(letter), leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.55 * inch,
                            title="remtlm tower-top prototype assembly checklist", author="Rus Healy, K2UA")
    doc.build(story, onFirstPage=foot, onLaterPages=foot)


def xlsx(path, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Assembly"
    ws.append(["Done", "#", "Stage", "Part or wire", "Holes", "Notes and checks"])
    for r in rows:
        ws.append(["\u2714" if r[0] else None, r[1], r[2], r[3], r[4], r[5]])
    thin = Side(style="thin", color="AAAAAA")
    for row in ws.iter_rows():
        for c in row:
            c.border = Border(left=thin, right=thin, top=thin, bottom=thin)
            c.alignment = Alignment(vertical="top", wrap_text=c.column in (4, 6))
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="F3F3F3")
    for col in ("A", "B"):
        for c in ws[col][1:]:
            c.alignment = Alignment(horizontal="center", vertical="top")
    for col, w in zip("ABCDEF", (7, 5, 18, 40, 22, 55)):
        ws.column_dimensions[col].width = w
    dv = DataValidation(type="list", formula1='"\u2714"', allow_blank=True)
    dv.add(f"A2:A{len(rows) + 1}")
    ws.add_data_validation(dv)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:F{len(rows) + 1}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "1:1"
    wb.save(path)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    pdf(f"{out}/tower-checklist.pdf", R)
    xlsx(f"{out}/tower-checklist.xlsx", R)
    print(f"tower-checklist: {len(R)} steps")
