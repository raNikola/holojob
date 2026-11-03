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
    ProviderOutcome,
    build_canonical_job,
    dropped_ad,
    place_drop_reason,
)

logger = logging.getLogger(__name__)


class WorkableProvider(JobProvider):
    provider_name = "workable"

    def fetch_jobs(
        self,
        search_terms: list[str],
        locations: list[str],
        remote_filters: list[str],
        country: str,
    ) -> list[dict]:
        terms = tuple(search_terms or ("Product Manager",))
        counts: dict = {}
        canonical: list[dict] = []

        def keep_as_it_comes(term: str, added: list[dict], dropped: list) -> None:
            # One search term is one request: its ads are staged before the next term. The same objects are returned below.
            jobs = [self._to_canonical(raw) for raw in added]
            canonical.extend(jobs)
            external = {job["jobId"]: raw.get("externalId") for job, raw in zip(jobs, added)}
            kept, out = [], [
                dropped_ad(self._to_canonical(raw), reason, raw.get("externalId"), counted=counted)
                for raw, reason, counted in dropped
            ]
            for job in jobs:
                reason = place_drop_reason(job, locations, remote_filters, country)
                if reason is None:
                    kept.append(job)
                else:
                    out.append(dropped_ad(job, reason, external.get(job["jobId"])))
            self.stage(kept, part=term, external_ids=external, dropped=out)

        try:
            raw_jobs = workable_client.fetch_jobs(terms, location=country, counts=counts, on_batch=keep_as_it_comes)
        except Exception as exc:
            logger.exception("Workable fetch failed; continuing without it")
            self.last_outcome = ProviderOutcome(status="failed", error=str(exc))
            return []

        logger.info("Workable: %d relevant ads before geo filtering", len(raw_jobs))

        jobs = canonical if len(canonical) == len(raw_jobs) else [self._to_canonical(job) for job in raw_jobs]
        kept = [
            job
            for job in jobs
            if place_drop_reason(job, locations, remote_filters, country) is None
        ]
        logger.info("Workable: %d jobs after geo filtering", len(kept))
        self.last_outcome = ProviderOutcome(read=counts.get("read", len(raw_jobs)), kept=len(kept))
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