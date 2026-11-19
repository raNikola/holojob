#!/usr/bin/env python3
"""Extract the requirements (llmFacts) of ads that are in the job ledger but not in the job list. Owner-run, never part of a pipeline run.

    .venv/bin/python python/job_scoring/extract_ledger_ads.py --ids FILE                           # estimate only: counts, tokens, USD; sends nothing
    .venv/bin/python python/job_scoring/extract_ledger_ads.py --ids FILE --max-usd 0.25 --confirm  # the paid run, hard-stopped at the cap

Why: enrich_jobs.py reads only the ads of the job list, so an ad the list no longer holds never gets its facts. This reads the same prompt, the same
extractor (`enrich_jobs.extract`, prompt unchanged), the same AI budget gate (feature `enrichment`) and the same spend guard (`--max-usd`), and writes
the facts back the way enrich_jobs.py does: into the ledger entry (`llmFacts`), ledger first, then the derived view, through `view_guard.commit`. The
job list gains or loses no ad. Before the first write the ledger is copied to data/backups/ (mode 600). The extractor never sees the candidate. Prints
counts and ids only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for sub in ("cv_analysis", "llm", "job_scoring"):
    sys.path.insert(0, str(ROOT / "python" / sub))
sys.path.append(str(ROOT / "python"))

import ai_gate  # noqa: E402
import competency_mapping  # noqa: E402
import enrich_jobs as ej  # noqa: E402
import job_history  # noqa: E402
import pipeline_lock  # noqa: E402
import requirement_frames  # noqa: E402
import row_state  # noqa: E402
import view_guard  # noqa: E402
from atomic_write import PRIVATE_DIR_MODE, PRIVATE_FILE_MODE, make_private_dirs  # noqa: E402
from llm_client import GuardrailRefused, LlmRefused, LlmUnavailable, active_provider, preflight  # noqa: E402

JOBS_PATH = ej.JOBS_PATH
BACKUP_DIR = ROOT / "data" / "backups"


def pending_of(ledger: dict, ids: set[str]) -> tuple[list[dict], dict]:
    """(rows to read, counts): the ledger's stored ad of each wanted id that has no current facts and is not closed / not found."""
    rows, counts = [], {"wanted": len(ids), "notInLedger": 0, "alreadyRead": 0, "closedOrNotFound": 0}
    for i in sorted(ids):
        entry = (ledger.get("jobs") or {}).get(i)
        if not isinstance(entry, dict) or not isinstance(entry.get("job"), dict):
            counts["notInLedger"] += 1
            continue
        job = {**entry["job"], "jobId": i}
        if (entry.get("llmFacts") or {}).get("_fingerprint") == ej._fingerprint(job):
            counts["alreadyRead"] += 1
        elif job.get("isClosed") or row_state.not_found(job):
            counts["closedOrNotFound"] += 1
        else:
            rows.append(job)
    counts["toRead"] = len(rows)
    return rows, counts


