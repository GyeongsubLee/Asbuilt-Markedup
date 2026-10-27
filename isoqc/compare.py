"""Decide whether each mark-up item is reflected in the AS-BUILT sheet."""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

import pymupdf as fitz

from . import config as C
from .config import Options
from .pdftext import group_lines, rc, tokens
from .regions import CONDITION, TITLE


@dataclass
class Check:
    status: str
    reason: str
    asbuilt_value: str = ""
    area: fitz.Rect | None = None          # AS-BUILT area that was inspected
    new_hits: list = field(default_factory=list)
    old_hits: list = field(default_factory=list)


class AsBuiltIndex:
    def __init__(self, words, page_rect: fitz.Rect):
        words = [w for w in words if w.norm]
        self.words = words
        self.page_rect = page_rect
        self.diag = abs(page_rect.br - page_rect.tl)
        self.by_norm: dict = {}
        for w in words:
            self.by_norm.setdefault(w.norm, []).append(w)
        self.lines = []
        for ws in group_lines(words).values():
            r = ws[0].rect
            for w in ws[1:]:
                r = r | w.rect
            self.lines.append((ws, [w.norm for w in ws], r))

    def nearest(self, tok: str, center: fitz.Point, radius: float):
        best = None
        for w in self.by_norm.get(tok, []):
            d = abs(w.center - center)
            if d <= radius and (best is None or d < best[0]):
                best = (d, w)
        return best

    def in_rect(self, r: fitz.Rect):
        return [w for w in self.words if r.contains(w.center)]

    def line_text_near(self, p: fitz.Point, radius: float) -> str:
        best = None
        for ws, _, r in self.lines:
            d = abs(rc(r) - p) if not r.contains(p) else 0
            if d <= radius and (best is None or d < best[0]):
                best = (d, ws)
        return " ".join(w.text for w in best[1]) if best else ""


def _neighbourhood(words, rect: fitz.Rect, exclude=(), reach: float = 30.0) -> set:
    zone = fitz.Rect(rect.x0 - reach * 2, rect.y0 - reach, rect.x1 + reach * 2, rect.y1 + reach)
    ex = {id(w) for w in exclude}
    return {w.norm for w in words if id(w) not in ex and zone.contains(w.center)}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _same(a: list, b: list) -> bool:
    return a == b or (a and b and "".join(a) == "".join(b))


# --------------------------------------------------------------------------- condition table
def _check_cell(item, T, ab: AsBuiltIndex, expected: list, old: list) -> Check:
    if item.old_words:
        src = item.old_words[0].rect
        for w in item.old_words[1:]:
            src = src | w.rect
    elif item.enclosed_words:
        src = item.enclosed_words[0].rect
        for w in item.enclosed_words[1:]:
            src = src | w.rect
    elif item.anchor is not None and not item.rect.contains(item.anchor):
        src = fitz.Rect(item.anchor.x - 4, item.anchor.y - 4, item.anchor.x + 4, item.anchor.y + 4)
    else:
        src = item.rect
    cell = T.rect(src)
    area = fitz.Rect(cell.x0 - 3, cell.y0 - 2, cell.x1 + 3, cell.y1 + 2)
    found = ab.in_rect(area)
    if not found:
        grow = max(cell.width * 0.5, 10)
        area = fitz.Rect(cell.x0 - grow, cell.y0 - 3, cell.x1 + grow, cell.y1 + 3)
        found = ab.in_rect(area)
    found.sort(key=lambda w: (round(w.rect.y0), w.rect.x0))
    val_toks = [w.norm for w in found]
    value = " ".join(w.text for w in found)

    if _same(val_toks, expected) or (expected and all(t in val_toks for t in expected)
                                     and not any(t in val_toks for t in old if t not in expected)):
        return Check(C.OK, "As-built 값 = Mark-up 값", value, area, new_hits=[w.rect for w in found])
    if old and _same(val_toks, old):
        return Check(C.NG, "As-built 이 기존값 그대로임", value, area, old_hits=[w.rect for w in found])
    if not found:
        return Check(C.NG, "As-built 해당 칸이 비어 있음", "", area)
    return Check(C.NG, "As-built 값이 Mark-up 값과 다름", value, area, old_hits=[w.rect for w in found])


# --------------------------------------------------------------------------- drawing text
def _check_context_line(item, T, ab: AsBuiltIndex, mk_words, new: list, old: list, opts: Options):
    exp_new = item.prefix + new + item.suffix
    exp_old = item.prefix + old + item.suffix
    center = T.point(item.anchor)
    radius = ab.diag * opts.context_ratio
    mk_neigh = _neighbourhood(mk_words, item.old_words[0].rect, item.old_words) - set(old) - set(new)
    scored = []
    for ws, toks, r in ab.lines:
        d = abs(rc(r) - center)
        if d > radius:
            continue
        sn = SequenceMatcher(None, toks, exp_new).ratio()
        so = SequenceMatcher(None, toks, exp_old).ratio()
        if max(sn, so) < opts.line_similarity:
            continue
        nb = _jaccard(mk_neigh, _neighbourhood(ab.words, r, ws) - set(old) - set(new))
        scored.append((max(sn, so) + 0.5 * nb - 0.25 * d / radius, sn, so, ws, r))
    if not scored:
        return None
    scored.sort(key=lambda s: -s[0])
    score, sn, so, ws, r = scored[0]
    text = " ".join(w.text for w in ws)
    hits = [w.rect for w in ws if w.norm in new or w.norm in old]
    if sn > so:
        # an equally good line still showing the old value nearby makes it ambiguous
        rivals = [s for s in scored[1:] if s[2] > s[1] and s[0] > score - 0.05]
        if rivals:
            return Check(C.CHECK, "변경값 라인과 기존값 라인이 모두 근처에 있음", text, r,
                         new_hits=hits, old_hits=[w.rect for w in rivals[0][3]])
        return Check(C.OK, "같은 문맥의 라인에서 변경값 확인", text, r, new_hits=hits)
    if so > sn:
        return Check(C.NG, "같은 문맥의 라인에 기존값이 그대로 있음", text, r, old_hits=hits)
    return None


