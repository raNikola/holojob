"""Shared role matching for job-board clients.

Boards rank free-text search loosely, so every client pulls a wide set and
filters locally. One filter for every source stops them drifting apart; its
phrase lists are in Settings (`roleFilter`), not here.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_LLM_DIR = Path(__file__).resolve().parents[2] / "llm"
if str(_LLM_DIR) not in sys.path:
    sys.path.insert(0, str(_LLM_DIR))

import ai_gate  # noqa: E402

_PROVIDERS_DIR = Path(__file__).resolve().parent
if str(_PROVIDERS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROVIDERS_DIR))

import text_rules  # noqa: E402

logger = logging.getLogger(__name__)

# The owner's description overlay (packages 12 and 13): `{jobId: text}`, set once per run by run_discovery and empty otherwise, so a
# test never reads the real data folder. An ad the owner pasted or refreshed is filtered, and its text rules read, on that text.
_OVERLAY: dict[str, str] = {}
_URLS: dict[str, str] = {}  # jobUrl -> jobId of the overlaid ads, for a row that has no id yet (Workable sets it after the filter)


def use_overlay(ads: dict | None, urls: dict[str, str] | None = None) -> None:
    """`ads` is `description_overlay.load`'s map; None or {} clears it. `urls` maps an overlaid ad's job address to its id."""
    _OVERLAY.clear()
    _URLS.clear()
    _URLS.update(urls or {})
    for job_id, entry in (ads or {}).items():
        if isinstance(entry, dict) and isinstance(entry.get("text"), str) and entry["text"].strip():
            _OVERLAY[job_id] = entry["text"]


def overlay_ids() -> set[str]:
    return set(_OVERLAY)


def description_of(job: dict) -> str:
    """The ad text a filter reads for this scraped row: the owner's text when the id has one, else the scraped description."""
    job_id = job.get("jobId") or _URLS.get(job.get("jobUrl") or "")
    return _OVERLAY.get(job_id) or job.get("description") or ""

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


_FOLD = text_rules.FOLD


def _fold(text: str) -> str:
    """Lower case with the Serbian diacritics folded ("menadžer" = "menadzer"), as text_utils does for scoring."""
    return (text or "").lower().translate(_FOLD)


def _has_phrase(haystack: str, phrase: str) -> bool:
    """Match on word boundaries so "technical product" does not match
    "technical production manager"."""
    return re.search(rf"\b{re.escape(phrase)}\b", haystack) is not None


# Seniority words (owner plan 2026-11-25, closed decision: "years, seniority and domain are labels only"). They were in the exclude list
# until package 3; now a title holding one is labelled, never dropped for it. Scoring judges seniority. Folded, word boundaries.
SENIORITY_LABELS = ("junior", "intern", "internship", "trainee", "praktikant", "pripravnik", "student")

# Rule classes of a decision (owner plan 2026-11-25): a hard rule drops; a soft rule and an unknown continue, with a label.
HARD = "hard"
SOFT = "soft"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Decision:
    tier: str               # TARGET, NEAR or EXCLUDED
    reason: str | None      # set only for EXCLUDED: the drop reason the discard line carries
    rule: str | None        # HARD for a drop, SOFT or UNKNOWN when a title miss continues, None for a title match
    labels: tuple = ()      # informational only: nothing scores or filters on them (package 3)


def _seniority(title_lower: str) -> tuple:
    return tuple(f"seniority:{word}" for word in SENIORITY_LABELS if _has_phrase(title_lower, word))


