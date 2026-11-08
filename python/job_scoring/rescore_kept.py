#!/usr/bin/env python3
"""Manual Re-score of one kept ad (Wave 2 e). User-triggered; no model call, no network.

Registers the id (kept_ads), scores the ad from the job history ledger with the same score_jobs() a full run uses
(over the list, the hand-entered jobs and the other registered ads), and merges that one row into scored_jobs.json,
keeping its tailoredAssets. Prints one JSON line. Exit: 0 done, 2 bad id, 4 ad not in the ledger or no intelligence,
75 a run is active.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
for extra in (SCRIPT_DIR, ROOT / "python" / "job_import"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import job_history  # noqa: E402
import kept_ads  # noqa: E402
import manual_jobs  # noqa: E402
import pipeline_lock  # noqa: E402
from scorer import score_jobs  # noqa: E402


def run(job_id: str, *, intelligence: Path, jobs: Path, manual: Path, scored: Path, kept: Path) -> tuple[int, dict]:
    if not kept_ads.JOB_ID.match(job_id or ""):
        return 2, {"ok": False, "error": "invalid", "field": "jobId"}
    if not intelligence.exists():
        return 4, {"ok": False, "error": "no_intelligence"}
    ledger = job_history.load(job_history.ledger_path(jobs), read_only=True)
    if kept_ads.ledger_row(ledger, job_id) is None:
        return 4, {"ok": False, "error": "not_in_history"}
    lock = pipeline_lock.acquire()
    if lock is None:
        return 75, {"ok": False, "error": "run_active"}
    try:
        import import_job_url  # noqa: PLC0415

        kept_ads.add(job_id, kept)
        discovered = json.loads(jobs.read_text(encoding="utf-8")) if jobs.exists() else {"jobs": []}
        rows = discovered.get("jobs") if isinstance(discovered, dict) else discovered
        rows = manual_jobs.with_manual(list(rows or []), manual_jobs.load(manual))
        rows = kept_ads.with_kept(rows, job_history.ledger_path(jobs), kept)
        scored_rows = score_jobs(rows, json.loads(intelligence.read_text(encoding="utf-8")))
        row = next((r for r in scored_rows if r.get("jobId") == job_id), None)
        if row is None:
            return 4, {"ok": False, "error": "not_in_history"}
        import_job_url.merge_into_scored([row], scored, meta_key="lastKeptRescoreAt")
        return 0, {"ok": True, "job": row}
    finally:
        lock.release()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Re-score one kept ad.")
    p.add_argument("--job-id", default="")
    p.add_argument("--intelligence", type=Path, default=ROOT / "data/intelligence/candidate-intelligence.json")
    p.add_argument("--jobs", type=Path, default=ROOT / "data/jobs/discovered_jobs.json")
    p.add_argument("--manual", type=Path, default=manual_jobs.MANUAL_PATH)
    p.add_argument("--scored", type=Path, default=ROOT / "data/jobs/scored_jobs.json")
    p.add_argument("--kept", type=Path, default=kept_ads.KEPT_PATH)
    p.add_argument("--prune", metavar="ID,ID", default=None,
                   help="instead of scoring: drop every registered id not in this list (the kept ads and the ads with an application)")
    args = p.parse_args(argv)
    if args.prune is not None:
        keep = {i for i in args.prune.split(",") if i}
        print(json.dumps({"ok": True, "dropped": kept_ads.prune(keep, args.kept)}))
        return 0
    code, body = run(args.job_id, intelligence=args.intelligence, jobs=args.jobs, manual=args.manual, scored=args.scored, kept=args.kept)
    print(json.dumps(body))
    return code


if __name__ == "__main__":
    sys.exit(main())