def _check_tokens(item, T, ab: AsBuiltIndex, new: list, old: list, opts: Options) -> Check:
    center = T.point(item.anchor)
    R = ab.diag * opts.near_ratio
    area = fitz.Rect(center.x - R, center.y - R, center.x + R, center.y + R)
    uniq_new = list(dict.fromkeys(new))
    old_diff = [t for t in dict.fromkeys(old) if t not in uniq_new]

    hits_new = {t: ab.nearest(t, center, R) for t in uniq_new}
    hits_new = {t: h for t, h in hits_new.items() if h}
    hits_old = {t: ab.nearest(t, center, R) for t in old_diff}
    hits_old = {t: h for t, h in hits_old.items() if h}
    value = ab.line_text_near(min((h[1].center for h in hits_new.values()), key=lambda p: abs(p - center),
                                  default=center), R)
    nr = [h[1].rect for h in hits_new.values()]
    orr = [h[1].rect for h in hits_old.values()]

    if item.kind == "delete":
        if hits_old:
            return Check(C.NG, "삭제 표시된 문자가 As-built 에 남아 있음: " + " ".join(hits_old), value, area,
                         old_hits=orr)
        return Check(C.OK, "삭제 표시된 문자가 As-built 에 없음", value, area)

    ratio = len(hits_new) / len(uniq_new) if uniq_new else 0
    if ratio >= opts.token_ratio:
        if hits_old:
            d_new = sum(h[0] for h in hits_new.values()) / len(hits_new)
            d_old = min(h[0] for h in hits_old.values())
            if d_old < d_new * 0.7:
                return Check(C.CHECK, "변경값이 있으나 기존값이 더 가까이 있음", value, area, nr, orr)
        return Check(C.OK, f"변경값을 근처에서 확인 ({len(hits_new)}/{len(uniq_new)})", value, area, nr, orr)

    if hits_old:
        return Check(C.NG, "변경값 없음, 기존값이 그대로 있음", value, area, nr, orr)
    anywhere = [t for t in uniq_new if t in ab.by_norm]
    if uniq_new and len(anywhere) / len(uniq_new) >= opts.token_ratio:
        far = [w.rect for t in anywhere for w in ab.by_norm[t]]
        return Check(C.CHECK, "변경값이 도면에 있으나 표시 위치와 다름", value, area, new_hits=far)
    missing = [t for t in uniq_new if t not in hits_new]
    return Check(C.NG, "변경값을 찾을 수 없음: " + " ".join(missing), value, area, nr, orr)


def _check_enclose(item, T, ab: AsBuiltIndex, opts: Options) -> Check:
    toks = [w.norm for w in item.enclosed_words]
    uniq = list(dict.fromkeys(toks))
    r = T.rect(item.rect)
    R = ab.diag * opts.near_ratio * 0.5
    area = fitz.Rect(r.x0 - R, r.y0 - R, r.x1 + R, r.y1 + R)
    inside = {w.norm for w in ab.in_rect(area)}
    found = [t for t in uniq if t in inside]
    missing = [t for t in uniq if t not in inside]
    hits = [w.rect for w in ab.in_rect(area) if w.norm in found]
    msg = f"구름/표시 영역 문자 일치 {len(found)}/{len(uniq)}"
    if missing:
        msg += " · 없음: " + " ".join(missing[:12])
    return Check(C.VISUAL, msg + " (형상 변경은 육안 확인)", " ".join(found[:20]), area, new_hits=hits)


def check_item(item, T, ab: AsBuiltIndex, mk_words, opts: Options) -> Check:
    if item.kind == "sign":
        return Check(C.INFO, "서명/스탬프/자유곡선 (검토 대상 아님)")
    if item.region == TITLE:
        return Check(C.INFO, "Title/Revision 영역 (검토 대상 아님)")
    if item.kind == "visual":
        r = T.rect(item.rect)
        return Check(C.VISUAL, "문자 없는 구름/도형 표시 → 형상(Routing) 변경 육안 확인", "", r)

    new = tokens(item.new_text)
    old = [w.norm for w in item.old_words]

    if item.region == CONDITION:
        if item.kind == "enclose":
            chk = _check_cell(item, T, ab, [w.norm for w in item.enclosed_words], [])
            if chk.status != C.OK:
                chk.status = C.CHECK
                chk.reason = "표시된 Condition 값과 As-built 값이 다름"
            return chk
        if item.kind == "delete":
            chk = _check_cell(item, T, ab, [], old)
            if chk.status == C.NG and not chk.asbuilt_value:
                return Check(C.OK, "삭제 표시된 값이 As-built 에 없음", "", chk.area)
            return Check(C.NG, "삭제 표시된 값이 As-built 에 남아 있음", chk.asbuilt_value, chk.area,
                         old_hits=chk.old_hits + chk.new_hits)
        return _check_cell(item, T, ab, new, old)

    if item.kind == "enclose":
        return _check_enclose(item, T, ab, opts)

    if item.kind in ("replace", "delete") and item.old_words and (item.prefix or item.suffix):
        chk = _check_context_line(item, T, ab, mk_words, new, old, opts)
        if chk:
            return chk
    return _check_tokens(item, T, ab, new, old, opts)
