"""RemoteOK public JSON API provider."""

from __future__ import annotations

import logging

import requests

from providers.base_provider import JobProvider, ProviderOutcome, build_canonical_job, filter_jobs

logger = logging.getLogger(__name__)

API_URL = "https://remoteok.com/api"


class RemoteOKProvider(JobProvider):
    provider_name = "remoteok"

    def _fetch_all(self) -> list[dict]:
        """The postings; raises when they cannot be read."""
        resp = requests.get(
            API_URL,
            headers={"User-Agent": "CareerOS/1.0"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError("the answer is not a list of postings")
        return [item for item in data if isinstance(item, dict) and item.get("position")]

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

        try:
            postings = self._fetch_all()
        except Exception as exc:
            logger.warning("RemoteOK fetch failed: %s", exc)
            self.last_outcome = ProviderOutcome(status="failed", error=str(exc))
            return []

        for posting in postings:
            title = posting.get("position") or posting.get("title") or ""
            company = posting.get("company") or "Unknown"
            location = posting.get("location") or "Remote"
            url = posting.get("url") or posting.get("apply_url") or ""
            description = posting.get("description") or ""
            tags = posting.get("tags") or []
            if tags and not description:
                description = "Tags: " + ", ".join(str(t) for t in tags)

            job = build_canonical_job(
                provider="remoteok",
                source="remoteok",
                title=title,
                company=company,
                location=location,
                job_url=url,
                description=description,
                salary=posting.get("salary") or "",
                is_remote=True,
                date_posted=str(posting.get("date") or posting.get("epoch") or ""),
                search_term=primary_term,
                search_location=primary_loc,
                site="remoteok",
            )
            if job["title"]:
                all_jobs.append(job)

        kept = filter_jobs(all_jobs, search_terms, locations, remote_filters, country)
        self.last_outcome = ProviderOutcome(read=len(all_jobs), kept=len(kept))
        return kept
