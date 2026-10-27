"""Build a small synthetic data set that mimics the real ISO sheets.

    python tests/make_samples.py OUT_DIR

creates OUT_DIR/CIMS MARK-UP ISO/*.pdf and OUT_DIR/AS BUILT ISO/*.pdf
  ISO-1TC-PL-2302-30-024-01 : every mark-up reflected      -> expect OK / 육안확인
  ISO-1TC-PL-2302-30-025-01 : WEST, 2618, PT=10, Y not reflected -> expect NG
  ISO-1TC-PL-2302-30-026-01 : mark-up only (no as-built)  -> expect "As-built 없음"
"""
import os
import sys

import pymupdf as fitz

W, H = 1191, 842  # A3 landscape
RED, BLUE = (1, 0, 0), (0, 0, 1)

HEAD = [("NPS", 30), ("MAT'L", 60), ("OPER", 110), ("DESIGN", 190), ("TEST", 270), ("INSULATION", 340),
        ("TRACING", 420), ("NDE", 470), ("PAINT", 560), ("PWHT", 610), ("STEAM", 650), ("TOXIC", 700)]
SUB = [("CLASS", 60), ("PRESS", 100), ("TEMP", 135), ("PRESS", 180), ("TEMP", 215), ("PRESS", 260),
       ("MEDIUM", 295), ("TYPE", 335), ("TH'K", 375), ("PAUT", 460), ("UT", 495), ("PT", 520), ("MT", 545)]


def frame(page, dx=0.0, dy=0.0, s=1.0):
    def t(x, y, txt, size=7, color=(0, 0, 0)):
        page.insert_text((x * s + dx, y * s + dy), txt, fontsize=size * s, color=color)
    page.draw_rect(fitz.Rect(10 * s + dx, 10 * s + dy, (W - 10) * s + dx, (H - 10) * s + dy), width=0.8)
    t(950, 40, "BILL OF MATERIALS", 10)
    t(830, 70, "SHOP MATERIALS")
    t(830, 95, "1 PIPE, AS A335-P9 SMLS BE M348154321 7.2 M G61H STH")
    t(830, 110, "2 45 DEG ELL LR M348154342 3 G61H STH")
    t(830, 125, "3 90 DEG ELL LR M348154351 2 G61H STH")
    t(830, 160, "FIELD MATERIALS")
    t(830, 185, "5 GLOBE VA Y M401195584 2 G61H STH")
    t(830, 260, "CUT PIPE LENGTH")
    t(830, 280, "<1> 1004 2 <2> 196 2")
    t(900, 690, "SHAHEEN PROJECT", 12)
    t(900, 720, "S-OIL Corporation", 12)
    t(900, 750, "HDL CONSORTIUM", 12)
    t(40, 640, "NOTE : INDEPENDENT PLANT ELEVATION SYSTEM")
    t(40, 655, "PACKAGE-1 HPP ELEVATION : 0.0 M (40.281M MSL, NGVD)")
    t(40, 668, "PACKAGE-2 HPP ELEVATION : 0.0 M (4.581M MSL, NGVD)")
    for txt, x in HEAD:
        t(x, 735, txt)
    for txt, x in SUB:
        t(x, 745, txt)
    t(700, 790, "REV DATE DESCRIPTION DWN CHK'D APP'D")
    return t


def condition_values(t, pt="5", hp="N"):
    for txt, x in [("2", 30), ("G61H", 60), ("16.84", 100), ("80", 135), ("18.5", 180), ("110", 215),
                   ("27.7", 260), ("WATER", 295), ("STH", 335), ("30", 375), ("5", 460), ("-", 495),
                   (pt, 520), ("-", 545), ("Z-2(1)_P", 560), ("N", 610)]:
        t(x, 757, txt)
    t(40, 800, "LOCAL REGULATION : - KOSHA Guide D-10 : N")
    t(40, 812, "- HIGH PRESSURE GAS SAFETY CONTROL ACT : " + hp)


def routing(t, o, v):
    """o: offset for routing labels (as-built re-plots move them); v: label values."""
    ox, oy = o
    t(300 + ox, 120 + oy, f"STEM D {v['stem1']} E")
    t(300 + ox, 130 + oy, f"ORIENT HANDLE {v['h1']}")
    t(330 + ox, 230 + oy, f"STEM U {v['stem2']} N")
    t(330 + ox, 240 + oy, f"ORIENT HANDLE {v['h2']}")
    t(500 + ox, 350 + oy, "2302 FO")
    t(500 + ox, 362 + oy, v["fo"])
    t(500 + ox, 374 + oy, "BY VENDOR")
    t(200 + ox, 400 + oy, "TAIL U " + v["tail"])
    t(420 + ox, 300 + oy, "235")
    t(470 + ox, 300 + oy, "235")
    t(260 + ox, 470 + oy, "SEE ISO ISO-1TC-PL-2302-30-014-01")


def word_rect(page, txt, near=None):
    hits = page.search_for(txt) if " " in txt else \
        [fitz.Rect(w[:4]) for w in page.get_text("words") if w[4] == txt]
    if near:
        hits.sort(key=lambda r: abs(r.tl - fitz.Point(near)))
    return hits[0]


