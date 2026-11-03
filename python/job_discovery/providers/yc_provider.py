"""Y Combinator Work at a Startup jobs API provider."""

from __future__ import annotations

import logging

import requests

from providers.base_provider import (
    JobProvider,
    ProviderOutcome,
    build_canonical_job,
    dropped_ad,
    filter_jobs,
    split_by_filter,
)

logger = logging.getLogger(__name__)

API_URL = "https://www.workatastartup.com/api/jobs"


class YCProvider(JobProvider):
    provider_name = "yc"

    def _fetch_all(self) -> list[dict]:
        """The postings; raises when they cannot be read."""
        resp = requests.get(API_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("jobs", data.get("data")) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ValueError("the answer has no list of postings")
        return rows

    def fetch_jobs(
        self,
        search_terms: list[str],
        locations: list[str],
        remote_filters: list[str],
        country: str,
    ) -> list[dict]:
        primary_term = search_terms[0] if search_terms else ""
        primary_loc = locations[0] if locations else ""
        all_jobs: list[dict] = []
        external: dict = {}
        dropped: list[dict] = []

        try:
            postings = self._fetch_all()
        except Exception as exc:
            logger.warning("YC jobs fetch failed: %s", exc)
            self.last_outcome = ProviderOutcome(status="failed", error=str(exc))
            return []

        for posting in postings:
            title = posting.get("title") or posting.get("role") or ""
            company_info = posting.get("company") or {}
            if isinstance(company_info, dict):
                company = company_info.get("name") or company_info.get("slug") or "YC Startup"
            else:
                company = str(company_info) or "YC Startup"
            location = posting.get("location") or posting.get("city") or "Unspecified"
            url = posting.get("url") or posting.get("apply_url") or posting.get("link") or ""
            description = posting.get("description") or posting.get("snippet") or ""

            job = build_canonical_job(
                provider="yc",
                source="workatastartup",
                title=title,
                company=company,
                location=str(location),
                job_url=url,
                description=description,
                is_remote="remote" in str(location).lower(),
                search_term=primary_term,
                search_location=primary_loc,
                site="workatastartup",
            )
            if job["title"]:
                all_jobs.append(job)
                external[job["jobId"]] = posting.get("id")
            else:  # never counted as read
                dropped.append(dropped_ad(job, "no_title", posting.get("id"), counted=False))

        kept = filter_jobs(all_jobs, search_terms, locations, remote_filters, country)
        _, filtered_out = split_by_filter(all_jobs, search_terms, locations, remote_filters, country)
        dropped += [dropped_ad(job, reason, external.get(job["jobId"])) for job, reason in filtered_out]
        # One HTTP response: nothing to stream, so the whole result is staged once, here.
        self.stage(kept, part="all", read=len(all_jobs), external_ids=external, dropped=dropped)
        self.last_outcome = ProviderOutcome(read=len(all_jobs), kept=len(kept))
        return kept
