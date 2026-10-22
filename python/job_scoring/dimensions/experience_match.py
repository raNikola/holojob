"""Experience and seniority match dimension.

Seniority is taken from what the ad says, not from its title. The previous
version read titles against a ladder that mapped "manager" to a lead level,
so every "Product Manager" came out one step above a senior candidate and the
dimension returned the same number for almost every job.

Where the extraction pass has read the ad (llmFacts), its stated seniority
and years are used. The title ladder is the fallback, and it no longer treats
role nouns as levels.
"""

from __future__ import annotations

import re

from text_utils import normalize_text

LEVELS = {"junior": 1, "mid": 2, "senior": 3, "lead": 4, "head": 5}

# Title words that genuinely signal a level. "Manager", "owner" and
# "engineer" are deliberately absent: they name the job, not its seniority.
TITLE_LEVELS = {
    "intern": 0,
    "graduate": 1,
    "entry": 1,
    "junior": 1,
    "associate": 2,
    "mid": 2,
    "senior": 3,
    "sr": 3,
    "staff": 4,
    "lead": 4,
    "principal": 5,
    "head": 5,
    "director": 5,
    "vp": 6,
    "chief": 6,
}

NEUTRAL = 65
FLOOR = 20
CEILING = 100


def _title_level(title: str) -> int | None:
    text = normalize_text(title)
    found = [
        level
        for word, level in TITLE_LEVELS.items()
        if re.search(rf"\b{re.escape(word)}\b", text)
    ]
    return max(found) if found else None


def _candidate_profile(intelligence: dict) -> tuple[int, int]:
    exp_map = intelligence.get("experienceMap") or {}
    summary = intelligence.get("candidateSummary") or {}

    match = re.search(r"\d+", str(exp_map.get("yearsOfExperience") or ""))
    years = int(match.group()) if match else 5

    stated = normalize_text(summary.get("seniorityLevel") or "")
    level = next((v for k, v in LEVELS.items() if k in stated), 0)
    if not level:
        level = 3 if years >= 5 else 2
    # Someone a decade in is at least senior, whatever the profile says.
    if years >= 8:
        level = max(level, 3)
    return level, years


def _level_score(job_level: int, candidate_level: int, source: str) -> tuple[int, str]:
    gap = job_level - candidate_level
    if gap == 0:
        return 92, f"Seniority matches ({source})"
    if gap == 1:
        return 78, f"One level above the candidate ({source})"
    if gap == -1:
        return 80, f"One level below the candidate ({source})"
    if gap >= 2:
        return 42, f"Pitched {gap} levels above the candidate ({source})"
    return 50, f"Pitched {abs(gap)} levels below the candidate ({source})"


def score_experience_match(job: dict, intelligence: dict) -> tuple[int, list[str]]:
    candidate_level, candidate_years = _candidate_profile(intelligence)
    facts = job.get("llmFacts") or {}

    stated = (facts.get("seniority") or "").strip().lower()
    job_level = LEVELS.get(stated)
    source = "ad"
    if job_level is None:
        job_level = _title_level(job.get("title") or "")
        source = "title"

    reasons: list[str] = []

    if job_level is None:
        score = NEUTRAL
        reasons.append("Seniority not stated")
    else:
        score, reason = _level_score(job_level, candidate_level, source)
        reasons.append(reason)

    required = facts.get("yearsRequired")
    if isinstance(required, int):
        if required > candidate_years + 1:
            score -= 25
            reasons.append(f"Asks for {required} years against {candidate_years}")
        elif required <= 3 and candidate_years >= 8:
            # Not a disqualifier, but a junior brief usually pays like one.
            score -= 10
            reasons.append(f"Asks for only {required} years")
        else:
            score += 5
            reasons.append(f"Meets the stated {required} years")

    return max(FLOOR, min(CEILING, int(score))), reasons