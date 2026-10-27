"""Check one MARK-UP / AS-BUILT pair."""
from __future__ import annotations

import os
import traceback

import pymupdf as fitz

from . import config as C
from .align import fit_transform
from .compare import AsBuiltIndex, check_item
from .config import Options
from .markup import extract_markups
from .pdftext import is_markup_color, open_pdf, page_words, shx_words
from .regions import CONDITION, REGION_LABEL, condition_field, detect_layout

KIND_LABEL = {
    "replace": "변경(삭선/덮어쓰기)",
    "add": "추가 기입",
    "delete": "삭제",
    "enclose": "구름/표시",
    "visual": "형상 표시",
    "sign": "서명/스탬프",
}


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


def _draw_box(pix: fitz.Pixmap, r: fitz.IRect, color, width=2):
    r = r & fitz.IRect(0, 0, pix.width, pix.height)
    if r.is_empty:
        return
    for edge in (fitz.IRect(r.x0, r.y0, r.x1, r.y0 + width), fitz.IRect(r.x0, r.y1 - width, r.x1, r.y1),
                 fitz.IRect(r.x0, r.y0, r.x0 + width, r.y1), fitz.IRect(r.x1 - width, r.y0, r.x1, r.y1)):
        pix.set_rect(edge, color)


def _crop(page, clip: fitz.Rect, path: str, zoom: float, annots: bool, boxes=()):
    clip = clip & page.rect
    if clip.is_empty or clip.width < 2 or clip.height < 2:
        return ""
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, annots=annots, alpha=False)
    pix.set_origin(0, 0)  # a clipped pixmap keeps the page origin; boxes below use crop pixels
    for rects, color in boxes:
        for r in rects:
            rr = fitz.Rect(r)
            ir = fitz.IRect(int((rr.x0 - clip.x0) * zoom) - 3, int((rr.y0 - clip.y0) * zoom) - 3,
                            int((rr.x1 - clip.x0) * zoom) + 3, int((rr.y1 - clip.y0) * zoom) + 3)
            _draw_box(pix, ir, color)
    pix.save(path)
    return path


def _pad(r: fitz.Rect, pad: float, min_w=260.0, min_h=120.0) -> fitz.Rect:
    r = fitz.Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad)
    if r.width < min_w:
        cx = (r.x0 + r.x1) / 2
        r.x0, r.x1 = cx - min_w / 2, cx + min_w / 2
    if r.height < min_h:
        cy = (r.y0 + r.y1) / 2
        r.y0, r.y1 = cy - min_h / 2, cy + min_h / 2
    return r


def process_pair(key: str, markup_path: str, asbuilt_path: str, out_dir: str, opts: Options) -> dict:
    res = {"iso": key, "markup": markup_path, "asbuilt": asbuilt_path, "items": [],
           "error": "", "align": ""}
    try:
        mk_doc = open_pdf(markup_path)
        ab_doc = open_pdf(asbuilt_path)
        mk_content = open_pdf(markup_path, strip_annots=True)
        ab_content = open_pdf(asbuilt_path, strip_annots=True)
        img_dir = os.path.join(out_dir, "images", _safe(os.path.splitext(os.path.basename(markup_path))[0]))
        if opts.images:
            os.makedirs(img_dir, exist_ok=True)
        n = 0
        aligns = []
        for pno, mk_page in enumerate(mk_doc):
            ab_pno = min(pno, len(ab_doc) - 1)
            ab_page = ab_doc[ab_pno]
            mk_words = page_words(mk_content[pno])
            ab_words = [w for w in page_words(ab_content[ab_pno]) if w.norm]
            if opts.use_shx_text or len(ab_words) < 20:
                # AS-BUILT without real text: fall back to the SHX helper annotations
                extra = shx_words(ab_page)
                if extra and (opts.use_shx_text or not ab_words):
                    ab_words += extra
            base_mk = [w for w in mk_words if not is_markup_color(w.color)]
            base_mk_tokens = [w for w in base_mk if w.norm]
            T = fit_transform(base_mk_tokens, ab_words, mk_page.rect, ab_page.rect)
            aligns.append(f"p{pno + 1}: {T.quality} (기준점 {T.pairs}, 오차 {T.residual:.1f}pt)")
            layout = detect_layout(mk_page.rect, base_mk)
            index = AsBuiltIndex(ab_words, ab_page.rect)

            items = extract_markups(mk_page, mk_content[pno], pno, mk_words, opts)
            for it in items:
                it.region = layout.region_of(it.anchor)
                if it.region == CONDITION:
                    src = it.old_words[0].rect if it.old_words else (
                        it.enclosed_words[0].rect if it.enclosed_words else it.rect)
                    it.field_name = condition_field(src, layout, base_mk)
            items.sort(key=lambda i: (i.region != CONDITION, i.anchor.y, i.anchor.x))

            for it in items:
                n += 1
                chk = check_item(it, T, index, base_mk_tokens, opts)
                row = {
                    "no": n,
                    "page": pno + 1,
                    "region": REGION_LABEL.get(it.region, it.region),
                    "field": it.field_name,
                    "kind": KIND_LABEL.get(it.kind, it.kind),
                    "source": it.source,
                    "author": it.author,
                    "old": it.old_text,
                    "new": it.new_text or (it.enclosed_text if it.kind == "enclose" else ""),
                    "asbuilt": chk.asbuilt_value,
                    "status": chk.status,
                    "reason": chk.reason,
                    "img_mk": "",
                    "img_ab": "",
                }
                if opts.images:
                    clip = _pad(it.rect, opts.image_pad)
                    row["img_mk"] = _crop(mk_page, clip, os.path.join(img_dir, f"{n:03d}_markup.png"),
                                          opts.image_zoom, True,
                                          [([w.rect for w in it.old_words], (255, 0, 255))])
                    if chk.status != C.INFO:
                        ab_clip = _pad(chk.area if chk.area is not None else T.rect(it.rect), 10)
                        ab_clip |= _pad(T.rect(clip), 0)
                        row["img_ab"] = _crop(ab_page, ab_clip, os.path.join(img_dir, f"{n:03d}_asbuilt.png"),
                                              opts.image_zoom, False,
                                              [(chk.new_hits, (0, 170, 0)), (chk.old_hits, (230, 0, 0))])
                res["items"].append(row)
        res["align"] = " / ".join(aligns)
        for d in (mk_doc, ab_doc, mk_content, ab_content):
            d.close()
    except Exception as e:  # keep going with the other 999 sheets
        res["error"] = f"{type(e).__name__}: {e}"
        res["trace"] = traceback.format_exc()
    return res


def verdict(res: dict) -> str:
    if res.get("error"):
        return "오류"
    if not res.get("asbuilt"):
        return "As-built 없음"
    st = [i["status"] for i in res["items"]]
    if C.NG in st:
        return "NG"
    if C.CHECK in st:
        return "확인필요"
    if C.VISUAL in st:
        return "육안확인"
    if not [s for s in st if s != C.INFO]:
        return "Mark-up 없음"
    return "OK"
