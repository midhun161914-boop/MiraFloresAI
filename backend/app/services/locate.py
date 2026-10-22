"""Locate an extracted value's text inside its page's printed_content.

Why: ``position`` boxes in the packet are synthetic, so they can place a highlight
on a page *representation* but cannot prove what is printed. ``printed_content``
is ground truth. Finding the value in the printed text lets the viewer highlight
the real words, and a value that is *not* on its page (in any normal formatting)
is an immediate signal that the read, or its page attribution, is suspect.

The pipeline normalises what it read (``text_as_read`` "01/10/2020" for a page that
prints "2020-01-10"; "24,800.00" for "24,800"), so we try the raw reading first and
then formatting variants derived from the typed value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Optional

MatchStatus = Literal["exact", "ambiguous", "not_found", "empty"]

_STOP = {
    "the", "and", "for", "from", "with", "of", "to", "in", "on", "a", "an", "or",
    "total", "amount", "box", "line", "form", "name", "acq", "acquired", "sold",
    "date", "proceeds", "basis",
}
_WINDOW = 140


@dataclass(frozen=True)
class TextMatch:
    status: MatchStatus
    start: Optional[int] = None
    end: Optional[int] = None
    candidates: int = 0
    matched_text: Optional[str] = None
    normalized: bool = False  # matched a formatting variant, not text_as_read verbatim


def _num_variants(v: float) -> list[str]:
    out = [f"{v:,.2f}"]
    if float(v).is_integer():
        out += [f"{int(v):,}", str(int(v))]
    else:
        out += [f"{v:,}", str(v)]
    out += [f"{v:.2f}", f"{v:,.1f}"]
    return out


def variants(text_as_read: str, value: Any, value_type: str, field: str = "") -> list[str]:
    out = [text_as_read.strip()]
    if value_type == "date" and isinstance(value, str):
        out.append(value)
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
        if m:
            y, mo, d = m.groups()
            out += [f"{mo}/{d}/{y}", f"{int(mo)}/{int(d)}/{y}"]
    elif value_type in ("money", "integer", "quantity") and isinstance(value, (int, float)) \
            and not isinstance(value, bool):
        out += _num_variants(float(value) if value_type == "money" else value)
        if value_type == "money" and value < 0:
            out += [f"({abs(value):,.2f})", f"({abs(value):,.0f})", f"-{abs(value):,.0f}"]
    elif value_type == "percent" and isinstance(value, (int, float)):
        out += [f"{value}%", f"{value:g}%", f"{value * 100:g}%" if value <= 1 else ""]
    elif value_type == "boolean" and value is True:
        # Checkboxes are read as "X"; the page prints the word ("covered", "checked").
        words = [w for w in re.split(r"[_\s]+", field) if w.isalpha() and len(w) >= 4]
        out += words + ["checked"]
    elif isinstance(value, str):
        out.append(value)
    seen: set[str] = set()
    return [x for x in out if x and not (x in seen or seen.add(x))]


def _occurrences(needle: str, hay: str) -> list[tuple[int, int]]:
    # Bound on alphanumerics so "1,840.00" doesn't match inside "11,840.00".
    for flags in (0, re.IGNORECASE):
        pat = re.compile(r"(?<![0-9A-Za-z.,])" + re.escape(needle) + r"(?![0-9A-Za-z]|[.,]\d)", flags)
        hits = [(m.start(), m.end()) for m in pat.finditer(hay)]
        if hits:
            return hits
    return []


def _anchors(field: str, label: str) -> list[tuple[str, float]]:
    """(token, weight) pairs that tend to sit just before the value on the page."""
    anchors: list[tuple[str, float]] = []
    # Lot / row identifiers in the field name: "M9_acquired" -> M9, "X116_sold" -> X116
    for tok in re.findall(r"(?<![A-Za-z0-9])([A-Z]{1,3}\d{1,4})(?![A-Za-z0-9])", field):
        anchors.append((tok, 5.0))
    m = re.search(r"box\s*(\d+[a-z]?)", f"{field} {label}", re.IGNORECASE)
    if m:
        anchors.append((f"box {m.group(1)}", 4.0))
    m = re.match(r"(trip|line|row|item)(\d+)", field, re.IGNORECASE)
    if m:
        anchors.append((m.group(2), 0.5))
    for word in re.findall(r"[A-Za-z][A-Za-z0-9]+", f"{label} {field.replace('_', ' ')}"):
        w = word.lower()
        if len(w) >= 3 and w not in _STOP and all(w != a.lower() for a, _ in anchors):
            anchors.append((w, 1.0))
    return anchors


def _segments(hay: str) -> list[tuple[int, int]]:
    bounds, start = [], 0
    for part in hay.split(";"):
        bounds.append((start, start + len(part)))
        start += len(part) + 1
    return bounds


def _row_segment(field: str, hay: str) -> Optional[tuple[int, int]]:
    """The ';'-separated entry a field belongs to.

    "trip7_date" -> the 7th entry; "M9_acquired" / "RSU-2502_adjusted_basis" ->
    the entry that names lot M9 / RSU-2502.
    """
    bounds = _segments(hay)
    m = re.match(r"(?:trip|row|entry)(\d+)_", field, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        return bounds[n - 1] if 1 <= n <= len(bounds) else None
    head = field.split("_", 1)[0]
    if "_" in field and re.search(r"\d", head) and re.search(r"[A-Za-z]", head)             and not head.lower().startswith("box"):
        tok = re.compile(r"(?<![0-9A-Za-z-])" + re.escape(head) + r"(?![0-9A-Za-z-])")
        rows = [b for b in bounds if tok.search(hay, b[0], b[1])]
        if len(rows) == 1:
            return rows[0]
    return None


def _score(hay: str, start: int, anchors: list[tuple[str, float]]) -> float:
    window = hay[max(0, start - _WINDOW): start]
    score = 0.0
    for tok, weight in anchors:
        ci = 0 if tok[0].isupper() and any(c.isdigit() for c in tok) else re.IGNORECASE
        hits = list(re.finditer(r"(?<![0-9A-Za-z])" + re.escape(tok) + r"(?![0-9A-Za-z])", window, ci))
        if hits:
            dist = len(window) - hits[-1].end()
            score += weight * (1 - dist / (_WINDOW + 1))
    return score


def locate(
    text_as_read: str, printed_content: str, field: str = "", label: str = "",
    value: Any = None, value_type: str = "text",
) -> TextMatch:
    if not text_as_read.strip() and value in (None, ""):
        return TextMatch("empty")
    for i, needle in enumerate(variants(text_as_read, value, value_type, field)):
        hits = _occurrences(needle, printed_content)
        if not hits:
            continue
        normalized = i > 0
        if len(hits) == 1:
            s, e = hits[0]
            return TextMatch("exact", s, e, 1, printed_content[s:e], normalized)
        row = _row_segment(field, printed_content)
        if row is not None:
            in_row = [(s, e) for s, e in hits if row[0] <= s < row[1]]
            if len(in_row) == 1:
                s, e = in_row[0]
                return TextMatch("exact", s, e, len(hits), printed_content[s:e], normalized)
            hits = in_row or hits
        anchors = _anchors(field, label)
        scored = sorted(((_score(printed_content, s, anchors), s, e) for s, e in hits),
                        key=lambda t: -t[0])
        (best, s, e), runner_up = scored[0], scored[1][0]
        status: MatchStatus = "exact" if best > 0 and best - runner_up > 0.05 else "ambiguous"
        return TextMatch(status, s, e, len(hits), printed_content[s:e], normalized)
    return TextMatch("not_found") if text_as_read.strip() else TextMatch("empty")
