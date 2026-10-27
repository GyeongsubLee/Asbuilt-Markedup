"""Map MARK-UP page coordinates to AS-BUILT page coordinates.

Both sheets share the same frame (title block, notes, BOM header ...), so words
that occur exactly once on both pages give point pairs. A per-axis linear map
x' = ax*x + bx, y' = ay*y + by is fitted with outlier trimming, which ignores
routing labels that moved between the two plots.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

import pymupdf as fitz


@dataclass
class Transform:
    ax: float = 1.0
    bx: float = 0.0
    ay: float = 1.0
    by: float = 0.0
    pairs: int = 0
    residual: float = 0.0

    def point(self, p: fitz.Point) -> fitz.Point:
        return fitz.Point(self.ax * p.x + self.bx, self.ay * p.y + self.by)

    def rect(self, r: fitz.Rect) -> fitz.Rect:
        return fitz.Rect(self.point(r.tl), self.point(r.br)).normalize()

    @property
    def quality(self) -> str:
        if self.pairs >= 8 and self.residual < 3:
            return "양호"
        if self.pairs >= 4:
            return "보통"
        return "낮음(페이지 비율로 정렬)"


def _fit(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx < 1e-6:
        return 1.0, my - mx
    a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return a, my - a * mx


def _unique(words):
    seen: dict = {}
    for w in words:
        if len(w.norm) < 3 and not w.norm.isdigit():
            continue
        if len(w.norm) < 2:
            continue
        seen.setdefault(w.norm, []).append(w)
    return {k: v[0] for k, v in seen.items() if len(v) == 1}


def fit_transform(mk_words, ab_words, mk_rect: fitz.Rect, ab_rect: fitz.Rect) -> Transform:
    base = Transform(ab_rect.width / mk_rect.width, ab_rect.x0 - mk_rect.x0 * ab_rect.width / mk_rect.width,
                     ab_rect.height / mk_rect.height, ab_rect.y0 - mk_rect.y0 * ab_rect.height / mk_rect.height)
    mu, au = _unique(mk_words), _unique(ab_words)
    pairs = [(mu[k].center, au[k].center) for k in mu.keys() & au.keys()]
    if len(pairs) < 4:
        return base

    # start from the page-ratio transform and keep pairs that agree with it roughly,
    # then refine with least squares and trim outliers
    diag = abs(ab_rect.br - ab_rect.tl)
    tol = diag * 0.08
    keep = [(p, q) for p, q in pairs if abs(base.point(p) - q) < tol]
    if len(keep) < 4:
        keep = pairs
    t = base
    for _ in range(5):
        ax, bx = _fit([p.x for p, _ in keep], [q.x for _, q in keep])
        ay, by = _fit([p.y for p, _ in keep], [q.y for _, q in keep])
        t = Transform(ax, bx, ay, by)
        res = [abs(t.point(p) - q) for p, q in keep]
        med = median(res)
        lim = max(med * 3, 2.0)
        new_keep = [pq for pq, r in zip(keep, res) if r <= lim]
        if len(new_keep) < 4 or len(new_keep) == len(keep):
            break
        keep = new_keep
    # reject absurd fits (e.g. mirrored or collapsed)
    if not (0.3 < t.ax < 3 and 0.3 < t.ay < 3):
        return base
    t.pairs = len(keep)
    t.residual = median(abs(t.point(p) - q) for p, q in keep)
    return t
