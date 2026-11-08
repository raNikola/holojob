"""Retention of `older_key` rows in the job-history ledger (Wave 4, h).

An `older_key` row is an ad the ledger saw under an earlier search (`seenUnder` differs from the current search) and that no later
run found, held, marked absent or closed (`all_ads.classify`). The importer never deletes it (`apply_run(prune=False)`). This module
plans, and on request makes, the one deletion the owner approved: rows of that class that are older than a window the owner chooses.

Nothing here runs by itself. `scripts/older-key-report.py` only counts. `scripts/prune-older-key.py` is a dry run unless `--apply`,
which needs the window (`--days`, no default), a backup, the pipeline lock, and both lists of protected ids (see below).

A row is never removed when any of these holds, whatever its age:
  - its class is not `older_key` (found, held, absent, stale, closed and unclassified rows are untouched);
  - it has no `lastSeen` or `firstSeen` (its age is unknown);
  - a job id in `application_ids` (the owner exports them: Python does not read the application store, TRACKER_PLAN 6a);
  - a job id in `protect_ids` (the owner exports the Keep / status / hand-entered ids from the browser, which the server cannot see);
  - it is a Keep re-score (`data/jobs/rescored_kept.json`);
  - the backend holds work for it: tailored documents, outreach, an AI finding, a tailored link in scored_jobs.json
    (`lifecycle_report.backend_user_data`).
`llmFacts` alone does not protect a row: it is a cache, and the report counts how many rows carry it.

The view (discovered_jobs.json) is derived from the rows a run found, held or marked absent; an `older_key` row is in none of them, so
removing it changes no view. `prune` checks that: the view derived before and after must be identical, or nothing is written.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import all_ads
import job_history
import kept_ads
import lifecycle_report
import pipeline_lock
import view_guard
from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic

CLASS = "older_key"
BUCKETS = ((30, "0-30d"), (60, "31-60d"), (90, "61-90d"), (180, "91-180d"), (365, "181-365d"), (10**9, "366d+"))
ID = re.compile(r"^[^\s#]{1,200}$")
BACKUPS_DIR = "data/backups"

REASON_APPLICATION = "application"
REASON_PROTECT_FILE = "protect_ids_file"
REASON_KEPT_RESCORE = "kept_rescore"
REASON_BACKEND = "backend_user_data"

BROWSER_NOTE = (
    "Browser-only data is INVISIBLE to the server: Keep, triage status, AI insights, outreach state and hand-entered jobs live in the "
    "browser (localStorage job-dashboard-discovered-jobs). Export their ids and pass them with --protect-ids FILE before any --apply."
)


def parse_ids(path: Path | None) -> set[str] | None:
    """The job ids in a file, one per line (blank lines and `#` comments ignored). None when no file was given."""
    if path is None:
        return None
    ids = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        token = line.split("#", 1)[0].strip()
        if token and ID.match(token):
            ids.add(token)
    return ids


def _parse(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None
    if moment is not None and moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def age_days(entry: dict, now: datetime) -> int | None:
    """Days since the row was last seen (its first sighting when it has no lastSeen); None when it has neither."""
    moment = _parse(entry.get("lastSeen")) or _parse(entry.get("firstSeen"))
    return None if moment is None else max(0, (now - moment).days)


def older_key_ids(ledger: dict) -> list[str]:
    run_id = (ledger.get("lastImport") or {}).get("runId")
    key, providers, source_runs = all_ads.current_key(ledger), all_ads.run_providers(ledger), ledger.get(all_ads.stale_rule.FIELD)
    return [
        job_id for job_id, entry in ledger["jobs"].items()
        if isinstance(entry, dict) and all_ads.classify(entry, run_id, key, providers, source_runs) == CLASS
    ]


def _protection(root: Path, ledger: dict, application_ids, protect_ids) -> dict[str, set[str]]:
    backend = lifecycle_report.backend_user_data(root, set(ledger["jobs"]), None)
    backend_ids = set().union(*(ids for kind, ids in backend.items() if kind != "applications"))
    return {
        REASON_APPLICATION: set(application_ids or ()),
        REASON_PROTECT_FILE: set(protect_ids or ()),
        REASON_KEPT_RESCORE: set(kept_ads.load(root / "data" / "jobs" / "rescored_kept.json")),
        REASON_BACKEND: backend_ids,
    }


def plan(ledger: dict, root: Path, *, days: int, now: datetime, application_ids=None, protect_ids=None) -> dict:
    """What a prune with this window would remove. Counts and ids only; reads, changes nothing."""
    protection = _protection(Path(root), ledger, application_ids, protect_ids)
    ids = older_key_ids(ledger)
    candidates, young, unknown = [], 0, 0
    protected_by = {reason: 0 for reason in protection}
    protected_total = 0
    for job_id in ids:
        entry = ledger["jobs"][job_id]
        age = age_days(entry, now)
        if age is None:
            unknown += 1
            continue
        if age <= days:
            young += 1
            continue
        reasons = [reason for reason, held in protection.items() if job_id in held]
        for reason in reasons:
            protected_by[reason] += 1
        if reasons:
            protected_total += 1
        else:
            candidates.append(job_id)
    return {
        "days": days, "olderKey": len(ids), "candidates": sorted(candidates), "withinWindow": young, "ageUnknown": unknown,
        "protected": protected_total, "protectedBy": protected_by,
        "applicationsJoined": application_ids is not None, "protectIdsGiven": protect_ids is not None,
    }


def report(ledger: dict, root: Path, *, now: datetime, application_ids=None, protect_ids=None) -> dict:
    """Counts for the owner's decision: older_key rows by age and provider, how many carry facts, how many are protected today."""
    ids = older_key_ids(ledger)
    ages = {label: 0 for _, label in BUCKETS} | {"unknown": 0}
    providers: dict[str, int] = {}
    with_facts = 0
    for job_id in ids:
        entry = ledger["jobs"][job_id]
        age = age_days(entry, now)
        label = "unknown" if age is None else next(label for limit, label in BUCKETS if age <= limit)
        ages[label] += 1
        providers[str(entry.get("provider") or "?")] = providers.get(str(entry.get("provider") or "?"), 0) + 1
        with_facts += bool(entry.get("llmFacts"))
    protection = _protection(Path(root), ledger, application_ids, protect_ids)
    held = {job_id for job_id in ids if any(job_id in held for held in protection.values())}
    # What each window would remove, with the protections known right now (the same rule `plan` applies).
    windows = {str(days): len(plan(ledger, root, days=days, now=now, application_ids=application_ids, protect_ids=protect_ids)["candidates"])
               for days in (90, 180, 365)}
    return {
        "ledgerRows": len(ledger["jobs"]), "olderKey": len(ids), "byAge": ages, "byProvider": dict(sorted(providers.items())),
        "withLlmFacts": with_facts, "protectedNow": len(held), "protectedBy": {r: len(s & set(ids)) for r, s in protection.items()},
        "wouldRemove": windows, "applicationsJoined": application_ids is not None, "protectIdsGiven": protect_ids is not None,
    }


