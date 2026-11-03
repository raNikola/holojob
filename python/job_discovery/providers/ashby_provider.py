"""Ashby public job board API provider."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import requests

from providers.base_provider import JobProvider, build_canonical_job, dropped_ad, filter_jobs, parts_outcome, split_by_filter

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[3] / "companies" / "ashby.json"
API_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


class AshbyProvider(JobProvider):
    provider_name = "ashby"

    def _load_companies(self) -> list[str]:
        if not CONFIG_PATH.exists():
            return []
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return [c for c in data if isinstance(c, str) and c.strip()]

    def _fetch_company(self, slug: str) -> list[dict]:
        """The board's postings; raises when it cannot be read, since an empty list means the board is empty."""
        resp = requests.get(API_URL.format(slug=slug), params={"includeCompensation": "true"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            raise ValueError("the answer has no jobs list")
        return jobs

    def _format_salary(self, compensation: dict | None) -> str:
        if not compensation:
            return ""
        summary = compensation.get("compensationTierSummary") or compensation.get("scrapeableCompensationSalarySummary")
        if summary:
            return str(summary)
        min_val = compensation.get("minValue")
        max_val = compensation.get("maxValue")
        if min_val or max_val:
            return f"{min_val or ''}-{max_val or ''}".strip("-")
        return ""

    def _normalize_posting(
        self,
        posting: dict,
        slug: str,
        search_term: str,
        search_location: str,
    ) -> dict:
        if posting.get("isListed") is False:
            return {}

        location = posting.get("location") or "Unspecified"
        if isinstance(location, dict):
            location = location.get("name") or str(location)
        workplace = posting.get("workplaceType") or posting.get("locationType") or ""
        is_remote = bool(
            re.search(r"\bremote\b", str(location), re.I)
            or str(workplace).lower() == "remote"
        )

        return build_canonical_job(
            provider="ashby",
            source=slug,
            title=posting.get("title") or "",
            company=posting.get("companyName") or slug.replace("-", " ").title(),
            location=str(location),
            job_url=posting.get("jobUrl") or posting.get("applyUrl") or "",
            description=posting.get("descriptionPlain") or posting.get("description") or "",
            salary=self._format_salary(posting.get("compensation")),
            is_remote=is_remote,
            date_posted=str(posting.get("publishedAt") or posting.get("updatedAt") or ""),
            search_term=search_term,
            search_location=search_location,
        )

    def fetch_jobs(
        self,
        search_terms: list[str],
        locations: list[str],
        remote_filters: list[str],
        country: str,
    ) -> list[dict]:
        companies = self._load_companies()
        all_jobs: list[dict] = []
        primary_term = search_terms[0] if search_terms else ""
        primary_loc = locations[0] if locations else ""
        failures: dict[str, str] = {}
        empty: list[str] = []

        for slug in companies:
            try:
                postings = self._fetch_company(slug)
            except Exception as exc:
                logger.warning("Ashby company %s failed: %s", slug, exc)
                failures[slug] = str(exc)
                continue
            if not postings:
                empty.append(slug)
            board_jobs, external, dropped = [], {}, []
            for posting in postings:
                job = self._normalize_posting(posting, slug, primary_term, primary_loc)
                if job and job.get("title"):
                    board_jobs.append(job)
                    external[job["jobId"]] = posting.get("id")
                else:  # never counted as read: a posting the board has taken down, or one with no title
                    reason = "not_listed" if posting.get("isListed") is False else "no_title"
                    row = {"title": posting.get("title"), "company": slug, "location": posting.get("location"),
                           "jobUrl": posting.get("jobUrl") or posting.get("applyUrl")}
                    dropped.append(dropped_ad(row, reason, posting.get("id"), counted=False))
            all_jobs.extend(board_jobs)
            # The board is staged as soon as it is read (filtered the way the whole list is below), so a stop keeps it.
            board_kept, board_dropped = split_by_filter(board_jobs, search_terms, locations, remote_filters, country)
            self.stage(
                board_kept, part=slug, read=len(board_jobs), external_ids=external,
                dropped=dropped + [dropped_ad(job, reason, external.get(job["jobId"])) for job, reason in board_dropped],
            )

        kept = filter_jobs(all_jobs, search_terms, locations, remote_filters, country)
        self.last_outcome = parts_outcome(
            read=len(all_jobs), kept=len(kept), total=len(companies), failures=failures, empty=empty
        )
        return kept
