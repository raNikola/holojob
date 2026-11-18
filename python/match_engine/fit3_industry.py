"""Fit 3 domain (A1.2 of ~/holojob-eval/w5-plan.md): the ad's industry against the candidate's industries, by synonym. No model, no matcher status.

The synonym table is the 1.x one (src/data/domainAdjacency.json: each domain has a label and markers). Ad industries come from the ad text
(domain_transfer.ad_domains, the 1.x rule) and from llmFacts.domain; the candidate's industries are the CONFIRMED ones only (A2.4: historyEntries[].domains and experienceMap.domainsWorkedIn; preferredIndustries is a
display field and never counts). Read locally, never sent.

match = the sets intersect (always valid); different = no overlap, the ad set non-empty and the candidate set COMPLETE (every history entry carries a table
domain); otherwise unknown (which moves nothing).
Adjacency edges are capability bridges, not synonyms: they play no part here.
"""

from __future__ import annotations

from typing import NamedTuple

import domain_transfer
from text_utils import normalize_text

DOMAINS = domain_transfer.ADJACENCY["domains"]


def domains_in_text(text: str | None) -> set[str]:
    """The table domains a short free text names: its label or any marker, word-bounded."""
    norm = normalize_text(text or "")
    if not norm:
        return set()
    return {d for d, spec in DOMAINS.items()
            if any(domain_transfer._has(norm, term) for term in [normalize_text(spec["label"]), *spec["markers"]])}


def ad_industries(posting: dict, facts: dict | None) -> set[str]:
    found = domain_transfer.ad_domains(posting.get("title") or "", posting.get("description") or "", posting.get("company") or "")
    value = (facts or {}).get("domain")
    return found | domains_in_text(value if isinstance(value, str) else None)


class Industries(NamedTuple):
    """The candidate's industries as Fit 3 reads them (A2.4). `confirmed` = table domains of the history entries and of experienceMap.domainsWorkedIn;
    `complete` = every history entry carries at least one table domain (Claude's own proposal); `preferred` = preferredIndustries, DISPLAY ONLY."""
    confirmed: frozenset = frozenset()
    complete: bool = False
    preferred: frozenset = frozenset()


def candidate_industries(intelligence: dict | None) -> Industries:
    intel = intelligence or {}
    entries = [e for e in intel.get("historyEntries") or [] if isinstance(e, dict)]
    from_history = [{d for d in e.get("domains") or [] if d in DOMAINS} for e in entries]
    confirmed = set().union(*from_history) if from_history else set()
    for text in (intel.get("experienceMap") or {}).get("domainsWorkedIn") or []:
        confirmed |= domains_in_text(text if isinstance(text, str) else None)
    preferred = set()
    for text in (intel.get("jobFitPreferences") or {}).get("preferredIndustries") or []:
        preferred |= domains_in_text(text if isinstance(text, str) else None)
    return Industries(frozenset(confirmed), bool(entries) and all(from_history), frozenset(preferred))


def compare(ad: set[str] | None, candidate: Industries | None) -> tuple[str, list[str]]:
    """(match | different | unknown, the shared domain ids). match is always valid; different needs a non-empty ad set and a COMPLETE candidate set."""
    ad = set(ad or ())
    candidate = candidate or Industries()
    shared = sorted(ad & candidate.confirmed)
    if shared:
        return "match", shared
    return ("different" if ad and candidate.confirmed and candidate.complete else "unknown"), []
