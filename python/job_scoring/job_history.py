"""The job history ledger: what discovery has seen, and what enrichment learned.

Discovery rewrites discovered_jobs.json from scratch every run, and enrichment
keeps its facts on the job record inside that file, so every run used to read
every ad again. The ledger (data/jobs/job_history.json) is the memory that
survives: for each jobId, when it was first and last seen, when it stopped being
listed, and the facts enrichment extracted, keyed by the same content
fingerprint (job_fingerprint.py) so an ad that changed is read again.

Closing a job means "discovery no longer finds it", which is only safe to say
for sources that list every open posting. LinkedIn searches return a rolling
window of recent ads, so a LinkedIn job missing from one run is not closed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "_ledger_job_fingerprint", Path(__file__).with_name("job_fingerprint.py")
)
_fingerprint_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fingerprint_module)
job_fingerprint = _fingerprint_module.job_fingerprint

_atomic_spec = importlib.util.spec_from_file_location(
    "_ledger_atomic_write", Path(__file__).with_name("atomic_write.py")
)
_atomic_module = importlib.util.module_from_spec(_atomic_spec)
_atomic_spec.loader.exec_module(_atomic_module)
write_text_atomic = _atomic_module.write_text_atomic

LEDGER_FILE = "job_history.json"

# Providers whose API returns every open posting of a board, so a job that is
# no longer listed has really been taken down.
CLOSURE_PROVIDERS = {"greenhouse", "lever", "ashby"}

# A description shorter than this is not a real ad; LinkedIn returns one when
# it rate-limits the detail fetch. It never replaces a fuller description the
# ledger already holds, or a throttled run would swap good facts for worse.
THIN_DESCRIPTION_CHARS = 200

NEW_WINDOW_DAYS = 3  # how long after first being seen a job is flagged new
CLOSED_KEEP_DAYS = 14  # how long a closed job stays in discovered_jobs.json
PRUNE_AFTER_DAYS = 90  # how long a closed job stays in the ledger

# Fields the ledger adds to a job; they are not part of the stored snapshot.
HISTORY_FIELDS = ("firstSeen", "lastSeen", "closedAt", "isNew", "isClosed", "llmFacts")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def search_key(terms, locations, country, remote_filters) -> str:
    """Identifies the search a run made; closing needs the same search twice."""
    raw = json.dumps(
        [sorted(terms or []), sorted(locations or []), country or "", sorted(remote_filters or [])]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def empty_ledger() -> dict:
    return {"version": 1, "updatedAt": None, "jobs": {}}


def ledger_path(jobs_file: Path) -> Path:
    return jobs_file.with_name(LEDGER_FILE)


def load(path: Path) -> dict:
    if not path.exists():
        return empty_ledger()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("jobs"), dict):
            return data
    except (OSError, ValueError):
        pass
    # An unreadable ledger is moved aside, never overwritten: it is the only copy.
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    path.rename(path.with_name(f"{path.name}.corrupt-{stamp}"))
    return empty_ledger()


def save(path: Path, ledger: dict) -> None:
    ledger["updatedAt"] = now_iso()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, json.dumps(ledger, indent=2))


def _snapshot(job: dict) -> dict:
    return {k: v for k, v in job.items() if k not in HISTORY_FIELDS}


def _annotate(job: dict, entry: dict, *, now: datetime, closed: bool) -> dict:
    first = _parse(entry.get("firstSeen"))
    return {
        **job,
        "firstSeen": entry["firstSeen"],
        "lastSeen": entry["lastSeen"],
        "closedAt": entry.get("closedAt"),
        # A job the ledger inherited from the file it replaced was seen before the
        # ledger existed, so it is not new, whatever date it is first recorded under.
        "isNew": bool(
            not closed
            and not entry.get("seeded")
            and first
            and now - first <= timedelta(days=NEW_WINDOW_DAYS)
        ),
        "isClosed": closed,
    }


def _board_failed(entry: dict, failed_boards: dict[str, set[str] | None]) -> bool:
    """Whether this entry's board went unread this run. An entry with no board name counts as unread when in doubt."""
    provider = entry.get("provider")
    if provider not in failed_boards:
        return False
    boards = failed_boards[provider]
    board = (entry.get("job") or {}).get("source")
    return boards is None or not board or board in boards


