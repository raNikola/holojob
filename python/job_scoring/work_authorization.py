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

import re

from dimensions.location_match import is_remote_job
from geography import REMOTE, WORLDWIDE, country_of_name, covers, resolve_countries
from location_text import VERIFY_FLAG, read_location

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

    Onsite or hybrid: every country the board's location names (an ad can list
    many offices), else the country the model read.
    Remote: where the ad says a hire may live, which is often nowhere at all.
    """
    facts = job.get("llmFacts") or {}
    if is_remote_job(job):
        return True, [str(p).upper() for p in facts.get("remoteEligibility") or [] if p]
    countries = resolve_countries(job.get("location") or "")
    if not countries and facts.get("jobCountry"):
        countries = [facts["jobCountry"]]
    return False, countries


_REMOTE_WORDS = {"remote", "fully remote", "remote work", "work from home", "home office", "wfh"}


def sole_board_country(job: dict) -> str | None:
    """The one country the board's location names, when it names nothing else onsite.

    "Germany" and "Germany; Remote" give DE. "Berlin, Germany" (an office city),
    "Remote - Europe" (a region) and "Amsterdam, Netherlands; Remote - Europe"
    (a city plus a remote option) give None: only a bare country is a restriction
    the ad itself states. Two countries give None as well.
    """
    location = job.get("location") or ""
    countries = resolve_countries(location)
    if len(countries) != 1:
        return None
    for part in (p.strip() for p in re.split(r"[,;|/()]", location)):
        if part and part.lower() not in _REMOTE_WORDS and not country_of_name(part) \
                and not (part.isupper() and resolve_countries(part)):
            return None
    return countries[0]


def outside_allowed_before_enrichment(job: dict, prefs: dict) -> bool:
    """True when the board's own data already puts the job outside the candidate's places.

    Decidable without reading the ad: the job is not remote by the board, and
    its location names countries, none of them inside allowedLocations. Scoring
    reaches the same OUTSIDE_ALLOWED status from the same fields, so reading
    such an ad only to cap it afterwards is a wasted model call. An empty
    allowedLocations gates nothing, and an ad whose country is unknown is not
    known to be outside.
    """
    allowed = [str(a).upper() for a in prefs.get("allowedLocations") or [] if a]
    if not allowed:
        return False
    bare = {k: v for k, v in job.items() if k != "llmFacts"}
    # An ad whose own words are remote or open to a region is read by scoring (location_text).
    if read_location(bare, allowed, is_remote_job(bare)):
        return False
    remote, places = job_places(bare)
    restricted = [p for p in places if p != WORLDWIDE]
    if remote or not restricted:
        return False
    return not any(covers(a, p) for a in allowed if a != REMOTE for p in restricted)


def authorization_status(job: dict, prefs: dict) -> dict:
    """{"status", "place", "reason"} for one job against the candidate's rights."""
    facts = job.get("llmFacts") or {}
    remote, places = job_places(job)
    # The candidate's own location set, only when they chose to set one.
    allowed = [str(a).upper() for a in prefs.get("allowedLocations") or [] if a]
    location = read_location(job, allowed, remote) if allowed else None
    state = location["state"] if location else None
    board_country = sole_board_country(job)
    if remote and not places and board_country and state != "pass":
        # Remote by the board, no stated eligibility, and the board names one bare country: the hire lives there.
        # An ad that states a geography itself (open worldwide, from Serbia) is read by location_text instead.
        places = [board_country]
    elif state in ("pass", "unknown") and not remote:
        # Remote by the ad's own words: the board's office city is not where the work is done.
        # One board country stays when the ad names no geography ("unknown"): the office is still a legal place.
        remote = True
        if not (state == "unknown" and len(resolve_countries(job.get("location") or "")) == 1):
            places = []
    restricted = [p for p in places if p != WORLDWIDE]
    shown = "/".join(restricted[:3]) + (f" +{len(restricted) - 3} more" if len(restricted) > 3 else "")
    place = "remote" if remote and not restricted else shown or "unknown"

    def result(status: str, reason: str) -> dict:
        found = {"status": status, "place": place, "reason": reason}
        if location:
            found["location"] = {k: location[k] for k in ("state", "flag", "quote", "reason")}
        return found

    if allowed:
        if location and location["state"] == "fail":
            # The ad's stated geography is outside the places taken. A refused visa is stricter and stays.
            refused = _visa_result(facts, prefs, restricted, result, place)
            return refused if refused and refused["status"] == NEEDS_VISA_REFUSED else result(OUTSIDE_ALLOWED, location["reason"])
        if remote:
            inside = REMOTE in allowed
        elif restricted:
            inside = any(covers(a, p) for a in allowed if a != REMOTE for p in restricted)
        else:
            inside = True  # an unknown place is not known to be outside
        if not inside:
            return result(OUTSIDE_ALLOWED, f"{place} is outside the locations you will take a job in")

    holds = _holds(prefs)
    if not holds:
        return result(UNKNOWN, "work authorization is not set in the profile, so the visa was not checked")
    if not restricted:
        if remote:
            if location and location["state"] == "unknown":
                return result(AUTHORIZED, f"{VERIFY_FLAG}: {location['reason']}")
            return result(AUTHORIZED, "remote with no restriction on where you live")
        return result(UNKNOWN, "the job's country is not known, so the visa was not checked")
    if any(covers(right, p) for right in holds for p in restricted):
        where = next(p for p in restricted if any(covers(right, p) for right in holds))
        return result(AUTHORIZED, f"you can work in {where}")

    return _visa_result(facts, prefs, restricted, result, place)


def _visa_result(facts, prefs, restricted, result, place="unknown"):
    """The status once a work permit is needed for every restricted place, or None when one is held."""
    holds = _holds(prefs)
    if not holds or not restricted or any(covers(right, p) for right in holds for p in restricted):
        return None
    sponsorship = facts.get("visaSponsorship") or "not_mentioned"
    open_to_sponsorship = bool((prefs.get("workAuthorization") or {}).get("openToSponsorship"))
    if sponsorship == "offered":
        if open_to_sponsorship:
            return result(SPONSORED, f"needs a work permit for {place}; the ad offers sponsorship")
        return result(NEEDS_VISA_REFUSED, f"needs a work permit for {place}; you are not open to sponsored roles")
    if sponsorship == "not_offered":
        return result(NEEDS_VISA_REFUSED, f"needs a work permit for {place} and the ad does not sponsor one")
    return result(NEEDS_VISA_SILENT, f"needs a work permit for {place}; the ad does not mention sponsorship")
