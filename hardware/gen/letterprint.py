"""Re-lay a KiCad 1:1 PDF onto US Letter (portrait) with a 100 mm scale bar.

usage: letterprint.py <name>    (run from hardware/; reads <name>/fab/<name>-print-1to1.pdf)
"""
import sys
import pymupdf

MM = 72 / 25.4
name, tag = sys.argv[1], sys.argv[2]
src = pymupdf.open(f"{name}/fab/{tag}-{name}-print-1to1.pdf")
pg = src[0]
xs, ys = [], []
for d in pg.get_drawings():
    xs += [d["rect"].x0, d["rect"].x1]
    ys += [d["rect"].y0, d["rect"].y1]
for b in pg.get_text("blocks"):
    xs += [b[0], b[2]]
    ys += [b[1], b[3]]
clip = pymupdf.Rect(min(xs) - 2 * MM, min(ys) - 2 * MM, max(xs) + 2 * MM, max(ys) + 2 * MM)

out = pymupdf.open()
page = out.new_page(width=8.5 * 72, height=11 * 72)
W = page.rect.width
x0 = (W - clip.width) / 2
y0 = 40 * MM
page.show_pdf_page(pymupdf.Rect(x0, y0, x0 + clip.width, y0 + clip.height), src, 0, clip=clip)

title = {"psu": "remtlm supply box", "tower": "remtlm tower top", "shack": "remtlm shack (base)"}[name]
page.insert_text((x0, 22 * MM), f"{tag.replace('-rev', ' Rev ')}  {title}: full-size fit check", fontsize=14)
page.insert_text((x0, 29 * MM), "Print at 100% / Actual size on Letter paper. Then measure the bar below:", fontsize=10)
page.insert_text((x0, 34 * MM), "it must be exactly 100 mm. If not, the printer is scaling - don't use the print.",
                 fontsize=10)
yb = y0 + clip.height + 20 * MM
bx = (W - 100 * MM) / 2
page.draw_line((bx, yb), (bx + 100 * MM, yb), width=1.2)
for i in range(11):
    h = 4 * MM if i % 5 == 0 else 2.5 * MM
    page.draw_line((bx + i * 10 * MM, yb), (bx + i * 10 * MM, yb - h), width=0.8)
page.insert_text((bx - 1 * MM, yb + 5 * MM), "0", fontsize=9)
page.insert_text((bx + 47 * MM, yb + 5 * MM), "50", fontsize=9)
page.insert_text((bx + 96 * MM, yb + 5 * MM), "100 mm", fontsize=9)
bw = {"psu": "102 x 52", "tower": "102 x 52", "shack": "64 x 40"}[name]
page.insert_text((bx, yb + 12 * MM), f"Board outline: {bw} mm.  Nano pin rows: 15.24 mm (0.6 in) apart.", fontsize=10)
out.save(f"{name}/fab/{tag}-{name}-print-letter.pdf")
print(name, "letter print ok")
