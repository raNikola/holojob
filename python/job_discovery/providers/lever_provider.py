"""Lever public postings API provider."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import requests

from providers.base_provider import JobProvider, board_read, build_canonical_job, dropped_ad, filter_jobs, parts_outcome, split_by_filter

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

    def __init__(self) -> None:
        self._answered_at: dict[str, str] = {}

    def _end_of_list(self, company: str, read: int) -> tuple[bool, str | None]:
        """Complete only if asking past what was read returns an empty list (S5b): one extra request, on the host that answered.
        Never raises: a check that cannot be made leaves the board unproven and costs the run nothing."""
        url = self._answered_at.get(company)
        if not url:
            return False, "the end of the list was not checked"
        try:
            resp = requests.get(url, params={"mode": "json", "skip": read, "limit": 1}, timeout=30)
            resp.raise_for_status()
            rest = resp.json()
        except Exception as exc:  # noqa: BLE001 - see the docstring
            return False, f"the end-of-list request failed ({type(exc).__name__})"
        if not isinstance(rest, list):
            return False, "the end-of-list request did not answer with a list"
        return (True, None) if not rest else (False, f"the end-of-list request returned postings past the {read} read")

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
                self._answered_at[company] = url
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
        boards_read: list[dict] = []

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
            # An empty board is not complete whatever this says (parts_outcome), so it costs no extra request.
            complete, why = self._end_of_list(company, len(postings)) if postings else (False, None)
            boards_read.append(board_read(company, read=len(board_jobs), postings=len(postings), complete=complete, reason=why, endChecked=bool(postings)))

        kept = filter_jobs(all_jobs, search_terms, locations, remote_filters, country)
        self.last_outcome = parts_outcome(
            read=len(all_jobs), kept=len(kept), total=len(companies), failures=failures, empty=empty, boards_read=boards_read
        )
        return kept