def backup(ledger_file: Path) -> Path:
    make_private_dirs(BACKUP_DIR)
    target = BACKUP_DIR / f"{ledger_file.name}.pre-extract-ledger-ads"
    n = 0
    while target.exists():
        n += 1
        target = BACKUP_DIR / f"{ledger_file.name}.pre-extract-ledger-ads-{n}"
    shutil.copyfile(ledger_file, target)
    target.chmod(PRIVATE_FILE_MODE)
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ids", type=Path, required=True, help="JSON file of ad ids (a list or {\"ids\": [...]}); only ledger ads without current facts are read")
    ap.add_argument("--max-usd", type=float, default=None, help="the run's hard stop in US dollars; required with --confirm")
    ap.add_argument("--confirm", action="store_true", help="make the paid calls")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    if args.confirm and args.max_usd is None:
        print("--confirm needs --max-usd", file=sys.stderr)
        return 2
    lock = pipeline_lock.acquire()
    if lock is None:
        print(pipeline_lock.BUSY_MESSAGE, file=sys.stderr)
        return pipeline_lock.EXIT_LOCKED
    try:
        return run(args)
    finally:
        lock.release()


def run(args) -> int:
    import os

    os.environ[ai_gate.TRIGGER_ENV] = ai_gate.MANUAL
    provider = active_provider()
    ledger_file = job_history.ledger_path(JOBS_PATH)
    view_guard.ensure_or_exit(JOBS_PATH, ledger_file)
    ledger = job_history.load(ledger_file)
    rows, counts = pending_of(ledger, ej._load_ids(args.ids))

    mapper = competency_mapping.load_mapper(ej._role_family(ej.INTELLIGENCE_PATH))
    remap = mapper.remap if mapper else competency_mapping.load_remap()
    frames = requirement_frames.load()
    requirement_frames.apply_remap(frames, remap)
    prompts = {j["jobId"]: ej.build_prompt(j, requirement_frames.previous_for(frames, j, remap), mapper) for j in rows}

    guard = ej.make_guard(args.max_usd if args.max_usd is not None else 1e9, provider, None)
    worst = sum(guard.worst(p) for p in prompts.values())
    print(f"ledger ads wanted {counts['wanted']}: to read now {counts['toRead']}, already read {counts['alreadyRead']}, "
          f"closed or not found {counts['closedOrNotFound']}, not in the ledger {counts['notInLedger']}")
    print(f"prompt size {sum(len(p) for p in prompts.values())} characters; estimated cost (upper bound) ${worst:.4f}")
    settings = ai_gate.load_settings()
    totals = ai_gate.totals(None, settings)
    print(f"budget: today {totals['today']['cost']:.4f} of {settings.get('dailyLimit')}; this month {totals['thisMonth']['cost']:.4f} of {settings.get('monthlyLimit')}")
    if not args.confirm or not rows:
        print("nothing sent: add --max-usd N --confirm after the estimate is approved")
        return 0
    if worst > args.max_usd:
        print(f"stopped: estimate ${worst:.4f} is over the cap ${args.max_usd:.2f}; nothing was sent", file=sys.stderr)
        return 1
    with ai_gate.context(feature="enrichment"):
        decision = preflight(max(len(p) for p in prompts.values()), provider, None)
    if not decision.allowed:
        ai_gate.record_refused(decision, skipped=len(rows))
        print(f"stopped: AI gate refused: {decision.reason}", file=sys.stderr)
        return 1

    guard = ej.make_guard(args.max_usd, provider, None)
    stop, done, failed, refused, facts_by_id = threading.Event(), 0, 0, 0, {}

    def one(job):
        if stop.is_set():
            raise ej._Skipped
        try:
            return ej.extract(job, None, provider, requirement_frames.previous_for(frames, job, remap),
                              **({"mapper": mapper} if mapper else {}), guard=guard)
        except GuardrailRefused:
            stop.set()
            raise

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(one, job): job for job in rows}
        for future in as_completed(futures):
            job = futures[future]
            try:
                facts_by_id[job["jobId"]] = future.result()
                requirement_frames.remember(frames, {**job, "llmFacts": facts_by_id[job["jobId"]]}, facts_by_id[job["jobId"]])
                done += 1
            except (ej._Skipped, GuardrailRefused):
                refused += 1
            except (LlmUnavailable, LlmRefused) as exc:
                print(f"{job['jobId']}: failed: {exc}", file=sys.stderr)
                failed += 1
    print(f"extraction spend: ${guard.spent():.4f} of the ${guard.cap:.2f} cap")
    if mapper:
        mapper.save()
    if facts_by_id:
        requirement_frames.save(frames)
        saved = backup(ledger_file)
        print(f"ledger backed up to {saved.relative_to(ROOT)}")
        for i, facts in facts_by_id.items():
            ledger["jobs"][i]["llmFacts"] = facts
        if isinstance(ledger.get("lastImport"), dict):
            ledger["generation"] = (ledger.get("generation") or 0) + 1
            ledger["updatedAt"] = job_history.now_iso()
            view_guard.commit(ledger, JOBS_PATH, ledger_file)
        else:
            job_history.save(ledger_file, ledger)
    print(f"extracted {done}, failed {failed}, refused {refused}")
    return 0 if done or not rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
