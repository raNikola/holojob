"""Can the candidate legally take this job, and if not, does the ad offer a way?

The model reports facts about the ad (where the role is based, where a remote
hire may live, what the ad says about visa sponsorship). This module combines
them with the candidate's own work rights into one status. scorer.py decides
what each status costs; nothing here hides a job.

Every input comes from the candidate or the ad. With no work rights in the
profile, or no country for the job, the status is unknown and nothing is
capped: an assumption here would cost the candidate a job they never saw.
"""

from __future__ import annotations

from dimensions.location_match import is_remote_job
from geography import REMOTE, WORLDWIDE, covers, resolve_country

AUTHORIZED = "authorized"
SPONSORED = "sponsored"
NEEDS_VISA_REFUSED = "needs_visa_refused"
NEEDS_VISA_SILENT = "needs_visa_silent"
OUTSIDE_ALLOWED = "outside_allowed"
UNKNOWN = "unknown"


def _holds(prefs: dict) -> list[str]:
    auth = prefs.get("workAuthorization") or {}
    return [
        str(h.get("jurisdiction")).upper()
        for h in auth.get("holds") or []
        if isinstance(h, dict) and h.get("jurisdiction")
    ]


def job_places(job: dict) -> tuple[bool, list[str]]:
    """(remote, places): where the work is legally done.

    Onsite or hybrid: the board's location, else the country the model read.
    Remote: where the ad says a hire may live, which is often nowhere at all.
    """
    facts = job.get("llmFacts") or {}
    if is_remote_job(job):
        return True, [str(p).upper() for p in facts.get("remoteEligibility") or [] if p]
    country = resolve_country(job.get("location") or "") or facts.get("jobCountry")
    return False, [country] if country else []


def authorization_status(job: dict, prefs: dict) -> dict:
    """{"status", "place", "reason"} for one job against the candidate's rights."""
    facts = job.get("llmFacts") or {}
    remote, places = job_places(job)
    restricted = [p for p in places if p != WORLDWIDE]
    place = "remote" if remote and not restricted else "/".join(restricted) or "unknown"

    def result(status: str, reason: str) -> dict:
        return {"status": status, "place": place, "reason": reason}

    # The candidate's own location set, only when they chose to set one.
    allowed = [str(a).upper() for a in prefs.get("allowedLocations") or [] if a]
    if allowed:
        if remote:
            inside = REMOTE in allowed
        elif restricted:
            inside = any(covers(a, restricted[0]) for a in allowed if a != REMOTE)
        else:
            inside = True  # an unknown place is not known to be outside
        if not inside:
            return result(OUTSIDE_ALLOWED, f"{place} is outside the locations you will take a job in")

    holds = _holds(prefs)
    if not holds:
        return result(UNKNOWN, "work authorization is not set in the profile, so the visa was not checked")
    if not restricted:
        if remote:
            return result(AUTHORIZED, "remote with no restriction on where you live")
        return result(UNKNOWN, "the job's country is not known, so the visa was not checked")
    if any(covers(right, p) for right in holds for p in restricted):
        return result(AUTHORIZED, f"you can work in {place}")

    sponsorship = facts.get("visaSponsorship") or "not_mentioned"
    open_to_sponsorship = bool((prefs.get("workAuthorization") or {}).get("openToSponsorship"))
    if sponsorship == "offered":
        if open_to_sponsorship:
            return result(SPONSORED, f"needs a work permit for {place}; the ad offers sponsorship")
        return result(NEEDS_VISA_REFUSED, f"needs a work permit for {place}; you are not open to sponsored roles")
    if sponsorship == "not_offered":
        return result(NEEDS_VISA_REFUSED, f"needs a work permit for {place} and the ad does not sponsor one")
    return result(NEEDS_VISA_SILENT, f"needs a work permit for {place}; the ad does not mention sponsorship")
