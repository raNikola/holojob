#!/usr/bin/env python3
"""Replay a staged scrape on the ledger as it was before it, and compare with what the old commit wrote (slice S3).

    import_run.py --run RUNID --dry-run [--limit N] [--report-file]
    import_run.py --latest  --dry-run
    import_run.py --latest  --lifecycle-report [--report-file] [--application-job-ids FILE]  what the S5 lifecycle rules would do (lifecycle_report.py); read-only
    import_run.py --run RUNID --import [--allow-older --confirm-overwrite-newer]   recovery: import a staged run that was never imported

--dry-run is read-only. It writes no live file; with --report-file it writes staging/RUNID/import-report.json and nothing else.
--import is the same import a Re-scrape makes (the importer: full validation, ledger then derived view, run marked imported). It
is for a staged run whose import did not happen (the run stopped after staging). It REFUSES a run that started before the last
imported run, with the reason; --allow-older overrides that for recovery only, and is off by default. It prints a warning first
(the import may overwrite newer ledger data with older data) and then needs the flag --confirm-overwrite-newer, or, at a terminal,
the word OVERWRITE typed at the prompt. Without either it refuses and changes nothing. Only this command line passes it: the
live pipeline, the recovery in run_discovery and the Node routes never do (tests/python/test_import.py scans for that).
Both take the pipeline lock (exit 2 when a run is active).

Exit codes (dry run): 0 compared and ZERO differences; 1 differences; 2 error, refused import or a run that is active; 3 nothing to
compare with (the committed files belong to another run: dry-run right after the run you want to check). Import: 0 imported, 2 not.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import importer  # noqa: E402
import lifecycle_report  # noqa: E402
import staging  # noqa: E402

_lock_spec = importlib.util.spec_from_file_location("pipeline_lock", SCRIPT_DIR.parent / "job_scoring" / "pipeline_lock.py")
pipeline_lock = importlib.util.module_from_spec(_lock_spec)
_lock_spec.loader.exec_module(pipeline_lock)


OVERRIDE_WARNING = (
    "WARNING: --allow-older imports a run that started BEFORE the last imported run. Its sightings are older than what the ledger "
    "holds now, so this import may overwrite newer ledger data with older data (lastSeen moves back, ads the newer run closed can "
    "reopen, newer facts can be replaced). Use it only to recover a run that was never imported, and keep a copy of "
    "data/jobs/job_history.json first."
)


def confirmed_override(args, stdin=None) -> bool:
    """True only when the owner has said yes explicitly: the flag, or the word OVERWRITE typed at a terminal. Never assumed."""
    print(OVERRIDE_WARNING, file=sys.stderr)
    if args.confirm_overwrite_newer:
        return True
    stdin = stdin or sys.stdin
    if not stdin.isatty():
        print("Refused: no confirmation. Add --confirm-overwrite-newer, or run it at a terminal and type OVERWRITE.", file=sys.stderr)
        return False
    print("Type OVERWRITE to go on, anything else stops: ", end="", file=sys.stderr, flush=True)
    return stdin.readline().strip() == "OVERWRITE"


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
                         f"source not run or unfinished {rep['heldSourceNotRun']}, board unproven {rep['heldUnproven']}, board not read {rep['heldBoardNotRead']}; "
                         f"listed but filtered {rep['listedButFiltered']}; boards proven complete: {', '.join(rep['boardsProvenComplete']) or 'none'}")
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
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="replay and compare; writes nothing")
    mode.add_argument("--import", dest="do_import", action="store_true", help="import the run for real (recovery)")
    mode.add_argument("--lifecycle-report", action="store_true", help="what the S5 lifecycle rules would do; writes nothing (--report-file: its own file)")
    parser.add_argument("--allow-older", action="store_true", help="with --import: import a run older than the last imported one")
    parser.add_argument("--limit", type=int, default=20, help="how many differences to print (default 20)")
    parser.add_argument("--report-file", action="store_true", help="also write staging/RUNID/import-report.json (the only file written)")
    parser.add_argument("--application-job-ids", type=Path, help="with --lifecycle-report: a file of job ids with an application, one a line; Python does not read the store")
    parser.add_argument("--confirm-overwrite-newer", action="store_true",
                        help="with --allow-older: yes, this may overwrite newer ledger data with older data")
    args = parser.parse_args(argv)
    root = Path(root or ROOT)
    if args.confirm_overwrite_newer and not args.allow_older:
        print("--confirm-overwrite-newer only goes with --allow-older.", file=sys.stderr)
        return 2
    if args.allow_older and not args.do_import:
        print("--allow-older only goes with --import.", file=sys.stderr)
        return 2
    run_id = args.run
    if args.latest:
        runs = staging.list_runs(root)
        if not runs:
            print("No staging runs in data/jobs/staging.", file=sys.stderr)
            return 2
        run_id = runs[0]
    if args.allow_older and not confirmed_override(args):
        print("Nothing was changed.", file=sys.stderr)
        return 2
    lock = pipeline_lock.acquire()
    if lock is None:
        print(pipeline_lock.BUSY_MESSAGE, file=sys.stderr)
        return 2
    if args.lifecycle_report:
        try:
            application_ids = None
            if args.application_job_ids:
                application_ids = {line.strip() for line in args.application_job_ids.read_text(encoding="utf-8").splitlines() if line.strip()}
            report = lifecycle_report.gather(root, run_id, as_of=datetime.now(timezone.utc).isoformat(), application_ids=application_ids)
            for line in lifecycle_report.render(report):
                print(line)
            if args.report_file:
                print(f"Report written: {lifecycle_report.write_report_file(root, run_id, report).relative_to(root)}")
        except (OSError, ValueError) as exc:
            print(f"Lifecycle report stopped: {exc}", file=sys.stderr)
            return 2
        finally:
            lock.release()
        return 0
    if args.do_import:
        try:
            outcome = importer.import_staged_run(root, run_id, allow_older=args.allow_older)
        except Exception as exc:  # noqa: BLE001 - say what stopped; the next reader rebuilds the view if the ledger was written
            print(f"Import stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        finally:
            lock.release()
        if not outcome.ok:
            print(f"Import of run {run_id} REFUSED; nothing was changed:", file=sys.stderr)
            for reason in outcome.refused:
                print(f"  {reason}", file=sys.stderr)
            return 2
        rep = outcome.result.report
        print(f"Imported run {run_id}: generation {outcome.generation}" + (" (it was already imported; the view was checked)" if not outcome.committed else ""))
        if outcome.committed:
            print(f"  ledger: " + ", ".join(f"{k} {v}" for k, v in rep["ledgerChanges"].items()))
            print(f"  complete scrape: {'yes' if rep['complete'] else 'NO (' + ', '.join(rep['incompleteSources'] or ['see the rejections']) + ')'}")
        print(f"  staging: {outcome.usage['runs']} runs, {megabytes(outcome.usage['bytes'])}; removed {outcome.pruned or 'nothing'}")
        return 0
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
