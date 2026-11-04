"""The run log: one record per discovery run, for the Activity screen.

run_discovery.py writes it, so a manual Re-scrape and a pipeline run each log exactly once. One file per run,
data/analytics/runs/<startedAt, UTC>-<runId>.json (HOLOJOB_ANALYTICS_DIR moves the folder). Files are 600, folders 700.
The pipeline lock (job_scoring/pipeline_lock.py) means only one run writes at a time.

Written at the start (status running) and again after each source, so a killed run leaves a record that says so. Beside it
<same name>.events.jsonl is the run's append-only event log, one JSON object per line, and .commit-in-progress.json is
the commit marker: on disk only while discovery replaces its output files.

Record, version 1. A later slice adds fields; a reader ignores what it does not know and treats a missing one as unknown:

    {
      "version": 1,
      "runId": "<discovered_jobs.json meta.sourceRunId>",
      "trigger": "manual" | "pipeline" | "scheduled",
      "startedAt": "<ISO>", "finishedAt": "<ISO>" | null,
      "status": "running" | "ok" | "partial" | "failed" | "skipped" | "interrupted" | "cancelled",
      "sources": [{"name", "status": "ok" | "partial" | "failed" | "skipped", "read", "kept", "new", "error",
                   "boardsFailed", "skipReason"}],
      "issues": [{"level": "error" | "warning", "source": "<name>" | null, "message"}],
      "staging": {"ok": true | false, "problems": ["..."]}      (S3; absent in older records = unknown)
    }

read: ads parsed before the search, role and location filters. kept: past them, before dedupe. new: ads no earlier run
recorded, counted after dedupe under the provider of the copy that won, so `new` is not a share of `kept`, and summed it
equals meta.history.new. skipped: the source did not search because it does not apply (skipReason says why); it is no
warning and does not lower the run's status; a run is skipped only when every source was. Left out because discovery does not know them yet: scored, closed, missing,
expired.

running: not finished, or dead and not noticed yet; the lock tells which. interrupted: found running with the lock free, so
nobody saw it end and finishedAt stays null. It is reported, never resumed. A Re-scrape (python/run_rescrape.py) adds
"steps": [{"name", "status", "startedAt", "finishedAt", "exitCode"}]; an interrupted record may add "incompleteCommit".

cancelled (S6): the owner cancelled a Re-scrape before its import commit point. The scrape stopped and scoring was skipped. The ads it
had validly collected were SAVED and nothing else changed: no ad became held, absent, closed or Stale, the list was not rebuilt, no
proven run was recorded, `appliedRuns` was not touched. A cancelled record adds `"cancel": {"requestedAt", "outcome", "saved"}`, outcome
`collected_ads_saved` (`saved` may be 0) or `stopped_nothing_imported` (the process had to be killed, or the cancel came before anything
was collected). A cancel that arrives once the commit is claimed does not cancel anything: the import finishes as any import, scoring is
skipped, the status is the run's own and `cancel.outcome` is `imported_before_cancel`. A step's status may be "cancelled" too; never a failure.

A request is a file beside the record, `<same name>.cancel`; the commit/kill arbitration is `<same name>.decision`. Both are keyed by the
run id, so a request for one run can never touch the next, and `prune` removes them with the record.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Loaded by path, as export_jobs does: job_scoring on sys.path would let its modules shadow this package's.
_atomic_spec = importlib.util.spec_from_file_location(
    "_run_log_atomic_write", ROOT / "python" / "job_scoring" / "atomic_write.py"
)
_atomic = importlib.util.module_from_spec(_atomic_spec)
_atomic_spec.loader.exec_module(_atomic)

logger = logging.getLogger(__name__)

VERSION = 1
RETENTION_DAYS = 90
TRIGGERS = ("manual", "pipeline", "scheduled")
EXIT_CANCELLED = 76  # a discovery step that stopped because it was cancelled (and saved what it had validly collected)
SOURCE_STATUSES = ("ok", "partial", "failed", "skipped")
RUN_STATUSES = ("ok", "partial", "failed", "skipped", "running", "interrupted", "cancelled")
MAX_MESSAGE_CHARS = 500

_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_RECORD_NAME = re.compile(r"^\d{8}T\d{6}Z-[^/]+\.json$")
_FILE_NAME = re.compile(r"^(\d{8}T\d{6}Z)-[^/]+\.(?:json|events\.jsonl|cancel|decision)$")
_COMMIT_MARKER = ".commit-in-progress.json"
_CREDENTIAL = re.compile(r"(?i)\b(api_?key|key|token|li_at|password|secret|authorization)=[^&\s]+")
_KEY_SHAPED = re.compile(r"\b(sk-|AIza)[A-Za-z0-9_-]{8,}")


def runs_dir() -> Path:
    return Path(os.environ.get("HOLOJOB_ANALYTICS_DIR") or ROOT / "data" / "analytics") / "runs"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(message) -> str:
    """Exception text can carry a whole request URL: no credential gets in, and one long message cannot bloat a record."""
    text = _CREDENTIAL.sub(lambda m: f"{m[1]}=[masked]", str(message))
    return _KEY_SHAPED.sub("[masked]", text)[:MAX_MESSAGE_CHARS]


def new_record(run_id: str, trigger: str) -> dict:
    if trigger not in TRIGGERS:
        raise ValueError(f"Unknown trigger: {trigger}")
    return {
        "version": VERSION,
        "runId": run_id,
        "trigger": trigger,
        "startedAt": _now().isoformat(),
        "finishedAt": None,
        "status": "running",  # until finish(), or until a later look finds it dead (mark_interrupted)
        "sources": [],
        "issues": [],
    }


def add_issue(record: dict, level: str, message: str, source: str | None = None) -> None:
    record["issues"].append({"level": level, "source": source, "message": _clean(message)})


def add_source(record: dict, name: str, outcome) -> None:
    """One source's row and its issues. 0 ads is a warning: it says something may be wrong, and it never closes an ad."""
    if outcome.status not in SOURCE_STATUSES:
        raise ValueError(f"Unknown source status: {outcome.status}")
    error = _clean(outcome.error) if outcome.error else None
    record["sources"].append({
        "name": name,
        "status": outcome.status,
        "read": outcome.read,
        "kept": outcome.kept,
        "new": 0,
        "error": error,
        "boardsFailed": list(outcome.boards_failed),
        "skipReason": outcome.skip_reason,
    })
    if error:
        add_issue(record, "error", error, name)
    for warning in outcome.warnings:
        add_issue(record, "warning", warning, name)
    if outcome.kept == 0 and outcome.status not in ("failed", "skipped"):
        detail = f"read {outcome.read}, all filtered out" if outcome.read else "read 0"
        add_issue(record, "warning", f"0 ads kept ({detail}); nothing was closed for this source", name)


