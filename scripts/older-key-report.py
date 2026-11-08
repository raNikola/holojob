#!/usr/bin/env python3
"""Counts of the `older_key` rows in the job-history ledger, to choose a retention window. Read-only; prints counts only.

    .venv/bin/python scripts/older-key-report.py [--root DIR] [--application-job-ids FILE] [--protect-ids FILE]

No title, company or link is printed. Without the two id files, applications and browser-only work are NOT joined, and the report
says so: its "would remove" numbers are then an upper bound.

IMPORTANT: Keep, triage statuses, AI insights, outreach state and hand-entered jobs live in the browser. The server cannot see them.
Export their ids (one per line) before any --apply of scripts/prune-older-key.py. In the browser console on the Jobs page:

    const s = JSON.parse(localStorage.getItem('job-dashboard-discovered-jobs')); const jobs = Array.isArray(s) ? s : s.jobs
    copy([...new Set(jobs.filter((j) => j.keptByUser === true || (j.status && j.status !== 'new') || j.manualEntry || j.aiInsights
      || j.tailoredAssets || j.outreach || j.applicationTracking).map((j) => j.jobId))].join('\n'))

Paste that into a file and check the line count against what you expect. Application job ids come from
`podman run ... node scripts/export-application-job-ids.js FILE` (see prune-older-key.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for part in ("python/job_discovery", "python/job_scoring", "python"):
    sys.path.insert(0, str(ROOT / part))

import job_history  # noqa: E402
import older_key_retention as retention  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--application-job-ids", type=Path)
    parser.add_argument("--protect-ids", type=Path)
    args = parser.parse_args(argv)
    ledger = job_history.load(args.root / "data" / "jobs" / job_history.LEDGER_FILE, read_only=True)
    out = retention.report(
        ledger, args.root, now=datetime.now(timezone.utc),
        application_ids=retention.parse_ids(args.application_job_ids), protect_ids=retention.parse_ids(args.protect_ids),
    )
    print(json.dumps(out, indent=2))
    notes = [retention.BROWSER_NOTE]
    if not out["applicationsJoined"]:
        notes.append("Applications were NOT joined (no --application-job-ids): protectedNow and wouldRemove ignore them.")
    if not out["protectIdsGiven"]:
        notes.append("No --protect-ids file: browser-only Keep, statuses and hand-entered jobs are not counted.")
    print("\n".join(f"NOTE: {n}" for n in notes), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