def make_markup(path):
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    t = frame(page)
    condition_values(t, pt="5", hp="N")
    routing(t, (0, 0), dict(stem1="65", h1="NORTH", stem2="70", h2="SOUTH", fo="2610", tail="Open"))

    # 1) NORTH struck with a Line annotation, SOUTH written in a red box above
    r = word_rect(page, "NORTH")
    a = page.add_line_annot(fitz.Point(r.x0 - 1, (r.y0 + r.y1) / 2), fitz.Point(r.x1 + 1, (r.y0 + r.y1) / 2))
    a.set_colors(stroke=RED); a.update()
    a = page.add_freetext_annot(fitz.Rect(r.x0, r.y0 - 14, r.x0 + 34, r.y0 - 3), "SOUTH", fontsize=7,
                                text_color=RED)
    a.update()
    # 2) SOUTH (second label) struck with a StrikeOut annotation, WEST in a box
    r = word_rect(page, "SOUTH", (330, 240))
    a = page.add_strikeout_annot(r); a.set_colors(stroke=RED); a.update()
    a = page.add_freetext_annot(fitz.Rect(r.x1 + 4, r.y0 - 2, r.x1 + 34, r.y1 + 2), "WEST", fontsize=7,
                                text_color=RED)
    a.update()
    # 3) 2610 covered by a white box showing 2618 (inside a cloud)
    r = word_rect(page, "2610")
    a = page.add_freetext_annot(fitz.Rect(r.x0 - 2, r.y0 - 1, r.x1 + 2, r.y1 + 1), "2618", fontsize=7,
                                text_color=RED, fill_color=(1, 1, 1))
    a.update()
    a = page.add_polygon_annot([fitz.Point(470, 330), fitz.Point(580, 330), fitz.Point(580, 385),
                                fitz.Point(470, 385), fitz.Point(470, 330)])
    a.set_colors(stroke=RED); a.set_border(width=1, clouds=2); a.update()
    # 4) Condition: PT 5 -> 10 (white box over the value) + cloud around the table
    pt = word_rect(page, "5", (520, 750))
    a = page.add_freetext_annot(fitz.Rect(pt.x0 - 4, pt.y0 - 1, pt.x1 + 8, pt.y1 + 1), "10", fontsize=7,
                                text_color=RED, fill_color=(1, 1, 1))
    a.update()
    a = page.add_polygon_annot([fitz.Point(415, 725), fitz.Point(600, 725), fitz.Point(600, 820),
                                fitz.Point(415, 820), fitz.Point(415, 725)])
    a.set_colors(stroke=RED); a.set_border(width=1, clouds=2); a.update()
    # 5) "Open" struck with a straight ink stroke, CLOSED written in blue + signature
    r = word_rect(page, "Open")
    cy = (r.y0 + r.y1) / 2
    a = page.add_ink_annot([[(r.x0 - 1, cy), (r.x1 + 1, cy)]]); a.set_colors(stroke=BLUE); a.update()
    a = page.add_freetext_annot(fitz.Rect(r.x1 + 4, r.y0 - 2, r.x1 + 44, r.y1 + 2), "CLOSED", fontsize=7,
                                text_color=BLUE)
    a.update()
    a = page.add_ink_annot([[(r.x1 + 50, cy), (r.x1 + 55, cy - 8), (r.x1 + 60, cy + 6), (r.x1 + 66, cy - 7),
                             (r.x1 + 72, cy + 4)]])
    a.set_colors(stroke=(0, 0, 0)); a.update()
    # 6) empty cloud around a piece of pipe (geometry change only)
    page.draw_line((600, 500), (700, 560), width=1.2)
    a = page.add_circle_annot(fitz.Rect(590, 490, 710, 570)); a.set_colors(stroke=RED); a.update()
    # 7) flattened mark-up: red "Y" printed over the "N" of HIGH PRESSURE GAS ... ACT
    nr = word_rect(page, "N", (206, 805))
    page.draw_rect(nr, color=None, fill=(1, 1, 1))
    page.insert_text((nr.x0, nr.y1 - 2.1), "Y", fontsize=7, color=RED)
    # 9) ignored: signature box (red box + "PIPING FE" name + ink), REV NO change, weld circle
    a = page.add_rect_annot(fitz.Rect(760, 600, 900, 660)); a.set_colors(stroke=RED); a.update()
    a = page.add_freetext_annot(fitz.Rect(765, 603, 895, 615), "PIPING FE HS.JEONG", fontsize=7, text_color=RED)
    a.update()
    a = page.add_ink_annot([[(780, 640), (790, 625), (800, 650), (812, 622), (830, 632)]])
    a.set_colors(stroke=(0, 0, 0)); a.update()
    t(1120, 800, "REV. NO")
    t(1125, 812, "21")
    r = word_rect(page, "21", (1125, 805))
    a = page.add_freetext_annot(fitz.Rect(r.x0 - 2, r.y0 - 1, r.x1 + 4, r.y1 + 1), "34", fontsize=7,
                                text_color=RED, fill_color=(1, 1, 1))
    a.update()
    a = page.add_circle_annot(fitz.Rect(150, 300, 180, 320)); a.set_colors(stroke=RED); a.update()
    a = page.add_freetext_annot(fitz.Rect(155, 304, 176, 316), "FW5", fontsize=7)
    a.update()
    a = page.add_line_annot(fitz.Point(180, 312), fitz.Point(240, 330)); a.set_colors(stroke=RED); a.update()
    # 10) signature pasted as an image inside a Square annotation (Bluebeam style)
    tmp = doc.new_page(width=100, height=100)
    sig = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 30), 0)
    sig.set_rect(sig.irect, (255, 255, 255))
    sig.set_rect(fitz.IRect(5, 14, 55, 17), (0, 0, 0))
    tmp.insert_image(fitz.Rect(0, 0, 60, 30), pixmap=sig)
    img_xref = tmp.get_images()[0][0]
    tmp_no = tmp.number
    page = doc[0]
    a = page.add_rect_annot(fitz.Rect(300, 690, 360, 715))
    form = doc.get_new_xref()
    doc.update_object(form, "<</Type/XObject/Subtype/Form/BBox[0 0 60 25]"
                            f"/Resources<</XObject<</Im1 {img_xref} 0 R>>>>>>")
    doc.update_stream(form, b"q 60 0 0 25 0 0 cm /Im1 Do Q")
    doc.xref_set_key(a.xref, "AP", f"<</N {form} 0 R>>")
    doc.delete_page(tmp_no)
    page = doc[0]
    # 11) weld symbol drawn with vectors (split circle, F over 3) highlighted by a red cloud,
    #     next to an ordinary item-number bubble that must NOT be treated as a weld
    cx, cy = 650, 420
    page.draw_circle((cx, cy), 9, width=0.6)
    page.draw_line((cx - 9, cy), (cx + 9, cy), width=0.6)
    page.draw_polyline([(cx + 2, cy - 7), (cx - 2, cy - 7), (cx - 2, cy - 2)], width=0.5)   # "F"
    page.draw_polyline([(cx - 2, cy + 2), (cx + 2, cy + 2), (cx, cy + 4), (cx + 2, cy + 7), (cx - 2, cy + 7)],
                       width=0.5)                                                           # "3"
    a = page.add_polygon_annot([(cx - 15, cy - 15), (cx + 15, cy - 15), (cx + 15, cy + 15), (cx - 15, cy + 15),
                                (cx - 15, cy - 15)])
    a.set_colors(stroke=RED, fill=(1, 0.6, 0.6)); a.set_opacity(0.5); a.set_border(width=1, clouds=1); a.update()
    page.draw_circle((720, 420), 9, width=0.6)                                              # item bubble
    a = page.add_circle_annot(fitz.Rect(705, 405, 735, 435)); a.set_colors(stroke=RED); a.update()
    # 8) AutoCAD SHX helper annotation (must be ignored)
    a = page.add_rect_annot(fitz.Rect(40, 20, 80, 30)); a.set_info(subject="AutoCAD SHX Text", content="N")
    a.set_opacity(0); a.update()
    doc.save(path)


