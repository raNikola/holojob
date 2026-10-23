"""Job scoring orchestrator."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dimensions.culture_match import score_culture_match
from dimensions.experience_match import score_experience_match
from dimensions.industry_match import score_industry_match
from dimensions.location_match import score_location_match
from dimensions.role_match import score_role_match
from dimensions.skill_match import score_skill_match
from labels import apply_recommendation, match_label, priority
from llm_enhancer import NoOpEnhancer
from red_flags import detect_red_flags
from corpus import build_idf
import work_authorization as wa

# The one set of default weights, shared with the UI's settings panel and the
# intelligence generator (src/modules/intelligence/candidateIntelligenceEngine.js).
WEIGHTS_FILE = Path(__file__).resolve().parents[2] / "src" / "data" / "scoringWeights.json"
DEFAULT_WEIGHTS = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))


def resolve_weights(saved: dict | None) -> dict:
    """The saved weights, each missing or malformed key filled from the defaults."""
    saved = saved if isinstance(saved, dict) else {}
    return {
        key: saved[key]
        if isinstance(saved.get(key), (int, float)) and not isinstance(saved.get(key), bool) and saved[key] >= 0
        else fallback
        for key, fallback in DEFAULT_WEIGHTS.items()
    }

# The ad's day-to-day work, as read from its own words. A delivery or
# programme role wearing a product title is not a weaker match -- it is the
# wrong job, so it is capped in code rather than argued down by weights.
ACCEPTABLE_TRACKS = {"product_management", "product_ownership"}
OFF_TRACK_CAP = 50

# A job the candidate may not legally take, or that sits outside the locations
# they chose, is capped the same way: never hidden, never argued down by
# weights. Statuses come from work_authorization.py; these numbers are what
# each costs. 25 is Reject (the ad refuses sponsorship); 45 is Weak and stays
# reviewable (the ad is silent, and many employers sponsor when asked); 40 is
# a location the candidate excluded themselves. Sponsored, authorized and
# unknown are not capped.
WORK_AUTHORIZATION_CAPS = {
    wa.NEEDS_VISA_REFUSED: 25,
    wa.OUTSIDE_ALLOWED: 40,
    wa.NEEDS_VISA_SILENT: 45,
}


def _weighted_total(dimensions: dict[str, int], weights: dict[str, int]) -> int:
    total_w = sum(weights.values()) or 100
    score = sum(dimensions[k] * weights.get(k, 0) for k in dimensions) / total_w
    return int(round(score))


def score_job(job: dict, intelligence: dict, enhancer=None, idf=None) -> dict:
    weights = resolve_weights(intelligence.get("scoringWeights"))
    enhancer = enhancer or NoOpEnhancer()

    role_score, role_reasons = score_role_match(job, intelligence)
    skill_score, skill_reasons, matched, missing = score_skill_match(job, intelligence, idf)
    industry_score, industry_reasons = score_industry_match(job, intelligence)
    exp_score, exp_reasons = score_experience_match(job, intelligence)
    loc_score, loc_reasons = score_location_match(job, intelligence)
    cult_score, cult_reasons = score_culture_match(job, intelligence)

    dimensions = {
        "roleMatch": role_score,
        "skillMatch": skill_score,
        "industryMatch": industry_score,
        "experienceMatch": exp_score,
        "locationMatch": loc_score,
        "cultureMatch": cult_score,
    }

    red_flags = detect_red_flags(job, intelligence)
    match_score = _weighted_total(dimensions, weights)

    if red_flags and match_score > 55:
        match_score = min(match_score, 54)

    track = (job.get("llmFacts") or {}).get("roleTrack")
    off_track = bool(track) and track not in ACCEPTABLE_TRACKS
    if off_track:
        match_score = min(match_score, OFF_TRACK_CAP)

    authorization = wa.authorization_status(job, intelligence.get("jobFitPreferences") or {})
    authorization_cap = WORK_AUTHORIZATION_CAPS.get(authorization["status"])
    if authorization_cap is not None:
        match_score = min(match_score, authorization_cap)

    breakdown = {
        k: {
            "raw": dimensions[k],
            "weight": weights.get(k, 0),
            "weighted": round(dimensions[k] * weights.get(k, 0) / 100, 2),
        }
        for k in dimensions
    }

    reasons = role_reasons + skill_reasons + industry_reasons + exp_reasons + loc_reasons + cult_reasons
    if off_track:
        reasons.append(f"Capped: the ad describes {track}, not a product role")
    if red_flags:
        reasons.extend([f"Red flag: {f}" for f in red_flags])
    if authorization_cap is not None:
        reasons.append(f"Capped: {authorization['reason']}")
    elif authorization["status"] in (wa.SPONSORED, wa.UNKNOWN):
        reasons.append(f"Work authorization: {authorization['reason']}")

    apply_rec = apply_recommendation(match_score, red_flags)
    result = {
        **job,
        "matchScore": match_score,
        "matchLabel": match_label(match_score),
        "applyRecommendation": apply_rec,
        "priority": priority(match_score, apply_rec, red_flags),
        "roleMatch": role_score,
        "skillMatch": skill_score,
        "industryMatch": industry_score,
        "experienceMatch": exp_score,
        "locationMatch": loc_score,
        "cultureMatch": cult_score,
        "matchedSkills": matched,
        "missingSkills": missing,
        "redFlags": red_flags,
        "reasons": reasons,
        "scoreBreakdown": breakdown,
        "workAuthorization": authorization,
        # True when a hard rule applies to the job, whether or not it lowered
        # this particular score. The enhancer never lifts such a job, so caps
        # stay decided here.
        "hardCapped": bool(red_flags) or off_track or authorization_cap is not None,
    }
    return enhancer.enhance(job, result, intelligence)


def score_jobs(
    jobs: list[dict], intelligence: dict, enhancer=None, workers: int = 8
) -> list[dict]:
    # Term rarity is measured over this run's corpus, so it is built once and
    # shared by every job rather than recomputed per call.
    idf = build_idf(jobs)
    if enhancer is None or isinstance(enhancer, NoOpEnhancer):
        return [score_job(j, intelligence, enhancer, idf) for j in jobs]

    # An enhancer that calls a model waits on the network per job, so jobs are
    # scored in parallel. map() keeps the input order.
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(lambda j: score_job(j, intelligence, enhancer, idf), jobs))
