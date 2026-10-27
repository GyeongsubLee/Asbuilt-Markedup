"""Find the MARK-UP / AS-BUILT folders and pair the PDFs by ISO number."""
from __future__ import annotations

import os
import re

from .config import ASBUILT_DIR_KEYS, MARKUP_DIR_KEYS


def _squash(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def find_dirs(base: str):
    """Return (markup_dir, asbuilt_dir) found directly under base (or one level deeper)."""
    markup = asbuilt = None
    candidates = []
    for root, dirs, _ in os.walk(base):
        depth = os.path.relpath(root, base).count(os.sep)
        if depth >= 2:
            dirs[:] = []
            continue
        for d in dirs:
            candidates.append(os.path.join(root, d))
    for path in sorted(candidates, key=lambda p: p.count(os.sep)):
        s = _squash(os.path.basename(path))
        if markup is None and any(k in s for k in MARKUP_DIR_KEYS):
            markup = path
        elif asbuilt is None and any(k in s for k in ASBUILT_DIR_KEYS):
            asbuilt = path
    return markup, asbuilt


def iso_key(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename))[0]
    return stem.split("_")[0].strip().upper()


def list_pdfs(folder: str) -> list[str]:
    out = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".pdf"):
                out.append(os.path.join(root, f))
    return sorted(out)


def pair_files(markup_dir: str, asbuilt_dir: str):
    """Return (pairs, markup_only, asbuilt_only, duplicates).

    pairs: list of (key, markup_path, asbuilt_path)
    duplicates: {key: [paths]} where a key had more than one file on one side
    """
    mk: dict = {}
    ab: dict = {}
    for p in list_pdfs(markup_dir):
        mk.setdefault(iso_key(p), []).append(p)
    for p in list_pdfs(asbuilt_dir):
        ab.setdefault(iso_key(p), []).append(p)
    dups = {k: v for k, v in list(mk.items()) + list(ab.items()) if len(v) > 1}
    pairs = []
    for k in sorted(mk):
        if k in ab:
            # several mark-ups (e.g. _3A, _3B): check them all against the as-built
            for m in mk[k]:
                pairs.append((k, m, ab[k][0]))
    markup_only = [(k, p) for k in sorted(mk) if k not in ab for p in mk[k]]
    asbuilt_only = [(k, p) for k in sorted(ab) if k not in mk for p in ab[k]]
    return pairs, markup_only, asbuilt_only, dups
