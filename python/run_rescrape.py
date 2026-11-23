#!/usr/bin/env python3
"""One Re-scrape as one background process under one lock: the whole intake of new ads in one manual run.

Order (owner decision 2026-11-23): discovery; classification of every ad with no role class; reading (llmFacts) of the Target / Adjacent ads not yet
read; a free scoring pass into a scratch file; engine fill for the ads that pass the gates and have no current engine answer (only when Settings allow it);
the real scoring. The three paid steps share ONE run budget set in Settings (runLimitUsd, runLimitAds); the orchestrator reads the real spend from the
AI ledger and passes each step the remainder. A limit stop is a stop point that is counted ("Stopped: <limit>, N ads waiting"), never a failure and
never a silent wait. Re-scrape is manual: independent of `automation.enabled`. No judge.

The browser only starts it and reads its status (scripts/run-rescrape.js), so closing the tab cannot skip scoring.

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
# The three paid steps (classification, reading, engine fill) share ONE run budget that lives in Settings (runLimitUsd, runLimitAds); the orchestrator
# measures the spend from the AI ledger and passes each step the REMAINDER. No limit is in code. The AI gate still decides every call.
CLASSIFY = PY / "job_scoring" / "classify_new.py"
ENRICH = PY / "job_scoring" / "enrich_jobs.py"
ENGINE = PY / "job_scoring" / "engine_missing.py"
PAID_STEPS = {  # step -> (script attribute, fixed flags, the AI ledger feature it spends under)
    "classification": ("CLASSIFY", ["--confirm", "--rescrape"], "fit3-classify"),
    "reading": ("ENRICH", ["--rescrape", "--manual"], "enrichment"),
    "engine": ("ENGINE", ["--confirm", "--rescrape"], "evidence-matcher"),
}
STEP_WORDS = {"classification": "classification", "reading": "reading", "engine": "engine fill"}
LIMIT_WORDS = {  # a stop code as the words the Activity screen may show (run-history.js allows exactly these)
    "run_usd": "run spend limit", "run_ads": "ads-per-run limit", "daily": "daily AI budget", "monthly": "monthly AI budget",
    "call_cap": "paid call limit", "failures": "3 calls in a row failed", "gate": "AI gate refused the next call",
    "unset": "run limit not set in Settings", "engine_not_allowed": "engine fill not allowed in Settings",
}
RUN_ID = re.compile(r"^[0-9A-Za-z]{1,32}$")
OUTPUT_TAIL_LINES = 3
CANCEL_POLL_SECONDS = 0.2
CANCEL_GRACE_SECONDS = float(os.environ.get("HOLOJOB_CANCEL_GRACE_SECONDS") or 20)
FINISHED = ("ok", "waiting", "partial", "failed", "skipped", "interrupted", "cancelled")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def step_commands(args) -> list[tuple[str, list[str]]]:
    discovery = [str(DISCOVERY), "--providers", args.providers, "--run-id", args.run_id]
    if args.country:
        discovery += ["--country", args.country]
    if getattr(args, "exclude", None):
        discovery += ["--exclude", args.exclude]
    return [("discovery", discovery)]


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


def _summary_of(output) -> dict | None:
    """The one JSON line a paid step prints last ({"step": name, ...counts and a fixed stop code}); None when it printed none."""
    output.seek(0)
    for line in reversed(output.read().decode("utf-8", "replace").strip().splitlines()):
        if not line.startswith("{"):
            continue
        try:
            found = json.loads(line)
        except ValueError:
            continue
        if isinstance(found, dict) and isinstance(found.get("step"), str):
            return found
    return None


def run_step(record: dict, name: str, cmd: list[str], lock: pipeline_lock.Lock) -> tuple[dict, bool, dict | None]:
    """Run one step, holding the lock with it. Returns the record as it now stands on disk, whether the step succeeded, and (a paid step) its summary.

    The step's output goes to an unnamed temp file, not a pipe: no reader can go away and kill it with EPIPE.
    A Re-scrape is a manual action: every step runs with the manual AI trigger, whatever `automation.enabled` says.
    """
    step = {"name": name, "status": "running", "startedAt": _now(), "finishedAt": None, "exitCode": None}
    record.setdefault("steps", []).append(step)
    run_log.save(record)
    run_log.event(record, "step_start", step=name)
    with tempfile.TemporaryFile() as output:
        proc = subprocess.Popen(
            [sys.executable, *cmd], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            pass_fds=(lock.fd,), env={**lock.child_env(), "PYTHONIOENCODING": "utf-8", "HOLOJOB_AI_TRIGGER": "manual"},
            start_new_session=True,  # its own group: a cancel can stop the step and everything it started, and nothing else
        )
        code, signalled, killed = wait_for_step(proc, record, name)
        tail = _tail(output) if code != 0 else ""
        summary = _summary_of(output) if name in PAID_STEPS and code == 0 else None

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
    return fresh, code == 0, summary


# --- the paid steps and their one budget ------------------------------------------------------------------------------------------------------------
class PaidBudget:
    """The run's one budget for classification, reading and engine fill. Settings hold the limits; the AI ledger holds what was spent.

    Nothing here is trusted from a step's own print: before each step the spend and the distinct ads so far are read from the ledger (rows since the
    run began, the three paid features), and the step gets the remainder as flags. The imports are lazy: `reconcile` stays stdlib-only.
    """

    DONE_KEY = {"classification": "classified", "reading": "read", "engine": "filled"}

    def __init__(self, record: dict, scratch: Path):
        sys.path.append(str(PY / "llm"))
        import ai_gate  # noqa: PLC0415
        import run_budget  # noqa: PLC0415

        settings = ai_gate.load_settings()
        self.rb = run_budget
        self.limits = ai_gate.run_limits(settings)  # (USD, ads) or None: not set, so the paid steps spend nothing
        self.engine_allowed = ai_gate.engine_fill_allowed(settings)
        self.run_start = record["startedAt"]
        self.started = datetime.fromisoformat(self.run_start)
        self.counted = scratch / "counted-ads.json"
        self.steps: dict[str, dict] = {}

    def flags(self) -> list[str]:
        """The remainder of the run's budget as the flags of the next step. Unset limits pass no flag: the step then finds them unset itself."""
        if self.limits is None:
            return []
        usd, ads = self.rb.usage_since(self.started)
        self.counted.write_text(json.dumps(sorted(ads)), encoding="utf-8")
        os.chmod(self.counted, 0o600)
        return ["--max-usd", f"{max(0.0, self.limits[0] - usd):.6f}", "--max-ads", str(max(0, self.limits[1] - len(ads))),
                "--run-start", self.run_start, "--counted-ids", str(self.counted)]

    def note(self, name: str, summary: dict | None) -> None:
        """What one step did: counts, its spend and the distinct ads it handled (from the ledger), and a fixed stop code."""
        if summary is None:
            return
        usd, ads = self.rb.usage_since(self.started, features=(PAID_STEPS[name][2],))

        def count(key):
            value = summary.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

        stopped = summary.get("stopped")
        self.steps[name] = {"candidates": count("candidates"), "done": count(self.DONE_KEY[name]), "failed": count("failed"), "waiting": count("waiting"),
                            "stopped": stopped if stopped in self.rb.STOP_CODES else None, "spentUsd": round(usd, 4), "ads": len(ads)}

    def skipped(self, name: str, code: str) -> None:
        self.steps[name] = {"candidates": 0, "done": 0, "failed": 0, "waiting": None, "stopped": code, "spentUsd": 0.0, "ads": 0}

    def finish(self, record: dict) -> int:
        """Write the run's one paid block and one issue per stopped step. Returns how many ads wait."""
        usd, ads = self.rb.usage_since(self.started)
        waiting = sum(s["waiting"] or 0 for s in self.steps.values())
        record["paid"] = {"limits": None if self.limits is None else {"usd": self.limits[0], "ads": self.limits[1]},
                          "spentUsd": round(usd, 4), "ads": len(ads), "waiting": waiting, "steps": self.steps}
        for name, step in self.steps.items():
            if not step["stopped"]:
                continue
            count = step["waiting"]
            tail = f", {count} ads waiting" if count is not None else ""
            run_log.add_issue(record, "warning", f"Stopped: {LIMIT_WORDS[step['stopped']]}{tail} ({STEP_WORDS[name]})")
        return waiting


