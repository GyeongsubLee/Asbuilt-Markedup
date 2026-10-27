"""Word extraction and token normalisation helpers."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import pymupdf as fitz

from .config import SHX_KEYS

# MuPDF prints harmless warnings ("cannot set rect ...") straight to the console
try:
    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)
except Exception:
    pass

_NUM_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")
_STRIP_CHARS = ",;:\"'`"


def norm_token(text: str) -> str:
    """Normalise one token so that '65' == '65.0', 'Open' == 'OPEN', '1,004' == '1004'."""
    s = unicodedata.normalize("NFKC", text).upper().strip().strip(_STRIP_CHARS)
    plain = s.replace(",", "")
    if _NUM_RE.fullmatch(plain):
        sign = "-" if plain.startswith("-") else ""
        plain = plain.lstrip("+-")
        if "." in plain:
            plain = plain.rstrip("0").rstrip(".")
        plain = plain.lstrip("0") or "0"
        return sign + plain
    return s


def rc(r: fitz.Rect) -> fitz.Point:
    """Centre of a rectangle."""
    return (r.tl + r.br) / 2


def tokens(text: str) -> list[str]:
    out = []
    for t in re.split(r"\s+", text or ""):
        n = norm_token(t)
        if n:
            out.append(n)
    return out


@dataclass
class Word:
    text: str
    norm: str
    rect: fitz.Rect
    block: int
    line: int
    color: tuple = (0.0, 0.0, 0.0)

    @property
    def center(self) -> fitz.Point:
        return (self.rect.tl + self.rect.br) / 2

    def to_dict(self):
        return {"text": self.text, "rect": list(self.rect)}


def int_to_rgb(c: int) -> tuple:
    return (((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255)


def is_markup_color(rgb) -> bool:
    """Saturated colour (red / blue / magenta / green ...) = mark-up ink.
    Black, grey and white are drawing colours."""
    if not rgb or len(rgb) < 3:
        return False
    r, g, b = rgb[:3]
    return max(r, g, b) - min(r, g, b) > 0.35


def page_words(page: fitz.Page) -> list[Word]:
    """Words of the page content (annotations are NOT included), with colour."""
    words: list[Word] = []
    M = page.rotation_matrix
    raw = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    for bno, block in enumerate(raw.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for lno, line in enumerate(block.get("lines", [])):
            for span in line.get("spans", []):
                rgb = int_to_rgb(span.get("color", 0))
                cur_txt, cur_rect = [], None
                for ch in span.get("chars", []) + [None]:
                    c = None if ch is None else ch["c"]
                    if c is None or c.isspace():
                        if cur_txt:
                            txt = "".join(cur_txt)
                            words.append(Word(txt, norm_token(txt), cur_rect, bno, lno, rgb))
                        cur_txt, cur_rect = [], None
                        continue
                    r = fitz.Rect(ch["bbox"]) * M
                    cur_txt.append(c)
                    cur_rect = r if cur_rect is None else cur_rect | r
    return words


def is_shx_annot(annot: fitz.Annot) -> bool:
    info = annot.info or {}
    hay = " ".join(str(info.get(k, "")) for k in ("subject", "title", "content", "name")).upper()
    return any(k in hay for k in SHX_KEYS)


def shx_words(page: fitz.Page) -> list[Word]:
    """Words from AutoCAD SHX Text annotations (optional text source for AS-BUILT)."""
    out = []
    for i, annot in enumerate(page.annots() or []):
        if not is_shx_annot(annot):
            continue
        txt = (annot.info or {}).get("content", "")
        toks = txt.split()
        if not toks:
            continue
        r = annot.rect * page.rotation_matrix
        w = r.width / max(len(toks), 1)
        for j, t in enumerate(toks):
            wr = fitz.Rect(r.x0 + j * w, r.y0, r.x0 + (j + 1) * w, r.y1)
            out.append(Word(t, norm_token(t), wr, 100000 + i, 0))
    return out


def group_lines(words: list[Word]) -> dict:
    """{(block, line): [words in reading order]}"""
    lines: dict = {}
    for w in words:
        lines.setdefault((w.block, w.line), []).append(w)
    return lines


def disp_point(page: fitz.Page, p) -> fitz.Point:
    """Unrotated page coordinates (text, annotations, drawings) -> displayed page
    coordinates (page.rect, rendering clips)."""
    return fitz.Point(p) * page.rotation_matrix


def disp_rect(page: fitz.Page, r) -> fitz.Rect:
    return fitz.Rect(r) * page.rotation_matrix


def open_pdf(path: str, strip_annots: bool = False) -> fitz.Document:
    """Open a PDF. Rotated pages are left untouched (remove_rotation() fails on some
    Polygon / PolyLine annotations); extracted coordinates are mapped to the displayed
    page with disp_point / disp_rect instead.

    strip_annots=True deletes every annotation (in memory only) so that text and
    drawing extraction see the printed drawing only - some PyMuPDF versions include
    annotation appearances in get_text()/get_drawings()."""
    doc = fitz.open(path)
    if doc.needs_pass:
        doc.authenticate("")
    if strip_annots:
        _strip_annots(doc)
    return doc


def _strip_annots(doc: fitz.Document):
    """Drop every page's /Annots array (in memory). Deleting annotations one by one
    with delete_annot() breaks on some PyMuPDF versions (1.26.x)."""
    for pno in range(len(doc)):
        doc.xref_set_key(doc[pno].xref, "Annots", "null")
