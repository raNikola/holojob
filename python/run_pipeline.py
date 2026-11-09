#!/usr/bin/env python3
"""Run the whole job pipeline as one command: discovery -> enrichment -> scoring [-> tailoring].

The UI's "Run Full Pipeline", `npm run pipeline` and cron all call this, so there
is one definition of the sequence.

Fail fast: a step that exits non-zero, or leaves its output unusable, stops the
run, names the step, and nothing after it runs on stale or missing input. Exit
codes: 0 done, 1 a step failed, 2 bad setup (nothing ran), 75 another run holds
the lock (cron can retry later).

Never judges: the fit judgement sends data off this server and has its own,
confirmed action (run_scoring.py --judge).

Every step runs as an automatic AI task (HOLOJOB_AI_TRIGGER=automation), so the
AI budget gate (python/llm/ai_gate.py) lets a model call through only when
automation is enabled in data/ai/settings.json and the budget allows it. When the
gate refuses enrichment, or --skip-enrich is given, the run does not stop: it
scores without the ad facts and labels the result reduced quality.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "python"
sys.path.insert(0, str(PY / "job_scoring"))
from atomic_write import write_text_atomic  # noqa: E402
import row_state  # noqa: E402
import pipeline_lock  # noqa: E402
import view_guard  # noqa: E402
from work_authorization import outside_allowed_before_enrichment  # noqa: E402
DATA = ROOT / "data"
INTELLIGENCE = DATA / "intelligence" / "candidate-intelligence.json"
DISCOVERED = DATA / "jobs" / "discovered_jobs.json"
SCORED = DATA / "jobs" / "scored_jobs.json"
LAST_RUN = DATA / "jobs" / "pipeline_last_run.json"
LOCK = DATA / "jobs" / ".pipeline.lock"

EXIT_FAILED, EXIT_SETUP, EXIT_LOCKED = 1, 2, pipeline_lock.EXIT_LOCKED

# The lock of this run, handed to each step: a step takes the pipeline lock itself when run alone.
_held_lock = None

# Scoring on jobs the model never read would skip the role-track and visa caps,
# so too few enriched jobs stops the run instead of producing a flattering list.
DEFAULT_MIN_ENRICHED = 0.8

SCORE_BANDS = [(85, "85-100"), (70, "70-84"), (55, "55-69"), (40, "40-54"), (0, "0-39")]


class StepFailed(Exception):
    def __init__(self, step: str, reason: str, code: int = EXIT_FAILED):
        super().__init__(reason)
        self.step, self.reason, self.code = step, reason, code


def read_view() -> dict:
    """discovered_jobs.json, after making sure it matches the ledger it is derived from (view_guard)."""
    try:
        view_guard.ensure(DISCOVERED, view_guard.job_history.ledger_path(DISCOVERED))
    except view_guard.ViewRecoveryError as exc:
        raise StepFailed("discovery", f"the job list is out of date and could not be rebuilt: {exc}")
    return read_json(DISCOVERED)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--providers", default="serbia", help="provider names or group (default: serbia)")
    p.add_argument("--country", help="overrides the country in the candidate intelligence")
    p.add_argument("--skip-discovery", action="store_true", help="reuse discovered_jobs.json as it is")
    p.add_argument("--skip-enrich", action="store_true",
                   help="score without reading the ads; the result is labelled reduced quality")
    p.add_argument("--min-enriched", type=float, default=DEFAULT_MIN_ENRICHED,
                   help="stop before scoring if fewer than this share of jobs has facts (default 0.8)")
    p.add_argument("--tailor", action="store_true", help="generate documents for Apply jobs after scoring")
    p.add_argument("--tailor-limit", type=int, default=10)
    p.add_argument("--tailor-confirm", action="store_true",
                   help="with --tailor: the redacted text may be sent to Claude Code (run_tailor.py --preview shows it); "
                        "without it the documents are rule-based and nothing is sent")
    p.add_argument("--json", action="store_true", help="print the summary as JSON on the last line")
    return p.parse_args(argv)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_step(name: str, cmd: list[str], steps: list[dict]) -> str:
    """Run one script, streaming its output; returns its stdout. Raises StepFailed."""
    print(f"\n=== {name} ===", flush=True)
    started = time.monotonic()
    handed = {"pass_fds": (_held_lock.fd,)} if _held_lock else {}
    proc = subprocess.Popen(
        [sys.executable, *cmd], cwd=ROOT, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        # Every model call in a pipeline step is an automatic AI task (ai_gate.py).
        env={**(_held_lock.child_env() if _held_lock else os.environ), "HOLOJOB_AI_TRIGGER": "automation"},
        **handed,
    )
    lines = []
    for line in proc.stdout:
        lines.append(line)
        sys.stdout.write(line)
    code = proc.wait()
    steps.append({"step": name, "seconds": round(time.monotonic() - started, 1), "exitCode": code})
    if code != 0:
        tail = "".join(lines[-3:]).strip()
        raise StepFailed(name, f"exited with code {code}" + (f": {tail}" if tail else ""))
    return "".join(lines)


def check_discovery(started_at: datetime) -> dict:
    if not DISCOVERED.exists():
        raise StepFailed("discovery", f"{DISCOVERED.name} was not written")
    payload = read_view()
    meta = payload.get("meta") or {}
    stamp = meta.get("generatedAt")
    if not stamp or datetime.fromisoformat(stamp) < started_at:
        raise StepFailed("discovery", "the jobs file was not refreshed by this run")
    if not (meta.get("dedupedCount") or 0):
        raise StepFailed("discovery", "no provider returned a job; scoring would reuse stale results")
    return payload


def enriched_share(jobs: list[dict], prefs: dict | None = None) -> float:
    """Share of the jobs that should have facts. Ads enrichment deliberately did
    not read (outside the candidate's places, or not found by this run) are not expected to have them."""
    open_jobs = [j for j in jobs if not j.get("isClosed") and not row_state.not_found(j)] or jobs
    if prefs:
        open_jobs = [
            j for j in open_jobs
            if (j.get("llmFacts") or {}).get("_fingerprint") or not outside_allowed_before_enrichment(j, prefs)
        ] or open_jobs
    return sum(1 for j in open_jobs if (j.get("llmFacts") or {}).get("_fingerprint")) / max(1, len(open_jobs))


def check_enrichment(minimum: float, refusal: str | None = None) -> float:
    """The enriched share. Too low stops the run, unless the AI budget gate is why: then scoring goes on, reduced."""
    jobs = read_view().get("jobs") or []
    prefs = (read_json(INTELLIGENCE).get("jobFitPreferences") or {}) if INTELLIGENCE.exists() else {}
    share = enriched_share(jobs, prefs)
    if share < minimum and refusal:
        print(f"Enrichment reduced: only {share:.0%} of jobs have facts because the AI gate refused calls "
              f"({refusal}). Scoring continues; results are labelled reduced quality.", flush=True)
    elif share < minimum:
        raise StepFailed(
            "enrichment",
            f"only {share:.0%} of jobs have facts (minimum {minimum:.0%}): is the LLM provider reachable? "
            "Scoring now would skip the role-track and visa caps.",
        )
    return share


def summarize(args, steps: list[dict], enrich_line: str | None, share: float | None,
              reduced: str | None = None) -> dict:
    summary: dict = {"steps": steps}
    if DISCOVERED.exists():
        try:
            meta = read_view().get("meta") or {}
        except StepFailed:
            meta = {}
        summary["discovery"] = {
            "providerCounts": meta.get("providerCounts") or {},
            "raw": meta.get("rawCount"), "deduped": meta.get("dedupedCount"),
            "history": meta.get("history") or {},
            "rows": row_state.counts(read_view().get("jobs") or []) if meta else None,
        }
    if enrich_line is not None:
        m = re.search(r"extracted (\d+), cached (\d+) \((\d+) from the ledger\), failed (\d+)"
                      r"(?:, not read (\d+)[^,]*)?(?:, refused (\d+))?", enrich_line)
        summary["enrichment"] = {
            "enrichedShare": None if share is None else round(share, 3),
            **({"extracted": int(m[1]), "cached": int(m[2]), "failed": int(m[4]), "notRead": int(m[5] or 0),
                "refused": int(m[6] or 0)} if m else {}),
        }
    if reduced:
        summary["quality"] = {
            "reduced": True,
            "reason": reduced,
            "note": "scored without AI facts for some jobs: no role-track, seniority or work-mode facts, "
                    "so the role-track and visa caps may not apply to them",
        }
    if SCORED.exists():
        scored = read_json(SCORED)
        jobs = scored.get("jobs") or []
        bands = Counter()
        for j in jobs:
            score = j.get("matchScore") or 0
            bands[next(label for floor, label in SCORE_BANDS if score >= floor)] += 1
        live = [j for j in jobs if not j.get("isClosed")]
        summary["scoring"] = {
            "jobs": len(jobs),
            "labels": (scored.get("meta") or {}).get("summary") or {},
            "priority": dict(Counter(j.get("priority") for j in jobs)),
            "scoreBands": {label: bands[label] for _, label in SCORE_BANDS},
            "workAuthorization": dict(Counter((j.get("workAuthorization") or {}).get("status") for j in jobs)),
            "hardCapped": sum(1 for j in jobs if j.get("hardCapped")),
            "applyNow": sum(1 for j in live if j.get("priority") == "P1"),
        }
    return summary


def print_summary(s: dict) -> None:
    print("\n=== Summary ===")
    d = s.get("discovery")
    if d:
        counts = ", ".join(f"{k} {v}" for k, v in d["providerCounts"].items())
        h = d["history"]
        print(f"Discovery : {d['raw']} found, {d['deduped']} after dedup ({counts})")
        if h:
            print(f"            new {h.get('new', 0)}, known {h.get('known', 0)}, closed {h.get('closed', 0)}")
        rows = d.get("rows")
        if rows:
            print(f"Job list  : {rows['found']} found by this run, {rows['held']} kept open, {rows['closed']} closed and still shown")
            print(f"Absent    : {rows['absent']} not listed in the latest fetch; shown, with no AI calls")
    e = s.get("enrichment")
    if e:
        print(f"Enrichment: {e.get('enrichedShare', 0):.0%} of jobs have facts"
              + (f" ({e['extracted']} read, {e['cached']} cached, {e['failed']} failed, {e.get('notRead', 0)} outside allowed places not read"
                 f", {e.get('refused', 0)} refused by the AI gate)" if "extracted" in e else ""))
    q = s.get("quality")
    if q:
        print(f"Quality   : REDUCED - {q['reason']}")
    sc = s.get("scoring")
    if sc:
        print(f"Scoring   : {sc['jobs']} jobs, {sc['hardCapped']} capped by a hard rule, {sc['applyNow']} open P1")
        print("            score  " + "  ".join(f"{k}: {v}" for k, v in sc["scoreBands"].items()))
        print("            priority  " + "  ".join(f"{k}: {v}" for k, v in sorted(sc["priority"].items(), key=lambda kv: str(kv[0]))))
    print("Timing    : " + ", ".join(f"{x['step']} {x['seconds']}s" for x in s["steps"]))


def execute(args: argparse.Namespace, steps: list[dict]) -> dict:
    started_at = datetime.now(timezone.utc)
    enrich_line = share = reduced = None

    if not args.skip_discovery:
        cmd = [str(PY / "job_discovery" / "run_discovery.py"), "--providers", args.providers, "--trigger", "pipeline"]
        if args.country:
            cmd += ["--country", args.country]
        run_step("discovery", cmd, steps)
        check_discovery(started_at)
    elif not DISCOVERED.exists():
        raise StepFailed("discovery", f"--skip-discovery but {DISCOVERED.name} does not exist", EXIT_SETUP)

    if not args.skip_enrich:
        out = run_step("enrichment", [str(PY / "job_scoring" / "enrich_jobs.py")], steps)
        enrich_line = next((l for l in reversed(out.splitlines()) if l.startswith("extracted ")), "")
        refused_line = next((l for l in reversed(out.splitlines()) if l.startswith("ai gate refused: ")), None)
        reduced = refused_line[len("ai gate refused: "):].strip() if refused_line else None
        share = check_enrichment(args.min_enriched, reduced)
        if reduced:
            reduced = f"AI enrichment refused: {reduced}"

    if args.skip_enrich and not reduced:
        reduced = "enrichment skipped (--skip-enrich)"
    scoring = [str(PY / "job_scoring" / "run_scoring.py")]
    if reduced:
        # Written into scored_jobs.json meta, where the scores are read.
        scoring += ["--reduced-quality", reduced]
    run_step("scoring", scoring, steps)
    if not SCORED.exists() or datetime.fromtimestamp(SCORED.stat().st_mtime, timezone.utc) < started_at:
        raise StepFailed("scoring", "scored_jobs.json was not refreshed by this run")

    if args.tailor:
        run_step("tailoring", [str(PY / "resume_generator" / "run_tailor.py"), "--apply-only",
                               "--limit", str(args.tailor_limit), *(["--confirm"] if args.tailor_confirm else [])], steps)
    return summarize(args, steps, enrich_line, share, reduced)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not INTELLIGENCE.exists():
        print(f"Missing {INTELLIGENCE}. Generate candidate intelligence in the app first.", file=sys.stderr)
        return EXIT_SETUP
    if not 0 <= args.min_enriched <= 1:
        print("--min-enriched must be between 0 and 1", file=sys.stderr)
        return EXIT_SETUP

    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        probe = LOCK.parent / ".write-probe"
        probe.write_text("ok")
        probe.unlink()
        for path in (INTELLIGENCE, DISCOVERED):
            if path.exists():
                path.read_bytes()[:1]
    except OSError as exc:
        # A 25-minute run that cannot save its result is worse than no run. On
        # SELinux hosts another container mounting ./data with :Z causes this.
        print(f"Cannot read and write {LOCK.parent}: {exc}. Nothing started.", file=sys.stderr)
        return EXIT_SETUP
    global _held_lock
    _held_lock = pipeline_lock.acquire()
    if _held_lock is None:
        print(pipeline_lock.BUSY_MESSAGE, file=sys.stderr)
        return EXIT_LOCKED

    steps: list[dict] = []
    record: dict = {"startedAt": datetime.now(timezone.utc).isoformat(), "status": "failed"}
    code = EXIT_FAILED
    try:
        summary = execute(args, steps)
        record.update(status="ok", **summary)
        print_summary(summary)
        if args.json:
            print(json.dumps(summary))
        code = 0
    except StepFailed as exc:
        record.update(failedStep=exc.step, reason=exc.reason, steps=steps)
        later = {"discovery": "enrichment, scoring", "enrichment": "scoring", "scoring": "document generation"}.get(exc.step, "")
        print(f"\nPIPELINE STOPPED at {exc.step}: {exc.reason}", file=sys.stderr)
        if later:
            print(f"Not run: {later}. The previous results on disk are unchanged by the steps that did not run.", file=sys.stderr)
        code = exc.code
    finally:
        record["finishedAt"] = datetime.now(timezone.utc).isoformat()
        write_text_atomic(LAST_RUN, json.dumps(record, indent=2))
        _held_lock.release()
        _held_lock = None
    return code


if __name__ == "__main__":
    raise SystemExit(main())
