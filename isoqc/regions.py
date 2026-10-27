"""Split an ISO sheet into zones: ROUTING (drawing), CONDITION (line condition table),
BOM (bill of materials) and TITLE (revision / title block)."""
from __future__ import annotations

from dataclasses import dataclass

import pymupdf as fitz

from . import config as C

ROUTING, CONDITION, BOM, TITLE = "ROUTING", "CONDITION", "BOM", "TITLE"
REGION_LABEL = {ROUTING: "Routing", CONDITION: "Line Condition", BOM: "BOM", TITLE: "Title/Rev"}


@dataclass
class Layout:
    page: fitz.Rect
    cond: fitz.Rect
    title: list
    bom: fitz.Rect
    header_top: float

    def region_of(self, p: fitz.Point) -> str:
        if self.cond.contains(p):
            return CONDITION
        if any(r.contains(p) for r in self.title):
            return TITLE
        if self.bom.contains(p):
            return BOM
        return ROUTING


def detect_layout(page_rect: fitz.Rect, words) -> Layout:
    W, H = page_rect.width, page_rect.height
    x0, y0 = page_rect.x0, page_rect.y0
    lower = [w for w in words if w.rect.y0 > y0 + H * 0.6]
    anchors = [w for w in lower if w.norm in C.CONDITION_ANCHORS]
    # the table header row: anchors that share roughly the same top
    header_top = None
    cond_right = None
    if len(anchors) >= 3:
        anchors.sort(key=lambda w: w.rect.y0)
        best = []
        for a in anchors:
            row = [b for b in anchors if abs(b.rect.y0 - a.rect.y0) < H * 0.015]
            if len(row) > len(best):
                best = row
        if len(best) >= 3:
            header_top = min(w.rect.y0 for w in best)
            cond_right = max(w.rect.x1 for w in best)
    if header_top is None:
        header_top = y0 + H * C.FALLBACK_COND_TOP
        cond_right = x0 + W * C.FALLBACK_COND_RIGHT
    else:
        # include the last column (e.g. TOXIC) completely
        cond_right += W * 0.012

    top = header_top - H * 0.012
    cond = fitz.Rect(x0, top, cond_right, page_rect.y1)

    bom_words = [w for w in words if w.norm in C.BOM_ANCHORS and w.rect.y1 < header_top
                 and w.rect.x0 > x0 + W * 0.5]
    bom_left = (min(w.rect.x0 for w in bom_words) - W * 0.015) if bom_words else x0 + W * C.FALLBACK_BOM_LEFT
    bom = fitz.Rect(bom_left, y0, page_rect.x1, top)
    title = [fitz.Rect(cond_right, top, page_rect.x1, page_rect.y1),
             fitz.Rect(bom_left, y0 + H * C.FALLBACK_TITLE_TOP, page_rect.x1, top)]
    return Layout(page_rect, cond, title, bom, header_top)


def condition_field(item_rect: fitz.Rect, layout: Layout, words) -> str:
    """Column header above a value in the condition table, or the label left of it
    (e.g. 'HIGH PRESSURE GAS SAFETY CONTROL ACT :')."""
    cy = (item_rect.y0 + item_rect.y1) / 2
    same_line = [w for w in words if layout.cond.contains(w.center) and w.rect.x1 <= item_rect.x0 + 1
                 and abs(w.center.y - cy) < max(item_rect.height, 4) * 0.6
                 and item_rect.x0 - w.rect.x1 < 260]
    same_line.sort(key=lambda w: w.rect.x0)
    if same_line and any(":" in w.text for w in same_line):
        txt = " ".join(w.text for w in same_line)
        # keep only the last "label :" part
        parts = txt.split(":")
        label = parts[-2] if len(parts) >= 2 else txt
        label = label.split("-")[-1].strip()
        return label.strip()

    xa, xb = item_rect.x0 - 2, item_rect.x1 + 2
    above = [w for w in words if layout.cond.contains(w.center)
             and w.rect.y1 <= item_rect.y0 + 1 and w.rect.y0 >= layout.header_top - 2
             and w.rect.x1 > xa and w.rect.x0 < xb]
    if not above:
        return ""
    # header words are in the band right below header_top; stop at the first data row
    above.sort(key=lambda w: (round(w.rect.y0, 0), w.rect.x0))
    return " ".join(w.text for w in above)
