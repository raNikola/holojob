#!/usr/bin/env python3
"""The ledger is the truth; discovered_jobs.json is a view derived from it (slice S4a). This module keeps the two together.

    view_guard.py check   [--jobs FILE] [--ledger FILE]     prints the state as JSON; exit 0 consistent, 1 not
    view_guard.py ensure  [--jobs FILE] [--ledger FILE]     makes them consistent; exit 0 ok, 1 explicit error

**Generation.** An import writes the ledger with a `generation` (first key of the file) and the view with the same number as
`meta.ledgerGeneration` (first key of its meta). They are consistent when the numbers are equal; a ledger and a view that both
have none are the pre-S4a pair and count as consistent until the first import. Every reader calls `ensure` before it uses
the view, so a view left behind by a stop between the two writes is rebuilt before anyone reads it. If it cannot be rebuilt
(unreadable ledger, disk error, a ledger no import produced) `ensure` raises ViewRecoveryError and the reader stops with that
message: a stale view is never served.

**Locks (deadlock-safe).** Recovery and the commit take one short lock of their own, `<jobs dir>/.view.lock` (flock). They never
take the pipeline lock, so it does not matter whether the caller holds it (a run's scoring step does, a status route does not).
The order is always pipeline lock, then view lock; nothing takes them the other way round, and nothing waits for the pipeline
lock while holding the view lock. The commit (ledger write, then view write) happens inside the view lock, so a recoverer can
never see the moment between the two writes: parallel readers queue on the view lock, the first rebuilds, the others find
the view consistent when their turn comes and do nothing. A view is replaced by rename, so nobody reads half a file.

The peek reads only the first bytes of each file (the ledger is 18 MB), which is why `generation` is written first.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import fcntl
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


job_history = _load("_view_guard_job_history", "job_history.py")
_atomic = _load("_view_guard_atomic_write", "atomic_write.py")
stale_rule = _load("_view_guard_stale_rule", "stale_rule.py")

LOCK_NAME = ".view.lock"
LOCK_WAIT_SECONDS = 60.0
PEEK_BYTES = 4096
_LEDGER_GENERATION = re.compile(r'^\s*\{\s*"generation"\s*:\s*(\d+)\s*[,}]')
_VIEW_GENERATION = re.compile(r'^\s*\{\s*"meta"\s*:\s*\{\s*"ledgerGeneration"\s*:\s*(\d+)\s*[,}]')


class ViewError(Exception):
    """The ledger cannot give a view: no import produced it."""


class ViewRecoveryError(Exception):
    """The view could not be brought in line with the ledger. The message says why; the stale view must not be used."""


# --- the view, from the ledger alone ----------------------------------------------------------------------------------


def view_payload(jobs: list[dict], meta: dict, generated_at: str, generation: int | None) -> dict:
    """What discovered_jobs.json holds. Same fields as export_jobs.discovered_payload, plus the ledger generation first."""
    raw_count = meta["rawCount"]
    deduped = meta["dedupedCount"]
    head = {"ledgerGeneration": generation} if generation is not None else {}
    return {
        "meta": {
            **head,
            "generatedAt": generated_at,
            "sourceRunId": meta["sourceRunId"],
            "searchTerms": meta["searchTerms"],
            "locations": meta["locations"],
            "remoteFilters": meta["remoteFilters"],
            "country": meta["country"],
            "providers": meta["providers"] or [],
            "providerCounts": meta["providerCounts"] or {},
            "rawCount": raw_count,
            "dedupedCount": deduped,
            "duplicateCount": max(0, raw_count - deduped),
            "history": meta["history"] or {},
        },
        "jobs": jobs,
    }


def _parse_time(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def derive_view(ledger: dict) -> dict:
    """discovered_jobs.json as it follows from this ledger: the same jobs, in the same order, as the import that left it.

    Reads only the ledger (the stamps `apply_run(run_id=...)` and `lastImport`). Mutates nothing; the same ledger always gives the same
    output, and what it returns shares nothing with the ledger. Raises ViewError for a ledger that no import has produced.
    """
    info = ledger.get("lastImport") if isinstance(ledger, dict) else None
    if not isinstance(info, dict) or not info.get("runId") or not isinstance(info.get("meta"), dict) or not isinstance(ledger.get("jobs"), dict):
        raise ViewError("this ledger has no lastImport: no import produced it, so no view can be derived")
    run_id, now = info["runId"], info["at"]
    moment = _parse_time(now)
    if moment is None:
        raise ViewError("this ledger's lastImport has no usable time")
    entries = ledger["jobs"]
    found = sorted((e for e in entries.values() if e.get("lastRunId") == run_id), key=lambda e: e.get("lastRunPos", 0))
    found_ids = {entry["job"]["jobId"] for entry in found}

    def record(entry: dict, closed: bool) -> dict:
        out = job_history._annotate(entry["job"], entry, now=moment, closed=closed)
        if entry.get("llmFacts"):
            out["llmFacts"] = entry["llmFacts"]
        return out

    # Only an import that says so marks its held rows, so a ledger from before (S5d2) gives the very bytes it always gave.
    marks = {job_history.NOT_FOUND_MARK: True} if info.get("marksNotFound") else {}
    jobs = [record(e, False) for e in found]
    source_runs = ledger.get(stale_rule.FIELD)

    def stale_mark(entry: dict) -> dict:
        return {job_history.STALE_MARK: True} if stale_rule.evidence(entry, source_runs) else {}

    jobs += [{**record(e, False), **marks, **stale_mark(e)} for e in entries.values() if e.get("heldRunId") == run_id and e["job"]["jobId"] not in found_ids]
    for job_id, entry in entries.items():
        closed_at = job_history._parse(entry.get("closedAt"))
        if not closed_at:
            continue
        if moment - closed_at <= timedelta(days=job_history.CLOSED_KEEP_DAYS) and job_id not in found_ids:
            jobs.append(record(entry, True))
    return copy.deepcopy(view_payload(jobs, info["meta"], now, ledger.get("generation")))


def serialize_ledger(ledger: dict) -> str:
    """The ledger as written: `generation` first, so a reader can peek at it without parsing 18 MB."""
    ordered = {k: v for k, v in ledger.items() if k != "generation"}
    if ledger.get("generation") is not None:
        ordered = {"generation": ledger["generation"], **ordered}
    return json.dumps(ordered, indent=2)


def serialize_view(view: dict) -> str:
    return json.dumps(view, indent=2)


# --- the state -------------------------------------------------------------------------------------------------------


def _peek(path: Path, pattern: re.Pattern) -> int | None:
    try:
        with open(path, "rb") as handle:
            head = handle.read(PEEK_BYTES).decode("utf-8", "replace")
    except OSError:
        return None
    found = pattern.match(head)
    return int(found.group(1)) if found else None


def ledger_generation(ledger_file: Path) -> int | None:
    return _peek(Path(ledger_file), _LEDGER_GENERATION)


def view_generation(jobs_file: Path) -> int | None:
    return _peek(Path(jobs_file), _VIEW_GENERATION)


def state(jobs_file: Path, ledger_file: Path) -> dict:
    """consistent, and why not. Cheap: it reads the first bytes of two files. Mirrored by scripts/view-guard.js
    (tests/fixtures/view-generation.json holds the cases both run)."""
    jobs_file, ledger_file = Path(jobs_file), Path(ledger_file)
    ledger_exists, view_exists = ledger_file.exists(), jobs_file.exists()
    ledger_gen = ledger_generation(ledger_file) if ledger_exists else None
    view_gen = view_generation(jobs_file) if view_exists else None
    if not ledger_exists:
        consistent, reason = True, "no ledger: nothing to derive the view from"
    elif ledger_gen is None:
        consistent = view_gen is None
        reason = "pre-S4a pair: neither has a generation" if consistent else f"the view is generation {view_gen} but the ledger has none"
    elif not view_exists:
        consistent, reason = False, f"the ledger is generation {ledger_gen} and there is no view"
    else:
        consistent = view_gen == ledger_gen
        reason = "same generation" if consistent else f"the ledger is generation {ledger_gen}, the view is {view_gen}"
    return {"consistent": consistent, "ledgerGeneration": ledger_gen, "viewGeneration": view_gen, "reason": reason}


# --- the lock --------------------------------------------------------------------------------------------------------


@contextlib.contextmanager
def view_lock(jobs_dir: Path, wait: float = LOCK_WAIT_SECONDS):
    """The short lock around the commit and around a rebuild. Blocks up to `wait` seconds, then raises ViewRecoveryError."""
    path = Path(jobs_dir) / LOCK_NAME
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, _atomic.PRIVATE_FILE_MODE)
    except OSError as exc:
        raise ViewRecoveryError(f"cannot open the view lock {path.name}: {exc}") from exc
    try:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ViewRecoveryError(f"the view lock has been held for more than {wait:.0f} s; try again")
                time.sleep(0.02)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# --- commit and recovery -------------------------------------------------------------------------------------------------


def commit(ledger: dict, jobs_file: Path, ledger_file: Path, *, wait: float = LOCK_WAIT_SECONDS) -> dict:
    """Write the ledger, then the view derived from it, inside the view lock. The ledger is the commit point: a stop between
    the two writes leaves a view one generation behind, which the next reader rebuilds. Returns the view."""
    jobs_file, ledger_file = Path(jobs_file), Path(ledger_file)
    view = derive_view(ledger)  # before anything is written: a ledger that cannot give a view is never committed
    with view_lock(jobs_file.parent, wait):
        _atomic.write_text_atomic(ledger_file, serialize_ledger(ledger), _atomic.PRIVATE_FILE_MODE)
        _atomic.write_text_atomic(jobs_file, serialize_view(view), _atomic.PRIVATE_FILE_MODE)
    return view


def ensure(jobs_file: Path, ledger_file: Path, *, wait: float = LOCK_WAIT_SECONDS) -> dict:
    """Before a reader uses the view: if it does not match the ledger, rebuild it. Returns {"regenerated", ...state};
    raises ViewRecoveryError when it cannot, and then the view on disk must not be used."""
    jobs_file, ledger_file = Path(jobs_file), Path(ledger_file)
    now = state(jobs_file, ledger_file)
    if now["consistent"]:
        return {**now, "regenerated": False}
    with view_lock(jobs_file.parent, wait):
        now = state(jobs_file, ledger_file)  # another reader may have rebuilt it while this one waited
        if now["consistent"]:
            return {**now, "regenerated": False}
        try:
            ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ViewRecoveryError(
                f"{now['reason']}, and the ledger {ledger_file.name} cannot be read ({type(exc).__name__}: {exc}); "
                f"{jobs_file.name} is out of date and was not used"
            ) from exc
        try:
            view = derive_view(ledger)
        except ViewError as exc:
            raise ViewRecoveryError(f"{now['reason']}; {exc}. {jobs_file.name} is out of date and was not used") from exc
        try:
            _atomic.write_text_atomic(jobs_file, serialize_view(view), _atomic.PRIVATE_FILE_MODE)
        except OSError as exc:
            raise ViewRecoveryError(f"{now['reason']}, and the view could not be rebuilt ({type(exc).__name__}: {exc})") from exc
        after = state(jobs_file, ledger_file)
        if not after["consistent"]:
            raise ViewRecoveryError(f"the view was rebuilt but still does not match the ledger ({after['reason']})")
        return {**after, "regenerated": True}


def ensure_or_exit(jobs_file: Path, ledger_file: Path) -> None:
    """For a script's start: rebuild the view if needed, or print the reason and exit 1."""
    try:
        ensure(jobs_file, ledger_file)
    except ViewRecoveryError as exc:
        print(f"The job list is out of date and could not be rebuilt: {exc}", file=sys.stderr)
        raise SystemExit(1)


def default_paths() -> tuple[Path, Path]:
    jobs = ROOT / "data" / "jobs" / "discovered_jobs.json"
    return jobs, job_history.ledger_path(jobs)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("check", "ensure"))
    jobs, ledger = default_paths()
    parser.add_argument("--jobs", type=Path, default=jobs)
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args(argv)
    ledger_file = args.ledger or job_history.ledger_path(args.jobs)
    if args.command == "check":
        found = state(args.jobs, ledger_file)
        print(json.dumps(found))
        return 0 if found["consistent"] else 1
    try:
        print(json.dumps({"ok": True, **ensure(args.jobs, ledger_file)}))
        return 0
    except ViewRecoveryError as exc:
        print(json.dumps({"ok": False, "error": "view_unrecoverable", "message": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
