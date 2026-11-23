#!/usr/bin/env python3
"""Put back the list rows of a search source that a run left out (owner-run, free, no scrape, no model call).

    .venv/bin/python python/job_scoring/restore_dropped_rows.py --provider jobspy --from-run <runId>            # dry run: counts only
    .venv/bin/python python/job_scoring/restore_dropped_rows.py --provider jobspy --from-run <runId> --apply    # backup, then write

Why: a run that skipped a source (before the 2026-11-24 fix) wrote a list without that source's ads; they stayed open in the ledger. This marks the open
ads of `--provider` that the list of `--from-run` showed (and the last list does not) as held by the last import, so the list derived from the ledger shows
them again, marked "not found by this run" like any held row: no model call, no closing, no change to the ad's own data. An ad the last list already shows is
left alone. The ledger is copied to data/backups/ (600) before the first write; the ledger is written first, then the view (`view_guard.commit`).
Prints counts only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.append(str(ROOT / "python"))

import job_history  # noqa: E402
import pipeline_lock  # noqa: E402
import view_guard  # noqa: E402
from atomic_write import PRIVATE_FILE_MODE, make_private_dirs  # noqa: E402

JOBS_PATH = ROOT / "data" / "jobs" / "discovered_jobs.json"
BACKUP_DIR = ROOT / "data" / "backups"


def restore(ledger: dict, provider: str, from_run: str, *, apply: bool = True) -> list[str]:
    """The ids that come back. With apply=False nothing is changed. Raises ValueError for a ledger no import produced."""
    info = ledger.get("lastImport")
    if not isinstance(info, dict) or not info.get("runId"):
        raise ValueError("the ledger has no lastImport: nothing to restore the list of")
    current = info["runId"]
    ids = [
        job_id for job_id, entry in ledger["jobs"].items()
        if entry.get("provider") == provider and not entry.get("closedAt") and entry.get("lastRunId") == from_run
        and from_run != current and entry.get("heldRunId") != current
    ]
    if apply:
        for job_id in ids:
            ledger["jobs"][job_id]["heldRunId"] = current
        if ids:
            ledger["generation"] = (ledger.get("generation") or 0) + 1
            ledger["updatedAt"] = job_history.now_iso()
    return ids


def _applied_copy(ledger: dict, args) -> dict:
    import copy  # noqa: PLC0415

    twin = copy.deepcopy(ledger)
    restore(twin, args.provider, args.from_run, apply=True)
    return twin


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--provider", required=True)
    ap.add_argument("--from-run", required=True, help="the run id whose list showed the ads (their `lastRunId`)")
    ap.add_argument("--jobs", type=Path, default=JOBS_PATH)
    ap.add_argument("--ledger", type=Path, default=None)
    ap.add_argument("--apply", action="store_true", help="write (default: counts only)")
    args = ap.parse_args(argv)
    ledger_file = args.ledger or job_history.ledger_path(args.jobs)
    lock = pipeline_lock.acquire()
    if lock is None:
        print(pipeline_lock.BUSY_MESSAGE, file=sys.stderr)
        return pipeline_lock.EXIT_LOCKED
    try:
        ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
        before = len(view_guard.derive_view(ledger)["jobs"])
        ids = restore(ledger, args.provider, args.from_run, apply=args.apply)
        after = len(view_guard.derive_view(ledger if args.apply else _applied_copy(ledger, args))["jobs"])
        print(f"rows that come back: {len(ids)} (provider {args.provider}, list of run {args.from_run}); list rows {before} -> {after}")
        if not args.apply or not ids:
            print("nothing written" + ("" if args.apply else " (dry run; --apply writes)"))
            return 0
        make_private_dirs(BACKUP_DIR)
        target = BACKUP_DIR / f"{ledger_file.name}.pre-restore-dropped-rows"
        n = 0
        while target.exists():
            n += 1
            target = BACKUP_DIR / f"{ledger_file.name}.pre-restore-dropped-rows-{n}"
        shutil.copyfile(ledger_file, target)
        target.chmod(PRIVATE_FILE_MODE)
        view = view_guard.commit(ledger, args.jobs, ledger_file)
        print(f"written; list rows now {len(view['jobs'])}; ledger backup: {target.name}")
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
