#!/usr/bin/env python3
"""One Re-scrape as one background process: discovery, then scoring, under one lock.

The browser only starts it and reads its status (scripts/run-rescrape.js), so closing the tab cannot skip scoring. Same
source order and arguments as the Re-scrape the browser used to chain itself: no enrichment, no judge, no model call.

    run_rescrape.py start --run-id ID --providers P [--country C]    0 ok, 1 failed, 2 bad input, 75 another run holds the lock
    run_rescrape.py reconcile      JSON: is a run alive; marks dead records interrupted; reports a stale commit marker
    run_rescrape.py cancel --run-id ID    JSON: ask a running Re-scrape to stop (S6); takes no lock, writes one small file, changes no data
    run_rescrape.py hold           prints "locked" and keeps the lock until stdin closes; 75 when held (backup restore)

Stdlib only until a step starts: a status poll runs `reconcile`.

Cancel (S6) is cooperative. `cancel` writes `<record>.cancel` and nothing else. This process polls for that file while a step runs,
and sends SIGTERM to the step's own process group (the step has one, so the whole tree can be stopped and the lock is not left with
an orphan). Discovery turns SIGTERM into "stop scraping, save what was collected, change nothing else" (run_discovery.py); it can only be killed
hard when it ignored SIGTERM for CANCEL_GRACE seconds AND the orchestrator wins the "kill" claim, which discovery's "commit" claim
excludes. Scoring writes one file atomically, so SIGTERM at any moment leaves the old file or the new one.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "python"
sys.path.append(str(PY / "job_scoring"))
sys.path.append(str(PY / "job_discovery"))
import pipeline_lock  # noqa: E402
import run_log  # noqa: E402

DISCOVERY = PY / "job_discovery" / "run_discovery.py"
SCORING = PY / "job_scoring" / "run_scoring.py"
RUN_ID = re.compile(r"^[0-9A-Za-z]{1,32}$")
OUTPUT_TAIL_LINES = 3
CANCEL_POLL_SECONDS = 0.2
CANCEL_GRACE_SECONDS = float(os.environ.get("HOLOJOB_CANCEL_GRACE_SECONDS") or 20)
FINISHED = ("ok", "partial", "failed", "skipped", "interrupted", "cancelled")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def step_commands(args) -> list[tuple[str, list[str]]]:
    discovery = [str(DISCOVERY), "--providers", args.providers, "--run-id", args.run_id]
    if args.country:
        discovery += ["--country", args.country]
    return [("discovery", discovery), ("scoring", [str(SCORING)])]


def _tail(output) -> str:
    output.seek(0)
    lines = output.read().decode("utf-8", "replace").strip().splitlines()
    return " / ".join(lines[-OUTPUT_TAIL_LINES:])


def _start_time(pid: int) -> str | None:
    """Field 22 of /proc/<pid>/stat, so a recycled pid is not mistaken for the process it replaced."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def descendants(pid: int) -> dict[int, str]:
    """pid -> start time of every process below `pid`, found by parent links in /proc. Catches a child that left the step's group."""
    parent_of: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                parent_of[int(entry.name)] = int(entry.joinpath("stat").read_text().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
    found: dict[int, str] = {}
    frontier = [pid]
    while frontier:
        parent = frontier.pop()
        for child, owner in parent_of.items():
            if owner == parent and child not in found:
                started = _start_time(child)
                if started:
                    found[child] = started
                    frontier.append(child)
    return found


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _signal_tree(pgid: int, tree: dict[int, str], sig: int) -> None:
    """The step's group, then any known descendant that is still the same process."""
    _signal_group(pgid, sig)
    for pid, started in tree.items():
        if _start_time(pid) == started:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass


def wait_for_step(proc: subprocess.Popen, record: dict, name: str) -> tuple[int, bool, bool]:
    """Wait for the step, watching for a cancel request. Returns (exit code, SIGTERM was sent, it was killed hard).

    On a request: SIGTERM to the step's group and every descendant. If the step is still there after CANCEL_GRACE_SECONDS, SIGKILL,
    but for discovery only after winning the "kill" claim, which it cannot win once discovery holds "commit" (its import is then
    running and is waited for). When the step is gone, whatever of its tree is left is killed, so no child outlives a cancelled run
    and none keeps the lock.
    """
    signalled_at: float | None = None
    killed = False
    tree: dict[int, str] = {}
    while True:
        try:
            code = proc.wait(timeout=CANCEL_POLL_SECONDS)
            break
        except subprocess.TimeoutExpired:
            pass
        if not run_log.cancel_requested(record):
            continue
        if signalled_at is None:
            signalled_at = time.monotonic()
            tree = descendants(proc.pid)
            run_log.event(record, "cancel_signal", step=name)
            _signal_tree(proc.pid, tree, signal.SIGTERM)
            continue
        tree.update(descendants(proc.pid))
        if not killed and time.monotonic() - signalled_at > CANCEL_GRACE_SECONDS:
            if name == "discovery" and not run_log.claim(record, "kill"):
                continue  # it holds "commit": its import is running; wait for it
            killed = True
            run_log.event(record, "cancel_kill", step=name)
            _signal_tree(proc.pid, tree, signal.SIGKILL)
    if signalled_at is not None:
        _signal_tree(proc.pid, tree | descendants_left(tree), signal.SIGKILL)
    return code, signalled_at is not None, killed


def descendants_left(tree: dict[int, str]) -> dict[int, str]:
    return {pid: started for pid, started in tree.items() if _start_time(pid) == started}


def run_step(record: dict, name: str, cmd: list[str], lock: pipeline_lock.Lock) -> tuple[dict, bool]:
    """Run one step, holding the lock with it. Returns the record as it now stands on disk, and whether the step succeeded.

    The step's output goes to an unnamed temp file, not a pipe: no reader can go away and kill it with EPIPE.
    """
    step = {"name": name, "status": "running", "startedAt": _now(), "finishedAt": None, "exitCode": None}
    record.setdefault("steps", []).append(step)
    run_log.save(record)
    run_log.event(record, "step_start", step=name)
    with tempfile.TemporaryFile() as output:
        proc = subprocess.Popen(
            [sys.executable, *cmd], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            pass_fds=(lock.fd,), env={**lock.child_env(), "PYTHONIOENCODING": "utf-8"},
            start_new_session=True,  # its own group: a cancel can stop the step and everything it started, and nothing else
        )
        code, signalled, killed = wait_for_step(proc, record, name)
        tail = _tail(output) if code != 0 else ""

    # Discovery wrote to the record meanwhile; only one process writes it at a time, and now it is this one again.
    fresh = run_log.find_record(record["runId"]) or record
    step = next(s for s in reversed(fresh.get("steps") or [step]) if s["name"] == name)
    # Stopped by a cancel is its own outcome: the code is 76 (discovery saved the ads it had collected and changed nothing else) or a signal (-15, -9).
    stopped = signalled and (code == run_log.EXIT_CANCELLED or code < 0)
    step.update(status="ok" if code == 0 else "cancelled" if stopped else "failed", finishedAt=_now(), exitCode=code)
    if killed and stopped:
        fresh.setdefault("cancel", {"requestedAt": run_log.cancel_info(fresh).get("requestedAt"), "outcome": "stopped_nothing_imported"})
    if code != 0 and not stopped:
        message = f"{name} failed with exit code {code}" + (f": {tail}" if tail else "")
        run_log.add_issue(fresh, "error", message)
        run_log.event(fresh, "error", step=name, message=message)
    run_log.save(fresh)
    run_log.event(fresh, "step_end", step=name, status=step["status"], exitCode=code)
    return fresh, code == 0


def start(args) -> int:
    if not RUN_ID.match(args.run_id):
        print("Bad run id", file=sys.stderr)
        return 2
    lock = pipeline_lock.acquire()
    if lock is None:
        print(pipeline_lock.BUSY_MESSAGE, file=sys.stderr)
        return pipeline_lock.EXIT_LOCKED
    try:
        run_log.sweep_interrupted()
        record = run_log.new_record(args.run_id, "manual")
        record["orchestrator"] = "rescrape"  # the only run a cancel may address
        if run_log.save(record) is None:
            print("Cannot write the run record; nothing started.", file=sys.stderr)
            return 1
        run_log.event(record, "run_start", trigger="manual")
        succeeded = True
        try:
            for name, cmd in step_commands(args):
                if name == "scoring" and run_log.cancel_requested(record):
                    run_log.event(record, "step_skipped", step=name, reason="cancelled")
                    break  # the scrape was imported before the request came: it counts, and only scoring is left undone
                record, succeeded = run_step(record, name, cmd, lock)
                if not succeeded:
                    break  # as the browser did: a failed discovery is not scored
        except Exception as exc:
            succeeded = False
            run_log.add_issue(record, "error", f"The run stopped: {exc}")
            run_log.event(record, "error", message=f"The run stopped: {exc}")
        cancelled, succeeded = settle_cancel(record, succeeded)
        run_log.save(run_log.finish(record, exit_ok=succeeded, cancelled=cancelled))
        run_log.event(record, "run_end", status=record["status"])
        return 0 if succeeded else 1
    finally:
        lock.release()


def settle_cancel(record: dict, succeeded: bool) -> tuple[bool, bool]:
    """After the steps: write what a cancel request amounted to into the record. Returns (the run is a cancelled one, the run succeeded).

    cancelled: the scrape was stopped. The ads it had validly collected were saved, and nothing else changed (discovery says so in `cancel`), or, when the step had to
      be killed, nothing was saved and the staging is marked so that no path will ever count it as a proven run.
    imported_before_cancel: the request came after the commit point. The import happened as any import does and counts; the run keeps
      its own status and only scoring is missing (or was stopped), which the status route reports as `scoringBehind`.
    A request on a run that failed anyway changes nothing: the run failed.
    """
    steps = record.get("steps") or []
    discovery = next((s for s in steps if s["name"] == "discovery"), None)
    scoring = next((s for s in steps if s["name"] == "scoring"), None)
    if discovery and discovery["status"] == "cancelled":
        cancel = record.setdefault("cancel", {"requestedAt": run_log.cancel_info(record).get("requestedAt"), "outcome": "stopped_nothing_imported"})
        if cancel["outcome"] == "stopped_nothing_imported":
            _mark_staging_cancelled(record)
        saved = cancel.get("saved") or 0
        run_log.add_issue(record, "warning", (
            ("Cancelled. %d collected ads were saved. Nothing else changed." % saved) if saved
            else "Cancelled. No ads were saved. Nothing else changed."
        ) + " Scoring was skipped.")
        return True, True
    scoring_stopped = bool(scoring and scoring["status"] == "cancelled")
    imported = bool(discovery and discovery["status"] == "ok")
    if not (run_log.cancel_requested(record) and imported and (succeeded or scoring_stopped)):
        return False, succeeded
    skipped = scoring_stopped or scoring is None
    record["cancel"] = {"requestedAt": run_log.cancel_info(record).get("requestedAt"),
                        "outcome": "imported_before_cancel" if skipped else "finished_before_cancel"}
    if skipped:
        run_log.add_issue(record, "warning", "The cancel came after the import was committed, so the scrape counts as any run. Scoring was skipped; Re-score runs it.")
    return False, True


def _mark_staging_cancelled(record: dict) -> None:
    try:
        import staging  # noqa: PLC0415 - only a killed step needs it, and a status poll must stay stdlib-only

        if (staging.staging_dir(ROOT) / record["runId"]).is_dir():
            staging.mark_cancelled(ROOT, record["runId"], {"requestedAt": run_log.cancel_info(record).get("requestedAt"), "killed": True})
    except Exception as exc:  # noqa: BLE001 - the record says what could not be done
        run_log.add_issue(record, "error", f"The cancelled run's staging could not be marked, so it is not safe to import it as a proven run: {exc}")


def lock_is_held(proc_locks: Path = Path("/proc/locks")) -> bool | None:
    """Is anyone holding the pipeline lock? Read from /proc/locks, so asking takes nothing and cannot make a starting run see it busy.
    None when it cannot be told.

    Matched on the inode alone. /proc/locks prints the filesystem's own device number, which a bind mount, a container or a btrfs
    subvolume may show differently from stat(); comparing it could read a live run as "not running" and make a cancel do nothing.
    An inode shared with an unrelated lock on another filesystem only reads as held, and then a harmless request file is written."""
    try:
        inode = pipeline_lock.lock_path().stat().st_ino
    except FileNotFoundError:
        return False  # never created: nobody has held it
    except OSError:
        return None
    try:
        rows = [row.split() for row in proc_locks.read_text().splitlines()]
    except OSError:
        return None
    for row in rows:
        if len(row) > 5 and "FLOCK" in row:
            try:
                if int(row[5].rsplit(":", 1)[-1]) == inode:
                    return True
            except ValueError:
                continue
    return False


def cancel(run_id: str) -> dict:
    """Ask a Re-scrape to stop. Idempotent; takes no lock; writes one request file and one event, never a data file or the record.

    Results: cancel_requested, cancel_already_requested, already_cancelled, already_finished, not_running (a record that says
    running but nobody holds the lock: it died; reconcile will mark it), not_cancellable (a run this orchestrator does not own:
    a pipeline or direct discovery), unknown_run, invalid_run_id. Nothing is written for any of the others.
    """
    if not RUN_ID.match(run_id or ""):
        return {"result": "invalid_run_id"}
    record = run_log.find_record(run_id)
    if record is None:
        return {"result": "unknown_run"}
    status = record.get("status")
    if status == "cancelled":
        return {"result": "already_cancelled", "status": status, "runId": run_id}
    if status in FINISHED:
        return {"result": "already_finished", "status": status, "runId": run_id}
    if record.get("orchestrator") != "rescrape":
        return {"result": "not_cancellable", "status": status, "runId": run_id}
    if lock_is_held() is False:
        return {"result": "not_running", "status": status, "runId": run_id}
    made = run_log.request_cancel(record)
    after = run_log.find_record(run_id) or record
    if after.get("status") in FINISHED and not (after.get("status") == "cancelled" or after.get("cancel")):
        if made:
            run_log.withdraw_cancel(record)  # it ended on its own just now: no request is left behind for a run that cannot read it
        return {"result": "already_finished", "status": after.get("status"), "runId": run_id}
    if made:
        run_log.event(record, "cancel_requested")
    return {"result": "cancel_requested" if made else "cancel_already_requested", "status": after.get("status"), "runId": run_id}


def reconcile() -> dict:
    """With the lock free every running record is dead and any commit marker is stale; both are decided while holding it,
    so a run starting this instant cannot be mistaken for a dead one. Reports only: no data is repaired, no run resumed."""
    lock = pipeline_lock.acquire()
    if lock is None:
        return {"busy": True, "interrupted": [], "incompleteCommit": None}
    try:
        return {"busy": False, "interrupted": run_log.sweep_interrupted(), "incompleteCommit": run_log.read_commit_marker()}
    finally:
        lock.release()


def hold() -> int:
    lock = pipeline_lock.acquire()
    if lock is None:
        return pipeline_lock.EXIT_LOCKED
    try:
        print("locked", flush=True)
        sys.stdin.read()  # Node closes it when done, and so does Node's death
        return 0
    finally:
        lock.release()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    begin = commands.add_parser("start")
    begin.add_argument("--run-id", required=True)
    begin.add_argument("--providers", required=True)
    begin.add_argument("--country")
    commands.add_parser("reconcile")
    commands.add_parser("hold")
    stop = commands.add_parser("cancel")
    stop.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "start":
        return start(args)
    if args.command == "hold":
        return hold()
    if args.command == "cancel":
        print(json.dumps(cancel(args.run_id)))
        return 0
    print(json.dumps(reconcile()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