def set_staging(record: dict, ok: bool, problems: list[str]) -> None:
    """Did staging (the copy of what the scrape collected, see staging.py) itself work? A failure is an error in the record,
    and a run that would be `ok` is `partial`: it is not fully saved, and an import must not take its staging for a complete
    scrape. Discovery's own output is not affected."""
    record["staging"] = {"ok": bool(ok), "problems": [_clean(problem) for problem in problems][:10]}
    if not ok:
        add_issue(record, "error", "Staging failed, so this run is not fully saved: " + "; ".join(problems[:3]))


def set_staging_usage(record: dict, usage: dict) -> None:
    """How much room staging takes after this run's import and pruning (staging.usage)."""
    record.setdefault("staging", {"ok": True, "problems": []}).update(
        runs=int(usage.get("runs", 0)), bytes=int(usage.get("bytes", 0))
    )


def clear_commit_marker(record: dict) -> None:
    """A commit marker left by the pre-S4a commit protocol is stale once a commit has finished: the files agree again."""
    try:
        if commit_marker_path().exists():
            commit_marker_path().unlink()
            event(record, "commit_end", files=["marker cleared after a finished commit"])
    except OSError as exc:
        add_issue(record, "warning", f"An old commit marker could not be removed: {exc}")


def set_new_counts(record: dict, counts: dict[str, int]) -> None:
    for source in record["sources"]:
        source["new"] = counts.get(source["name"], 0)


