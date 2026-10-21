"""Skill match dimension.

Two signals, blended.

The keyword bank says what the candidate brings. Matching is per token, with
crude singularisation, because banks are written as polished phrases
("Cross-functional Leadership") while ads say "cross-functional teams".
Each keyword is weighted by how rare its tokens are across this run's jobs,
so "Product Management" -- in nearly every listing -- earns almost nothing.

The must-haves say what this particular ad demands. They come from the
extraction pass, so they exist only after enrich_jobs.py has run; without
them the bank score stands alone. Their coverage is the more decision-useful
of the two, and what they leave uncovered is what a tailored resume has to
answer.
"""

from __future__ import annotations

from corpus import flat_idf
from text_utils import term_tokens

HIGH_WEIGHT = 3
MEDIUM_WEIGHT = 2
SUPPORTING_WEIGHT = 1

MIN_COVERAGE = 0.5

# Share of the achievable keyword mass a strong match is expected to cover.
TARGET_COVERAGE = 0.22

# A token this common across the corpus carries no information about fit, so
# it is dropped from requirement matching rather than diluting it.
GENERIC_IDF_FLOOR = 0.25

# How much of the final score the ad's own requirements carry, when it has any.
MUST_HAVE_SHARE = 0.5

FLOOR = 20
CEILING = 100


def _bank(intelligence: dict) -> tuple[list[str], list[str], list[str]]:
    bank = intelligence.get("atsKeywordBank") or {}
    high = [k for k in (bank.get("highPriority") or []) if k]
    medium = [k for k in (bank.get("mediumPriority") or []) if k]
    supporting = [k for k in (bank.get("supportingKeywords") or []) if k]

    if not (high or medium or supporting):
        skills_map = intelligence.get("skillsMap") or {}
        flat: list[str] = []
        for value in skills_map.values():
            if isinstance(value, list):
                flat.extend(v for v in value if v)
        medium = flat

    return high, medium, supporting


def _candidate_tokens(intelligence: dict) -> set[str]:
    """Every term the candidate can evidence, flattened into tokens."""
    parts: list[str] = []

    for section in ("skillsMap", "atsKeywordBank"):
        container = intelligence.get(section) or {}
        for value in container.values():
            if isinstance(value, list):
                parts.extend(str(v) for v in value if v)

    for key in ("resumeKeywords", "candidateStrengths"):
        parts.extend(str(v) for v in (intelligence.get(key) or []) if v)

    experience = intelligence.get("experienceMap") or {}
    for key in ("domainsWorkedIn", "projectHighlights", "ownershipExamples"):
        parts.extend(str(v) for v in (experience.get(key) or []) if v)

    return term_tokens(" ".join(parts))


def _credit(keywords, weight, jd_tokens, idf):
    """Return (earned credit, keywords that cleared MIN_COVERAGE, achievable)."""
    earned = 0.0
    achievable = 0.0
    hits: list[str] = []

    for keyword in keywords:
        kw_tokens = term_tokens(keyword)
        if not kw_tokens:
            continue
        rarity = sum(idf(token) for token in kw_tokens) / len(kw_tokens)
        achievable += weight * rarity

        coverage = len(kw_tokens & jd_tokens) / len(kw_tokens)
        if coverage >= MIN_COVERAGE:
            earned += weight * rarity * coverage
            hits.append(keyword)

    return earned, hits, achievable


def _must_have_score(must_haves, candidate_tokens, idf):
    """Score the candidate against this ad's own stated requirements.

    Returns (score, covered, uncovered) or (None, [], []) when the ad listed
    nothing usable -- a requirement made only of corpus-generic words says
    nothing either way.
    """
    earned = 0.0
    achievable = 0.0
    covered: list[str] = []
    uncovered: list[str] = []

    for requirement in must_haves:
        tokens = {t for t in term_tokens(requirement) if idf(t) >= GENERIC_IDF_FLOOR}
        if not tokens:
            continue
        weight = sum(idf(token) for token in tokens) / len(tokens)
        achievable += weight

        coverage = len(tokens & candidate_tokens) / len(tokens)
        earned += weight * coverage
        if coverage >= MIN_COVERAGE:
            covered.append(requirement)
        else:
            uncovered.append(requirement)

    if achievable <= 0:
        return None, [], []

    ratio = min(1.0, earned / achievable)
    return FLOOR + (CEILING - FLOOR) * ratio, covered, uncovered


def score_skill_match(
    job: dict, intelligence: dict, idf=None
) -> tuple[int, list[str], list[str], list[str]]:
    idf = idf or flat_idf
    high, medium, supporting = _bank(intelligence)
    if not (high or medium or supporting):
        return 50, ["No keyword bank in intelligence"], [], []

    jd_tokens = term_tokens(f"{job.get('title', '')} {job.get('description', '')}")
    if not jd_tokens:
        return FLOOR, ["Empty job description"], [], []

    high_earned, high_hits, high_max = _credit(high, HIGH_WEIGHT, jd_tokens, idf)
    med_earned, med_hits, med_max = _credit(medium, MEDIUM_WEIGHT, jd_tokens, idf)
    sup_earned, sup_hits, sup_max = _credit(
        supporting, SUPPORTING_WEIGHT, jd_tokens, idf
    )

    earned = high_earned + med_earned + sup_earned
    target = (high_max + med_max + sup_max) * TARGET_COVERAGE
    bank_ratio = min(1.0, earned / target) if target > 0 else 0.0
    bank_score = FLOOR + (CEILING - FLOOR) * bank_ratio

    reasons = [
        f"Keyword coverage: {len(high_hits)}/{len(high)} high, "
        f"{len(med_hits)}/{len(medium)} medium, "
        f"{len(sup_hits)}/{len(supporting)} supporting"
    ]
    matched = high_hits + med_hits + sup_hits
    missing = [k for k in high if k not in high_hits]

    must_haves = (job.get("llmFacts") or {}).get("mustHaves") or []
    must_score, covered, uncovered = _must_have_score(
        must_haves, _candidate_tokens(intelligence), idf
    )

    score = bank_score
    if must_score is not None:
        reasons.append(
            f"Stated requirements, token overlap: "
            f"{len(covered)}/{len(covered) + len(uncovered)}"
        )

    return int(round(score)), reasons, matched[:20], missing[:15]