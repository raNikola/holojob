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

from llm_client import active_provider, judge_model  # noqa: E402
from llm_enhancer import DEFAULT_THRESHOLD, DIGEST_FIELDS, NEVER_SENT, LlmFitEnhancer  # noqa: E402
from scorer import resolve_weights, score_jobs  # noqa: E402

INTELLIGENCE_PATH = ROOT / "data" / "intelligence" / "candidate-intelligence.json"
JOBS_PATH = ROOT / "data" / "jobs" / "discovered_jobs.json"
OUTPUT_PATH = ROOT / "data" / "jobs" / "scored_jobs.json"
FIT_CACHE_PATH = ROOT / "data" / "cache" / "llm_fit.json"

# Providers that answer from this machine; every other one is a remote service.
LOCAL_PROVIDERS = {"ollama"}


def _no_network(*_args, **_kwargs):
    raise RuntimeError("a cache-only run must never call the model")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Score discovered jobs.")
    p.add_argument("--intelligence", type=Path, default=INTELLIGENCE_PATH)
    p.add_argument("--jobs", type=Path, default=JOBS_PATH)
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
    p.add_argument("--judge-provider", default=None, help="HOLOJOB_LLM_PROVIDER when unset")
    p.add_argument("--judge-model", default=None, help="<PROVIDER>_JUDGE_MODEL when unset")
    p.add_argument("--workers", type=int, default=8, help="parallel judge calls")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.judge and args.judge_preview:
        print("--judge and --judge-preview are exclusive", file=sys.stderr)
        return 2
    if not args.intelligence.exists():
        print(f"Missing intelligence: {args.intelligence}", file=sys.stderr)
        return 1
    if not args.jobs.exists():
        print(f"Missing jobs: {args.jobs}", file=sys.stderr)
        return 1

    intelligence = json.loads(args.intelligence.read_text(encoding="utf-8"))
    discovered = json.loads(args.jobs.read_text(encoding="utf-8"))
    jobs = discovered.get("jobs") if isinstance(discovered, dict) else discovered
    if not isinstance(jobs, list):
        print("Invalid discovered jobs format", file=sys.stderr)
        return 1

    provider = args.judge_provider or active_provider()
    model = args.judge_model or judge_model(provider)
    if args.judge:
        enhancer = LlmFitEnhancer(
            provider, model, threshold=args.judge_threshold, cache_path=FIT_CACHE_PATH
        )
        print(
            f"judge: provider={provider} model={model or '(provider default)'} "
            f"threshold={args.judge_threshold}",
            flush=True,
        )
    else:
        # Local scoring: judgements already in the cache are re-applied, so a
        # re-score does not throw them away. Nothing is sent: the model call is
        # replaced with one that raises.
        enhancer = LlmFitEnhancer(
            provider, model, threshold=args.judge_threshold, cache_path=FIT_CACHE_PATH,
            complete=_no_network, cache_only=True,
        )

    scored = score_jobs(jobs, intelligence, enhancer, workers=args.workers)
    c = enhancer.counts
    if args.judge_preview:
        eligible = c["cached"] + c["uncached"]
        print(json.dumps({
            "provider": provider,
            "model": model,
            "leavesServer": provider not in LOCAL_PROVIDERS,
            "threshold": args.judge_threshold,
            "eligible": eligible,
            "cached": c["cached"],
            "toSend": c["uncached"],
            "sent": DIGEST_FIELDS,
            "neverSent": NEVER_SENT,
        }))
        return 0
    if args.judge:
        enhancer.save()
        print(
            f"judge: {c['judged']} judged, {c['cached']} cached, "
            f"{c['skipped']} below threshold, {c['failed']} failed"
        )
    elif c["cached"]:
        print(f"judge: re-applied {c['cached']} cached judgements (no calls made)")
    if args.min_score > 0:
        scored = [j for j in scored if j.get("matchScore", 0) >= args.min_score]

    labels = Counter(j.get("matchLabel") for j in scored)
    weights = resolve_weights(intelligence.get("scoringWeights"))

    payload = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sourceRunId": uuid.uuid4().hex[:12],
            "scoringVersion": "1.0",
            "intelligenceGeneratedAt": (intelligence.get("meta") or {}).get("generatedAt"),
            "discoveryGeneratedAt": (discovered.get("meta") or {}).get("generatedAt") if isinstance(discovered, dict) else None,
            "weights": weights,
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
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Scored {len(scored)} jobs -> {args.output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