def finish(record: dict, *, exit_ok: bool, cancelled: bool = False) -> dict:
    if cancelled:
        record["status"] = "cancelled"  # its own outcome: not a failure, and never "ok" (the scrape did not run to its end)
        record["finishedAt"] = _now().isoformat()
        return record
    all_statuses = [source["status"] for source in record["sources"]]
    statuses = [status for status in all_statuses if status != "skipped"]  # a skipped source says nothing about the run
    if not exit_ok or not all_statuses or (statuses and all(status == "failed" for status in statuses)):
        record["status"] = "failed"
    elif not statuses:
        record["status"] = "skipped"
        add_issue(record, "warning", "Every source was skipped: no source searched in this run")
    elif any(status != "ok" for status in statuses):
        record["status"] = "partial"
    else:
        record["status"] = "ok"
    if record.get("staging", {}).get("ok") is False and record["status"] == "ok":
        record["status"] = "partial"  # not fully saved: the staging copy is incomplete
    record["finishedAt"] = _now().isoformat()
    return record


def prune(folder: Path, now: datetime | None = None) -> int:
    """Remove records and event logs that started more than RETENTION_DAYS ago, read from the file name; returns how many."""
    cutoff = (now or _now()) - timedelta(days=RETENTION_DAYS)
    removed = 0
    for path in folder.iterdir():
        match = _FILE_NAME.match(path.name)
        if not match:
            continue
        try:
            started = datetime.strptime(match[1], _STAMP_FORMAT).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if started < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def is_record_name(name: str) -> bool:
    return bool(_RECORD_NAME.match(name))


def record_path(record: dict) -> Path:
    started = datetime.fromisoformat(record["startedAt"]).astimezone(timezone.utc)
    return runs_dir() / f"{started.strftime(_STAMP_FORMAT)}-{record['runId']}.json"


def events_path(record: dict) -> Path:
    return record_path(record).with_suffix(".events.jsonl")


def _records() -> list[dict]:
    """Every readable record on disk. One unreadable file is skipped: it cannot be told apart from foreign data."""
    found = []
    folder = runs_dir()
    if not folder.is_dir():
        return found
    for path in sorted(folder.iterdir()):
        if not is_record_name(path.name):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("runId") and record.get("startedAt"):
            found.append(record)
    return found


def find_record(run_id: str) -> dict | None:
    return next((record for record in _records() if record["runId"] == run_id), None)


# --- cancel (S6) ------------------------------------------------------------------------------------------------------


def cancel_path(record: dict) -> Path:
    return record_path(record).with_suffix(".cancel")


def decision_path(record: dict) -> Path:
    return record_path(record).with_suffix(".decision")


def _create_new(path: Path, text: str) -> bool:
    """Create `path` and write `text` in one write; False when it already exists. Exactly one caller wins (O_EXCL)."""
    _atomic.make_private_dirs(path.parent)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, _atomic.PRIVATE_FILE_MODE)
    except FileExistsError:
        return False
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    return True


def request_cancel(record: dict) -> bool:
    """Ask the run to stop. True when this call made the request, False when one was already there. Touches no lock and no data file."""
    return _create_new(cancel_path(record), json.dumps({"requestedAt": _now().isoformat()}))


def withdraw_cancel(record: dict) -> None:
    cancel_path(record).unlink(missing_ok=True)


def cancel_requested(record: dict) -> bool:
    return cancel_path(record).exists()


def cancel_info(record: dict) -> dict:
    try:
        info = json.loads(cancel_path(record).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"requestedAt": None}
    return info if isinstance(info, dict) else {"requestedAt": None}


def claim(record: dict, role: str) -> bool:
    """The one decision between the import and a hard kill. The discovery process claims "commit" before it imports; the orchestrator
    claims "kill" before it SIGKILLs a step that ignored SIGTERM. O_EXCL lets exactly one of them have it: a run that has claimed
    "commit" is never killed, and one that has been claimed for "kill" never starts to commit."""
    if role not in ("commit", "kill"):
        raise ValueError(role)
    return _create_new(decision_path(record), role)


def decision(record: dict) -> str | None:
    try:
        return decision_path(record).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _clean_fields(fields: dict) -> dict:
    return {key: _clean(value) if isinstance(value, str) else value for key, value in fields.items()}


def event(record: dict, kind: str, **fields) -> None:
    """Append one event: O_APPEND and one os.write, so a line is whole or absent and a reader can follow along.

    A writer killed mid-line leaves no newline; the next writer ends that line first, so a torn line never swallows an
    event. A report on the run: a failure here is logged and never fails the run.
    """
    try:
        path = events_path(record)
        _atomic.make_private_dirs(path.parent)
        line = {"type": kind, "at": _now().isoformat(), **_clean_fields(fields)}
        fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, _atomic.PRIVATE_FILE_MODE)
        try:
            size = os.fstat(fd).st_size
            torn = size > 0 and os.pread(fd, 1, size - 1) != b"\n"
            os.write(fd, (b"\n" if torn else b"") + json.dumps(line).encode("utf-8") + b"\n")
        finally:
            os.close(fd)
    except Exception as exc:
        logger.warning("Run event not written: %s", _clean(exc))


