"""Fit 3 domain (A1.2 of ~/holojob-eval/w5-plan.md): the ad's industry against the candidate's industries, by synonym. No model, no matcher status.

The synonym table is the 1.x one (src/data/domainAdjacency.json: each domain has a label and markers). Ad industries come from the ad text
(domain_transfer.ad_domains, the 1.x rule) and from llmFacts.domain; the candidate's industries come from the stored fields the 1.x industry
dimension reads (historyEntries[].domains, jobFitPreferences.preferredIndustries) and experienceMap.domainsWorkedIn. Read locally, never sent.

match = the sets intersect; different = both sets non-empty and no overlap; otherwise unknown (which moves nothing).
Adjacency edges are capability bridges, not synonyms: they play no part here.
"""

from __future__ import annotations

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


def candidate_industries(intelligence: dict | None) -> set[str]:
    intel = intelligence or {}
    out = {d for e in intel.get("historyEntries") or [] if isinstance(e, dict) for d in e.get("domains") or [] if d in DOMAINS}
    for text in (intel.get("jobFitPreferences") or {}).get("preferredIndustries") or []:
        out |= domains_in_text(text if isinstance(text, str) else None)
    for text in (intel.get("experienceMap") or {}).get("domainsWorkedIn") or []:
        out |= domains_in_text(text if isinstance(text, str) else None)
    return out


def compare(ad: set[str] | None, candidate: set[str] | None) -> tuple[str, list[str]]:
    """(match | different | unknown, the shared domain ids)."""
    ad, candidate = set(ad or ()), set(candidate or ())
    shared = sorted(ad & candidate)
    if shared:
        return "match", shared
    return ("different" if ad and candidate else "unknown"), []
