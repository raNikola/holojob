"""Ads the owner kept and asked to have re-scored (Wave 2 e).

Keep is a browser flag; a kept ad that has left the current job list has no row in scored_jobs.json, so it has no
score and cannot be tailored. A manual Re-score of a kept ad registers its id here, scores the ad from the job
history ledger with the same score_jobs() a full run uses, and merges that one row into scored_jobs.json.

The set is not permanent. `prune` drops every id that is no longer kept and has no application, so an ad whose Keep was
removed does not stay in the scoring set because of an earlier Re-score. Pruning removes the id only: the owner's
stored copy of the job, and every application, are never touched here. Nothing here calls a model.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from atomic_write import write_text_atomic

ROOT = Path(__file__).resolve().parents[2]
KEPT_PATH = ROOT / "data" / "jobs" / "rescored_kept.json"
JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
FILE_MODE = 0o600
MARK = "keptRescore"


def load(path: Path = KEPT_PATH) -> dict:
    """{jobId: {"rescoredAt": iso}}; a missing or unreadable file is empty (it only ever lists ids)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = data.get("ids") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {k: v if isinstance(v, dict) else {} for k, v in entries.items() if isinstance(k, str) and JOB_ID.match(k)}


def _save(entries: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, json.dumps({"version": 1, "ids": entries}, indent=2), FILE_MODE)


def add(job_id: str, path: Path = KEPT_PATH) -> None:
    if not JOB_ID.match(job_id or ""):
        raise ValueError("invalid jobId")
    entries = load(path)
    entries[job_id] = {"rescoredAt": datetime.now(timezone.utc).isoformat()}
    _save(entries, path)


def register_owner_ads(ids, ledger_file: Path, path: Path = KEPT_PATH) -> dict:
    """Register the owner's own ads (an ad with an application, a kept ad) so every scoring run keeps their rows (backlog item 11).

    Such an ad can stay open in the ledger after a run no longer lists it; the list view then drops it and, before this, its scored row went with
    it. Only ids the ledger holds are registered (the row is read from there); already registered ids are untouched. Writes nothing when nothing is
    new. Returns counts: registered, already, notInLedger."""
    wanted = sorted({i for i in ids or () if isinstance(i, str) and JOB_ID.match(i)})
    entries = load(path)
    fresh = [i for i in wanted if i not in entries]
    out = {"registered": 0, "already": len(wanted) - len(fresh), "notInLedger": 0}
    if not fresh:
        return out
    import job_history  # noqa: PLC0415

    held = (job_history.load(ledger_file, read_only=True).get("jobs") or {})
    now = datetime.now(timezone.utc).isoformat()
    for job_id in fresh:
        if isinstance(held.get(job_id), dict) and isinstance(held[job_id].get("job"), dict):
            entries[job_id] = {"rescoredAt": now, "owner": True}
            out["registered"] += 1
        else:
            out["notInLedger"] += 1
    if out["registered"]:
        _save(entries, path)
    return out


def prune(keep_ids: set[str], path: Path = KEPT_PATH) -> list[str]:
    """Drops the ids that are not in `keep_ids` (the kept ads plus the ads with an application); returns the dropped ones."""
    entries = load(path)
    dropped = sorted(i for i in entries if i not in keep_ids)
    if dropped:
        _save({i: v for i, v in entries.items() if i in keep_ids}, path)
    return dropped


def ledger_row(ledger: dict, job_id: str) -> dict | None:
    """The ad as the ledger holds it, marked, or None. A row only the ledger holds is not part of any view.

    The stored extraction facts sit on the entry, not on its job snapshot; the list view merges them in
    (job_history, `record["llmFacts"] = entry["llmFacts"]`), so this does too. Without them a kept ad was scored as unread.
    """
    entry = (ledger.get("jobs") or {}).get(job_id)
    job = entry.get("job") if isinstance(entry, dict) else None
    if not isinstance(job, dict):
        return None
    row = {**job, "jobId": job_id, MARK: True}
    facts = entry.get("llmFacts")
    if isinstance(facts, dict) and facts:
        row["llmFacts"] = facts
    return row


def with_kept(jobs: list[dict], ledger_file: Path, path: Path = KEPT_PATH) -> list[dict]:
    """`jobs` plus the registered ads the list does not hold. A row in the list wins: it is already scored with the run.
    The ledger (large) is read only when there is an id to look up."""
    have = {j.get("jobId") for j in jobs}
    wanted = [i for i in load(path) if i not in have]
    if not wanted:
        return jobs
    import job_history  # noqa: PLC0415

    ledger = job_history.load(ledger_file, read_only=True)
    return [*jobs, *(row for row in (ledger_row(ledger, i) for i in wanted) if row)]