# --- the one write ----------------------------------------------------------------------------------------------------------


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _view_text(ledger: dict) -> str:
    return json.dumps(view_guard.derive_view(ledger), sort_keys=True)


def prune(root: Path, *, days: int, now: datetime, application_ids, protect_ids, apply: bool, stamp: str | None = None) -> dict:
    """Plan, and with `apply` make, the removal. Refuses `apply` without both id lists (an empty list is a list), the pipeline lock,
    a git-ignored backup of the ledger, and an unchanged view. Returns the plan plus what was done."""
    root = Path(root)
    ledger_file = root / "data" / "jobs" / job_history.LEDGER_FILE
    if apply and (application_ids is None or protect_ids is None):
        raise SystemExit("refusing --apply: pass --application-job-ids FILE and --protect-ids FILE (an empty file is fine). " + BROWSER_NOTE)
    lock = pipeline_lock.acquire(path=root / "data" / "jobs" / ".pipeline.lock")
    if lock is None:
        raise SystemExit(pipeline_lock.BUSY_MESSAGE.replace("nothing started", "nothing pruned"))
    try:
        ledger = job_history.load(ledger_file, read_only=True)
        result = plan(ledger, root, days=days, now=now, application_ids=application_ids, protect_ids=protect_ids)
        result["applied"] = False
        if not apply or not result["candidates"]:
            return result
        target = _backup(root, ledger_file, result, stamp or now.strftime("%Y%m%d-%H%M%S"))
        before_view = _view_text(ledger) if ledger.get("lastImport") else None
        after = copy.deepcopy(ledger)
        for job_id in result["candidates"]:
            del after["jobs"][job_id]
        if before_view is not None and _view_text(after) != before_view:
            raise SystemExit("refusing: removing these rows would change the derived view, so nothing was written")
        job_history.save(ledger_file, after)
        result.update(applied=True, backup=str(target.relative_to(root)), removed=len(result["candidates"]), rowsAfter=len(after["jobs"]))
        return result
    finally:
        lock.release()


def _ignored(path: Path, root: Path) -> bool:
    return subprocess.run(["git", "-C", str(root), "check-ignore", "-q", str(path)], capture_output=True).returncode == 0


def _backup(root: Path, ledger_file: Path, result: dict, stamp: str) -> Path:
    target = root / BACKUPS_DIR / f"older-key-{stamp}"
    if target.exists():
        raise SystemExit(f"backup already exists: {target}")
    if (root / ".git").exists() and not _ignored(target / "manifest.json", root):
        raise SystemExit(f"git does not ignore {target}; add {BACKUPS_DIR}/ to .gitignore first")
    make_private_dirs(target)
    copy_to = target / "data" / "jobs" / ledger_file.name
    make_private_dirs(copy_to.parent)
    shutil.copy2(ledger_file, copy_to)
    copy_to.chmod(PRIVATE_FILE_MODE)
    if _sha(copy_to) != _sha(ledger_file):
        raise SystemExit("the backup copy of the ledger does not match its source; nothing was changed")
    write_text_atomic(target / "removed-ids.txt", "\n".join(result["candidates"]) + "\n", new_file_mode=PRIVATE_FILE_MODE)
    manifest = {"created": stamp, "days": result["days"], "removed": len(result["candidates"]),
                "files": {"data/jobs/" + ledger_file.name: {"sha256": _sha(copy_to), "bytes": copy_to.stat().st_size}},
                "restore": f"copy data/jobs/{ledger_file.name} from this folder back to data/jobs/ while no run is active"}
    write_text_atomic(target / "manifest.json", json.dumps(manifest, indent=1), new_file_mode=PRIVATE_FILE_MODE)
    return target