def intake(record: dict, lock: pipeline_lock.Lock) -> tuple[dict, bool, bool]:
    """After a good discovery: classification, reading, a free scoring pass for the engine to read, engine fill, then the real scoring.
    Returns (the record, the final scoring succeeded, a paid step failed).

    A limit stop is not a failure: the step ends, the ads left are counted, and the next step still runs. A paid step that fails adds an issue and the run
    goes on to scoring. The engine plans from a scored list (its score, requirements and gates), so it reads a scratch scoring written beside the real one,
    never `scored_jobs.json`: the pre-re-score backups are not used up and the list the owner sees changes only once, at the end.
    """
    paid_failed = False
    with tempfile.TemporaryDirectory(prefix="holojob-rescrape-") as scratch:
        budget = PaidBudget(record, Path(scratch))
        scored_view = Path(scratch) / "scored-for-engine.json"
        view_ready = False
        succeeded = True
        engine_wanted = budget.limits is not None and budget.engine_allowed
        for name in ("classification", "reading", "scoring-prepare", "engine", "scoring"):
            if name == "scoring-prepare" and not engine_wanted:
                continue
            if run_log.cancel_requested(record):
                run_log.event(record, "step_skipped", step=name, reason="cancelled")
                continue
            if name in PAID_STEPS:
                if name != "classification" and budget.limits is None:
                    budget.skipped(name, budget.rb.STOP_UNSET)
                    run_log.event(record, "step_skipped", step=name, reason="run_limit_not_set")
                    continue
                if name == "engine" and not budget.engine_allowed:
                    budget.skipped(name, budget.rb.STOP_ENGINE_NOT_ALLOWED)
                    run_log.event(record, "step_skipped", step=name, reason="engine_not_allowed")
                    continue
                if name == "engine" and not view_ready:
                    run_log.event(record, "step_skipped", step=name, reason="no_scored_view")
                    continue
                script, fixed, _ = PAID_STEPS[name]
                cmd = [str(globals()[script]), *fixed, *budget.flags()]
                if name == "engine":
                    cmd += ["--jobs", str(scored_view)]
                record, ok, summary = run_step(record, name, cmd, lock)
                budget.note(name, summary)
                paid_failed = paid_failed or (not ok and not run_log.cancel_requested(record))
            elif name == "scoring-prepare":
                record, view_ready, _ = run_step(record, name, [str(SCORING), "--output", str(scored_view)], lock)
                paid_failed = paid_failed or (not view_ready and not run_log.cancel_requested(record))
            else:
                record, succeeded, _ = run_step(record, name, [str(SCORING)], lock)
        budget.finish(record)
    return record, succeeded, paid_failed


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
        paid_failed = False
        try:
            for name, cmd in step_commands(args):  # discovery
                record, succeeded, _ = run_step(record, name, cmd, lock)
                if not succeeded:
                    break  # as the browser did: a failed discovery is not scored
                if name == "discovery" and (record.get("import") or {}).get("nothingSaved") == "no_usable_source":
                    run_log.event(record, "step_skipped", step="scoring", reason="nothing_imported")
                    break  # S8b: no source was usable, the list did not change, so there is nothing to score
                if run_log.cancel_requested(record):
                    # the scrape was imported before the request came: it counts, and only the paid steps and scoring are left undone
                    run_log.event(record, "step_skipped", step="scoring", reason="cancelled")
                    break
                record, succeeded, paid_failed = intake(record, lock)
        except Exception as exc:
            succeeded = False
            run_log.add_issue(record, "error", f"The run stopped: {exc}")
            run_log.event(record, "error", message=f"The run stopped: {exc}")
        cancelled, succeeded = settle_cancel(record, succeeded)
        finished = run_log.finish(record, exit_ok=succeeded, cancelled=cancelled)
        if finished["status"] == "ok" and paid_failed:
            finished["status"] = "partial"  # a paid step failed (its issue says which); sources are fine
        elif finished["status"] == "ok" and (finished.get("paid") or {}).get("waiting"):
            finished["status"] = "waiting"  # completed, but a limit left ads waiting: never shown as plainly finished
        run_log.save(finished)
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
    begin.add_argument("--exclude", default="")
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
