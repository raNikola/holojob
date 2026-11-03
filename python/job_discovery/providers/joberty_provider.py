"""Joberty provider -- an opt-in source: Serbian and regional IT ads.

An opt-in source (source_definitions.py): in no provider group, and it runs only
while the owner has switched it on, with consent, in Settings > Sources
(data/config/sources.json, enforced by run_discovery.py whatever the request
says). The board's API is undocumented and its terms restrict commercial and
unauthorized use (sections 7 and 8), see joberty_client.py.

Role filtering is on the title (is_relevant_role). The board's own
"Product Management" domain is only used to narrow the listing: it also holds
ads such as "Implementation Manager", so it is not trusted as a role match.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from providers import joberty_client
from providers.base_provider import (
    JobProvider,
    ProviderOutcome,
    _geography,
    build_canonical_job,
    matches_country,
    matches_location_filters,
)
from providers.role_filter import is_relevant_role
from providers.workable_client import _strip_html

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
JOB_URL = "https://www.joberty.com/sr/job/{company}/{slug}/{job_id}"

# The ledger module, loaded by path as run_discovery does (its siblings would shadow this package's).
_history_spec = importlib.util.spec_from_file_location(
    "_joberty_job_history", ROOT / "python" / "job_scoring" / "job_history.py"
)
job_history = importlib.util.module_from_spec(_history_spec)
_history_spec.loader.exec_module(job_history)


def default_ledger_path() -> Path:
    return job_history.ledger_path(ROOT / "data" / "jobs" / "discovered_jobs.json")


def _slug(text: str) -> str:
    folded = unicodedata.normalize("NFKD", (text or "").replace("đ", "dj").replace("Đ", "Dj"))
    ascii_text = "".join(c for c in folded if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def job_url(item: dict) -> str:
    """The ad's public page; built from fields that do not change, so the jobId stays stable."""
    return JOB_URL.format(
        company=item.get("companyUrlName") or "",
        slug=_slug(item.get("jobTitle") or ""),
        job_id=item.get("id"),
    )


def supported_countries(cities: list[str]) -> tuple[set[str], set[str]]:
    """(country codes, folded names) the board lists ads in, read from its city facet."""
    codes: set[str] = set()
    names: set[str] = set()
    for value in cities:
        codes.update(_geography.resolve_countries(value))
        for part in re.split(r"[()]", value):
            if part.strip():
                names.add(_geography._fold(part))
    return codes, names


def country_supported(country: str, cities: list[str]) -> bool:
    if not (country or "").strip():
        return False
    codes, names = supported_countries(cities)
    code = _geography.country_of_name(country)
    return code in codes if code else _geography._fold(country) in names


def known_ids(ledger_path: Path | None = None) -> set[str]:
    """JobIds the ledger already holds with a real description: their detail is not fetched again."""
    path = ledger_path or default_ledger_path()
    try:
        entries = job_history.load(path, read_only=True)["jobs"]  # a scrape never renames a ledger it cannot read
    except OSError:
        return set()
    return {
        job_id
        for job_id, entry in entries.items()
        if len((((entry or {}).get("job") or {}).get("description") or "").strip())
        >= job_history.THIN_DESCRIPTION_CHARS
    }


def _expires(item: dict) -> str:
    millis = item.get("expirationDate")
    if not isinstance(millis, (int, float)):
        return ""
    # The board stamps local midnight (23:00 UTC the evening before), so half a day is added
    # to land on the calendar date without hard-coding a timezone.
    return datetime.fromtimestamp(millis / 1000 + 12 * 3600, tz=timezone.utc).date().isoformat()


def to_canonical(item: dict, detail: dict | None = None, *, country: str = "") -> dict:
    """Map a listing item (and, when read, its detail) onto the pipeline's job shape."""
    detail = detail or {}
    cities = [c.strip() for c in item.get("cities") or [] if isinstance(c, str) and c.strip()]
    job = build_canonical_job(
        provider="joberty",
        source="joberty",
        site="joberty",
        title=(item.get("jobTitle") or "").strip(),
        company=(item.get("companyName") or "").strip(),
        location="; ".join(cities),
        job_url=job_url(item),
        description=_strip_html(detail.get("text") or ""),
        is_remote=any(c.lower().startswith("remote") for c in cities),
        search_location=country,
    )
    job["domains"] = item.get("domains") or []
    job["technologies"] = item.get("technologies") or []
    job["seniority"] = item.get("seniority") or ""
    job["applyUrl"] = detail.get("applyUrl") or ""
    job["expiresAt"] = _expires(item)
    job["externalId"] = f"joberty:{item.get('id')}"
    return job


class JobertyProvider(JobProvider):
    provider_name = "joberty"

    def __init__(self, ledger_path: Path | None = None):
        self.ledger_path = ledger_path

    def fetch_jobs(
        self,
        search_terms: list[str],
        locations: list[str],
        remote_filters: list[str],
        country: str,
    ) -> list[dict]:
        try:
            return self._fetch(search_terms, locations, remote_filters, country)
        except Exception as exc:
            logger.exception("Joberty fetch failed; continuing without it")
            self.last_outcome = ProviderOutcome(status="failed", error=str(exc))
            return []

    def _fetch(self, search_terms, locations, remote_filters, country) -> list[dict]:
        cities = joberty_client.fetch_cities()
        if not cities:  # the board always lists places, so none means they could not be read, not "not this country"
            logger.warning("Joberty's place list could not be read; not searched")
            self.last_outcome = ProviderOutcome(status="failed", error="Joberty's place list could not be read")
            return []
        if not country_supported(country, cities):
            logger.info("Joberty has no ads for country=%r -- skipping", country)
            self.last_outcome = ProviderOutcome(status="skipped", skip_reason=f"Joberty lists no ads for {country!r}")
            return []

        terms = tuple(search_terms or ())
        wanted: dict[int, dict] = {}
        read: set[int] = set()
        for item in joberty_client.fetch_listing():
            if not isinstance(item.get("id"), int) or item["id"] in wanted:
                continue
            read.add(item["id"])
            job = to_canonical(item, country=country)
            if (
                is_relevant_role(job["title"], "", terms)
                and matches_location_filters(job, locations, remote_filters)
                and matches_country(job, country)
            ):
                wanted[item["id"]] = item
        logger.info("Joberty: %d relevant ads in the listing", len(wanted))

        known = known_ids(self.ledger_path)
        jobs: list[dict] = []
        fetched = 0
        deferred = 0
        for item in wanted.values():
            if to_canonical(item)["jobId"] in known:
                # No description: the ledger restores the one it holds (job_history.apply_run).
                jobs.append(to_canonical(item, country=country))
                continue

            if fetched >= joberty_client.MAX_DETAILS:
                deferred += 1  # an ad with no description is no use; it is read next run
                continue
            fetched += 1
            detail = joberty_client.fetch_detail(item["id"])
            if detail.get("text"):
                jobs.append(to_canonical(item, detail, country=country))
        if deferred:
            logger.info("Joberty: %d ads left for the next run (cap of %d details)", deferred, joberty_client.MAX_DETAILS)
        logger.info("Joberty: %d jobs (%d details read)", len(jobs), fetched)
        self.last_outcome = ProviderOutcome(
            read=len(read),
            kept=len(jobs),
            warnings=[f"{deferred} ads left for the next run (cap of {joberty_client.MAX_DETAILS} details)"] if deferred else [],
        )
        return jobs
