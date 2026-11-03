"""Infostud provider -- coverage of the Serbian domestic job market.

LinkedIn, via JobSpy, carries international and remote roles but very little
of what Serbian employers post locally. Infostud is where those ads live.

Role filtering happens in infostud_client, not through filter_jobs(). The
client matches on Infostud's hand-assigned standardizedPosition, which
catches ads whose title never spells out the role -- "Customer Channels AI
Product and Delivery Expert" is tagged Product Manager by the board itself.
Running matches_search_terms() on top would discard exactly those.
"""

from __future__ import annotations

import logging

from providers import infostud_client
from providers.base_provider import (
    JobProvider,
    ProviderOutcome,
    build_canonical_job,
    matches_country,
    matches_location_filters,
)

logger = logging.getLogger(__name__)

SUPPORTED_COUNTRIES = {"serbia", "srbija"}


class InfostudProvider(JobProvider):
    provider_name = "infostud"

    def fetch_jobs(
        self,
        search_terms: list[str],
        locations: list[str],
        remote_filters: list[str],
        country: str,
    ) -> list[dict]:
        if (country or "").strip().lower() not in SUPPORTED_COUNTRIES:
            logger.info(
                "Infostud covers Serbia only -- skipping for country=%r", country
            )
            self.last_outcome = ProviderOutcome(status="skipped", skip_reason=f"Infostud covers Serbia only, not {country!r}")
            return []

        counts: dict = {}
        canonical: list[dict] = []

        def keep_as_it_comes(raw: dict) -> None:
            # An ad is final once its full description is read, and that is one slow request per ad, so it is staged
            # here, not at the end. The same object is returned below, so what is staged is what the run gets.
            job = self._to_canonical(raw)
            canonical.append(job)
            if matches_location_filters(job, locations, remote_filters) and matches_country(job, country):
                self.stage([job], part=job["jobId"])

        try:
            raw_jobs = infostud_client.fetch_jobs(
                extra_terms=tuple(search_terms or ()),
                counts=counts,
                on_job=keep_as_it_comes,
            )
        except Exception as exc:
            logger.exception("Infostud fetch failed; continuing without it")
            self.last_outcome = ProviderOutcome(status="failed", error=str(exc))
            return []

        logger.info("Infostud: %d relevant ads before geo filtering", len(raw_jobs))

        jobs = canonical if len(canonical) == len(raw_jobs) else [self._to_canonical(job) for job in raw_jobs]
        kept = [
            job
            for job in jobs
            if matches_location_filters(job, locations, remote_filters)
            and matches_country(job, country)
        ]
        logger.info("Infostud: %d jobs after geo filtering", len(kept))
        self.last_outcome = ProviderOutcome(
            read=counts.get("read", len(raw_jobs)), kept=len(kept), total_reported=counts.get("reported")
        )
        return kept

    @staticmethod
    def _to_canonical(job: dict) -> dict:
        canonical = build_canonical_job(
            provider="infostud",
            source="infostud",
            site="infostud",
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            job_url=job.get("jobUrl", ""),
            description=job.get("description", ""),
            salary=job.get("salary") or "",
            employment_type=job.get("employmentType") or "",
            is_remote=bool(job.get("isRemote")),
            date_posted=job.get("datePosted") or "",
            search_location="Serbia",
        )
        # Infostud-specific context the canonical shape has no slot for.
        canonical["workMode"] = job.get("workMode")
        canonical["expiresAt"] = job.get("expiresAt")
        canonical["category"] = job.get("category")
        canonical["standardizedPosition"] = job.get("standardizedPosition")
        canonical["tags"] = job.get("tags") or []
        return canonical