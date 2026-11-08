"""JobSpy provider — wraps existing jobspy_adapter + normalize_jobs."""

from __future__ import annotations

import logging

import pandas as pd

from jobspy_adapter import fetch_jobs
from normalize_jobs import _safe_str, normalize_jobs
from providers.base_provider import JobProvider, dropped_ad, parts_outcome
from providers.role_filter import role_drop_reason

logger = logging.getLogger(__name__)


def _should_use_remote(remote_filters: list[str], location: str) -> bool:
    loc = (location or "").lower()
    if loc == "remote":
        return True
    filters = [f.lower() for f in remote_filters]
    return "remote" in filters and loc == "remote"


def _row_facts(df: pd.DataFrame) -> tuple[list[str | None], list[dict]]:
    """For the rows `normalize_jobs` keeps (those with a title), in its order: the id LinkedIn or the board gives each.
    And the rows it silently drops for having no title, as far as they can be told apart."""
    ids: list[str | None] = []
    untitled: list[dict] = []
    for _, row in df.iterrows():
        external = _safe_str(row.get("id")) or None
        if _safe_str(row.get("title")):
            ids.append(external)
        else:
            untitled.append({
                "company": _safe_str(row.get("company")), "location": _safe_str(row.get("location")),
                "jobUrl": _safe_str(row.get("job_url") or row.get("jobUrl")), "externalId": external,
            })
    return ids, untitled


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
        site_warnings: list[str] = []

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

                sites_failed = list((getattr(df, "attrs", None) or {}).get("sitesFailed") or [])
                if sites_failed and (df is None or df.empty):
                    # Every site that could answer raised (429, block, timeout): an empty frame here is not "0 ads".
                    failures[f"{term} @ {location}"] = f"{', '.join(sites_failed)} could not be read"
                    continue
                if sites_failed:
                    # Some sites failed, others answered: keep what was read, say what was missing.
                    site_warnings.append(f"{term} @ {location}: {', '.join(sites_failed)} could not be read; ads from the other sites were kept")
                normalized: list[dict] = []
                external: list[str | None] = []
                dropped: list[dict] = []
                if df is not None and not df.empty:
                    frames.append(df)
                    normalized = normalize_jobs(df, term, location)
                    external, untitled = _row_facts(df)
                    if len(external) != len(normalized):
                        external = [None] * len(normalized)  # never guess which id belongs to which ad
                    # Rows with no title never counted as read: dropped before the count, so `counted` is False.
                    dropped += [dropped_ad(row, "no_title", row["externalId"], counted=False) for row in untitled]
                # LinkedIn ranks its free-text search loosely, so a query for "Product Lead" also returns sales
                # engineers and SAP consultants. The same title filter the other providers use is applied here,
                # one search at a time, and the search is staged before the next one starts: this source takes
                # the better part of half an hour, and a stop keeps every search that had finished.
                found = []
                for job, ext in zip(normalized, external or [None] * len(normalized)):
                    reason = role_drop_reason(job.get("title", ""), "", tuple(search_terms or ()))
                    if reason is None:
                        found.append(job)
                    else:
                        dropped.append(dropped_ad(job, reason, ext))
                read_count += len(normalized)
                relevant.extend(found)
                self.stage(
                    found, part=f"{term} @ {location}", read=len(normalized),
                    external_ids={job["jobId"]: ext for job, ext in zip(normalized, external) if ext},
                    dropped=dropped,
                )

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
        self.last_outcome.warnings.extend(site_warnings)
        return relevant

    @property
    def last_raw_df(self) -> pd.DataFrame:
        return self._last_raw_df
