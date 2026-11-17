"""Extraction facts of a shape the scorer does not know are no facts.

`llmFacts` is a cache written by another step and read back from files the owner can restore, merge or edit. A value of
an unexpected type must stop here: scoring it would turn a broken cache into a confident wrong fact (a visa refusal, a
role track). Nothing is repaired or guessed; a row whose facts fail the check is scored as an ad that was not extracted.
"""

from __future__ import annotations

_STR_OR_NONE = ("visaEvidence", "jobCountry", "workModeEvidence", "roleTrackEvidence", "domain")
_STR = ("visaSponsorship", "roleTrack", "workMode", "seniority")
_LISTS = ("requirements", "remoteEligibility", "mustHaves", "niceToHaves", "listingFlags")
VISA_VALUES = {"offered", "not_offered", "not_mentioned"}


def facts_shape_ok(facts) -> bool:
    """True for a non-empty dict whose known fields have the types the extraction step writes."""
    if not isinstance(facts, dict) or not facts:
        return False
    for key in _STR_OR_NONE:
        if facts.get(key) is not None and not isinstance(facts[key], str):
            return False
    for key in _STR:
        if key in facts and not isinstance(facts[key], str):
            return False
    for key in _LISTS:
        if key in facts and not isinstance(facts[key], list):
            return False
    if facts.get("visaSponsorship") is not None and facts["visaSponsorship"] not in VISA_VALUES:
        return False
    return all(isinstance(r, dict) for r in facts.get("requirements") or [])


def guard_job(job: dict) -> dict:
    """The job itself when its facts are usable or absent; a copy without `llmFacts` when they are of an unknown shape."""
    if "llmFacts" not in job or not job["llmFacts"] or facts_shape_ok(job["llmFacts"]):
        return job
    return {k: v for k, v in job.items() if k != "llmFacts"}
