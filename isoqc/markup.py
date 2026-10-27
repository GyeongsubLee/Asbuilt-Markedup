"""Extract mark-up items from a CIMS MARK-UP ISO page.

Mark-ups are read from PDF annotations (FreeText, StrikeOut, Line, Ink, cloud
Polygon, Square/Circle ...) and, optionally, from content that was flattened
into the page in a mark-up colour (red/blue text and lines).

Every primitive is then combined into MarkupItems:
  replace  - old text struck through / covered, new text written
  add      - new text written, nothing covered
  delete   - old text struck through, nothing written
  enclose  - cloud / circle / box around drawing text, no text written
  visual   - cloud / shape around geometry only (no text inside)
  sign     - signature / stamp / free-hand ink (reference only)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pymupdf as fitz

from .config import Options
from .pdftext import group_lines, is_markup_color, is_shx_annot, rc, tokens

SKIP_TYPES = {"Link", "Widget", "Popup", "FileAttachment", "Sound", "Movie",
              "Screen", "PrinterMark", "TrapNet", "Watermark", "3D", "Projection"}
ENCLOSE_TYPES = {"Polygon", "Square", "Circle", "PolyLine"}


@dataclass
class TextMark:
    text: str
    box: fitz.Rect                 # where the text is written
    anchor: fitz.Point             # what it points at (callout end) or box centre
    covered: list                  # base words hidden under the box
    source: str
    author: str = ""
    used: bool = False


@dataclass
class StrikeMark:
    words: list
    rect: fitz.Rect
    source: str
    author: str = ""
    used: bool = False


@dataclass
class ShapeMark:
    kind: str                      # enclose / sign
    rect: fitz.Rect
    source: str
    author: str = ""
    filled: bool = False


@dataclass
class MarkupItem:
    page: int
    kind: str
    source: str
    rect: fitz.Rect
    anchor: fitz.Point
    new_text: str = ""
    old_words: list = field(default_factory=list)
    enclosed_words: list = field(default_factory=list)
    prefix: list = field(default_factory=list)   # same-line context tokens before old text
    suffix: list = field(default_factory=list)   # same-line context tokens after old text
    author: str = ""
    region: str = ""
    field_name: str = ""

    @property
    def old_text(self) -> str:
        return " ".join(w.text for w in self.old_words)

    @property
    def enclosed_text(self) -> str:
        return " ".join(w.text for w in self.enclosed_words)


# --------------------------------------------------------------------------- geometry
def _words_in_rect(words, rect: fitz.Rect, shrink: float = 0.0):
    r = fitz.Rect(rect)
    if shrink:
        r = fitz.Rect(r.x0 + shrink, r.y0 + shrink, r.x1 - shrink, r.y1 - shrink)
    return [w for w in words if r.contains(w.center)]


def _segment_hits(words, p0: fitz.Point, p1: fitz.Point):
    """Words crossed by the segment p0-p1 through their middle band (strike-through)."""
    hit = []
    length = abs(p1 - p0)
    if length < 2:
        return hit
    n = max(int(length / 1.5), 8)
    pts = [p0 + (p1 - p0) * (i / n) for i in range(n + 1)]
    for w in words:
        r = w.rect
        h = r.height
        band = fitz.Rect(r.x0, r.y0 + h * 0.2, r.x1, r.y1 - h * 0.2)
        if not band.intersects(fitz.Rect(min(p0.x, p1.x), min(p0.y, p1.y),
                                         max(p0.x, p1.x) + 0.1, max(p0.y, p1.y) + 0.1)):
            continue
        inside = sum(1 for p in pts if band.contains(p))
        # the line must run along the word, not just touch a corner
        if inside and inside * (length / n) >= min(r.width, r.height) * 0.5:
            hit.append(w)
    return hit


def _straightness(points) -> float:
    """0 = perfectly straight; large = curvy."""
    if len(points) < 3:
        return 0.0
    a, b = fitz.Point(points[0]), fitz.Point(points[-1])
    L = abs(b - a)
    if L < 1:
        return 99.0
    dev = 0.0
    for p in points:
        p = fitz.Point(p)
        dev = max(dev, abs((b.x - a.x) * (a.y - p.y) - (a.x - p.x) * (b.y - a.y)) / L)
    return dev / L


def _dist_rect(p: fitz.Point, r: fitz.Rect) -> float:
    dx = max(r.x0 - p.x, 0, p.x - r.x1)
    dy = max(r.y0 - p.y, 0, p.y - r.y1)
    return math.hypot(dx, dy)


def _rect_gap(a: fitz.Rect, b: fitz.Rect) -> float:
    dx = max(b.x0 - a.x1, 0, a.x0 - b.x1)
    dy = max(b.y0 - a.y1, 0, a.y0 - b.y1)
    return math.hypot(dx, dy)


def _union(rects):
    out = None
    for r in rects:
        out = fitz.Rect(r) if out is None else out | r
    return out


# --------------------------------------------------------------------------- annotations
def _annot_text(annot: fitz.Annot) -> str:
    txt = (annot.info or {}).get("content", "") or ""
    if not txt.strip():
        try:
            txt = annot.get_text() or ""
        except Exception:
            txt = ""
    return " ".join(txt.split())


def _freetext_geometry(doc: fitz.Document, annot: fitz.Annot):
    """Return (text box, anchor point) honouring /RD and callout /CL."""
    rect = fitz.Rect(annot.rect)
    box = fitz.Rect(rect)
    try:
        rd = annot.rect_delta
        if rd and any(rd):
            box = fitz.Rect(rect.x0 + rd[0], rect.y0 + rd[1], rect.x1 - rd[2], rect.y1 - rd[3])
    except Exception:
        pass
    anchor = None
    try:
        kind, val = doc.xref_get_key(annot.xref, "CL")
        if kind == "array":
            nums = [float(v) for v in val.strip("[]").split()]
            if len(nums) >= 4:
                # PDF user space (origin bottom-left) -> MuPDF space
                page = annot.parent
                m = page.transformation_matrix
                p = fitz.Point(nums[0], nums[1]) * m
                end = fitz.Point(nums[-2], nums[-1]) * m
                diag = abs(page.rect.br - page.rect.tl)
                # some writers emit a dummy callout from the page origin; a real one
                # ends at the text box and starts reasonably close to it
                corners = (page.rect.tl, page.rect.tr, page.rect.bl, page.rect.br)
                if (_dist_rect(end, box) < 15 and _dist_rect(p, box) < diag * 0.3
                        and min(abs(p - c) for c in corners) > 1):
                    anchor = p
    except Exception:
        anchor = None
    return box, anchor


def _collect_annotations(page: fitz.Page, base_words, opts: Options):
    texts, strikes, shapes, leaders = [], [], [], []
    doc = page.parent
    for annot in page.annots() or []:
        tname = annot.type[1]
        if tname in SKIP_TYPES or is_shx_annot(annot):
            continue
        info = annot.info or {}
        author = info.get("title", "") or ""
        text = _annot_text(annot)
        rect = fitz.Rect(annot.rect)
        colors = annot.colors or {}
        filled = bool(colors.get("fill"))

        if tname == "FreeText":
            if not text:
                continue
            box, anchor = _freetext_geometry(doc, annot)
            covered = [w for w in _words_in_rect(base_words, box, 0.5)]
            texts.append(TextMark(text, box, anchor if anchor is not None else rc(box),
                                  covered, "FreeText", author))
        elif tname in ("StrikeOut",):
            verts = annot.vertices or []
            hit = []
            for i in range(0, len(verts) - 3, 4):
                q = fitz.Quad(verts[i:i + 4]).rect
                hit += _words_in_rect(base_words, q)
            if hit:
                strikes.append(StrikeMark(hit, _union(w.rect for w in hit), tname, author))
            if text:
                texts.append(TextMark(text, rect, rc(rect), [], tname + " note", author))
        elif tname == "Line":
            v = annot.vertices or []
            if len(v) >= 2:
                p0, p1 = fitz.Point(v[0]), fitz.Point(v[-1])
                hit = _segment_hits(base_words, p0, p1)
                if hit:
                    strikes.append(StrikeMark(hit, _union(w.rect for w in hit), "Line", author))
                else:
                    leaders.append((p0, p1))
            if text:
                texts.append(TextMark(text, rect, rc(rect), [], "Line note", author))
        elif tname == "Ink":
            strokes = annot.vertices or []
            straight_hits = []
            curvy = False
            for stroke in strokes:
                if len(stroke) >= 2 and _straightness(stroke) < 0.08:
                    straight_hits += _segment_hits(base_words, fitz.Point(stroke[0]), fitz.Point(stroke[-1]))
                else:
                    curvy = True
            if straight_hits and not curvy:
                strikes.append(StrikeMark(straight_hits, _union(w.rect for w in straight_hits), "Ink", author))
            else:
                shapes.append(ShapeMark("sign", rect, "Ink", author))
        elif tname == "Stamp":
            shapes.append(ShapeMark("sign", rect, "Stamp", author))
            if text:
                texts.append(TextMark(text, rect, rc(rect), [], "Stamp", author, used=True))
        elif tname in ENCLOSE_TYPES:
            r = fitz.Rect(rect)
            if tname in ("Polygon", "PolyLine") and annot.vertices:
                r = fitz.Rect(fitz.Point(annot.vertices[0]), fitz.Point(annot.vertices[0]))
                for p in annot.vertices:
                    r |= fitz.Point(p)
            shapes.append(ShapeMark("enclose", r, tname, author, filled))
            if text:
                texts.append(TextMark(text, r, rc(r), [], tname + " note", author))
        elif tname in ("Text", "Caret", "Highlight", "Underline", "Squiggly"):
            if tname in ("Highlight", "Underline", "Squiggly"):
                shapes.append(ShapeMark("enclose", rect, tname, author))
            if text:
                texts.append(TextMark(text, rect, rc(rect), [], tname, author))
        elif tname == "Redact":
            hit = _words_in_rect(base_words, rect)
            if hit:
                strikes.append(StrikeMark(hit, rect, tname, author))
        else:
            if text:
                texts.append(TextMark(text, rect, rc(rect), [], tname, author))
            else:
                shapes.append(ShapeMark("enclose", rect, tname, author))

    # FreeText without a callout but with a separate leader Line touching it
    for t in texts:
        if t.source != "FreeText" or t.anchor != rc(t.box):
            continue
        best = None
        for p0, p1 in leaders:
            for a, b in ((p0, p1), (p1, p0)):
                d = _dist_rect(a, t.box)
                if d < 12 and (best is None or d < best[0]):
                    best = (d, b)
        if best:
            t.anchor = best[1]
    return texts, strikes, shapes


# --------------------------------------------------------------------------- flattened
def _collect_flattened(page: fitz.Page, words, base_words):
    texts, strikes, shapes = [], [], []
    colored = [w for w in words if is_markup_color(w.color)]
    lines: dict = {}
    for w in colored:
        lines.setdefault((w.block, w.line, w.color), []).append(w)
    for ws in lines.values():
        box = _union(w.rect for w in ws)
        covered = [b for b in _words_in_rect(base_words, box, 0.5)]
        texts.append(TextMark(" ".join(w.text for w in ws), box, rc(box), covered, "Flattened text"))

    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []
    for d in drawings:
        col = d.get("color") or d.get("fill")
        if not is_markup_color(col):
            continue
        items = d.get("items", [])
        r = fitz.Rect(d["rect"])
        curves = sum(1 for it in items if it[0] == "c")
        if curves >= 6 or (r.width > 25 and r.height > 25 and len(items) >= 4):
            shapes.append(ShapeMark("enclose", r, "Flattened cloud"))
            continue
        for it in items:
            if it[0] == "l":
                hit = _segment_hits(base_words, fitz.Point(it[1]), fitz.Point(it[2]))
                if hit:
                    strikes.append(StrikeMark(hit, _union(w.rect for w in hit), "Flattened line"))
            elif it[0] == "re":
                rr = fitz.Rect(it[1])
                if rr.width > 6 and rr.height > 6:
                    shapes.append(ShapeMark("enclose", rr, "Flattened box", filled=bool(d.get("fill"))))
    return texts, strikes, shapes


# --------------------------------------------------------------------------- assembly
def _context(item: MarkupItem, lines: dict):
    """Same-line tokens before / after the old words (used to find the line in AS-BUILT)."""
    if not item.old_words:
        return
    w0 = item.old_words[0]
    line = lines.get((w0.block, w0.line), [])
    old_ids = {id(w) for w in item.old_words}
    idx = [i for i, w in enumerate(line) if id(w) in old_ids]
    if not idx:
        return
    item.prefix = [w.norm for w in line[:idx[0]]]
    item.suffix = [w.norm for w in line[idx[-1] + 1:]]


def extract_markups(page: fitz.Page, content_page: fitz.Page, page_no: int, all_words,
                    opts: Options) -> list[MarkupItem]:
    """page: original page (annotations); content_page: same page with annotations
    stripped; all_words: words of content_page."""
    all_words = [w for w in all_words if w.norm]
    base_words = [w for w in all_words if not is_markup_color(w.color)]
    texts, strikes, shapes = _collect_annotations(page, base_words, opts)
    if opts.detect_flattened:
        t2, s2, sh2 = _collect_flattened(content_page, all_words, base_words)
        texts += t2
        strikes += s2
        shapes += sh2

    ignore = {t.upper() for t in opts.extra_ignore_text}
    texts = [t for t in texts if t.text.strip().upper() not in ignore]

    items: list[MarkupItem] = []
    lines = group_lines(base_words)

    # 1) strike-through + nearest written text = replacement
    for s in strikes:
        best = None
        for t in texts:
            if t.used:
                continue
            d = min(_rect_gap(s.rect, t.box), _dist_rect(t.anchor, s.rect))
            if d <= opts.pair_distance and (best is None or d < best[0]):
                best = (d, t)
        if best:
            t = best[1]
            t.used = True
            s.used = True
            old = list({id(w): w for w in s.words + t.covered}.values())
            items.append(MarkupItem(page_no, "replace", f"{s.source}+{t.source}",
                                    s.rect | t.box, rc(s.rect), t.text, old, author=t.author or s.author))
        else:
            s.used = True
            items.append(MarkupItem(page_no, "delete", s.source, s.rect, rc(s.rect), "",
                                    s.words, author=s.author))

    # 2) remaining written text
    for t in texts:
        if t.used:
            continue
        t.used = True
        # covered words that the new text repeats are not changes ("STEM D 65 E" -> "STEM D 70 E")
        new_set = set(tokens(t.text))
        if not t.covered and t.anchor is not None and not t.box.contains(t.anchor):
            # callout pointing straight at a drawing text = that text is replaced
            p = t.anchor
            t.covered = [w for w in base_words
                         if fitz.Rect(w.rect.x0 - 3, w.rect.y0 - 3, w.rect.x1 + 3, w.rect.y1 + 3).contains(p)]
        old = [w for w in t.covered if w.norm not in new_set]
        rect = t.box | _union(w.rect for w in t.covered) if t.covered else fitz.Rect(t.box)
        if t.anchor is not None:
            rect |= t.anchor
        anchor = t.anchor if not t.covered else rc(_union(w.rect for w in t.covered))
        items.append(MarkupItem(page_no, "replace" if old else "add", t.source, rect, anchor,
                                t.text, old, author=t.author))

    # 3) shapes: clouds/circles grouping text are only grouping; empty ones are checked
    written = list(items)
    for sh in shapes:
        if sh.kind == "sign":
            items.append(MarkupItem(page_no, "sign", sh.source, sh.rect, rc(sh.rect), author=sh.author))
            continue
        inner = [it for it in written if sh.rect.contains(it.anchor)
                 or (sh.rect & it.rect).get_area() > 0.5 * max(it.rect.get_area(), 1)]
        if inner:
            continue
        enclosed = _words_in_rect(base_words, sh.rect)
        if sh.filled and enclosed:
            # opaque box hiding drawing text without writing anything = deletion
            items.append(MarkupItem(page_no, "delete", sh.source, sh.rect, rc(sh.rect), "",
                                    enclosed, author=sh.author))
        elif enclosed:
            items.append(MarkupItem(page_no, "enclose", sh.source, sh.rect, rc(sh.rect),
                                    enclosed_words=enclosed, author=sh.author))
        else:
            items.append(MarkupItem(page_no, "visual", sh.source, sh.rect, rc(sh.rect), author=sh.author))

    # drop shapes nested inside another enclose shape of the same kind (cloud + inner circle)
    items = _dedupe_shapes(items)
    for it in items:
        _context(it, lines)
    return items


def _dedupe_shapes(items):
    """A cloud drawn around circled values is only grouping: keep the inner shapes."""
    shapes = [i for i in items if i.kind in ("enclose", "visual")]
    out = []
    for it in items:
        if it.kind in ("enclose", "visual") and any(
                o is not it and o.kind == "enclose" and it.rect.contains(o.rect)
                and o.rect.get_area() < it.rect.get_area() for o in shapes):
            continue
        out.append(it)
    return out
