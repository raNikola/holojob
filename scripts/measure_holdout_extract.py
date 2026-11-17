#!/usr/bin/env python3
"""Holdout extraction: one extraction pass for the holdout ads that have no facts, written into a SCRATCH copy of the data dir.

THIS SCRIPT CALLS A MODEL PROVIDER (and bills it) ONLY WITH --confirm. Without it, it prints the estimate and the hard cap and stops.

    .venv/bin/python scripts/measure_holdout_extract.py --max-usd 0.15              # estimate only
    .venv/bin/python scripts/measure_holdout_extract.py --max-usd 0.15 --confirm    # the run

--ids FILE      default /home/ranikola/holojob-eval/holdout-ids.json. Ads that already carry facts for this exact text are left out.
--scratch DIR   default /home/ranikola/holojob-eval/holdout-scratch-data (mode 700). Refused if it is, or sits inside, the real data dir.
--max-usd X     required. With --confirm the run is refused when the worst case (every call returns its maximum output) is above X,
                and enrich_jobs.SpendGuard enforces X per call as well.

Reuses measure_extraction_variance (ad-text lookup, price estimate, the extraction loop) and enrich_jobs.extract; nothing forked.
The real data dir is only read. Facts go into <scratch>/jobs/job_history.json (the ledger entry and its stored ad row, because a
kept ad is scored from that row). The AI ledger the gate writes is the scratch copy of data/ai, so this run's spend is recorded
there and NOT in the real data/ai ledger. Refuses if the price is unknown or any ad text is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_common as mc  # noqa: E402
import measure_extraction_variance as mv  # noqa: E402

DEFAULT_IDS = mc.EVAL_DIR / "holdout-ids.json"
DEFAULT_SCRATCH = mc.EVAL_DIR / "holdout-scratch-data"
# Copied into the scratch dir: what a Re-score and the gate read. Never secrets, CVs, applications or backups.
COPY_DIRS = ("jobs", "intelligence", "profile", "cache", "config", "ai")


def check_scratch(scratch: Path, data_dir: Path) -> None:
    s, d = Path(scratch).resolve(), Path(data_dir).resolve()
    if s == d or d in s.parents or s in d.parents:
        raise SystemExit(f"refusing: scratch dir {s} is, contains or sits inside the real data dir {d}")


def ledger_entry_text(ledger: dict, job_id: str) -> str:
    entry = (ledger.get("jobs") or {}).get(job_id) or {}
    return ((entry.get("job") or {}).get("description") or "").strip()


def pending_ids(data_dir: Path, ids: list[str]) -> tuple[list[dict], list[str], list[str]]:
    """(jobs to read, ids already read, ids whose text is unavailable). Reads the real data dir only."""
    from job_fingerprint import job_fingerprint
    jobs, missing = mv.load_jobs(data_dir, ids)
    no_text = list(missing) + [j["jobId"] for j in jobs if not (j.get("description") or "").strip()]
    todo, read = [], []
    for j in jobs:
        facts = j.get("llmFacts")
        if facts and facts.get("_fingerprint") == job_fingerprint(j):
            read.append(j["jobId"])
        else:
            todo.append(j)
    return todo, read, no_text


def prepare_scratch(scratch: Path, data_dir: Path) -> None:
    from atomic_write import make_private_dirs
    scratch = Path(scratch)
    make_private_dirs(scratch)
    os.chmod(scratch, 0o700)
    for sub in COPY_DIRS:
        src, dst = Path(data_dir) / sub, scratch / sub
        if src.exists() and not dst.exists():
            shutil.copytree(src, dst)
            for p in [dst, *dst.rglob("*")]:
                os.chmod(p, 0o700 if p.is_dir() else 0o600)


def store_facts(scratch: Path, results: dict) -> int:
    """Put each ad's facts on its scratch ledger entry and stored ad row. Returns how many ads were written."""
    import job_history
    path = Path(scratch) / "jobs" / "job_history.json"
    ledger = job_history.load(path)
    n = 0
    for job_id, runs in results.items():
        entry = ledger["jobs"].get(job_id)
        if not runs or entry is None:
            continue
        entry["llmFacts"] = runs[0]
        if isinstance(entry.get("job"), dict):
            entry["job"]["llmFacts"] = runs[0]  # kept_ads.ledger_row scores from this row
        n += 1
    if n:
        job_history.save(path, ledger)  # generation is untouched, so the view stays in step
        os.chmod(path, 0o600)
    return n


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ids", type=Path, default=DEFAULT_IDS)
    p.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH)
    p.add_argument("--max-usd", type=float, required=True)
    p.add_argument("--provider", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--data-dir", type=Path, default=None, help="the real data dir (read only); default as the other measure scripts")
    p.add_argument("--confirm", action="store_true", help="REQUIRED to call the provider")
    args = p.parse_args(argv)

    if args.max_usd <= 0:
        print("--max-usd must be positive", file=sys.stderr)
        return 2
    data_dir = Path(args.data_dir or mc.default_data_dir())
    check_scratch(args.scratch, data_dir)
    # Estimate phase: settings and key store of the real data dir, read only.
    for var, sub in (("HOLOJOB_CONFIG_DIR", "config"), ("HOLOJOB_AI_DIR", "ai"), ("HOLOJOB_SECRETS_DIR", "secrets")):
        os.environ[var] = str(data_dir / sub)
    before = mc.data_fingerprint(data_dir)

    ids = mv.read_ids(args.ids)
    todo, already, no_text = pending_ids(data_dir, ids)
    if no_text:
        print(f"refusing: ad text is unavailable for {len(no_text)} ids: {', '.join(no_text)}", file=sys.stderr)
        return 1
    if not todo:
        print(f"nothing to read: all {len(ids)} ads already have facts")
        return 0

    import competency_mapping
    from llm_client import LlmUnavailable
    intelligence = data_dir / "intelligence" / "candidate-intelligence.json"
    family = (json.loads(intelligence.read_text(encoding="utf-8")).get("roleFamily") or None) if intelligence.exists() else None
    mapper = competency_mapping.load_mapper(family)  # mapper.save() is never called
    try:
        est = mv.estimate(todo, 1, args.provider, args.model, None, mapper)
    except LlmUnavailable as exc:
        print(f"cannot price the run, so nothing is called: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"estimate": est, "adsToRead": len(todo), "alreadyRead": already, "hardCapUsd": args.max_usd,
                      "scratchDir": str(args.scratch)}, indent=1))
    if not est.get("priceKnown"):
        print("the price of this provider/model is unknown to the budget gate, so the cost cannot be bounded: refusing.", file=sys.stderr)
        return 1
    if not args.confirm:
        print(f"\nNothing was called and nothing was written. Estimated worst case ${est['worstCaseUsd']:.4f} for {est['calls']} calls "
              f"(input-only floor ${est['inputOnlyUsd']:.4f}); hard cap --max-usd {args.max_usd}. Add --confirm to run it.")
        if est["worstCaseUsd"] > args.max_usd:
            print(f"NOTE: the worst case is above the cap, so --confirm would be refused at this --max-usd.")
        return 0
    if est["worstCaseUsd"] > args.max_usd:
        print(f"refusing: worst case ${est['worstCaseUsd']:.4f} is above --max-usd {args.max_usd}", file=sys.stderr)
        return 1

    # Confirmed: from here on the gate's ledger and settings are the scratch copies; the key store stays the real one (read only).
    prepare_scratch(args.scratch, data_dir)
    os.environ["HOLOJOB_CONFIG_DIR"] = str(args.scratch / "config")
    os.environ["HOLOJOB_AI_DIR"] = str(args.scratch / "ai")
    import ai_gate
    import enrich_jobs
    from llm_client import LlmRefused
    os.environ[ai_gate.TRIGGER_ENV] = ai_gate.MANUAL
    try:
        guard = enrich_jobs.make_guard(args.max_usd, args.provider, args.model)
    except (LlmUnavailable, LlmRefused) as exc:
        print(f"spend guard refused: {exc}", file=sys.stderr)
        return 1
    results, failures = mv.run_extractions(todo, 1, args.provider, args.model, guard, args.workers, None, mapper)
    written = store_facts(args.scratch, results)
    changed = mc.fingerprint_changes(before, mc.data_fingerprint(data_dir))
    print(f"read {written} of {len(todo)} ads; failures: {failures or 'none'}; spent ${guard.spent():.4f} of the ${args.max_usd:.2f} cap")
    print(f"real data dir changed by this run: {'NO' if not changed else changed}")
    print(f"next: .venv/bin/python scripts/measure_holdout_compare.py --data-dir {args.scratch}")
    return 0 if written == len(todo) and not changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
