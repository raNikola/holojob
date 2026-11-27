"""Repost counter (package 7, owner plan 2026-11-25). Pure and read-only: it counts, it never drops, hides or scores an ad.

Two postings are reposts of one role when ALL of these hold (owner decision, PACKAGES_PLAN "Closed decisions"):
  - same company key (`company_key.key_of`);
  - same title word set (accents folded, lower case, order and repeats ignored);
  - different URL;
  - at least 2 dates (a group needs two distinct posting days to count as a repost at all);
  - same source host (the host of the URL; the crosspost across boards is the dedupe's job, not this counter's);
  - within the window (default 90 days, Settings `repostWindowDays`; `source_settings.repost_window`): a group is a run of postings
    whose dates all lie within the window of the group's first date.
A posting's date is `datePosted`, else the day of `firstSeen`; a posting with neither has no date and is never counted.

SimHash is a NOTE only (owner decision): two descriptions of at least 400 characters whose 64-bit SimHash differs in at most 7 bits are
listed as `similarText` pairs beside the groups. It changes no group and no count.

Source of the rule shape: career-ops `detect-reposts.mjs` (company key + title match, benchmark read 2026-11-27); the host, URL and
90-day conditions and the SimHash note are owner decisions, not benchmark.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

_spec = importlib.util.spec_from_file_location("_repost_company_key", Path(__file__).with_name("company_key.py"))
_company_key = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_company_key)
_spec_text = importlib.util.spec_from_file_location("_repost_text_utils", Path(__file__).with_name("text_utils.py"))
_text_utils = importlib.util.module_from_spec(_spec_text)
_spec_text.loader.exec_module(_text_utils)

DEFAULT_WINDOW_DAYS = 90
SIMHASH_MIN_CHARS = 400
SIMHASH_MAX_DISTANCE = 7
_WORD = re.compile(r"[a-z0-9+#]+")


def title_words(title) -> frozenset:
    return frozenset(_WORD.findall(_text_utils.normalize_text(str(title or ""))))


def host_of(url) -> str:
    host = (urlsplit(str(url or "").strip()).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def simhash(text: str) -> int:
    """64-bit SimHash over word 3-grams of the lowered text (pure, stdlib)."""
    words = _WORD.findall(_text_utils.normalize_text(text))
    grams = [" ".join(words[i:i + 3]) for i in range(max(len(words) - 2, 1))]
    weights = [0] * 64
    for gram in grams:
        h = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=8).digest(), "big")
        for bit in range(64):
            weights[bit] += 1 if (h >> bit) & 1 else -1
    return sum(1 << bit for bit in range(64) if weights[bit] > 0)


def _posting(job_id: str, entry: dict) -> dict | None:
    job = entry.get("job") if isinstance(entry.get("job"), dict) else entry
    when = _day(job.get("datePosted")) or _day(entry.get("firstSeen"))
    url = str(job.get("jobUrl") or "").strip()
    words = title_words(job.get("title"))
    key = _company_key.key_of(entry)
    if when is None or not url or not words or not key:
        return None
    return {"id": job_id, "key": key, "words": words, "host": host_of(url), "url": url, "date": when, "text": str(job.get("description") or "")}


def count_reposts(entries: dict, *, window_days: int = DEFAULT_WINDOW_DAYS, with_similar: bool = False) -> dict:
    """Groups of reposts among `entries` ({jobId: ledger entry or row}).

    Returns {"groups": [{companyKey, titleWords, host, ids, urls, dates, count}], "repostsOf": {jobId: other postings of its group},
    "similarText": [[idA, idB], ...] (only when `with_similar`)}. A group has at least two distinct URLs and two distinct dates.
    """
    buckets: dict[tuple, list[dict]] = {}
    for job_id, entry in entries.items():
        post = _posting(job_id, entry) if isinstance(entry, dict) else None
        if post and post["host"]:
            buckets.setdefault((post["key"], post["words"], post["host"]), []).append(post)
    groups = []
    for (key, words, host), posts in buckets.items():
        posts.sort(key=lambda p: (p["date"], p["id"]))
        i = 0
        while i < len(posts):
            start = posts[i]["date"]
            run = [p for p in posts[i:] if (p["date"] - start).days <= window_days]
            i += len(run)
            urls = {p["url"].lower() for p in run}
            if len(urls) >= 2 and len({p["date"] for p in run}) >= 2:
                groups.append({"companyKey": key, "titleWords": sorted(words), "host": host, "ids": [p["id"] for p in run],
                               "urls": sorted(urls), "dates": sorted({p["date"].isoformat() for p in run}), "count": len(run)})
    groups.sort(key=lambda g: (-g["count"], g["companyKey"], g["ids"][0]))
    result = {"groups": groups, "repostsOf": {job_id: g["count"] - 1 for g in groups for job_id in g["ids"]}}
    if with_similar:
        result["similarText"] = _similar_pairs(entries)
    return result


def _similar_pairs(entries: dict) -> list:
    hashed = []
    for job_id, entry in entries.items():
        job = entry.get("job") if isinstance(entry.get("job"), dict) else entry
        text = str(job.get("description") or "").strip() if isinstance(job, dict) else ""
        if len(text) >= SIMHASH_MIN_CHARS:
            hashed.append((job_id, simhash(text)))
    return [[a, b] for n, (a, ha) in enumerate(hashed) for b, hb in hashed[n + 1:] if bin(ha ^ hb).count("1") <= SIMHASH_MAX_DISTANCE]
