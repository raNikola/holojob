#!/usr/bin/env python3
"""Score discovered jobs against candidate intelligence."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
# match_engine is a package under python/; appended, so no folder there shadows a module here.
if str(ROOT / "python") not in sys.path:
    sys.path.append(str(ROOT / "python"))

from atomic_write import write_text_atomic  # noqa: E402
from llm_client import LlmUnavailable, active_provider, judge_model, peek_provider  # noqa: E402
from llm_enhancer import (  # noqa: E402
    DEFAULT_JUDGE_LIMIT,
    DEFAULT_THRESHOLD,
    DIGEST_FIELDS,
    NEVER_SENT,
    LlmFitEnhancer,
)
import manual_jobs  # noqa: E402
import pipeline_lock  # noqa: E402
import view_guard  # noqa: E402
import job_history  # noqa: E402
from scorer import resolve_weights, score_jobs  # noqa: E402
from match_engine import shadow  # noqa: E402
from redact import identity_of  # noqa: E402 (on the path through llm_enhancer)

INTELLIGENCE_PATH = ROOT / "data" / "intelligence" / "candidate-intelligence.json"
JOBS_PATH = ROOT / "data" / "jobs" / "discovered_jobs.json"
OUTPUT_PATH = ROOT / "data" / "jobs" / "scored_jobs.json"
FIT_CACHE_PATH = ROOT / "data" / "cache" / "llm_fit.json"
PROFILE_PATH = ROOT / "data" / "profile" / "candidate-profile.json"

# Providers that answer from this machine; every other one is a remote service.
LOCAL_PROVIDERS = {"ollama"}


def _no_network(*_args, **_kwargs):
    raise RuntimeError("a cache-only run must never call the model")


def _load_profile() -> dict | None:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8")) if PROFILE_PATH.exists() else None


def _shadow_engine(profile: dict | None, intelligence: dict, judge: bool, provider: str, model: str | None):
    """The shadow engine when HOLOJOB_ENGINE_SHADOW is on and a profile is on disk, else None."""
    if not shadow.enabled():
        return None
    if profile is None:
        print(f"engine (shadow): skipped, no profile at {PROFILE_PATH}", file=sys.stderr)
        return None
    from confirmed_facts import load as load_confirmed_facts
    from evidence_index import build_candidate

    candidate = build_candidate(profile, intelligence, load_confirmed_facts())
    return shadow.ShadowEngine(candidate, judge=judge, provider=provider, model=model,
                               identity=identity_of(profile))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Score discovered jobs.")
    p.add_argument("--intelligence", type=Path, default=INTELLIGENCE_PATH)
    p.add_argument("--jobs", type=Path, default=JOBS_PATH)
    p.add_argument("--manual", type=Path, default=manual_jobs.MANUAL_PATH,
                   help="jobs typed in by hand; scored with the discovered ones, never rewritten here")
    p.add_argument("--output", type=Path, default=OUTPUT_PATH)
    p.add_argument("--min-score", type=int, default=0)
    p.add_argument(
        "--judge",
        action="store_true",
        help="ask an LLM to judge fit above the threshold; sends a candidate digest to the provider",
    )
    p.add_argument(
        "--judge-preview",
        action="store_true",
        help="print, as JSON, what --judge would send and to whom; calls nothing, writes nothing",
    )
    p.add_argument("--judge-threshold", type=int, default=DEFAULT_THRESHOLD)
    p.add_argument(
        "--judge-limit",
        type=int,
        default=DEFAULT_JUDGE_LIMIT,
        help="send at most this many jobs to the judge, the highest by local score (0 = no limit)",
    )
    p.add_argument("--judge-provider", default=None, help="the provider selected in Settings when unset")
    p.add_argument("--judge-model", default=None, help="<PROVIDER>_JUDGE_MODEL when unset")
    p.add_argument("--workers", type=int, default=8, help="parallel judge calls")
    p.add_argument(
        "--reduced-quality",
        default=None,
        metavar="REASON",
        help="run_pipeline.py: the ads were not (all) read by the model, and why; recorded in the meta",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.judge and args.judge_preview:
        print("--judge and --judge-preview are exclusive", file=sys.stderr)
        return 2
    if args.judge_preview:  # writes nothing, so it can answer during a run
        return score(args)
    lock = pipeline_lock.acquire()
    if lock is None:
        print(pipeline_lock.BUSY_MESSAGE, file=sys.stderr)
        return pipeline_lock.EXIT_LOCKED
    try:
        return score(args)
    finally:
        lock.release()


def score(args: argparse.Namespace) -> int:
    if not args.intelligence.exists():
        print(f"Missing intelligence: {args.intelligence}", file=sys.stderr)
        return 1
    manual = manual_jobs.load(args.manual)
    # Before the first discovery run only the hand-entered jobs exist; that is a valid input.
    if not args.jobs.exists() and not manual:
        print(f"Missing jobs: {args.jobs}", file=sys.stderr)
        return 1

    if args.jobs.exists():
        # The job list is a view of the ledger: one left behind by a stopped commit is rebuilt before it is scored.
        view_guard.ensure_or_exit(args.jobs, job_history.ledger_path(args.jobs))
    intelligence = json.loads(args.intelligence.read_text(encoding="utf-8"))
    discovered = json.loads(args.jobs.read_text(encoding="utf-8")) if args.jobs.exists() else {"jobs": []}
    jobs = discovered.get("jobs") if isinstance(discovered, dict) else discovered
    if not isinstance(jobs, list):
        print("Invalid discovered jobs format", file=sys.stderr)
        return 1
    # A hand-entered job is scored with every run and wins over a discovered row with the same URL.
    discovered_rows = len(jobs)
    jobs = manual_jobs.with_manual(jobs, manual)
    replaced_rows = discovered_rows + len(manual) - len(jobs)
    if manual:
        # Counts only: nothing of a job's text is printed.
        print(f"manual jobs: {len(manual)} added, {replaced_rows} discovered rows replaced by them", file=sys.stderr)

    profile = _load_profile()
    # The owner's name and links, to strip from the judge's digest; never sent.
    # Every enhancer gets it, so a cache-only run builds the same prompts and
    # finds the judgements a judged run stored.
    identity = identity_of(profile)
    # A judged run (or its preview) needs the selected provider and refuses without one. A local re-score makes no
    # call and only re-applies cached judgements, so it never fails for want of a selection.
    try:
        provider = args.judge_provider or (active_provider() if args.judge or args.judge_preview else peek_provider())
    except LlmUnavailable as exc:
        print(f"judge: {exc}", file=sys.stderr)
        return 1
    model = args.judge_model or (judge_model(provider) if provider else None)
    limit = args.judge_limit if args.judge_limit > 0 else None
    if args.judge or args.judge_preview:
        # A preview reads the cache and counts what a judged run would send,
        # under the same cap, without calling anything.
        enhancer = LlmFitEnhancer(
            provider, model, threshold=args.judge_threshold, cache_path=FIT_CACHE_PATH,
            limit=limit, identity=identity,
            **({"complete": _no_network, "cache_only": True} if args.judge_preview else {}),
        )
        if args.judge:
            print(
                f"judge: provider={provider} model={model or '(provider default)'} "
                f"threshold={args.judge_threshold} limit={limit or 'none'}",
                flush=True,
            )
    else:
        # Local scoring: judgements already in the cache are re-applied, so a
        # re-score does not throw them away. Nothing is sent: the model call is
        # replaced with one that raises.
        enhancer = LlmFitEnhancer(
            provider, model, threshold=args.judge_threshold, cache_path=FIT_CACHE_PATH,
            complete=_no_network, cache_only=True, identity=identity,
        )

    scored = score_jobs(jobs, intelligence, enhancer, workers=args.workers)
    c = enhancer.counts

    # Shadow mode (ENGINE_CONTRACT.md section 7): adds engineShadow to each job
    # and changes no other field, so ranking, labels and priority stay the
    # current score's. A failure here is reported and never stops the run.
    engine, engine_summary = None, None
    try:
        engine = _shadow_engine(profile, intelligence, args.judge, provider, model)
        if engine and args.judge_preview:
            engine_summary = engine.preview(scored)
        elif engine:
            scored = engine.apply(scored)
            engine.save()
            engine_summary = {"enabled": True, **engine.counts, "refusal": engine.refusal,
                              "limit": engine.limit if args.judge else None}
            n = engine.counts
            print(f"engine (shadow): {n['matched']} new calls, {n['cached']} from cache; without output: "
                  f"{n['uncached']} not matched yet (needs a judged run), {n['beyondLimit']} beyond the "
                  f"per-run limit, {n['noRequirements']} with no requirements extracted, {n['closed']} closed; "
                  f"{n['failed']} failed")
    except Exception as exc:  # shadow output is optional; the scoring run is not
        print(f"engine (shadow): skipped after an error: {exc}", file=sys.stderr)
        engine_summary = {"enabled": True, "error": str(exc)[:300]}

    if args.judge_preview:
        eligible = c["cached"] + c["uncached"] + c["beyond_limit"]
        print(json.dumps({
            "provider": provider,
            "model": model,
            "leavesServer": provider not in LOCAL_PROVIDERS,
            "threshold": args.judge_threshold,
            "limit": limit,
            "eligible": eligible,
            "cached": c["cached"],
            "toSend": c["uncached"],
            "beyondLimit": c["beyond_limit"],
            "sent": DIGEST_FIELDS,
            "neverSent": NEVER_SENT,
            "engine": engine_summary or {"enabled": False},
        }))
        return 0
    judge_summary = {
        "scored": len(scored),
        "judged": c["judged"],
        "fromCache": c["cached"],
        "beyondLimit": c["beyond_limit"],
        "belowThreshold": c["skipped"],
        "closed": c["closed"],
        "failed": c["failed"],
        "refused": c["refused"],
        "refusal": enhancer.refusal,
        "limit": limit if args.judge else None,
        "threshold": args.judge_threshold,
    }
    if args.judge:
        enhancer.save()
        print(
            f"judge: scored {len(scored)} jobs, judged {c['judged'] + c['cached']} "
            f"({c['judged']} new calls, {c['cached']} from cache); "
            f"{c['beyond_limit']} more at or above {args.judge_threshold} left at their local score "
            f"beyond the top {limit or 'all'}; {c['skipped']} below the threshold; {c['failed']} failed"
            + (f"; {c['refused']} refused by the AI gate ({enhancer.refusal})" if c["refused"] else "")
        )
    elif c["cached"]:
        print(f"judge: re-applied {c['cached']} cached judgements (no calls made)")
    if args.min_score > 0:
        # Nothing is hidden: a hand-entered job stays whatever its score.
        scored = [j for j in scored if j.get("manualEntry") or j.get("matchScore", 0) >= args.min_score]

    # A job scored without the ad facts (enrichment refused by the AI gate, skipped,
    # failed, or the ad lies outside the allowed places) is marked, never hidden:
    # its role-track and visa caps could not be checked against the ad.
    for job in scored:
        manual_jobs.mark_missing_facts(job)
    without_facts = sum(1 for j in scored if j.get("aiEnrichment") == "missing")

    labels = Counter(j.get("matchLabel") for j in scored)
    weights = resolve_weights(intelligence.get("scoringWeights"))

    payload = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sourceRunId": uuid.uuid4().hex[:12],
            # The run-log record of the discovery run these jobs came from. A Re-score has its own sourceRunId and the
            # same discoveryRunId, so several scorings can point at one record. None: hand-entered jobs only, or an older file.
            "discoveryRunId": (discovered.get("meta") or {}).get("sourceRunId") if isinstance(discovered, dict) else None,
            "scoringVersion": "1.0",
            "intelligenceGeneratedAt": (intelligence.get("meta") or {}).get("generatedAt"),
            "discoveryGeneratedAt": (discovered.get("meta") or {}).get("generatedAt") if isinstance(discovered, dict) else None,
            "weights": weights,
            "judge": judge_summary,
            "engineShadow": engine_summary or {"enabled": False},
            "aiEnrichment": {"jobsWithoutFacts": without_facts, "jobs": len(scored)},
            "manualJobs": {"count": len(manual), "replacedRows": replaced_rows},
            "quality": {"reduced": True, "reason": args.reduced_quality} if args.reduced_quality
            else {"reduced": False},
            "jobCount": len(scored),
            "summary": {
                "excellent": labels.get("Excellent", 0),
                "strong": labels.get("Strong", 0),
                "good": labels.get("Good", 0),
                "weak": labels.get("Weak", 0),
                "reject": labels.get("Reject", 0),
            },
        },
        "jobs": scored,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(args.output, json.dumps(payload, indent=2))

    shown = args.output.relative_to(ROOT) if args.output.is_relative_to(ROOT) else args.output
    print(f"Scored {len(scored)} jobs -> {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
