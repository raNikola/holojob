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
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "python"
DATA = ROOT / "data"
INTELLIGENCE = DATA / "intelligence" / "candidate-intelligence.json"
DISCOVERED = DATA / "jobs" / "discovered_jobs.json"
SCORED = DATA / "jobs" / "scored_jobs.json"
LAST_RUN = DATA / "jobs" / "pipeline_last_run.json"
LOCK = DATA / "jobs" / ".pipeline.lock"

EXIT_FAILED, EXIT_SETUP, EXIT_LOCKED = 1, 2, 75

# Scoring on jobs the model never read would skip the role-track and visa caps,
# so too few enriched jobs stops the run instead of producing a flattering list.
DEFAULT_MIN_ENRICHED = 0.8

SCORE_BANDS = [(85, "85-100"), (70, "70-84"), (55, "55-69"), (40, "40-54"), (0, "0-39")]


class StepFailed(Exception):
    def __init__(self, step: str, reason: str, code: int = EXIT_FAILED):
        super().__init__(reason)
        self.step, self.reason, self.code = step, reason, code


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--providers", default="serbia", help="provider names or group (default: serbia)")
    p.add_argument("--country", help="overrides the country in the candidate intelligence")
    p.add_argument("--skip-discovery", action="store_true", help="reuse discovered_jobs.json as it is")
    p.add_argument("--skip-enrich", action="store_true", help="score without reading the ads (not recommended)")
    p.add_argument("--min-enriched", type=float, default=DEFAULT_MIN_ENRICHED,
                   help="stop before scoring if fewer than this share of jobs has facts (default 0.8)")
    p.add_argument("--tailor", action="store_true", help="tailor documents for Apply jobs after scoring")
    p.add_argument("--tailor-limit", type=int, default=10)
    p.add_argument("--json", action="store_true", help="print the summary as JSON on the last line")
    return p.parse_args(argv)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_step(name: str, cmd: list[str], steps: list[dict]) -> str:
    """Run one script, streaming its output; returns its stdout. Raises StepFailed."""
    print(f"\n=== {name} ===", flush=True)
    started = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, *cmd], cwd=ROOT, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
    payload = read_json(DISCOVERED)
    meta = payload.get("meta") or {}
    stamp = meta.get("generatedAt")
    if not stamp or datetime.fromisoformat(stamp) < started_at:
        raise StepFailed("discovery", "the jobs file was not refreshed by this run")
    if not (meta.get("dedupedCount") or 0):
        raise StepFailed("discovery", "no provider returned a job; scoring would reuse stale results")
    return payload


def enriched_share(jobs: list[dict]) -> float:
    open_jobs = [j for j in jobs if not j.get("isClosed")] or jobs
    return sum(1 for j in open_jobs if (j.get("llmFacts") or {}).get("_fingerprint")) / max(1, len(open_jobs))


def check_enrichment(minimum: float) -> float:
    jobs = read_json(DISCOVERED).get("jobs") or []
    share = enriched_share(jobs)
    if share < minimum:
        raise StepFailed(
            "enrichment",
            f"only {share:.0%} of jobs have facts (minimum {minimum:.0%}): is the LLM provider reachable? "
            "Scoring now would skip the role-track and visa caps.",
        )
    return share


def summarize(args, steps: list[dict], enrich_line: str | None, share: float | None) -> dict:
    summary: dict = {"steps": steps}
    if DISCOVERED.exists():
        meta = read_json(DISCOVERED).get("meta") or {}
        summary["discovery"] = {
            "providerCounts": meta.get("providerCounts") or {},
            "raw": meta.get("rawCount"), "deduped": meta.get("dedupedCount"),
            "history": meta.get("history") or {},
        }
    if enrich_line is not None:
        m = re.search(r"extracted (\d+), cached (\d+) \((\d+) from the ledger\), failed (\d+)", enrich_line)
        summary["enrichment"] = {
            "enrichedShare": None if share is None else round(share, 3),
            **({"extracted": int(m[1]), "cached": int(m[2]), "failed": int(m[4])} if m else {}),
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
    e = s.get("enrichment")
    if e:
        print(f"Enrichment: {e.get('enrichedShare', 0):.0%} of jobs have facts"
              + (f" ({e['extracted']} read, {e['cached']} cached, {e['failed']} failed)" if "extracted" in e else ""))
    sc = s.get("scoring")
    if sc:
        print(f"Scoring   : {sc['jobs']} jobs, {sc['hardCapped']} capped by a hard rule, {sc['applyNow']} open P1")
        print("            score  " + "  ".join(f"{k}: {v}" for k, v in sc["scoreBands"].items()))
        print("            priority  " + "  ".join(f"{k}: {v}" for k, v in sorted(sc["priority"].items(), key=lambda kv: str(kv[0]))))
    print("Timing    : " + ", ".join(f"{x['step']} {x['seconds']}s" for x in s["steps"]))


def execute(args: argparse.Namespace, steps: list[dict]) -> dict:
    started_at = datetime.now(timezone.utc)
    enrich_line = share = None

    if not args.skip_discovery:
        cmd = [str(PY / "job_discovery" / "run_discovery.py"), "--providers", args.providers]
        if args.country:
            cmd += ["--country", args.country]
        run_step("discovery", cmd, steps)
        check_discovery(started_at)
    elif not DISCOVERED.exists():
        raise StepFailed("discovery", f"--skip-discovery but {DISCOVERED.name} does not exist", EXIT_SETUP)

    if not args.skip_enrich:
        out = run_step("enrichment", [str(PY / "job_scoring" / "enrich_jobs.py")], steps)
        enrich_line = next((l for l in reversed(out.splitlines()) if l.startswith("extracted ")), "")
        share = check_enrichment(args.min_enriched)

    run_step("scoring", [str(PY / "job_scoring" / "run_scoring.py")], steps)
    if not SCORED.exists() or datetime.fromtimestamp(SCORED.stat().st_mtime, timezone.utc) < started_at:
        raise StepFailed("scoring", "scored_jobs.json was not refreshed by this run")

    if args.tailor:
        run_step("tailoring", [str(PY / "resume_generator" / "run_tailor.py"), "--apply-only",
                               "--limit", str(args.tailor_limit)], steps)
    return summarize(args, steps, enrich_line, share)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not INTELLIGENCE.exists():
        print(f"Missing {INTELLIGENCE}. Generate candidate intelligence in the app first.", file=sys.stderr)
        return EXIT_SETUP
    if not 0 <= args.min_enriched <= 1:
        print("--min-enriched must be between 0 and 1", file=sys.stderr)
        return EXIT_SETUP

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    lock = LOCK.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another pipeline run is in progress; nothing started.", file=sys.stderr)
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
        later = {"discovery": "enrichment, scoring", "enrichment": "scoring", "scoring": "tailoring"}.get(exc.step, "")
        print(f"\nPIPELINE STOPPED at {exc.step}: {exc.reason}", file=sys.stderr)
        if later:
            print(f"Not run: {later}. The previous results on disk are unchanged by the steps that did not run.", file=sys.stderr)
        code = exc.code
    finally:
        record["finishedAt"] = datetime.now(timezone.utc).isoformat()
        LAST_RUN.write_text(json.dumps(record, indent=2), encoding="utf-8")
        lock.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
