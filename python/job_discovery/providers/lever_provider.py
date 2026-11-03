"""Lever public postings API provider."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import requests

from providers.base_provider import JobProvider, build_canonical_job, dropped_ad, filter_jobs, parts_outcome, split_by_filter

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[3] / "companies" / "lever.json"
API_URL = "https://api.lever.co/v0/postings/{company}"
# A company on Lever's EU-hosted instance 404s on the main API; its own
# hosted board (jobs.eu.lever.co) names api.eu.lever.co as the primary and
# api.lever.co as the fallback, so this provider tries both, in that order.
EU_API_URL = "https://api.eu.lever.co/v0/postings/{company}"


class LeverProvider(JobProvider):
    provider_name = "lever"

    def _load_companies(self) -> list[str]:
        if not CONFIG_PATH.exists():
            return []
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return [c for c in data if isinstance(c, str) and c.strip()]

    def _fetch_company(self, company: str) -> list[dict]:
        """The board's postings; raises when neither host can read it, since an empty list means the board is empty."""
        last_error: Exception = LookupError("404 on both Lever hosts")
        for url in (API_URL.format(company=company), EU_API_URL.format(company=company)):
            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    raise ValueError("the answer is not a list of postings")
                return data
            except Exception as exc:
                logger.warning("Lever company %s failed on %s: %s", company, url, exc)
                last_error = exc
        raise last_error

    def _normalize_posting(
        self,
        posting: dict,
        company: str,
        search_term: str,
        search_location: str,
    ) -> dict:
        categories = posting.get("categories") or {}
        location = categories.get("location") or posting.get("workplaceType") or "Unspecified"
        if isinstance(location, list):
            location = ", ".join(location)

        commitment = categories.get("commitment") or ""
        is_remote = bool(
            re.search(r"\bremote\b", str(location), re.I)
            or str(posting.get("workplaceType", "")).lower() == "remote"
        )

        return build_canonical_job(
            provider="lever",
            source=company,
            title=posting.get("text") or "",
            company=posting.get("company") or company.title(),
            location=str(location),
            job_url=posting.get("hostedUrl") or posting.get("applyUrl") or "",
            description=posting.get("descriptionPlain") or posting.get("description") or "",
            employment_type=str(commitment),
            is_remote=is_remote,
            date_posted=str(posting.get("createdAt") or ""),
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

        for company in companies:
            try:
                postings = self._fetch_company(company)
            except Exception as exc:
                logger.warning("Lever company %s failed: %s", company, exc)
                failures[company] = str(exc)
                continue
            if not postings:
                empty.append(company)
            board_jobs, external, dropped = [], {}, []
            for posting in postings:
                job = self._normalize_posting(posting, company, primary_term, primary_loc)
                if job["title"]:
                    board_jobs.append(job)
                    external[job["jobId"]] = posting.get("id")
                else:  # never counted as read
                    dropped.append(dropped_ad(job, "no_title", posting.get("id"), counted=False))
            all_jobs.extend(board_jobs)
            # The board is staged as soon as it is read (filtered the way the whole list is below), so a stop keeps it.
            board_kept, board_dropped = split_by_filter(board_jobs, search_terms, locations, remote_filters, country)
            self.stage(
                board_kept, part=company, read=len(board_jobs), external_ids=external,
                dropped=dropped + [dropped_ad(job, reason, external.get(job["jobId"])) for job, reason in board_dropped],
            )

        kept = filter_jobs(all_jobs, search_terms, locations, remote_filters, country)
        self.last_outcome = parts_outcome(
            read=len(all_jobs), kept=len(kept), total=len(companies), failures=failures, empty=empty
        )
        return kept
