"""Whether an ad says enough to be scored at all.

A junk or near-empty description used to score about 44, because every dimension has a neutral baseline for
"not stated". Neutral is right for one missing fact, not for an ad that states nothing. An ad without enough
information gets the explicit state "Insufficient data" instead of a Fit Score.

The length thresholds are only a first signal. A short ad that carries real role or requirement information
is NOT insufficient: extracted requirements (llmFacts), or enough distinct terms and at least two cues of
a concrete duty or requirement, are enough.
"""

from __future__ import annotations

from text_utils import normalize_text, term_tokens

MIN_CHARS = 80  # the same line as the "Thin job description" red flag
MIN_TERMS = 30  # distinct meaningful terms of a full description
MIN_SHORT_TERMS = 12  # a short ad needs at least this many distinct terms ...
MIN_SHORT_CUES = 2  # ... and this many duty / requirement cues to count as informative
LOW_CONFIDENCE_CHARS = 400  # below this a scored ad is shown with a low-confidence reason

CUES = (
    "responsib", "requir", "experience", "you will", "you'll", "years", "skills", "qualif", "must",
    "own ", "manage", "lead", "build", "develop", "design", "define", "drive", "deliver", "collaborat",
    "stakeholder", "roadmap", "strategy", "analy", "ownership",
)

STATE = "insufficient"
SCORE_CEILING = 5


def _requirements(job: dict) -> list:
    facts = job.get("llmFacts") or {}
    return [r for r in (facts.get("requirements") or []) if isinstance(r, dict) and (r.get("text") or "").strip()]


def metrics(job: dict) -> dict:
    desc = normalize_text(job.get("description") or "")
    return {
        "chars": len(desc),
        "terms": len(term_tokens(desc)),
        "cues": sum(1 for cue in CUES if cue in desc),
        "requirements": len(_requirements(job)),
    }


def assess(job: dict) -> list[str]:
    """Reasons the ad cannot be scored; an empty list means it can."""
    m = metrics(job)
    if m["requirements"]:
        return []
    if m["chars"] >= MIN_CHARS and m["terms"] >= MIN_TERMS:
        return []
    if m["terms"] >= MIN_SHORT_TERMS and m["cues"] >= MIN_SHORT_CUES:
        return []
    reasons = []
    if m["chars"] < MIN_CHARS:
        reasons.append(f"Description too short to judge ({m['chars']} characters)")
    elif m["terms"] < MIN_SHORT_TERMS:
        reasons.append(f"Description has too little content ({m['terms']} distinct terms)")
    else:
        reasons.append("Description names no concrete duties or requirements")
    reasons.append("No requirements could be read from the ad")
    return reasons


def low_confidence(job: dict, *, location_stated: bool, seniority_stated: bool, has_keyword_bank: bool) -> list[str]:
    """Reasons a score that was computed deserves less trust. The score itself is not changed."""
    m = metrics(job)
    reasons = []
    if not m["requirements"]:
        reasons.append("Requirements not extracted: must-have and nice-to-have are not separated")
    if m["chars"] < LOW_CONFIDENCE_CHARS:
        reasons.append(f"Short description ({m['chars']} characters)")
    if not location_stated:
        reasons.append("Location not stated")
    if not seniority_stated:
        reasons.append("Seniority not stated")
    if not has_keyword_bank:
        reasons.append("No keyword bank in the profile: skill match is a neutral baseline")
    return reasons
