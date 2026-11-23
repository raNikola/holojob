#!/usr/bin/env python3
"""Multi-provider job discovery runner."""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import signal
import sys
import uuid
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from discovery_common import (  # noqa: E402
    INTELLIGENCE_PATH,
    load_intelligence,
    resolve_search_config,
)
from providers.base_provider import ProviderOutcome  # noqa: E402
from providers.provider_registry import PROVIDER_GROUPS, get_provider, resolve_providers  # noqa: E402
import run_log  # noqa: E402
import source_settings  # noqa: E402
import importer  # noqa: E402
import staging  # noqa: E402

# The ledger lives beside the scorer's shared modules; it is loaded by path so
# that module's siblings do not shadow this package's.
_history_spec = importlib.util.spec_from_file_location(
    "job_history", SCRIPT_DIR.parent / "job_scoring" / "job_history.py"
)
job_history = importlib.util.module_from_spec(_history_spec)
_history_spec.loader.exec_module(job_history)
_guard_spec = importlib.util.spec_from_file_location("view_guard", SCRIPT_DIR.parent / "job_scoring" / "view_guard.py")
view_guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(view_guard)
_lock_spec = importlib.util.spec_from_file_location(
    "pipeline_lock", SCRIPT_DIR.parent / "job_scoring" / "pipeline_lock.py"
)
pipeline_lock = importlib.util.module_from_spec(_lock_spec)
_lock_spec.loader.exec_module(pipeline_lock)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class RunCancelled(BaseException):
    """Raised by SIGTERM, only while the scrape loop runs. A BaseException, so no provider's `except Exception` can swallow it."""


class CancelState:
    """What a cancel may do to this process (S6). SIGTERM raises RunCancelled only while `interruptible`, which is the source loop and
    nothing else: staging is append-only there and the ledger is not touched. Everywhere else, and always from the moment the commit is
    claimed, the signal only sets `pending`, and the code looks at it at the points it chose. So a cancel can never land inside the
    import's writes: it either arrives before the claim (the run saves its collected ads only) or after (the import finishes)."""

    def __init__(self) -> None:
        self.interruptible = False
        self.pending = False

    def handle(self, _signum, _frame) -> None:
        self.pending = True
        if self.interruptible:
            self.interruptible = False
            raise RunCancelled()

    def install(self) -> "CancelState":
        signal.signal(signal.SIGTERM, self.handle)
        return self

    def wants_stop(self, record: dict) -> bool:
        return self.pending or run_log.cancel_requested(record)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run multi-provider job discovery.")
    parser.add_argument(
        "--providers",
        default="serbia",
        help=(
            "Comma-separated provider names or group: "
            f"{', '.join(PROVIDER_GROUPS)}"
        ),
    )
    parser.add_argument(
        "--country",
        help="Country filter. Overrides the country in the candidate intelligence.",
    )
    parser.add_argument(
        "--locations",
        nargs="+",
        help="Location filters. Overrides intelligence locationFilters.",
    )
    parser.add_argument(
        "--intelligence",
        type=Path,
        default=INTELLIGENCE_PATH,
        help="Path to candidate-intelligence.json",
    )
    parser.add_argument(
        "--trigger",
        choices=run_log.TRIGGERS,
        default="manual",
        help="What started this run, for the run log. run_pipeline.py passes pipeline.",
    )
    parser.add_argument(
        "--exclude",
        default="",
        help="Comma-separated sources to skip in this run only (the saved switches are not changed).",
    )
    parser.add_argument(
        "--run-id",
        help="run_rescrape.py: fill this run's record and leave finishing it to the orchestrator.",
    )
    return parser.parse_args()


