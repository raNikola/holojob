"""JobSpy provider — wraps existing jobspy_adapter + normalize_jobs."""

from __future__ import annotations

import logging

import pandas as pd

from jobspy_adapter import fetch_jobs
from normalize_jobs import normalize_jobs
from providers.base_provider import JobProvider, parts_outcome
from providers.role_filter import is_relevant_role

logger = logging.getLogger(__name__)


def _should_use_remote(remote_filters: list[str], location: str) -> bool:
    loc = (location or "").lower()
    if loc == "remote":
        return True
    filters = [f.lower() for f in remote_filters]
    return "remote" in filters and loc == "remote"


class JobSpyProvider(JobProvider):
    provider_name = "jobspy"

    def __init__(self) -> None:
        self._last_raw_df: pd.DataFrame = pd.DataFrame()

    def fetch_jobs(
        self,
        search_terms: list[str],
        locations: list[str],
        remote_filters: list[str],
        country: str,
    ) -> list[dict]:
        read_count = 0
        relevant: list[dict] = []
        frames: list[pd.DataFrame] = []
        failures: dict[str, str] = {}

        for term in search_terms:
            for location in locations:
                remote = _should_use_remote(remote_filters, location)
                logger.info(
                    "JobSpy: fetching %r @ %r (remote=%s, country=%s)",
                    term, location, remote, country,
                )
                try:
                    df = fetch_jobs(term, location, remote=remote, country=country)
                except Exception as exc:
                    logger.warning("JobSpy fetch failed for %r @ %r: %s", term, location, exc)
                    failures[f"{term} @ {location}"] = str(exc)
                    continue

                normalized: list[dict] = []
                if df is not None and not df.empty:
                    frames.append(df)
                    normalized = normalize_jobs(df, term, location)
                # LinkedIn ranks its free-text search loosely, so a query for "Product Lead" also returns sales
                # engineers and SAP consultants. The same title filter the other providers use is applied here,
                # one search at a time, and the search is staged before the next one starts: this source takes
                # the better part of half an hour, and a stop keeps every search that had finished.
                found = [
                    job for job in normalized
                    if is_relevant_role(job.get("title", ""), "", tuple(search_terms or ()))
                ]
                read_count += len(normalized)
                relevant.extend(found)
                self.stage(found, part=f"{term} @ {location}", read=len(normalized))

        self._last_raw_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

        logger.info(
            "JobSpy: %d ads fetched, %d kept after title filtering",
            read_count, len(relevant),
        )
        self.last_outcome = parts_outcome(
            read=read_count,
            kept=len(relevant),
            total=len(search_terms) * len(locations),
            failures=failures,
            named=False,  # searches, not boards
        )
        return relevant

    @property
    def last_raw_df(self) -> pd.DataFrame:
        return self._last_raw_df
