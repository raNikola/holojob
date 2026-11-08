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

# Excluded: a seniority the candidate is past, or a clearly different function. Checked first, and it beats a board's own
# position. "project manager" and "delivery manager" are NOT here any more: scoring caps them (role_tier.title_tier), so
# discovery keeps them as Near instead of deciding by name alone.
TITLE_EXCLUDE = (
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

# Near: neighbouring roles scoring can judge. Kept in step with src/data/roleFamilies.json `titleRules`
# (nearTitlePatterns, productResponsibilityTitlePatterns); tests/python/test_role_filter_tiers.py checks it.
TITLE_NEAR = (
    "project manager",
    "delivery manager",
    "program manager",
    "programme manager",
    "product operations",
    "product ops",
    "product management",
    "tpm",
    # Serbian boards (diacritics folded, see _fold)
    "projekt menadzer",
    "projektni menadzer",
    "menadzer projekata",
    "menadzer za upravljanje projektima",
    "rukovodilac projekta",
)

TARGET = "target"
NEAR = "near"
EXCLUDED = "excluded"


_FOLD = str.maketrans({"š": "s", "ž": "z", "č": "c", "ć": "c", "đ": "d"})


def _fold(text: str) -> str:
    """Lower case with the Serbian diacritics folded ("menadžer" = "menadzer"), as text_utils does for scoring."""
    return (text or "").lower().translate(_FOLD)


def _has_phrase(haystack: str, phrase: str) -> bool:
    """Match on word boundaries so "technical product" does not match
    "technical production manager"."""
    return re.search(rf"\b{re.escape(phrase)}\b", haystack) is not None


def role_tier(
    title: str,
    position: str = "",
    extra_terms: tuple[str, ...] = (),
) -> tuple[str, str | None]:
    """(tier, reason): Target, Near or Excluded; the reason is set only for Excluded.

    Excluded: `title_excluded:<term>` (the first excluded phrase the title holds; it beats a board's own position) or
    `title_not_matched` (nothing in the title or the position let it in). Target: a target phrase or a board position
    assigned by hand. Near: a neighbouring role, or a title that only holds one of the caller's search terms
    (`extra_terms`): a search term alone never makes a title Target, scoring decides relevance from there.
    Target and Near both go on to scoring; only Excluded is dropped.
    """
    title_lower = _fold(title)
    position_lower = _fold(position)

    for term in TITLE_EXCLUDE:
        if _has_phrase(title_lower, term):
            return EXCLUDED, f"title_excluded:{term}"
    if position_lower in POSITION_WHITELIST:
        return TARGET, None
    if any(_has_phrase(title_lower, term) for term in TITLE_INCLUDE):
        return TARGET, None
    if any(_has_phrase(title_lower, term) for term in TITLE_NEAR) or any(_has_phrase(position_lower, term) for term in TITLE_NEAR):
        return NEAR, None
    if any(_has_phrase(title_lower, _fold(t)) for t in extra_terms if t):
        return NEAR, None
    return EXCLUDED, "title_not_matched"


def role_drop_reason(
    title: str,
    position: str = "",
    extra_terms: tuple[str, ...] = (),
) -> str | None:
    """Why the role filter drops this ad, or None when it keeps it (Target or Near)."""
    return role_tier(title, position, extra_terms)[1]


def is_relevant_role(
    title: str,
    position: str = "",
    extra_terms: tuple[str, ...] = (),
) -> bool:
    return role_drop_reason(title, position, extra_terms) is None