def effective_provider_names(spec: str | None) -> list[str]:
    """The providers this run uses: the request, with the owner's opt-in switches applied.

    The switches in data/config/sources.json are the gate, not the request: an opt-in
    source that is off never runs, even when the request names it.
    """
    try:
        settings = source_settings.read()
    except source_settings.SourcesError as exc:
        logger.warning("Source settings unusable (%s); every opt-in source is off for this run", exc)
        settings = None
    names, dropped = source_settings.effective_providers(spec, resolve_providers(spec), settings)
    for name in dropped:
        logger.warning("Skipping %s: an opt-in source that is off; %s", name, source_settings.OFF_HINT)
    return names


def apply_owner_skips(names: list[str], exclude: list[str] | None) -> tuple[list[str], list[tuple[str, str]]]:
    """Takes out the sources the owner switched off in Settings > Sources and the one-off `--exclude` names.
    Unreadable settings switch nothing off here (effective_provider_names already keeps the opt-in sources off)."""
    try:
        settings = source_settings.read()
    except source_settings.SourcesError:
        settings = None
    return source_settings.owner_skips(names, settings, exclude)


def main() -> int:
    args = parse_args()
    lock = pipeline_lock.acquire()
    if lock is None:
        print(pipeline_lock.BUSY_MESSAGE, file=sys.stderr)
        return pipeline_lock.EXIT_LOCKED
    try:
        return run_locked(args)
    finally:
        lock.release()


def run_locked(args: argparse.Namespace) -> int:
    managed = bool(args.run_id)
    if managed:
        record = run_log.find_record(args.run_id)
        if record is None:
            logger.error("No run record for %s", args.run_id)
            return 1
    else:
        run_log.sweep_interrupted()
        record = run_log.new_record(uuid.uuid4().hex[:12], args.trigger)
        run_log.save(record)
        run_log.event(record, "run_start", trigger=args.trigger)
    run_log.report_incomplete_commit(record)
    code = 1
    cancel = CancelState().install() if managed else None  # only the Re-scrape orchestrator cancels; a direct run keeps SIGTERM's default
    try:
        code = discover(args, record, cancel)
        return code
    except Exception as exc:
        run_log.add_issue(record, "error", f"Discovery stopped: {exc}")
        run_log.event(record, "error", message=f"Discovery stopped: {exc}")
        raise
    finally:
        # Here, not in a caller: a manual Re-scrape and a pipeline run both come through this one line.
        if managed:
            run_log.save(record)  # still running: scoring comes next, and the orchestrator finishes the record
        else:
            run_log.save(run_log.finish(record, exit_ok=code == 0))
            run_log.event(record, "run_end", status=record["status"])


NO_USABLE_SOURCE_TEXT = "No source gave a usable result, so nothing was imported and the job list was not changed."


def stop(record: dict, message: str) -> int:
    """A run that cannot start: reported like any other failed run."""
    logger.error("%s", message)
    run_log.add_issue(record, "error", message)
    run_log.event(record, "error", message=message)
    return 1


def cancelled_without_staging(record: dict) -> int:
    """Cancelled before the scrape began: nothing was collected, nothing is saved, no file other than the record changes."""
    record["cancel"] = {"requestedAt": run_log.cancel_info(record).get("requestedAt"), "outcome": "stopped_nothing_imported"}
    run_log.event(record, "cancelled", imported=0, sourcesDone=0)
    return run_log.EXIT_CANCELLED


def fetch_source(
    provider, name: str, search_terms, locations, remote_filters, country, stage=None
) -> tuple[list[dict], ProviderOutcome]:
    """One provider's jobs and outcome. A provider that raises is one failed source, not a stopped run.

    `stage` is the source's staging file. A provider may have appended to it while it collected; when the fetch is over
    (or has raised) the source's footer is written, and a provider that appended nothing has its list staged whole.
    Staging copies what the source returns and changes nothing of it.
    """
    try:
        provider.stage_writer = stage
    except AttributeError:
        pass  # a provider that cannot hold it is staged whole when it returns
    try:
        jobs = provider.fetch_jobs(search_terms, locations, remote_filters, country)
        if provider.last_outcome is None:
            raise RuntimeError("the provider reported no outcome")
        result = jobs, provider.last_outcome
    except Exception as exc:
        logger.exception("Provider %s failed", name)
        result = [], ProviderOutcome(status="failed", error=str(exc))
    finally:
        try:
            provider.stage_writer = None
        except AttributeError:
            pass
    if stage is not None:
        stage.close_source(*result)
    return result


