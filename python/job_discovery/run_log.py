"""The run log: one record per discovery run, for the Activity screen.

run_discovery.py writes it, so a manual Re-scrape and a pipeline run each log exactly once. One file per run,
data/analytics/runs/<startedAt, UTC>-<runId>.json (HOLOJOB_ANALYTICS_DIR moves the folder): a Re-scrape takes no
pipeline lock, so two runs can overlap, and rewriting one shared file could lose a record. Files are 600, folders 700.

Record, version 1. A later slice adds fields; a reader ignores what it does not know and treats a missing one as unknown:

    {
      "version": 1,
      "runId": "<discovered_jobs.json meta.sourceRunId>",
      "trigger": "manual" | "pipeline" | "scheduled",
      "startedAt": "<ISO>", "finishedAt": "<ISO>",
      "status": "ok" | "partial" | "failed" | "skipped",
      "sources": [{"name", "status": "ok" | "partial" | "failed" | "skipped", "read", "kept", "new", "error",
                   "boardsFailed", "skipReason"}],
      "issues": [{"level": "error" | "warning", "source": "<name>" | null, "message"}]
    }

read: ads parsed before the search, role and location filters. kept: past them, before dedupe. new: ads no earlier run
recorded, counted after dedupe under the provider of the copy that won, so `new` is not a share of `kept`, and summed it
equals meta.history.new. skipped: the source did not search because it does not apply (skipReason says why); it is no
warning and does not lower the run's status; a run is skipped only when every source was. Left out because discovery does not know them yet: scored, closed, missing,
expired.
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
SOURCE_STATUSES = ("ok", "partial", "failed", "skipped")
RUN_STATUSES = ("ok", "partial", "failed", "skipped")
MAX_MESSAGE_CHARS = 500

_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_FILE_NAME = re.compile(r"^(\d{8}T\d{6}Z)-[^/]+\.json$")
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
        "status": "failed",  # until finish(): a record that says less than the truth is never the flattering one
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


def set_new_counts(record: dict, counts: dict[str, int]) -> None:
    for source in record["sources"]:
        source["new"] = counts.get(source["name"], 0)


def finish(record: dict, *, exit_ok: bool) -> dict:
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
    record["finishedAt"] = _now().isoformat()
    return record


def prune(folder: Path, now: datetime | None = None) -> int:
    """Remove records that started more than RETENTION_DAYS ago, read from the file name; returns how many."""
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


def save(record: dict) -> Path | None:
    """Write the record and prune. The log is a report on the run: a failure here is logged and never fails the run."""
    try:
        folder = runs_dir()
        _atomic.make_private_dirs(folder)
        started = datetime.fromisoformat(record["startedAt"]).astimezone(timezone.utc)
        path = folder / f"{started.strftime(_STAMP_FORMAT)}-{record['runId']}.json"
        _atomic.write_text_atomic(path, json.dumps(record, indent=2), _atomic.PRIVATE_FILE_MODE)
        prune(folder)
        return path
    except Exception as exc:
        logger.warning("Run log not written: %s", _clean(exc))
        return None
