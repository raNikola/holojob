"""Industry match dimension."""

from __future__ import annotations

import domain_transfer
from text_utils import normalize_text


MAX_SCORE = 95


def score_industry_match(job: dict, intelligence: dict, transfer_allowed: bool = True) -> tuple[int, list[str]]:
    score, reasons, _ = score_industry_match_detail(job, intelligence, transfer_allowed)
    return score, reasons


def score_industry_match_detail(
    job: dict, intelligence: dict, transfer_allowed: bool = True
) -> tuple[int, list[str], dict | None]:
    """(score, reasons, transferability). Proven industry experience and assumed transfer add to the base score
    (domain_transfer.py); an avoided industry stays at 20 and gets nothing."""
    score, reasons, avoided = _base(job, intelligence)
    if avoided:
        return score, reasons, None
    transfer = domain_transfer.assess(job, intelligence, allowed=transfer_allowed)
    if transfer["bonus"]:
        score = min(MAX_SCORE, score + transfer["bonus"])
    reasons = reasons + transfer["reasons"]
    return score, reasons, {k: v for k, v in transfer.items() if k != "reasons"}


def _base(job: dict, intelligence: dict) -> tuple[int, list[str], bool]:
    prefs = intelligence.get("jobFitPreferences") or {}
    preferred = [i.lower() for i in prefs.get("preferredIndustries") or []]
    avoided = [i.lower() for i in prefs.get("avoidedIndustries") or []]

    haystack = normalize_text(
        f"{job.get('company', '')} {job.get('description', '')} {job.get('title', '')}"
    )

    for a in avoided:
        if a and a in haystack:
            return 20, [f"Avoided industry signal: {a}"], True

    hits = [p for p in preferred if p and p in haystack]
    if hits:
        return min(MAX_SCORE, 70 + len(hits) * 8), [f"Preferred industry: {', '.join(hits[:3])}"], False

    if preferred:
        return 55, ["No clear industry match in posting"], False
    return 60, ["Industry preferences not set"], False
