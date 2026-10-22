"""Workable provider -- remote and hybrid roles open to Serbia.

Workable hosts applicant tracking for a large number of companies and
publishes them on one public board. The value here is remote-EU postings
that accept Serbian candidates, which LinkedIn surfaces unreliably.

As with Infostud, role filtering happens in the client rather than through
filter_jobs(), so matches_search_terms() is not applied on top.
"""

from __future__ import annotations

import logging

from providers import workable_client
from providers.base_provider import (
    JobProvider,
    build_canonical_job,
    matches_country,
    matches_location_filters,
)

logger = logging.getLogger(__name__)


class WorkableProvider(JobProvider):
    provider_name = "workable"

    def fetch_jobs(
        self,
        search_terms: list[str],
        locations: list[str],
        remote_filters: list[str],
        country: str = "Serbia",
    ) -> list[dict]:
        terms = tuple(search_terms or ("Product Manager",))
        try:
            raw_jobs = workable_client.fetch_jobs(terms, location=country or "Serbia")
        except Exception:
            logger.exception("Workable fetch failed; continuing without it")
            return []

        logger.info("Workable: %d relevant ads before geo filtering", len(raw_jobs))

        jobs = [self._to_canonical(job) for job in raw_jobs]
        kept = [
            job
            for job in jobs
            if matches_location_filters(job, locations, remote_filters)
            and matches_country(job, country)
        ]
        logger.info("Workable: %d jobs after geo filtering", len(kept))
        return kept

    @staticmethod
    def _to_canonical(job: dict) -> dict:
        canonical = build_canonical_job(
            provider="workable",
            source="workable",
            site="workable",
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            job_url=job.get("jobUrl", ""),
            description=job.get("description", ""),
            employment_type=job.get("employmentType") or "",
            is_remote=bool(job.get("isRemote")),
            date_posted=job.get("datePosted") or "",
            search_location=job.get("location", ""),
        )
        canonical["workMode"] = job.get("workMode")
        return canonical