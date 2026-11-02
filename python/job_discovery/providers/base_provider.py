"""Base provider interface and shared helpers."""

from __future__ import annotations

import importlib.util
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from normalize_jobs import _make_job_id

# The scorer's geography table, loaded by path so its sibling modules do not
# shadow this package's. It is reference data about the world, shared with the
# UI, and it is how "Europe" or "United States" is told from a job's location.
_GEOGRAPHY_FILE = Path(__file__).resolve().parents[2] / "job_scoring" / "geography.py"
_spec = importlib.util.spec_from_file_location("_discovery_geography", _GEOGRAPHY_FILE)
_geography = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_geography)

logger = logging.getLogger(__name__)


@dataclass
class ProviderOutcome:
    """How a fetch went, beside the jobs it returned. run_discovery passes boards_failed and boards_empty to the ledger,
    so ads of an unread or empty board are not taken for ads that were removed, and the rest to the run log.

    read: ads parsed before the search, role and location filters. kept: the ones returned.
    An unsupported country and a source not built yet are status ok with read 0, explained in warnings.
    """

    status: str = "ok"  # ok, partial (some boards or feeds failed) or failed (nothing could be read)
    read: int = 0
    kept: int = 0
    error: str | None = None
    boards_failed: list[str] = field(default_factory=list)
    boards_empty: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parts_outcome(
    *, read: int, kept: int, total: int, failures: dict[str, str], empty: list[str] | None = None, named: bool = True
) -> ProviderOutcome:
    """The outcome of a fetch made of several parts (boards, feeds, searches). `failures` maps a part to its error;
    `named` says the parts are boards or feeds, which the record lists by name."""
    status = "ok"
    if failures:
        status = "failed" if len(failures) >= total else "partial"
    return ProviderOutcome(
        status=status,
        read=read,
        kept=kept,
        error="; ".join(f"{part}: {error}" for part, error in failures.items()) or None,
        boards_failed=list(failures) if named else [],
        boards_empty=list(empty or []),
        warnings=[f"board {board} answered with 0 ads; its open ads were kept" for board in empty or []],
    )


class JobProvider(ABC):
    provider_name = "base"
    # Set by every fetch_jobs; a provider that forgets fails its run-log row instead of reporting a guess.
    last_outcome: ProviderOutcome | None = None

    @abstractmethod
    def fetch_jobs(
        self,
        search_terms: list[str],
        locations: list[str],
        remote_filters: list[str],
        country: str,
    ) -> list[dict]:
        raise NotImplementedError


def build_canonical_job(
    *,
    provider: str,
    source: str,
    title: str,
    company: str,
    location: str,
    job_url: str = "",
    description: str = "",
    salary: str = "",
    employment_type: str = "",
    is_remote: bool = False,
    date_posted: str = "",
    search_term: str = "",
    search_location: str = "",
    scraped_at: str | None = None,
    site: str = "",
) -> dict:
    scraped = scraped_at or datetime.now(timezone.utc).isoformat()
    site_val = site or source
    return {
        "jobId": _make_job_id(job_url, title, company, location),
        "provider": provider,
        "source": source,
        "title": title,
        "company": company,
        "location": location,
        "site": site_val,
        "jobUrl": job_url,
        "description": description,
        "datePosted": date_posted,
        "salary": salary,
        "employmentType": employment_type,
        "isRemote": is_remote,
        "searchTerm": search_term,
        "searchLocation": search_location,
        "scrapedAt": scraped,
        "status": "new",
    }


def _normalize_terms(terms: list[str]) -> list[str]:
    return [t.strip().lower() for t in terms if t and t.strip()]


def _normalize_locations(locations: list[str]) -> list[str]:
    return [loc.strip().lower() for loc in locations if loc and loc.strip()]


def matches_search_terms(job: dict, search_terms: list[str]) -> bool:
    terms = _normalize_terms(search_terms)
    if not terms:
        return True
    haystack = f"{job.get('title', '')} {job.get('description', '')}".lower()
    return any(term in haystack for term in terms)


def in_searched_place(job: dict, locations: list[str]) -> bool:
    """Whether the job is in a country or region the search locations name.

    The locations are the candidate's own search places: a region such as
    "Europe" or "United States" is among them only when the profile says they
    would relocate there. A job in such a place is wanted, so it is never
    dropped for being outside the run's home country.
    """
    wanted = {
        code
        for loc in locations or []
        if (loc or "").strip().lower() != "remote"
        for code in _geography.place_codes(loc)
    }
    if not wanted:
        return False
    return any(
        _geography.covers(code, country)
        for code in wanted
        for country in _geography.resolve_countries(job.get("location") or "")
    )


def matches_location_filters(job: dict, locations: list[str], remote_filters: list[str]) -> bool:
    locs = _normalize_locations(locations)
    if not locs:
        return True

    job_loc = (job.get("location") or "").lower()
    is_remote = bool(job.get("isRemote"))
    remote_in_filters = any(f.lower() == "remote" for f in remote_filters)
    wants_remote = "remote" in locs or remote_in_filters

    if wants_remote and is_remote:
        return True

    non_remote_locs = [loc for loc in locs if loc != "remote"]
    if not non_remote_locs:
        return wants_remote and is_remote

    return any(loc in job_loc or job_loc in loc for loc in non_remote_locs) or in_searched_place(job, locations)


def matches_country(job: dict, country: str) -> bool:
    if not country:
        return True
    country_lower = country.strip().lower()
    job_loc = (job.get("location") or "").lower()
    aliases = {
        "europe": ["europe", "european union", "eu", "emea", "cet", "cest"],
        "usa": ["usa", "us", "united states", "san francisco", "new york", "seattle", "austin"],
        "serbia": ["serbia", "srbija", "belgrade", "beograd", "novi sad", "niš", "nis", "kragujevac", "subotica", "europe", "emea", "cet", "cest"],
    }
    tokens = aliases.get(country_lower, [country_lower])
    if any(token in job_loc for token in tokens):
        return True
    if job.get("isRemote"):
        return True
    return not job_loc


def filter_jobs(
    jobs: list[dict],
    search_terms: list[str],
    locations: list[str],
    remote_filters: list[str],
    country: str = "Serbia",
) -> list[dict]:
    kept = [
        job
        for job in jobs
        if matches_search_terms(job, search_terms)
        and matches_location_filters(job, locations, remote_filters)
        and (matches_country(job, country) or in_searched_place(job, locations))
    ]
    # "0 jobs" is two different results: nothing was fetched (a broken or empty
    # board), or everything fetched was filtered out. The log says which.
    logger.info("%d postings fetched, %d kept after search, location and country filters", len(jobs), len(kept))
    return kept
