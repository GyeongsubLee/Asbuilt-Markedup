"""Tunable settings for the ISO mark-up QC checker.

All distances are in PDF points (1/72 inch). Ratios are relative to the page.
"""
from dataclasses import dataclass, field

# Folder name detection: the folder name is upper-cased and stripped of every
# non-alphanumeric character before testing, so "CIMS MARK-UP ISO" -> "CIMSMARKUPISO".
MARKUP_DIR_KEYS = ("MARKUP", "MARKEDUP")
ASBUILT_DIR_KEYS = ("ASBUILT",)

# Annotations whose subject / title / contents contain one of these strings are
# AutoCAD's searchable-text helpers, not mark-ups.
SHX_KEYS = ("AUTOCAD SHX TEXT", "SHX TEXT")

# Words used to locate the line-condition table (bottom-left of the sheet).
CONDITION_ANCHORS = {"OPER", "DESIGN", "TEST", "INSULATION", "TRACING", "NDE",
                     "PWHT", "TOXIC", "PAINT", "STEAM"}
# Words used to locate the bill-of-materials column (right side of the sheet).
BOM_ANCHORS = {"BILL", "SHOP", "FIELD", "MATERIALS", "CUT"}

# Fallback zones (page ratios, measured on the HDL / SHAHEEN template) used when
# the anchor words above cannot be found.
FALLBACK_COND_TOP = 0.855      # condition table header top (y ratio)
FALLBACK_COND_RIGHT = 0.47     # condition table right edge (x ratio)
FALLBACK_BOM_LEFT = 0.675      # BOM / title column left edge (x ratio)
FALLBACK_TITLE_TOP = 0.70      # title block top inside the right column (y ratio)


@dataclass
class Options:
    # search radius around a mark-up (ratio of the page diagonal)
    near_ratio: float = 0.06
    # wider radius used when the mark-up has text context on the same line
    context_ratio: float = 0.12
    # max distance between a strike-through and the replacement text (points)
    pair_distance: float = 60.0
    # minimum ratio of new-value tokens that must be found to call it reflected
    token_ratio: float = 0.75
    # minimum line similarity for the context (same-line) comparison
    line_similarity: float = 0.75
    # detect mark-ups that were flattened into the page content (coloured text/lines)
    detect_flattened: bool = True
    # also use "AutoCAD SHX Text" annotations of the AS-BUILT as text source
    use_shx_text: bool = False
    # write cropped evidence images
    images: bool = True
    image_zoom: float = 2.0
    image_pad: float = 45.0
    workers: int = 0
    extra_ignore_text: tuple = field(default_factory=tuple)


# Result statuses (Korean labels are what the QC team sees in the report)
OK = "반영"
NG = "미반영"
CHECK = "확인필요"
VISUAL = "육안확인"
INFO = "참고"

STATUS_ORDER = {NG: 0, CHECK: 1, VISUAL: 2, OK: 3, INFO: 4}

# Mark-ups that are not QC items and are left out of the report completely
# - signature / review stamps, e.g. "PIPING FE HS.JEONG", "REV.3A, 2026-04-14 PIPING FE YOO S.H"
SIGN_TEXT_PATTERNS = (r"PIPING\s+FE\b", r"\bREV\.?\s*\d+[A-Z]?\s*,\s*\d{4}-\d{2}-\d{2}")
# - weld numbers written in / circled by a red circle, e.g. "FW5", "F12", "F11S1"
WELD_TEXT_PATTERN = r"^F[A-Z]{0,2}\s*-?\d+[A-Z0-9]*$"
