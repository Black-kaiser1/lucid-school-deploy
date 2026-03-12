"""
Grading logic — all functions accept an optional `scale` dict.
If scale is None, the built-in WAEC Ghana scale is used.

scale dict shape (loaded from grading_scales table):
  {
    "grades": [
      {"min": 75, "letter": "A1", "point": 1, "remark": "Excellent"},
      ...  sorted high→low by min
    ],
    "aggregate_subjects": "best6",   # "best6" | "all_core" | "all"
    "agg_distinction": 12,
    "agg_credit":      18,
    "agg_pass":        24,
    "class_score_max": 40,
    "exam_score_max":  60,
  }
"""
import json

# ── Default WAEC scale ────────────────────────────────────────────────────────
DEFAULT_GRADES = [
    {"min": 75, "letter": "A1", "point": 1, "remark": "Excellent"},
    {"min": 70, "letter": "B2", "point": 2, "remark": "Very Good"},
    {"min": 65, "letter": "B3", "point": 3, "remark": "Good"},
    {"min": 60, "letter": "C4", "point": 4, "remark": "Credit"},
    {"min": 55, "letter": "C5", "point": 5, "remark": "Credit"},
    {"min": 50, "letter": "C6", "point": 6, "remark": "Credit"},
    {"min": 45, "letter": "D7", "point": 7, "remark": "Pass"},
    {"min": 40, "letter": "E8", "point": 8, "remark": "Pass"},
    {"min":  0, "letter": "F9", "point": 9, "remark": "Fail"},
]

DEFAULT_SCALE = {
    "grades":              DEFAULT_GRADES,
    "aggregate_subjects":  "best6",
    "agg_distinction":     12,
    "agg_credit":          18,
    "agg_pass":            24,
    "class_score_max":     40,
    "exam_score_max":      60,
}

def _resolve_scale(scale):
    """Return DEFAULT_SCALE merged with any overrides provided."""
    if scale is None:
        return DEFAULT_SCALE
    result = dict(DEFAULT_SCALE)
    result.update({k: v for k, v in scale.items() if v is not None})
    # Ensure grades are sorted high→low
    if "grades" in result and result["grades"]:
        result["grades"] = sorted(result["grades"], key=lambda g: -float(g["min"]))
    return result

def scale_from_db_row(row):
    """Convert a grading_scales DB row (dict) into a scale dict."""
    if row is None:
        return None
    try:
        grades = json.loads(row["grades_json"])
    except Exception:
        grades = DEFAULT_GRADES
    return {
        "grades":             grades,
        "aggregate_subjects": row.get("aggregate_subjects", "best6"),
        "agg_distinction":    row.get("agg_distinction", 12),
        "agg_credit":         row.get("agg_credit",      18),
        "agg_pass":           row.get("agg_pass",        24),
        "class_score_max":    row.get("class_score_max", 40),
        "exam_score_max":     row.get("exam_score_max",  60),
    }

# ── Core grading functions ────────────────────────────────────────────────────

def waec_grade(score, scale=None):
    """Return (letter, point, remark) for a numeric score."""
    sc = _resolve_scale(scale)
    if score is None:
        return ("ABS", 9, "Absent")
    s = float(score)
    for band in sc["grades"]:          # already sorted high→low
        if s >= float(band["min"]):
            return (band["letter"], int(band["point"]), band["remark"])
    # Fallback to last band
    last = sc["grades"][-1]
    return (last["letter"], int(last["point"]), last["remark"])


def compute_aggregate(scores, scale=None, subject_flags=None):
    """
    Compute BECE/WASSCE-style aggregate from a list of totals.
    subject_flags: parallel list of is_core booleans (required when
                   aggregate_subjects == 'all_core').
    Returns int aggregate or None.
    """
    sc = _resolve_scale(scale)
    mode = sc.get("aggregate_subjects", "best6")

    # Filter to relevant scores
    if mode == "all_core" and subject_flags:
        pairs = [(s, f) for s, f in zip(scores, subject_flags) if s is not None and f]
        relevant = [p[0] for p in pairs]
    elif mode == "all":
        relevant = [s for s in scores if s is not None]
    else:
        # best6 (default)
        relevant = [s for s in scores if s is not None]

    pts = sorted([waec_grade(s, sc)[1] for s in relevant])

    if mode in ("best6", "all_core"):
        return sum(pts[:6]) if len(pts) >= 6 else None
    else:  # "all"
        return sum(pts) if pts else None


def aggregate_remark(agg, scale=None):
    """Return (label, hex_colour) for an aggregate score."""
    sc = _resolve_scale(scale)
    if agg is None:
        return ("—", "#888888")
    if agg <= sc["agg_distinction"]:
        return ("DISTINCTION", "#1B4332")
    if agg <= sc["agg_credit"]:
        return ("CREDIT", "#1565C0")
    if agg <= sc["agg_pass"]:
        return ("PASS", "#E65100")
    return ("FAIL", "#B71C1C")


def ordinal(n):
    if n is None: return "—"
    s = {1:"st", 2:"nd", 3:"rd"}.get(n % 10, "th")
    if 11 <= n % 100 <= 13: s = "th"
    return f"{n}{s}"


def grade_colors(letter):
    """Return (text_color, bg_color) for a grade letter."""
    MAP = {
        "A1": ("#1B5E20","#DCEDC8"), "B2": ("#1B5E20","#C8E6C9"),
        "B3": ("#2E7D32","#E8F5E9"), "C4": ("#1565C0","#E3F2FD"),
        "C5": ("#1565C0","#E8F0FE"), "C6": ("#1565C0","#EDE7F6"),
        "D7": ("#E65100","#FFF3E0"), "E8": ("#BF360C","#FBE9E7"),
        "F9": ("#B71C1C","#FFCDD2"), "ABS":("#757575","#F5F5F5"),
        # Generic letter grades
        "A" : ("#1B5E20","#DCEDC8"), "B" : ("#1565C0","#E3F2FD"),
        "C" : ("#E65100","#FFF3E0"), "D" : ("#BF360C","#FBE9E7"),
        "F" : ("#B71C1C","#FFCDD2"), "E" : ("#E65100","#FFF3E0"),
        "P" : ("#1565C0","#E3F2FD"),
    }
    return MAP.get(letter, ("#333333","#F5F5F5"))


# Keep backward-compatible alias
GRADE_COLORS = {
    "A1":("#1B5E20","#DCEDC8"), "B2":("#1B5E20","#C8E6C9"),
    "B3":("#2E7D32","#E8F5E9"), "C4":("#1565C0","#E3F2FD"),
    "C5":("#1565C0","#E8F0FE"), "C6":("#1565C0","#EDE7F6"),
    "D7":("#E65100","#FFF3E0"), "E8":("#BF360C","#FBE9E7"),
    "F9":("#B71C1C","#FFCDD2"), "ABS":("#757575","#F5F5F5"),
}