def _title_decision(
    title: str,
    position: str = "",
    extra_terms: tuple[str, ...] = (),
    description: str | None = None,
) -> Decision:
    """The title filter's decision for one ad.

    1. Hard: a title holding an `exclude` phrase is dropped (`title_excluded:<term>`, the first phrase; it beats a board's position).
    2. Target: a board position assigned by hand, or an `include` phrase in the title. Near: a `near` phrase in the title or position,
       or a title that holds one of the caller's search terms (`extra_terms`; a search term alone never makes a title Target).
    3. A title that matches none of these goes to a free-text check (owner plan 2026-11-25, round 1) on the `description` the caller has:
       - an `include` phrase in the text: soft, the ad continues as Near (label `title_not_matched:text_match`);
       - no such phrase in a non-empty text: hard, dropped as `title_not_matched` (the drop it always was);
       - an empty text: unknown, the ad continues as Near (label `title_not_matched:no_text`): an empty description never drops an ad.
       `description=None` means the caller has no text check at all (title-only replays and audits): the title miss drops as before.
    A seniority word in the title (`SENIORITY_LABELS`) is a label, never a drop.
    """
    vocab = vocabulary()
    title_lower = _fold(title)
    position_lower = _fold(position)
    labels = _seniority(title_lower)

    for term in vocab.exclude:
        if _has_phrase(title_lower, term):
            return Decision(EXCLUDED, f"title_excluded:{term}", HARD, labels)
    if position_lower in vocab.position_whitelist:
        return Decision(TARGET, None, None, labels)
    if any(_has_phrase(title_lower, term) for term in vocab.include):
        return Decision(TARGET, None, None, labels)
    if any(_has_phrase(title_lower, term) for term in vocab.near) or any(_has_phrase(position_lower, term) for term in vocab.near):
        return Decision(NEAR, None, None, labels)
    if any(_has_phrase(title_lower, _fold(t)) for t in extra_terms if t):
        return Decision(NEAR, None, None, labels)
    if description is None:
        return Decision(EXCLUDED, "title_not_matched", HARD, labels)
    text = _fold(description)
    if not text.strip():
        return Decision(NEAR, None, UNKNOWN, labels + ("title_not_matched:no_text",))
    # `include` phrases only: a `near` phrase in body text ("you report to the project manager") is too common to let an ad in.
    if any(_has_phrase(text, term) for term in vocab.include):
        return Decision(NEAR, None, SOFT, labels + ("title_not_matched:text_match",))
    return Decision(EXCLUDED, "title_not_matched", HARD, labels)


def assess(
    title: str,
    position: str = "",
    extra_terms: tuple[str, ...] = (),
    description: str | None = None,
) -> Decision:
    """The title decision plus the round 2 text rules (package 4, `text_rules.py`): language, years, on-site only, visa and employment
    type, read from the ad text when the caller has one. Each fired rule adds a label; a rule whose class is HARD drops the ad
    (`text_rule:<label>`, never pins dedup). Every rule is SOFT today, so the text rules never change a keep or a drop. An empty or
    missing text is unknown: no label, the decision is the title's."""
    decision = _title_decision(title, position, extra_terms, description)
    if not description or decision.tier == EXCLUDED:
        return decision
    fired = text_rules.evaluate(_fold(description))
    if not fired:
        return decision
    labels = decision.labels + tuple(label for _, _, label in fired)
    for _, rule_class, label in fired:
        if rule_class == HARD:
            return Decision(EXCLUDED, f"text_rule:{label}", HARD, labels)
    return dataclasses.replace(decision, labels=labels)


def role_tier(
    title: str,
    position: str = "",
    extra_terms: tuple[str, ...] = (),
    description: str | None = None,
) -> tuple[str, str | None]:
    """(tier, reason) of `assess`: Target, Near or Excluded; the reason is set only for Excluded. Target and Near go on to scoring."""
    decision = assess(title, position, extra_terms, description)
    return decision.tier, decision.reason


def role_drop_reason(
    title: str,
    position: str = "",
    extra_terms: tuple[str, ...] = (),
    description: str | None = None,
) -> str | None:
    """Why the role filter drops this ad, or None when it keeps it (Target or Near)."""
    return role_tier(title, position, extra_terms, description)[1]


def is_relevant_role(
    title: str,
    position: str = "",
    extra_terms: tuple[str, ...] = (),
    description: str | None = None,
) -> bool:
    return role_drop_reason(title, position, extra_terms, description) is None
