"""Location and remote match dimension.

Scores are deliberately far apart. For a candidate who will not move, an
onsite role in the wrong city is not a weaker match -- it is unusable.

Work mode is known precisely only for sources that report it (Infostud,
Workable). JobSpy exposes isRemote alone, so a non-remote LinkedIn ad may
still be hybrid; it is penalised, but less than a confirmed onsite role.

Whether the candidate may legally work somewhere is not scored here: that is
work_authorization.py, applied as a cap in scorer.py. This dimension only asks
whether they can get to the work, from where they live or by relocating.
"""

from __future__ import annotations

from geography import country_of_name, resolve_country
from text_utils import normalize_text

REMOTE_PREFERRED = 95
REMOTE = 85
PREFERRED_PLACE = 90
# Onsite or hybrid somewhere the candidate said they would relocate to. Below
# remote and their own cities, above a commute they did not choose.
RELOCATION_ACCEPTABLE = 60
HYBRID_ELSEWHERE = 55
UNKNOWN_LOCATION = 50
# Work mode unknown, so the ad could still be an office. A named city says
# where that office is -- anywhere but the candidate's own cities is unusable
# -- so it keeps the lower score. A bare country names no office at all, and
# boards (Workable, LinkedIn) use it for roles open to the whole country, so
# it is weaker evidence of an office and scores higher. It stays under
# UNKNOWN_LOCATION (50): an ad that at least names a country is no better than
# one that says nothing, and well under REMOTE (85), which is confirmed.
NOT_REMOTE_UNKNOWN_MODE = 35
COUNTRY_ONLY_UNKNOWN_MODE = 45
ONSITE_ELSEWHERE = 15

RELOCATION_POLICIES = ("none", "abroad", "anywhere")

# Boards spell the same mode differently (Workable sends "on_site").
_MODE_SPELLINGS = {"on_site": "onsite", "on-site": "onsite", "on site": "onsite", "in_office": "onsite"}


def job_work_mode(job: dict) -> str:
    """The board's own work mode first; where it left it unset, the mode the
    model read out of the ad. "unclear" stays unknown rather than becoming a
    guess -- most ads genuinely do not say."""
    work_mode = normalize_text(job.get("workMode") or "")
    if not work_mode or work_mode in ("unclear", "unknown"):
        extracted = normalize_text((job.get("llmFacts") or {}).get("workMode") or "")
        work_mode = extracted if extracted != "unclear" else ""
    return _MODE_SPELLINGS.get(work_mode, work_mode)


def is_remote_job(job: dict) -> bool:
    return bool(job.get("isRemote")) or job_work_mode(job) == "remote"


def _country_only(location: str) -> bool:
    """True when every part of the location is a country, e.g. "Serbia"."""
    parts = [p.strip() for p in location.split(",") if p.strip()]
    return bool(parts) and all(country_of_name(p) for p in parts)


def _relocation_allows(job: dict, prefs: dict) -> bool:
    """Whether the candidate said they would move for a job where this one is."""
    policy = prefs.get("relocation") or "none"
    if policy == "anywhere":
        return True
    if policy != "abroad":
        return False
    home = resolve_country(prefs.get("country") or "")
    there = resolve_country(job.get("location") or "") or (job.get("llmFacts") or {}).get("jobCountry")
    # Unknown on either side is not "abroad": the candidate's own country stays
    # under the commute rules.
    return bool(home and there and there != home)


def score_location_match(job: dict, intelligence: dict) -> tuple[int, list[str]]:
    prefs = intelligence.get("jobFitPreferences") or {}
    preferred = [normalize_text(p) for p in prefs.get("preferredLocations") or []]
    # A commute place is a city. A country there ("Serbia") would match every
    # office in it, so countries are never treated as places to commute to.
    places = [p for p in preferred if p and p != "remote" and not country_of_name(p)]
    remote_pref = normalize_text(prefs.get("remotePreference") or "")

    job_loc = normalize_text(job.get("location") or "")
    work_mode = job_work_mode(job)

    if is_remote_job(job):
        if "remote" in remote_pref or "flexible" in remote_pref:
            return REMOTE_PREFERRED, ["Remote, matches stated preference"]
        return REMOTE, ["Remote"]

    for place in places:
        if place in job_loc:
            return PREFERRED_PLACE, [f"Located in {place}"]

    if job_loc and _relocation_allows(job, prefs):
        return RELOCATION_ACCEPTABLE, [f"In {job_loc}; you are open to relocating there"]

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
