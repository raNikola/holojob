"""Repair Infostud ads stored with a cut-off description (Wave 5). A DRY RUN unless apply=True; nothing in the app calls this.

Ads stored before Wave 5 hold the listing teaser (about 500 characters ending in "..."), with no `descriptionStatus`. This reads each
one's public detail page again, politely, and stores the full text with its status. Only `teaser`, `failed` and legacy (no status, text
ending in an ellipsis) ads are candidates; `source_truncated` ads were already read and are not fetched again, `complete` ads never.

Politeness: one request per ad, no retry, sequential, a delay with jitter between requests, a hard `limit` (default 20), and a stop
at the first 403 / 429 / 503 or after three failures in a row. The dry run makes no request at all. Output is counts only.
"""

from __future__ import annotations

import copy
import random
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import job_history
import pipeline_lock
from providers import infostud_client, infostud_description as desc
from atomic_write import make_private_dirs

DEFAULT_LIMIT = 20
DEFAULT_DELAY = 3.0
STOP_CODES = (403, 429, 503)
GONE_CODES = (404, 410)
MAX_CONSECUTIVE_FAILURES = 3
LEGACY_MAX_CHARS = 1000  # an unflagged text longer than this is not a teaser
BUCKETS = (0, 200, 400, 600, 800, 1000)
BACKUPS_DIR = "data/backups"


def is_candidate(entry: dict) -> bool:
    job = entry.get("job") or {}
    if job.get("source") != "infostud" or entry.get("closedAt") or not job.get("jobUrl"):
        return False
    status = job.get("descriptionStatus")
    if status in desc.REPAIRABLE:
        return True
    if status:  # complete or source_truncated
        return False
    text = (job.get("description") or "").strip()
    return len(text) <= LEGACY_MAX_CHARS and (not text or text.endswith(desc.ELLIPSIS))


def _bucket(n: int) -> str:
    low = max(b for b in BUCKETS if b <= n)
    return f"{low}+" if low == BUCKETS[-1] else f"{low}-{BUCKETS[BUCKETS.index(low) + 1]}"


def plan(ledger: dict, limit: int = DEFAULT_LIMIT) -> dict:
    ids = [i for i, e in ledger["jobs"].items() if is_candidate(e)]
    counts: dict[str, int] = {}
    for i in ids:
        key = _bucket(len((ledger["jobs"][i]["job"].get("description") or "").strip()))
        counts[key] = counts.get(key, 0) + 1
    infostud = [e for e in ledger["jobs"].values() if (e.get("job") or {}).get("source") == "infostud"]
    by_status: dict[str, int] = {}
    for e in infostud:
        by_status[e["job"].get("descriptionStatus") or "unflagged"] = by_status.get(e["job"].get("descriptionStatus") or "unflagged", 0) + 1
    return {"infostudAds": len(infostud), "byStatus": by_status, "candidates": len(ids), "candidateLengthBuckets": counts,
            "limit": limit, "wouldFetch": min(limit, len(ids)), "ids": ids[:limit]}


def _fetch(url: str) -> str:
    return infostud_client._get(url, retries=1)


def repair(root: Path, *, limit: int = DEFAULT_LIMIT, delay: float = DEFAULT_DELAY, apply: bool = False,
           fetch=_fetch, sleep=time.sleep, now: datetime | None = None) -> dict:
    root = Path(root)
    ledger_file = root / "data" / "jobs" / job_history.LEDGER_FILE
    if limit < 1:
        raise SystemExit("--limit must be at least 1")
    lock = pipeline_lock.acquire(path=root / "data" / "jobs" / ".pipeline.lock")
    if lock is None:
        raise SystemExit(pipeline_lock.BUSY_MESSAGE.replace("nothing started", "nothing repaired"))
    try:
        ledger = job_history.load(ledger_file, read_only=True)
        result = plan(ledger, limit)
        ids = result.pop("ids")
        result["applied"] = False
        if not apply or not ids:
            return result
        stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
        base = root / BACKUPS_DIR / f"infostud-description-{stamp}"
        backup = base / "data" / "jobs"
        if base.exists():
            raise SystemExit(f"backup already exists: {base}")
        make_private_dirs(backup)
        (backup / ledger_file.name).write_bytes(ledger_file.read_bytes())
        (backup / ledger_file.name).chmod(0o600)
        after = copy.deepcopy(ledger)
        tally = {"fetched": 0, "complete": 0, "sourceTruncated": 0, "gone": 0, "failed": 0, "factsReset": 0, "stoppedEarly": None}
        streak = 0
        for n, job_id in enumerate(ids):
            if n:
                sleep(delay + random.uniform(0, delay / 2))
            entry = after["jobs"][job_id]
            job = entry["job"]
            try:
                html = fetch(job["jobUrl"])
            except RuntimeError as exc:
                code = getattr(exc.__cause__, "code", None) if isinstance(exc.__cause__, urllib.error.HTTPError) else None
                if code in STOP_CODES:
                    tally["stoppedEarly"] = f"HTTP {code}"
                    break
                tally["gone" if code in GONE_CODES else "failed"] += 1
                streak = 0 if code in GONE_CODES else streak + 1
                if streak >= MAX_CONSECUTIVE_FAILURES:
                    tally["stoppedEarly"] = "three failures in a row"
                    break
                continue
            streak = 0
            tally["fetched"] += 1
            read = desc.read_detail(html, job.get("description") or "")
            if read["description"] != job.get("description") and entry.get("llmFacts"):
                entry["llmFacts"] = None  # facts were read from the teaser; the next run reads the full ad
                tally["factsReset"] += 1
            job.update(description=read["description"], descriptionStatus=read["status"], descriptionSource=read["source"])
            tally["complete" if read["status"] == desc.COMPLETE else "sourceTruncated"] += 1
        job_history.save(ledger_file, after)
        result.update(applied=True, backup=str(base.relative_to(root)), **tally)
        return result
    finally:
        lock.release()
