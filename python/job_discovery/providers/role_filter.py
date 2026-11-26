"""Shared role matching for job-board clients.

Boards rank free-text search loosely, so every client pulls a wide set and
filters locally. One filter for every source stops them drifting apart; its
phrase lists are in Settings (`roleFilter`), not here.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_LLM_DIR = Path(__file__).resolve().parents[2] / "llm"
if str(_LLM_DIR) not in sys.path:
    sys.path.insert(0, str(_LLM_DIR))

import ai_gate  # noqa: E402

logger = logging.getLogger(__name__)

# The vocabulary lives in Settings (`roleFilter` in data/ai/settings.json, defaults in ai_gate.DEFAULT_SETTINGS; package 3, owner plan
# 2026-11-25). What each list does:
# - positionWhitelist: a board's own hand-assigned position; it beats any title heuristic, so a match short-circuits the title check.
# - include: Target.
# - near: neighbouring roles scoring can judge, kept in step with src/data/roleFamilies.json `titleRules` (nearTitlePatterns,
#   productResponsibilityTitlePatterns; tests/python/test_role_filter_tiers.py checks the defaults). "project manager" and "delivery
#   manager" are here, not in exclude: scoring caps them (role_tier.title_tier), discovery keeps them.
# - exclude: the hard drop, checked first, beats a board's own position.
# The module-level tuples are the DEFAULTS, for readers that need them without Settings (tests, audits); the filter itself reads
# `vocabulary()`.
_DEFAULTS = ai_gate.DEFAULT_SETTINGS["roleFilter"]
POSITION_WHITELIST = frozenset(_DEFAULTS["positionWhitelist"])
TITLE_INCLUDE = tuple(_DEFAULTS["include"])
TITLE_NEAR = tuple(_DEFAULTS["near"])
TITLE_EXCLUDE = tuple(_DEFAULTS["exclude"])


@dataclass(frozen=True)
class Vocabulary:
    position_whitelist: frozenset
    include: tuple
    near: tuple
    exclude: tuple


def _folded(phrases) -> tuple:
    return tuple(dict.fromkeys(_fold(p) for p in phrases if _fold(p).strip()))


_cache: dict = {}


def vocabulary() -> Vocabulary:
    """The Settings vocabulary, folded. Read once per settings file state (path and mtime), not once per title; a list that cannot be used
    is its default and logged (ai_gate.role_filter_vocabulary), never an empty list."""
    path = ai_gate.settings_path()
    try:
        stamp = (str(path), path.stat().st_mtime_ns)
    except OSError:
        stamp = (str(path), None)
    if _cache.get("stamp") != stamp:
        lists, warning = ai_gate.role_filter_vocabulary()
        if warning:
            logger.warning("role filter: %s", warning)
        _cache.update(stamp=stamp, vocab=Vocabulary(
            position_whitelist=frozenset(_folded(lists["positionWhitelist"])), include=_folded(lists["include"]),
            near=_folded(lists["near"]), exclude=_folded(lists["exclude"])))
    return _cache["vocab"]


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
    vocab = vocabulary()
    title_lower = _fold(title)
    position_lower = _fold(position)

    for term in vocab.exclude:
        if _has_phrase(title_lower, term):
            return EXCLUDED, f"title_excluded:{term}"
    if position_lower in vocab.position_whitelist:
        return TARGET, None
    if any(_has_phrase(title_lower, term) for term in vocab.include):
        return TARGET, None
    if any(_has_phrase(title_lower, term) for term in vocab.near) or any(_has_phrase(position_lower, term) for term in vocab.near):
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
