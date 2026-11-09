"""The candidate's own words, and the rules for choosing among them.

The CV and the cover letter state only what the candidate wrote. This module
is where that text comes from (the questionnaire's career summary, read from
the profile itself) and how sentences are chosen from it: whole sentences, in
the candidate's order, never rewritten. A sentence with a banned phrase is
left out rather than edited.
"""

from __future__ import annotations

import re

BANNED_PHRASES = (
    "passionate",
    "team player",
    "fast-paced environment",
    "results-driven",
    "go-getter",
    "think outside the box",
    "self-starter",
    "synergy",
    "dynamic",
)

# Each word of a phrase may carry an ending, so "thinking outside the box" and
# "team players" are caught as well as the exact phrase.
_BANNED_RES = [
    re.compile(r"\b" + r"[\s-]+".join(rf"{re.escape(w)}\w*" for w in re.split(r"[\s-]+", phrase)) + r"\b", re.I)
    for phrase in BANNED_PHRASES
]

# The questionnaire item that asks for a career summary in the candidate's own
# words. The intelligence file's careerNarrative is not used: when this answer
# is missing, the engine fills that field from a template, or leaves it empty
# and lists it under candidateSummary.unknown.
NARRATIVE_QUESTION_ID = 17


def banned_phrases_in(text: str) -> list[str]:
    """The banned phrases the text contains, in any inflection."""
    return [phrase for phrase, pattern in zip(BANNED_PHRASES, _BANNED_RES) if pattern.search(text or "")]


def narrative_answer(profile: dict) -> str:
    """The candidate's own career summary from the questionnaire, or ''."""
    for answer in (profile.get("questionnaire") or {}).get("answers") or []:
        if not isinstance(answer, dict) or str(answer.get("id")) != str(NARRATIVE_QUESTION_ID):
            continue
        text = answer.get("answer")
        return re.sub(r"\s+", " ", text).strip() if isinstance(text, str) else ""
    return ""


def own_sentences(text: str, limit: int | None = None) -> list[str]:
    """Whole sentences (up to `limit`), in order, skipping any with a banned phrase."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]
    return [s for s in sentences if not banned_phrases_in(s)][:limit]
