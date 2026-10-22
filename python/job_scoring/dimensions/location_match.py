"""Location and remote match dimension.

Scores are deliberately far apart. For a candidate who will not relocate,
an onsite role in the wrong city is not a weaker match -- it is unusable.

Work mode is known precisely only for sources that report it (Infostud,
Workable). JobSpy exposes isRemote alone, so a non-remote LinkedIn ad may
still be hybrid; it is penalised, but less than a confirmed onsite role.
"""

from __future__ import annotations

from text_utils import normalize_text

REMOTE_PREFERRED = 95
REMOTE = 85
PREFERRED_PLACE = 90
HYBRID_ELSEWHERE = 55
UNKNOWN_LOCATION = 50
# Work mode unknown, so the ad could still be an office. A named city says
# where that office is -- for a candidate in Nis anywhere else is unusable --
# so it keeps the lower score. A bare country names no office at all, and
# boards (Workable, LinkedIn) use it for roles open to the whole country, so
# it is weaker evidence of an office and scores higher. It stays under
# UNKNOWN_LOCATION (50): an ad that at least says "Serbia" is no better than
# one that says nothing, and well under REMOTE (85), which is confirmed.
NOT_REMOTE_UNKNOWN_MODE = 35
COUNTRY_ONLY_UNKNOWN_MODE = 45
ONSITE_ELSEWHERE = 15

COUNTRIES = frozenset({"serbia", "srbija"})


def _country_only(location: str) -> bool:
    """True when every part of the location is a country, e.g. "Serbia"."""
    parts = [p.strip() for p in location.split(",") if p.strip()]
    return bool(parts) and all(p in COUNTRIES for p in parts)


def score_location_match(job: dict, intelligence: dict) -> tuple[int, list[str]]:
    prefs = intelligence.get("jobFitPreferences") or {}
    preferred = [normalize_text(p) for p in prefs.get("preferredLocations") or []]
    places = [p for p in preferred if p and p != "remote"]
    remote_pref = normalize_text(prefs.get("remotePreference") or "")

    job_loc = normalize_text(job.get("location") or "")

    # The board's own field first; where it left the mode unset, the fact the
    # LLM read out of the ad itself. "unclear" stays unknown rather than
    # becoming a guess -- most ads genuinely do not say.
    work_mode = normalize_text(job.get("workMode") or "")
    if not work_mode or work_mode == "unclear":
        extracted = normalize_text((job.get("llmFacts") or {}).get("workMode") or "")
        work_mode = extracted if extracted != "unclear" else ""

    is_remote = bool(job.get("isRemote")) or work_mode == "remote"

    if is_remote:
        if "remote" in remote_pref or "flexible" in remote_pref:
            return REMOTE_PREFERRED, ["Remote, matches stated preference"]
        return REMOTE, ["Remote"]

    for place in places:
        if place in job_loc:
            return PREFERRED_PLACE, [f"Located in {place}"]

    if work_mode == "hybrid":
        return HYBRID_ELSEWHERE, ["Hybrid outside preferred locations"]

    if not job_loc:
        return UNKNOWN_LOCATION, ["Location not stated"]

    if work_mode in ("onsite", "fieldwork"):
        return ONSITE_ELSEWHERE, [f"Onsite in {job_loc}, relocation required"]

    if _country_only(job_loc):
        return COUNTRY_ONLY_UNKNOWN_MODE, [
            f"Not remote, country only ({job_loc}); work mode unknown"
        ]

    return NOT_REMOTE_UNKNOWN_MODE, [f"Not remote, in {job_loc}; work mode unknown"]