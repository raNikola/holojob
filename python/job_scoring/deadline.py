"""The date an ad gives for applying. Display metadata: it reaches no score, and it never closes an ad.

A board's own expiry date comes first. Failing that, a date in the ad's text is taken only right after a phrase that
announces a deadline, and only when the date cannot be misread: a month written out, or a dotted European date, or a
slash date whose day is over 12. The one exception is the fixed US-format boilerplate "the application window is
expected to close on: MM/DD/YYYY". Anything else is unknown.
"""

from __future__ import annotations

import re
from datetime import date

from text_utils import normalize_text

MONTHS = {
    name: number
    for number, names in enumerate(
        (("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"), ("july", "jul"),
         ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"), ("december", "dec")),
        start=1,
    )
    for name in names
}
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
_US_ONLY_ANCHOR = r"application window (?:is )?expected to close on"
_ANCHOR = (
    rf"(?P<us>{_US_ONLY_ANCHOR})"
    r"|application window closes(?: on)?"
    r"|(?:expected )?application deadline(?: for this job)?(?: is)?"
    r"|deadline (?:to|for) appl(?:y|ications?)(?: is)?"
    r"|applications? close[sd]?(?: on)?"
    r"|closing date(?: is)?"
    r"|accept applications until"
    r"|apply (?:by|before)"
    r"|rok za prijav[ue](?: je)?"
    r"|prijave (?:traju )?do"
)
_DATE = (
    rf"(?P<mdy>(?P<m1>{_MONTH})\.? (?P<d1>\d{{1,2}})(?:st|nd|rd|th)?,? (?P<y1>\d{{4}}))"
    rf"|(?P<dmy>(?P<d2>\d{{1,2}})(?:st|nd|rd|th)? (?P<m2>{_MONTH})\.?,? (?P<y2>\d{{4}}))"
    r"|(?P<dots>(?P<d3>\d{1,2})\.\s?(?P<m3>\d{1,2})\.\s?(?P<y3>\d{4}))"
    r"|(?P<slash>(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y4>\d{4}))"
)
_PATTERN = re.compile(rf"(?:{_ANCHOR})[\s:*_–-]{{0,8}}(?:{_DATE})")


def _build(year, month, day) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except (TypeError, ValueError):
        return None


def _from_match(match: re.Match) -> str | None:
    if match["mdy"]:
        return _build(match["y1"], MONTHS[match["m1"]], match["d1"])
    if match["dmy"]:
        return _build(match["y2"], MONTHS[match["m2"]], match["d2"])
    if match["dots"]:
        return _build(match["y3"], match["m3"], match["d3"])
    first, second = int(match["a"]), int(match["b"])
    if match["us"] or second > 12:
        return _build(match["y4"], first, second)
    if first > 12:
        return _build(match["y4"], second, first)
    return None  # 03/04/2026 can be read two ways


def _board_date(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def date_in_text(text) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    for match in _PATTERN.finditer(normalize_text(text)):
        found = _from_match(match)
        if found:
            return found
    return None


def deadline_metadata(job: dict) -> dict:
    """The two display fields scorer.py attaches to a scored job."""
    board = _board_date(job.get("expiresAt"))
    if board:
        return {"applyDeadline": board, "applyDeadlineSource": "board"}
    in_text = date_in_text(job.get("description"))
    return {"applyDeadline": in_text, "applyDeadlineSource": "ad_text" if in_text else None}