def apply_run(
    ledger: dict,
    jobs: list[dict],
    *,
    now: str,
    providers_returned: dict[str, int],
    key: str,
    role_key,
    previous_facts: dict[str, dict] | None = None,
    seen_before: dict[str, str] | None = None,
    failed_boards: dict[str, set[str] | None] | None = None,
) -> tuple[list[dict], dict]:
    """Record one discovery run; return the jobs to write and what changed.

    `jobs` are this run's deduplicated jobs. `providers_returned` maps a provider
    to how many jobs it returned, so one that failed (and returned nothing) can
    never close its jobs. `role_key` is the title+company key discovery already
    uses to merge copies of one role. `previous_facts` are llmFacts from the
    discovered file this run replaces: they seed a ledger that has not seen the
    job yet, so the first run on an existing install does not read every ad again.
    `seen_before` maps the jobIds in that same file to when it was written: a job
    the ledger meets for the first time but that is in it was seen earlier, so it
    takes that date as firstSeen and is never flagged new.
    `failed_boards` maps a provider to the boards it could not read this run (None: it failed before naming any). Their
    ads say nothing about what is listed, so they are not closed, and stay in the output unchanged instead of dropping
    out of it. Only CLOSURE_PROVIDERS read this: a search-based provider's missing ad is not closed anyway.
    """
    moment = _parse(now) or datetime.now(timezone.utc)
    entries = ledger["jobs"]
    previous_facts = previous_facts or {}
    seen_before = seen_before or {}
    failed_boards = failed_boards or {}
    stats = {
        "new": 0, "known": 0, "reopened": 0, "changed": 0, "carriedFacts": 0, "closed": 0,
        "keptFullerDescription": 0, "keptFailedBoard": 0,
    }
    found_ids = set()
    found_roles = set()
    out = []

    for job in jobs:
        job_id = job["jobId"]
        found_ids.add(job_id)
        entry = entries.get(job_id)
        stored_description = ((entry or {}).get("job") or {}).get("description") or ""
        if (
            len((job.get("description") or "").strip()) < THIN_DESCRIPTION_CHARS
            and len(stored_description.strip()) >= THIN_DESCRIPTION_CHARS
        ):
            job = {**job, "description": stored_description}
            stats["keptFullerDescription"] += 1
        found_roles.add(role_key(job))
        fingerprint = job_fingerprint(job)

        if entry is None:
            entry = entries[job_id] = {
                "firstSeen": seen_before.get(job_id, now), "lastSeen": now,
                "closedAt": None, "llmFacts": None,
            }
            if job_id in seen_before:
                entry["seeded"] = True
            stats["new"] += 1
            candidate = previous_facts.get(job_id)
        else:
            stats["known"] += 1
            entry["lastSeen"] = now
            if entry.get("closedAt"):
                entry["closedAt"] = None
                stats["reopened"] += 1
            candidate = entry.get("llmFacts") or previous_facts.get(job_id)

        if candidate and candidate.get("_fingerprint") == fingerprint:
            entry["llmFacts"] = candidate
            stats["carriedFacts"] += 1
        else:
            if entry.get("llmFacts"):
                stats["changed"] += 1  # the ad changed, so its old facts no longer apply
            entry["llmFacts"] = None

        entry.update(
            provider=job.get("provider"), roleKey=role_key(job), seenUnder=key, job=_snapshot(job)
        )
        record = _annotate(job, entry, now=moment, closed=False)
        if entry["llmFacts"]:
            record["llmFacts"] = entry["llmFacts"]
        out.append(record)

    for job_id, entry in entries.items():
        if job_id in found_ids or entry.get("closedAt"):
            continue
        provider = entry.get("provider")
        if (
            provider not in CLOSURE_PROVIDERS
            or entry.get("seenUnder") != key
            or entry.get("roleKey") in found_roles  # still listed under another copy
        ):
            continue
        if _board_failed(entry, failed_boards):
            record = _annotate(entry["job"], entry, now=moment, closed=False)
            if entry.get("llmFacts"):
                record["llmFacts"] = entry["llmFacts"]
            out.append(record)
            stats["keptFailedBoard"] += 1
        elif providers_returned.get(provider, 0) > 0:
            entry["closedAt"] = now
            stats["closed"] += 1

    for job_id, entry in list(entries.items()):
        closed_at = _parse(entry.get("closedAt"))
        if not closed_at:
            continue
        age = moment - closed_at
        if age > timedelta(days=PRUNE_AFTER_DAYS):
            del entries[job_id]
        elif age <= timedelta(days=CLOSED_KEEP_DAYS) and job_id not in found_ids:
            record = _annotate(entry["job"], entry, now=moment, closed=True)
            if entry.get("llmFacts"):
                record["llmFacts"] = entry["llmFacts"]
            out.append(record)

    return out, stats


def facts_for(ledger: dict, job: dict) -> dict | None:
    """The stored facts for this job if its content is unchanged, else None."""
    entry = ledger["jobs"].get(job.get("jobId"))
    facts = entry.get("llmFacts") if entry else None
    return facts if facts and facts.get("_fingerprint") == job_fingerprint(job) else None


def store_facts(ledger: dict, job: dict) -> bool:
    """Keep a job's current facts in its ledger entry; False if discovery never saw it."""
    entry = ledger["jobs"].get(job.get("jobId"))
    if entry is None or not job.get("llmFacts"):
        return False
    entry["llmFacts"] = job["llmFacts"]
    return True
