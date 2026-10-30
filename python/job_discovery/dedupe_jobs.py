"""Deduplicate normalized jobs: by URL, then by title+company across every source."""

from __future__ import annotations

import importlib.util
from pathlib import Path

# The scorer's country table, loaded by path so its sibling modules do not shadow this package's.
_spec = importlib.util.spec_from_file_location(
    "_dedupe_geography", Path(__file__).resolve().parents[1] / "job_scoring" / "geography.py"
)
_geography = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_geography)


def _norm(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _exact_key(job: dict) -> str:
    url = _norm(job.get("jobUrl"))
    if url:
        return f"url:{url}"
    return (
        f"tcl:{_norm(job.get('title'))}"
        f"|{_norm(job.get('company'))}"
        f"|{_norm(job.get('location'))}"
    )


def _company_name(value: str | None) -> str:
    """The company without a trailing country: "Fivetran Serbia" is Fivetran's Serbian
    entity, and the same role arrives under "Fivetran" from other boards. A name that
    ends "of <country>" ("Bank of Serbia") is the country's own and stays whole."""
    name = _norm(value)
    words = name.split()
    for size in (2, 1):
        if len(words) > size and _geography.country_of_name(" ".join(words[-size:])):
            rest = words[:-size]
            if rest[-1] not in ("of", "in", "for", "de", "du"):
                return " ".join(rest)
    return name


def _crosspost_key(job: dict) -> str | None:
    """One role is often several ads: LinkedIn posts it once per city, and the
    same role reaches us from LinkedIn and from the company's own board."""
    title = _norm(job.get("title"))
    company = _company_name(job.get("company"))
    if not title or not company:
        return None
    return f"tc:{title}|{company}"


def _rank(job: dict) -> tuple:
    description = (job.get("description") or "").strip()
    return (
        1 if description else 0,
        len(description),
        job.get("scrapedAt") or "",
        job.get("datePosted") or "",
    )


def _collapse(jobs: list[dict], key_fn) -> list[dict]:
    best: dict[str, dict] = {}
    unkeyed: list[dict] = []

    for job in jobs:
        key = key_fn(job)
        if key is None:
            unkeyed.append(job)
            continue
        current = best.get(key)
        if current is None or _rank(job) > _rank(current):
            best[key] = job

    return list(best.values()) + unkeyed


def dedupe_jobs(jobs: list[dict]) -> list[dict]:
    return _collapse(_collapse(jobs, _exact_key), _crosspost_key)
