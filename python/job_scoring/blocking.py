"""Blocking facts: what makes an ad one the candidate cannot take (Step 2b, scoringVersion 1.5, no score change).

A blocked ad keeps its Fit number and stays visible; only the verdict (Apply / priority) reads this. Each blocker is a fact
the profile already expresses:

  sponsorship_refused  eligibility.py state "sponsorship_refused" (a refusing quote found in the ad, or a right to work required outside
                       the authorized countries; B2B wording keeps it unknown)
  language             the ad REQUIRES a language the profile does not list (language_gap_names: required demands only; nice-to-have never)
  location             the ad names a place outside the profile's allowedLocations, or states a geography outside them

Location is a state: "in" / "outside" / "unknown" (None when the profile sets no allowedLocations: dormant). A bare "Remote" with no
country is not country evidence: unknown, never "in", never "outside". The profile has no on-site exclusion field of its own;
allowedLocations is its only place list, so a place outside it is the only location fact used.
"""

from __future__ import annotations

import eligibility
import work_authorization as wa
from geography import REMOTE, covers

IN, OUTSIDE, UNKNOWN = "in", "outside", "unknown"


def location_state(job: dict, prefs: dict) -> dict | None:
    """{"state": in|outside|unknown, "reason"} against allowedLocations, or None when the profile sets none."""
    found = wa.resolve_places(job, prefs)
    allowed, restricted, loc, remote = found["allowed"], found["restricted"], found["location"], found["remote"]
    if not allowed:
        return None
    countries = [a for a in allowed if a != REMOTE]
    if loc and loc["state"] == "fail":
        return {"state": OUTSIDE, "reason": loc["reason"]}
    if restricted:
        if any(covers(a, p) for a in countries for p in restricted):
            return {"state": IN, "reason": f"{found['place']} is inside the locations you will take a job in"}
        if not (remote and REMOTE in allowed):
            return {"state": OUTSIDE, "reason": f"{found['place']} is outside the locations you will take a job in"}
        return {"state": UNKNOWN, "reason": f"remote, limited to {found['place']}: the ad does not say a hire may live in your places"}
    if loc and loc["state"] == "pass":
        return {"state": IN, "reason": loc["reason"]}
    return {"state": UNKNOWN, "reason": "the ad names no country, so the location was not checked"}


def blockers(eligible: dict | None, language_names: list[str], location: dict | None) -> list[dict]:
    """The blocking facts of one ad as [{"kind", "text"}]; [] when none."""
    out = []
    if eligible and eligible["state"] == eligibility.REFUSED:
        out.append({"kind": "sponsorship_refused", "text": eligible["reason"]})
    if language_names:
        out.append({"kind": "language", "text": f"the ad requires {' and '.join(language_names)}, which your profile does not list"})
    if location and location["state"] == OUTSIDE:
        out.append({"kind": "location", "text": location["reason"]})
    return out
