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
from .regions import CONDITION, REGION_LABEL, TITLE, condition_field, detect_layout

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


MAX_GROUP_W, MAX_GROUP_H = 560.0, 400.0


def _group_items(items, pad):
    """Cluster nearby mark-ups so that one image pair shows several of them.
    All line-condition items share one image."""
    groups = []  # [clip, [indexes]]
    cond = [i for i, it in enumerate(items) if it.region == CONDITION]
    if cond:
        clip = None
        for i in cond:
            r = _pad(items[i].rect, pad * 0.5, min_w=120, min_h=60)
            clip = r if clip is None else clip | r
        groups.append([clip, cond])
    for i, it in enumerate(items):
        if it.region == CONDITION:
            continue
        r = _pad(it.rect, pad)
        for g in groups[1 if cond else 0:]:
            u = g[0] | r
            if g[0].intersects(r) and u.width <= MAX_GROUP_W and u.height <= MAX_GROUP_H:
                g[0] = u
                g[1].append(i)
                break
        else:
            groups.append([r, [i]])
    return groups


def _write_group_images(items, checks, rows, mk_page, ab_page, T, img_dir, prefix, img_no, opts):
    for clip, idx in _group_items(items, opts.image_pad):
        img_no += 1
        ab_clip = T.rect(clip)
        for i in idx:
            if checks[i].area is not None and items[i].region != CONDITION:
                a = checks[i].area
                # keep the as-built search area in view, but never let one item blow the image up
                if (ab_clip | a).width <= MAX_GROUP_W * 1.3 and (ab_clip | a).height <= MAX_GROUP_H * 1.3:
                    ab_clip |= a
        name = f"{prefix}{img_no:02d}"
        mk = _crop(mk_page, clip, os.path.join(img_dir, name + "_markup.png"), opts.image_zoom, True,
                   [([w.rect for i in idx for w in items[i].old_words], (255, 0, 255))])
        ab = _crop(ab_page, ab_clip, os.path.join(img_dir, name + "_asbuilt.png"), opts.image_zoom, False,
                   [([r for i in idx for r in checks[i].new_hits], (0, 170, 0)),
                    ([r for i in idx for r in checks[i].old_hits], (230, 0, 0))])
        first = min(idx)
        for i in idx:
            rows[i]["img_mk"], rows[i]["img_ab"] = mk, ab
            rows[i]["img_first"] = i == first
            rows[i]["img_ref"] = rows[first]["no"]
    return img_no


def process_pair(key: str, markup_path: str, asbuilt_path: str, out_dir: str, opts: Options) -> dict:
    res = {"iso": key, "markup": markup_path, "asbuilt": asbuilt_path, "items": [],
           "error": "", "align": "", "ignored": 0}
    try:
        mk_doc = open_pdf(markup_path)
        ab_doc = open_pdf(asbuilt_path)
        mk_content = open_pdf(markup_path, strip_annots=True)
        ab_content = open_pdf(asbuilt_path, strip_annots=True)
        img_dir = os.path.join(out_dir, "images", _safe(os.path.splitext(os.path.basename(markup_path))[0]))
        if opts.images:
            os.makedirs(img_dir, exist_ok=True)
        n = 0
        img_no = 0
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
            kept = []
            for it in items:
                it.region = layout.region_of(it.anchor)
                if it.region == TITLE:  # revision no. / title block differ by design
                    res["ignored"] += 1
                    continue
                if it.region == CONDITION:
                    src = it.old_words[0].rect if it.old_words else (
                        it.enclosed_words[0].rect if it.enclosed_words else it.rect)
                    it.field_name = condition_field(src, layout, base_mk)
                kept.append(it)
            items = sorted(kept, key=lambda i: (i.region != CONDITION, i.anchor.y, i.anchor.x))

            rows, checks = [], []
            for it in items:
                n += 1
                chk = check_item(it, T, index, base_mk_tokens, opts)
                checks.append(chk)
                rows.append({
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
                    "img_first": True,
                })
            if opts.images and items:
                img_no = _write_group_images(items, checks, rows, mk_page, ab_page, T, img_dir,
                                             f"p{pno + 1}_" if len(mk_doc) > 1 else "", img_no, opts)
            res["items"] += rows
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
