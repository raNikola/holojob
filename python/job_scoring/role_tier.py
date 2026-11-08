"""The role-family config read by scoring (src/data/roleFamilies.json), and the vocabulary it holds for titles.

A family without a `titleRules` entry has no vocabulary: nothing about a title is decided for it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from text_utils import normalize_text

ROLE_FAMILIES_FILE = Path(__file__).resolve().parents[2] / "src" / "data" / "roleFamilies.json"
ROLE_FAMILIES = json.loads(ROLE_FAMILIES_FILE.read_text(encoding="utf-8"))


def title_rules(family: str | None) -> dict:
    """The family's title vocabulary; empty for no family or a family that has none."""
    return (ROLE_FAMILIES.get(family) or {}).get("titleRules") or {} if family else {}


def names_another_job(title: str, family: str | None) -> bool:
    """A target phrase inside a title for another function: "Head of Product Marketing" holds "head of product"."""
    normalized = normalize_text(title)
    return any(phrase in normalized for phrase in title_rules(family).get("notTargetPhrases") or [])


TARGET = "target"
NEAR = "near"
UNRELATED = "unrelated"

# role_match scores from these up: a target title, then a product role in other words (or a stretch role).
_TARGET_ROLE_SCORE = 80
_PRODUCT_WORDING_ROLE_SCORE = 65


def _any(patterns, text: str) -> bool:
    return any(re.search(pattern, text) for pattern in patterns or [])


def title_tier(title: str, role_score: int, family: str | None, facts: dict | None = None) -> str | None:
    """Target, near or unrelated, for the candidate's role family; None when nothing can be said.

    No family, a family with no vocabulary and an empty title are None: unknown never caps. A project or delivery
    title is near only when the ad's own words, read by enrichment, show product responsibility.
    """
    rules = title_rules(family)
    normalized = normalize_text(title)
    if not rules or not normalized:
        return None
    if role_score >= _TARGET_ROLE_SCORE:
        return TARGET
    if _any(rules.get("otherFunctionPatterns"), normalized):
        return UNRELATED
    if _any(rules.get("productResponsibilityTitlePatterns"), normalized):
        facts = facts or {}
        evidenced = bool((facts.get("roleTrackEvidence") or "").strip())
        return NEAR if evidenced and facts.get("roleTrack") in rules.get("productResponsibilityTracks", []) else UNRELATED
    if role_score >= _PRODUCT_WORDING_ROLE_SCORE or _any(rules.get("nearTitlePatterns"), normalized):
        return NEAR
    return UNRELATED