def discover(args: argparse.Namespace, record: dict, cancel: CancelState | None = None) -> int:
    source_run_id = record["runId"]

    intelligence = load_intelligence(args.intelligence)
    try:
        config = resolve_search_config(
            intelligence,
            country=args.country,
            locations=args.locations,
        )
    except ValueError as exc:
        return stop(record, str(exc))
    search_terms = config["search_terms"]
    locations = config["locations"]
    remote_filters = config["remote_filters"]
    country = config["country"]

    if not search_terms:
        return stop(record, "No jobSpySearchTerms found in intelligence file.")

    provider_names = effective_provider_names(args.providers)
    if not provider_names:
        return stop(record, f"No valid providers resolved from: {args.providers}")
    provider_names, owner_skipped = apply_owner_skips(provider_names, [p for p in (args.exclude or "").split(",")])
    for name, reason in owner_skipped:
        # Not staged and not in the manifest: the importer sees a source that did not run and keeps its ads as they are.
        logger.info("Not running %s: %s", name, reason)
        run_log.add_source(record, name, ProviderOutcome(status="skipped", skip_reason=reason))
        run_log.event(record, "source_end", source=name, status="skipped", read=0, kept=0, readClass="skipped", error=None, skipReason=reason)
    if owner_skipped:
        run_log.save(record)
    if not provider_names:
        return stop(record, "Every requested source is switched off, so nothing ran. Switch one on in Settings > Sources.")

    # A view left behind by a stopped commit is rebuilt first, so the discovered file the run keeps beside its staging (and
    # takes facts from) is the one the ledger says it is.
    jobs_file = ROOT / "data" / "jobs" / "discovered_jobs.json"
    try:
        view_guard.ensure(jobs_file, job_history.ledger_path(jobs_file))
    except view_guard.ViewRecoveryError as exc:
        return stop(record, f"The job list is out of date and could not be rebuilt: {exc}")

    if cancel and cancel.wants_stop(record):
        return cancelled_without_staging(record)

    # What the scrape collects is written to data/jobs/staging/<runId>/ as it comes; the importer reads it from there. The
    # ledger and the discovered file as they are now are kept beside it, because the import replaces both.
    search_key = job_history.search_key(search_terms, locations, country, remote_filters)
    stage_run = staging.StagingRun.begin(
        ROOT, record["runId"], search_key=search_key, terms=search_terms, locations=locations, country=country,
        remote_filters=remote_filters, providers=provider_names,
        ledger_path=job_history.ledger_path(ROOT / "data" / "jobs" / "discovered_jobs.json"),
        discovered_path=ROOT / "data" / "jobs" / "discovered_jobs.json",
    )

    all_jobs: list[dict] = []
    provider_counts: dict[str, int] = {}

    cancelled = False
    if cancel:
        cancel.interruptible = True
    try:
        for name in provider_names:
            if cancel and cancel.wants_stop(record):
                cancelled = True
                break
            logger.info("Running provider: %s", name)
            provider = get_provider(name)
            run_log.event(record, "source_start", source=name)
            source_started = run_log.now_iso()
            jobs, outcome = fetch_source(
                provider, name, search_terms, locations, remote_filters, country, stage=stage_run.open_source(name)
            )
            run_log.add_source(record, name, outcome)
            record["sources"][-1].update(startedAt=source_started, finishedAt=run_log.now_iso())
            run_log.save(record)
            run_log.event(record, "source_end", source=name, status=outcome.status, read=outcome.read, kept=outcome.kept,
                          readClass=record["sources"][-1]["readClass"], error=outcome.error, skipReason=outcome.skip_reason)
            provider_counts[name] = len(jobs)
            all_jobs.extend(jobs)
            logger.info("Provider %s returned %d jobs", name, len(jobs))
        if cancel:
            cancel.interruptible = False  # inside the try: a signal before this line is still caught below
    except RunCancelled:
        cancelled = True  # the source in flight has no footer: the importer treats it as unfinished
    if cancel:
        cancel.interruptible = False
    if cancelled:
        run_log.event(record, "scrape_stopped", reason="cancelled", sourcesDone=len(record["sources"]))

    for warning in stage_run.warnings:
        run_log.add_issue(record, "warning", warning)
    staging_ok, staging_problems = stage_run.finish()
    run_log.set_staging(record, staging_ok, staging_problems)

    raw_count = len(all_jobs)
    if not staging_ok:
        # What was collected is not safely on disk, so it is not imported as if it were a complete scrape. Nothing is
        # committed: the ledger and the view stay exactly as they were, and the run says so.
        return stop(record, "Nothing was imported: staging failed (" + "; ".join(staging_problems[:3]) + "). The ledger and the job list are unchanged.")

    if cancel:
        # The commit point. From here a signal only sets a flag. Exactly one of this claim and the orchestrator's "kill" claim succeeds:
        # a run that holds "commit" is never killed, and one that lost it never starts to write.
        if not run_log.claim(record, "commit"):
            run_log.event(record, "error", message="The orchestrator stopped this step before its import; nothing was imported.")
            return run_log.EXIT_CANCELLED
        cancelled = cancelled or cancel.wants_stop(record)  # a request that arrived while the claim was made still cancels the scrape
    if cancelled:
        try:
            staging.mark_cancelled(ROOT, source_run_id, {"requestedAt": run_log.cancel_info(record).get("requestedAt")})
        except (OSError, ValueError) as exc:
            return stop(record, f"The run was cancelled but its staging could not be marked, so nothing was imported: {exc}")

    # The switch (S4a): what the scrape wrote to staging is imported by the importer, the ledger is the one source of truth and
    # discovered_jobs.json is derived from it. The commit is: ledger, then view (view_guard.commit). No marker: a stop between
    # the two writes leaves a view one generation behind, which every reader rebuilds before it uses it.
    run_log.event(record, "commit_start", files=["job_history", "discovered_jobs"])
    try:
        outcome = importer.import_staged_run(ROOT, source_run_id, require_usable=True)
    except (view_guard.ViewRecoveryError, OSError) as exc:
        return stop(record, f"The import stopped while writing: {exc}. The next reader rebuilds the job list from the ledger.")
    if not outcome.ok:
        record["import"] = {"kind": "refused", "saved": 0, "new": 0, "refreshed": 0, "sources": []}
        return stop(record, "Import refused: " + "; ".join(outcome.refused))
    if not cancelled and outcome.result.report.get("nothingSaved") == importer.NO_USABLE_SOURCE:
        # S8b: no source gave a usable result (all skipped, failed, partial, unfinished or held as not run). Nothing was written: the list,
        # the ledger and the view are as the last run left them. The run is still recorded, with its sources and this reason.
        record["import"] = importer.evidence_block(outcome.result.report, outcome.result.stats)
        run_log.set_staging_usage(record, outcome.usage)
        if all(one.get("state") == "skipped" for one in outcome.result.report.get("sources") or []):
            # Skipped is not failed: nothing was searched, so nothing went wrong. Exit 0 keeps the record's status "skipped" (run_log.finish);
            # the orchestrator sees the reason in the record and does not score a list that did not change.
            run_log.add_issue(record, "warning", NO_USABLE_SOURCE_TEXT)
            print(NO_USABLE_SOURCE_TEXT)
            return 0
        return stop(record, NO_USABLE_SOURCE_TEXT)  # scraping was attempted and nothing came of it: a failed run
    run_log.clear_commit_marker(record)  # a marker left by the old commit protocol: this commit finished, so the files agree again
    run_log.event(record, "commit_end", files=["job_history", "discovered_jobs"])
    result = outcome.result
    record["import"] = importer.evidence_block(result.report, result.stats)
    if cancelled:
        # S6: only the ads collected were saved (importer._plan_partial). The list, the lifecycle and the proven runs were not touched.
        run_log.set_new_counts(record, Counter(result.new_by_provider))
        run_log.set_staging_usage(record, outcome.usage)
        for warning in outcome.warnings:
            logger.warning("%s", warning)
        record["cancel"] = {"requestedAt": run_log.cancel_info(record).get("requestedAt"), "outcome": "collected_ads_saved", "saved": outcome.saved}
        run_log.event(record, "cancelled", saved=outcome.saved, sourcesDone=len(record["sources"]))
        print(f"Cancelled. {outcome.saved} collected ads saved. Nothing else changed." if outcome.saved else "Cancelled. No ads were saved. Nothing else changed.")
        return run_log.EXIT_CANCELLED
    history_stats = result.stats
    to_write = result.view["jobs"]
    run_log.set_new_counts(record, Counter(result.new_by_provider))
    run_log.set_staging_usage(record, outcome.usage)
    logger.info("Staging: %d runs, %.1f MB on disk; removed %s", outcome.usage["runs"], outcome.usage["bytes"] / 1e6, outcome.pruned or "nothing")
    for warning in result.report.get("warnings", []):
        run_log.add_issue(record, "warning", warning)
        logger.warning("%s", warning)
    for warning in outcome.warnings:  # the log only: the store of dropped ads has no screen yet (S5e1)
        logger.warning("%s", warning)
    if not result.report.get("complete"):
        logger.info("Import: not a complete scrape (%s)", ", ".join(result.report.get("incompleteSources") or ["see the report"]))

    found_count = result.view["meta"]["dedupedCount"]
    discovered_path = ROOT / "data" / "jobs" / "discovered_jobs.json"

    print("")
    print("===================================")
    print("MULTI-PROVIDER DISCOVERY SUMMARY")
    print("===================================")
    print("")
    print("Providers:", ", ".join(provider_names))
    print("Country:", country)
    print("Search Terms:", ", ".join(search_terms))
    print("Locations:", ", ".join(locations))
    print("Remote Filters:", ", ".join(remote_filters))
    print("")
    for name in provider_names:
        print(f"  {name}: {provider_counts.get(name, 0)} jobs")
    print("")
    print(f"Raw Jobs: {raw_count}")
    print(f"Deduped Jobs: {found_count}")
    print(f"Duplicates Removed: {max(0, raw_count - found_count)}")
    print("")
    print("Job history:")
    print(f"  new {history_stats['new']}, already known {history_stats['known']}, "
          f"reopened {history_stats['reopened']}, absent from a proven board {history_stats['absent']}, closed this run {history_stats['closed']}")
    print(f"  facts carried over {history_stats['carriedFacts']}, "
          f"ads changed since last run {history_stats['changed']}, "
          f"fuller description kept over a throttled one {history_stats['keptFullerDescription']}")
    print(f"  ads kept open: {history_stats['keptFailedBoard']} of unread boards, {history_stats['keptEmptyBoard']} of empty boards, "
          f"{history_stats['keptSourceNotRun']} of sources that did not run, {history_stats['keptUnproven']} of unproven boards, "
          f"{history_stats['keptBoardNotRead']} of boards not read")
    closed_written = sum(1 for job in to_write if job.get("isClosed"))
    print(f"  absent rows shown: {sum(1 for job in to_write if job.get('isAbsent') and not job.get('isClosed'))}")
    print(f"  jobs written: {len(to_write)} ({closed_written} closed, kept {job_history.CLOSED_KEEP_DAYS} days)")
    print("")
    print(f"Output: {discovered_path.relative_to(ROOT)}")
    print("===================================")
    print("")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
