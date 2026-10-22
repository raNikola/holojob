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


def is_relevant_role(
    title: str,
    position: str = "",
    extra_terms: tuple[str, ...] = (),
) -> bool:
    title_lower = (title or "").lower()
    position_lower = (position or "").lower()

    if any(_has_phrase(title_lower, term) for term in TITLE_EXCLUDE):
        return False
    if position_lower in POSITION_WHITELIST:
        return True
    includes = TITLE_INCLUDE + tuple(t.lower() for t in extra_terms if t)
    return any(_has_phrase(title_lower, term) for term in includes)