def make_asbuilt(path, reflected: bool):
    doc = fitz.open()
    s, dx, dy = 1.02, 6, -4          # re-plotted: slightly bigger and shifted
    page = doc.new_page(width=W * s + 12, height=H * s)
    t = frame(page, dx, dy, s)
    condition_values(t, pt="10" if reflected else "5", hp="Y" if reflected else "N")
    v = dict(stem1="65.0", h1="SOUTH", stem2="70.0", h2="WEST" if reflected else "SOUTH",
             fo="2618" if reflected else "2610", tail="CLOSED")
    routing(t, (14, 9), v)
    t(900, 640, "AS-BUILT", 14)
    for txt, (x, y) in (("NORTH", (300, 130)), ("2610", (500, 362))):
        a = page.add_rect_annot(fitz.Rect(x * s + dx, y * s + dy - 8, x * s + dx + 30, y * s + dy))
        a.set_info(subject="AutoCAD SHX Text", content=txt); a.set_opacity(0); a.update()
    doc.save(path)


def main(out):
    mk = os.path.join(out, "CIMS MARK-UP ISO")
    ab = os.path.join(out, "AS BUILT ISO")
    os.makedirs(mk, exist_ok=True)
    os.makedirs(ab, exist_ok=True)
    make_markup(os.path.join(mk, "ISO-1TC-PL-2302-30-024-01_3B.pdf"))
    make_asbuilt(os.path.join(ab, "ISO-1TC-PL-2302-30-024-01_Sheet1-Model.pdf"), True)
    make_markup(os.path.join(mk, "ISO-1TC-PL-2302-30-025-01_2A.pdf"))
    make_asbuilt(os.path.join(ab, "ISO-1TC-PL-2302-30-025-01_Sheet1-Model.pdf"), False)
    make_markup(os.path.join(mk, "ISO-1TC-PL-2302-30-026-01_1A.pdf"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sample_data")