def commit_marker_path() -> Path:
    return runs_dir() / _COMMIT_MARKER


def read_commit_marker() -> dict | None:
    """The marker on disk, or None. One that cannot be read still says a commit did not finish."""
    try:
        marker = json.loads(commit_marker_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"unreadable": True, "files": [], "written": []}
    return marker if isinstance(marker, dict) else {"unreadable": True, "files": [], "written": []}


def _write_marker(marker: dict) -> None:
    _atomic.make_private_dirs(runs_dir())
    _atomic.write_text_atomic(commit_marker_path(), json.dumps(marker), _atomic.PRIVATE_FILE_MODE)


def begin_commit(record: dict, files: list[str]) -> dict:
    """Before the first output file is replaced. Each file is atomic, the set is not: see DECISIONS.md, Activity slice 2a."""
    marker = {"runId": record["runId"], "startedAt": _now().isoformat(), "files": list(files), "written": []}
    try:
        _write_marker(marker)
    except OSError as exc:
        add_issue(record, "warning", f"Commit marker not written, so a stop during this save would go unnoticed: {exc}")
    event(record, "commit_start", files=list(files))
    return marker


def commit_wrote(marker: dict, name: str) -> None:
    marker["written"].append(name)
    try:
        _write_marker(marker)
    except OSError as exc:
        logger.warning("Commit marker not updated: %s", _clean(exc))


def end_commit(record: dict, marker: dict) -> None:
    try:
        commit_marker_path().unlink(missing_ok=True)
    except OSError as exc:
        add_issue(record, "warning", f"Commit marker not removed, so the next run will report this save as incomplete: {exc}")
    event(record, "commit_end", files=marker["written"])


def describe_incomplete_commit(marker: dict) -> str:
    if marker.get("unreadable"):
        return "A save of the job files did not finish (its marker is unreadable); they may not match each other. Nothing was repaired."
    written = marker.get("written") or []
    pending = [name for name in marker.get("files") or [] if name not in written]
    return (
        f"Run {marker.get('runId')} left an incomplete save of the job files. Written: {', '.join(written) or 'none'}. "
        f"Not written: {', '.join(pending) or 'none'}. They may not match each other. Nothing was repaired."
    )


def report_incomplete_commit(record: dict) -> None:
    """Call with the lock held, so a marker on disk is a dead run's. It stays until a later commit finishes."""
    marker = read_commit_marker()
    if marker:
        message = describe_incomplete_commit(marker)
        add_issue(record, "error", message)
        event(record, "commit_incomplete", runId=marker.get("runId"), message=message)


def mark_interrupted(record: dict) -> None:
    """A record found running with the lock free. Nobody saw it end, so finishedAt stays as it is."""
    unfinished = None
    for step in record.get("steps") or []:
        if step.get("status") == "running":
            step["status"] = "interrupted"
            unfinished = step.get("name")
    where = f" during {unfinished}" if unfinished else ""
    message = f"The run did not finish: it stopped{where} (killed, or the server restarted). It was not resumed."
    add_issue(record, "error", message)
    marker = read_commit_marker()
    if marker and marker.get("runId") == record["runId"]:
        record["incompleteCommit"] = marker
        add_issue(record, "error", describe_incomplete_commit(marker))
    record["status"] = "interrupted"
    event(record, "interrupted", message=message)


def sweep_interrupted() -> list[str]:
    """Call with the lock held: then every record still saying running is dead. Returns their run ids."""
    swept = []
    for record in _records():
        if record.get("status") == "running":
            mark_interrupted(record)
            save(record)
            swept.append(record["runId"])
    return swept


def save(record: dict) -> Path | None:
    """Write the record and prune. The log is a report on the run: a failure here is logged and never fails the run."""
    try:
        folder = runs_dir()
        _atomic.make_private_dirs(folder)
        path = record_path(record)
        _atomic.write_text_atomic(path, json.dumps(record, indent=2), _atomic.PRIVATE_FILE_MODE)
        prune(folder)
        return path
    except Exception as exc:
        logger.warning("Run log not written: %s", _clean(exc))
        return None
