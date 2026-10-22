"""Deduplicate normalized jobs by URL or title+company+location."""

from __future__ import annotations


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


def _crosspost_key(job: dict) -> str | None:
    title = _norm(job.get("title"))
    company = _norm(job.get("company"))
    if not title or not company:
        return None
    source = _norm(job.get("source")) or _norm(job.get("provider"))
    return f"tc:{source}|{title}|{company}"


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
