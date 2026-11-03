#!/usr/bin/env python3
"""Replay a staged scrape on the ledger as it was before it, and compare with what the old commit wrote (slice S3).

    import_run.py --run RUNID --dry-run [--limit N] [--report-file]
    import_run.py --latest  --dry-run

Read-only. It writes no live file; with --report-file it writes staging/RUNID/import-report.json and nothing else. It takes the
pipeline lock while it reads, so a run cannot be half way through its commit under it (it stops with 2 when one is active).
A real import is not built yet (slice S4a): without --dry-run this refuses.

Exit codes: 0 compared and ZERO differences; 1 differences; 2 error, refused import or a run that is active; 3 nothing to compare
with (the committed files belong to another run: dry-run right after the run you want to check).
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import importer  # noqa: E402
import staging  # noqa: E402

_lock_spec = importlib.util.spec_from_file_location("pipeline_lock", SCRIPT_DIR.parent / "job_scoring" / "pipeline_lock.py")
pipeline_lock = importlib.util.module_from_spec(_lock_spec)
_lock_spec.loader.exec_module(pipeline_lock)


def megabytes(size: int) -> str:
    return f"{size / 1_000_000:.1f} MB"


def render(dry: importer.DryRun, limit: int) -> list[str]:
    lines = [f"Import dry-run of run {dry.run_id}  (read-only; nothing was written)"]
    used = dry.usage
    lines.append(f"Staging on disk: {used.get('runs', 0)} runs, {used.get('files', 0)} files, {megabytes(used.get('bytes', 0))} "
                 "(each hard-linked data file counted once; nothing deletes a staging run yet)")
    result = dry.result
    for error in dry.errors:
        lines.append(f"ERROR: {error}")
    if result and result.report:
        rep = result.report
        lines.append(f"Staging: {rep.get('stagingStatus', '?')}; replay {'exact' if dry.replay_exact else 'NOT exact (the discovered file before the run was not kept)'}; "
                     f"import time {dry.time_used}")
        lines.append("Sources:")
        for source in rep["sources"]:
            note = "; ".join(source["anomalies"])
            lines.append(f"  {source['name']:<11} {source['state']:<10} staged {source['staged']:>5}  imported {source['imported']:>5}"
                         f"  rejected {source['rejected']}" + ("  [held as not run]" if source["heldAsNotRun"] else "")
                         + (f"  ({note})" if note else "") + ("  [last line torn]" if source["torn"] else ""))
        if result.ok:
            changes = rep["ledgerChanges"]
            lines.append(f"Import: duplicates removed {rep['duplicatesRemoved']}, cross-posts merged {rep['crosspostsMerged']}, "
                         f"rejected as invalid {rep['rejected']}, thin description replaced by the stored one {rep['thinDescriptionReplaced']}")
            lines.append(f"Held open: failed board {rep['heldFailedBoard']}, empty board {rep['heldEmptyBoard']}, "
                         f"source not run or unfinished {rep['heldSourceNotRun']}")
            lines.append("Ledger: " + ", ".join(f"{k} {v}" for k, v in changes.items()))
            lines.append(f"Complete scrape: {'yes' if rep['complete'] else 'NO (' + ', '.join(rep['incompleteSources'] or ['see rejections']) + ')'}")
            if rep["reasons"]:
                lines.append("Rejections: " + ", ".join(f"{k} x{v}" for k, v in rep["reasons"].items()))
            for example in rep["rejectedExamples"][:5]:
                lines.append(f"  rejected: {example['source']} {example['jobId']} {example['title']!r}: {', '.join(example['reasons'])}")
    if result and not result.ok:
        return lines
    if dry.errors:
        return lines
    if not dry.comparable:
        lines.append(f"Compared with the committed files: NOT POSSIBLE. They belong to run {dry.committed_run_id!r}, not to this one.")
        lines.append(f"derive_view vs replay: {dry.derived_vs_replay.total} differences")
    else:
        lines.append(f"Compared with the committed files of this run:")
        lines.append(f"  ledger, replay vs committed:            {dry.ledger_diff.total} differences")
        lines.append(f"  discovered_jobs.json, replay vs committed: {dry.view_diff.total} differences")
        lines.append(f"  derive_view vs replay:                  {dry.derived_vs_replay.total} differences")
        lines.append(f"  derive_view vs committed:               {dry.derived_vs_committed.total} differences")
    lines.append("Excluded as volatile (never counted): " + "; ".join(importer.EXCLUDED))
    shown = 0
    for label, diff in (("ledger", dry.ledger_diff), ("discovered_jobs.json", dry.view_diff),
                        ("derive_view vs replay", dry.derived_vs_replay), ("derive_view vs committed", dry.derived_vs_committed)):
        for item in diff.items:
            if shown >= limit:
                break
            lines.append(f"  [{label}] {item}")
            shown += 1
    if dry.difference_count > shown:
        lines.append(f"  ... {dry.difference_count - shown} more differences not shown (--limit)")
    if dry.comparable:
        lines.append("RESULT: ZERO DIFFERENCES" if dry.difference_count == 0 else f"RESULT: {dry.difference_count} DIFFERENCES")
    else:
        lines.append("RESULT: NOTHING TO COMPARE WITH")
    return lines


def exit_code(dry: importer.DryRun) -> int:
    if dry.errors or (dry.result and not dry.result.ok):
        return 2
    if not dry.comparable:
        return 3
    return 0 if dry.difference_count == 0 else 1


def main(argv=None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--run", help="the run id (a folder in data/jobs/staging)")
    which.add_argument("--latest", action="store_true", help="the newest run in staging")
    parser.add_argument("--dry-run", action="store_true", help="required: a real import is not built yet")
    parser.add_argument("--limit", type=int, default=20, help="how many differences to print (default 20)")
    parser.add_argument("--report-file", action="store_true", help="also write staging/RUNID/import-report.json (the only file written)")
    args = parser.parse_args(argv)
    root = Path(root or ROOT)
    if not args.dry_run:
        print("A real import is not built yet (slice S4a). Use --dry-run.", file=sys.stderr)
        return 2
    run_id = args.run
    if args.latest:
        runs = staging.list_runs(root)
        if not runs:
            print("No staging runs in data/jobs/staging.", file=sys.stderr)
            return 2
        run_id = runs[0]
    lock = pipeline_lock.acquire()
    if lock is None:
        print(pipeline_lock.BUSY_MESSAGE, file=sys.stderr)
        return 2
    try:
        dry = importer.dry_run(root, run_id)
    finally:
        lock.release()
    for line in render(dry, max(0, args.limit)):
        print(line)
    if args.report_file:
        try:
            print(f"Report written: {importer.write_report(root, run_id, dry).relative_to(root)}")
        except (OSError, ValueError) as exc:
            print(f"Report not written: {exc}", file=sys.stderr)
            return 2
    return exit_code(dry)


if __name__ == "__main__":
    raise SystemExit(main())
