#!/usr/bin/env python3
"""One Re-scrape as one background process: discovery, then scoring, under one lock.

The browser only starts it and reads its status (scripts/run-rescrape.js), so closing the tab cannot skip scoring. Same
source order and arguments as the Re-scrape the browser used to chain itself: no enrichment, no judge, no model call.

    run_rescrape.py start --run-id ID --providers P [--country C]    0 ok, 1 failed, 2 bad input, 75 another run holds the lock
    run_rescrape.py reconcile      JSON: is a run alive; marks dead records interrupted; reports a stale commit marker
    run_rescrape.py hold           prints "locked" and keeps the lock until stdin closes; 75 when held (backup restore)

Stdlib only until a step starts: a status poll runs `reconcile`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
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
        )
        code = proc.wait()
        tail = _tail(output) if code != 0 else ""

    # Discovery wrote to the record meanwhile; only one process writes it at a time, and now it is this one again.
    fresh = run_log.find_record(record["runId"]) or record
    step = next(s for s in reversed(fresh.get("steps") or [step]) if s["name"] == name)
    step.update(status="ok" if code == 0 else "failed", finishedAt=_now(), exitCode=code)
    if code != 0:
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
        if run_log.save(record) is None:
            print("Cannot write the run record; nothing started.", file=sys.stderr)
            return 1
        run_log.event(record, "run_start", trigger="manual")
        succeeded = True
        try:
            for name, cmd in step_commands(args):
                record, succeeded = run_step(record, name, cmd, lock)
                if not succeeded:
                    break  # as the browser did: a failed discovery is not scored
        except Exception as exc:
            succeeded = False
            run_log.add_issue(record, "error", f"The run stopped: {exc}")
            run_log.event(record, "error", message=f"The run stopped: {exc}")
        run_log.save(run_log.finish(record, exit_ok=succeeded))
        run_log.event(record, "run_end", status=record["status"])
        return 0 if succeeded else 1
    finally:
        lock.release()


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
    args = parser.parse_args(argv)
    if args.command == "start":
        return start(args)
    if args.command == "hold":
        return hold()
    print(json.dumps(reconcile()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
