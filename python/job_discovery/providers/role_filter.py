"""Shared role matching for job-board clients.

Boards rank free-text search loosely, so every client pulls a wide set and
filters locally. Keeping the term lists here stops them drifting apart as
sources are added.
"""

from __future__ import annotations

import re

# Some boards assign a normalized position by hand. That beats any title
# heuristic, so a match here short-circuits the title check.
POSITION_WHITELIST = {"product manager", "product owner"}

TITLE_INCLUDE = (
    "product manager",
    "product owner",
    "product lead",
    "head of product",
    "group product manager",
    "platform product",
    "technical product",
)

TITLE_EXCLUDE = (
    "project manager",
    "delivery manager",
    "account manager",
    "sales manager",
    "area sales",
    "brand manager",
    "category manager",
    "product technologist",
    "junior",
    "intern",
    "praktikant",
    "pripravnik",
)


def _has_phrase(haystack: str, phrase: str) -> bool:
    """Match on word boundaries so "technical product" does not match
    "technical production manager"."""
    return re.search(rf"\b{re.escape(phrase)}\b", haystack) is not None


def role_drop_reason(
    title: str,
    position: str = "",
    extra_terms: tuple[str, ...] = (),
) -> str | None:
    """Why the role filter drops this ad, or None when it keeps it. This is the rule; `is_relevant_role` is its yes/no.

    `title_excluded:<term>` names the first excluded phrase the title holds (the exclusion beats a board's own position),
    `title_not_matched` says nothing in the title or the position let it in.
    """
    title_lower = (title or "").lower()
    position_lower = (position or "").lower()

    for term in TITLE_EXCLUDE:
        if _has_phrase(title_lower, term):
            return f"title_excluded:{term}"
    if position_lower in POSITION_WHITELIST:
        return None
    includes = TITLE_INCLUDE + tuple(t.lower() for t in extra_terms if t)
    if any(_has_phrase(title_lower, term) for term in includes):
        return None
    return "title_not_matched"


def is_relevant_role(
    title: str,
    position: str = "",
    extra_terms: tuple[str, ...] = (),
) -> bool:
    return role_drop_reason(title, position, extra_terms) is None