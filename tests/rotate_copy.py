"""Make a copy of a (rotation 0) PDF whose pages are stored rotated (/Rotate) but
look identical on screen - like many CAD-exported ISO sheets. Annotations are
re-created in the rotated page space."""
import pymupdf as fitz


def rotate_copy(src_path: str, dst_path: str, rot: int = 90):
    src = fitz.open(src_path)
    content = fitz.open(src_path)
    for p in content:  # page content only; annotations are rebuilt below
        a = p.first_annot
        while a:
            a = p.delete_annot(a)
    out = fitz.open()
    for pno, sp in enumerate(src):
        W, H = sp.rect.width, sp.rect.height
        page = out.new_page(width=H if rot in (90, 270) else W, height=W if rot in (90, 270) else H)
        page.set_rotation(rot)
        Mi = page.derotation_matrix          # displayed -> unrotated
        page.show_pdf_page(page.rect * Mi, content, pno, rotate=rot)

        def P(p):
            return fitz.Point(p) * Mi

        for a in sp.annots():
            t = a.type[1]
            info = a.info
            col = a.colors.get("stroke")
            if t == "FreeText":
                fill = a.colors.get("fill")
                n = page.add_freetext_annot(fitz.Rect(a.rect) * Mi, info["content"], fontsize=7, rotate=rot,
                                            fill_color=fill or None)
            elif t == "Line":
                v = a.vertices
                n = page.add_line_annot(P(v[0]), P(v[-1]))
            elif t == "StrikeOut":
                v = [P(p) for p in a.vertices]
                n = page.add_strikeout_annot(fitz.Quad(v[0], v[1], v[2], v[3]))
            elif t == "Polygon":
                n = page.add_polygon_annot([P(p) for p in a.vertices])
                n.set_border(width=1, clouds=2)
            elif t == "Ink":
                n = page.add_ink_annot([[tuple(P(p)) for p in s] for s in a.vertices])
            elif t == "Circle":
                n = page.add_circle_annot(fitz.Rect(a.rect) * Mi)
            elif t == "Square":
                n = page.add_rect_annot(fitz.Rect(a.rect) * Mi)
            else:
                continue
            if col and t != "FreeText":
                n.set_colors(stroke=col)
            n.set_info(info)
            n.update()
    out.save(dst_path)
