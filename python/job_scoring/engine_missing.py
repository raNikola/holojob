#!/usr/bin/env python3
"""Run the evidence engine for the open ads that have no current answer (the ones scored "ceiling not evaluated"). Owner-run, never part of a pipeline run.

    .venv/bin/python python/job_scoring/engine_missing.py                                  # estimate only: counts, tokens, USD; sends nothing
    .venv/bin/python python/job_scoring/engine_missing.py --max-usd 1.00 --confirm         # the paid run, hard-stopped at the cap

Which ads: the ShadowEngine's own plan (ad open, requirements extracted, no cached answer under the current profile / prompt / requirement set,
no confirmed cheap-gate fail), highest score first, at most --max-ads (default: all). The answers go to the production engine cache
(data/cache/engine.json); nothing is scored here: run Re-score afterwards and the ceiling reads them.

What is sent is exactly what a judged run sends for the matcher (see .claude/rules/privacy-inventory.md, "Evidence matcher"): the ad, its
requirements, the redacted evidence index. Every outgoing prompt is scanned for the owner's identifiers (fail closed); every call, a retry
included, is counted at its worst case against --max-usd before it is made, and the AI gate's daily and monthly limits still apply. A limit that
stops the run is a stop point: it prints what is left and ends. Prints counts and ids only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for sub in ("cv_analysis", "llm", "job_scoring"):
    sys.path.insert(0, str(ROOT / "python" / sub))
sys.path.append(str(ROOT / "python"))

import ai_gate  # noqa: E402
import pipeline_lock  # noqa: E402
import run_scoring  # noqa: E402
from ai_selection import require as require_selection  # noqa: E402
from calibration.engine_sample import OUTPUT_BASE, OUTPUT_PER_REQUIREMENT, tokens_of  # noqa: E402
from calibration.prelabel import owner_leaks  # noqa: E402
from job_fingerprint import job_fingerprint  # noqa: E402
from llm_client import GuardrailRefused, LlmUnavailable, complete_json, preflight, service_tier_for  # noqa: E402
from match_engine import matcher, shadow  # noqa: E402

JOBS_PATH = ROOT / "data" / "jobs" / "scored_jobs.json"


class Captured(LlmUnavailable):
    """Raised by the dry-run `complete` after it has kept the prompt: nothing is sent."""


def build(jobs_path: Path, max_ads: int | None, first_ids: set | None = None):
    """(engine, jobs, send ids): the production shadow engine in judge mode, over the scored rows, with the plan of what it would send."""
    os.environ[shadow.SHADOW_ENV] = "1"
    intelligence = json.loads(run_scoring.INTELLIGENCE_PATH.read_text(encoding="utf-8"))
    profile = run_scoring._load_profile()
    selection = require_selection()
    engine = run_scoring._shadow_engine(profile, intelligence, True, selection["provider"], selection["model"])
    if engine is None:
        raise SystemExit("no profile on disk: nothing to match against")
    engine.limit = max_ads
    engine.first = set(first_ids or ())
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"]
    jobs = jobs + ledger_rows(jobs_path, {str(j.get("jobId")) for j in jobs}, first_ids)
    return engine, jobs, engine.plan(jobs), profile, selection


def ledger_rows(jobs_path: Path, present: set, wanted: set | None) -> list[dict]:
    """The stored ad rows of `wanted` ids that the job list does not hold, read from the job ledger (read only), as measure_fit_b does.
    Their answers go to the engine cache under the ad fingerprint like any other; nothing is written to the job list."""
    missing = {str(i) for i in wanted or ()} - present
    if not missing:
        return []
    import job_history
    ledger = job_history.load(job_history.ledger_path(jobs_path.parent / "discovered_jobs.json"), read_only=True).get("jobs") or {}
    # The extraction facts sit on the entry, not on its job snapshot (kept_ads.ledger_row merges them the same way).
    return [{**entry["job"], "jobId": i, **({"llmFacts": entry["llmFacts"]} if entry.get("llmFacts") else {})} for i in sorted(missing)
            for entry in [ledger.get(i)] if isinstance(entry, dict) and isinstance(entry.get("job"), dict)]


def read_ids(path: Path) -> set:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(i) for i in (data.get("ids") if isinstance(data, dict) else data)}


def leaks_of(prompt: str, profile: dict, candidate: dict) -> list[str]:
    """What the owner-identifier scan finds in an outgoing prompt. An evidence id is a hash made here; a few hold a run of digits that reads as a
    phone number, so those ids (and only those) are masked for the scan. The ids stay as they are in the prompt and the cache."""
    masked = prompt
    for item in candidate["evidence"]:
        if owner_leaks(str(item["id"]), profile):
            masked = masked.replace(str(item["id"]), "ev")
    return owner_leaks(masked, profile)


def estimate(engine, jobs, send, profile, selection) -> dict:
    """Builds every prompt (nothing is sent), scans it, prices it at the upper bound the calibration runners use."""
    price = ai_gate.classify(selection["provider"], selection["model"], selection.get("baseUrl") or None, tier=service_tier_for(selection["provider"]))
    prompts, leaks = {}, []
    for job in jobs:
        key = job.get("jobId") or id(job)
        if key not in send:
            continue
        captured: list[str] = []

        def capture(prompt, schema=None, model=None, provider=None, _c=captured):
            _c.append(prompt)
            raise Captured("dry run")

        posting = engine._posting(job)
        matcher.match_posting(posting, engine.candidate, confirmed=True, provider=selection["provider"], model=selection["model"],
                              complete=capture, identity=engine.identity, select=engine.select, compact=engine.compact)
        if not captured:
            continue  # every requirement settled locally: nothing to ask
        prompts[key] = captured[0]
        if leaks_of(captured[0], profile, engine.candidate):
            leaks.append(key)
    cost = None
    if price.get("priceKnown") and prompts:
        cost = round(sum(tokens_of(len(p)) * price["inputPerMTok"] / 1e6 + (OUTPUT_BASE + OUTPUT_PER_REQUIREMENT * 40) * price["outputPerMTok"] / 1e6
                         for p in prompts.values()), 4)
    settings = ai_gate.load_settings()
    totals = ai_gate.totals(None, settings)
    return {"toAsk": len(prompts) - len(leaks), "maxChars": max((len(p) for p in prompts.values()), default=0), "planned": len(send), "send": set(send), "leaks": leaks, "price": price, "costUsd": cost,
            "excluded": dict(engine.excluded),
            "budget": {"dailyLimit": settings.get("dailyLimit"), "monthlyLimit": settings.get("monthlyLimit"),
                       "dailySpent": totals["today"]["cost"], "monthlySpent": totals["thisMonth"]["cost"]}}


def run(engine, jobs, est: dict, max_usd: float, profile: dict) -> dict:
    """The paid run. Worst-case accounting per call, stop at the cap; the AI gate still enforces the owner's daily and monthly limits."""
    price = est["price"]
    spent = {"usd": 0.0, "calls": 0, "reason": None}
    for key in matcher.MASKED_CONTACTS:
        matcher.MASKED_CONTACTS[key] = 0  # the estimate built the same prompts; count the run's own
    lock = threading.Lock()

    def guarded(prompt, schema=None, model=None, provider=None):
        if leaks_of(prompt, profile, engine.candidate):
            raise GuardrailRefused("privacy scan hit on an outgoing request")
        worst = tokens_of(len(prompt)) * price["inputPerMTok"] / 1e6 + (OUTPUT_BASE + OUTPUT_PER_REQUIREMENT * 40) * price["outputPerMTok"] / 1e6
        with lock:
            if spent["usd"] + worst > max_usd:
                spent["reason"] = f"the next call could pass the ${max_usd:.2f} cap"
                raise GuardrailRefused(spent["reason"])
            spent["usd"] += worst
            spent["calls"] += 1
        return complete_json(prompt, schema=schema, model=model, provider=provider)

    engine._complete = guarded
    os.environ[ai_gate.TRIGGER_ENV] = ai_gate.MANUAL
    with ai_gate.context(feature="evidence-matcher"):
        decision = preflight(est["maxChars"], engine.provider, engine.model)
    if not decision.allowed:
        ai_gate.record_refused(decision, skipped=est["toAsk"])
        return {"stopped": f"AI gate refused: {decision.reason}", "asked": 0}
    # Only the ads the estimate scanned: with a limit, apply() would plan again over the list minus the refused ads and reach ads nobody scanned.
    engine.limit = None
    engine.apply([j for j in jobs if (j.get("jobId") or id(j)) in est["send"] and (j.get("jobId") or id(j)) not in set(est["leaks"])])
    engine.save()  # whatever was paid for is kept, also after a stop
    stop = spent["reason"] or engine.refusal
    return {"stopped": stop, "newCalls": engine.counts["matched"], "failed": engine.counts["failed"], "refused": engine.counts["refused"],
            "modelCalls": spent["calls"], "worstCaseUsd": round(spent["usd"], 4), "contactsMasked": dict(matcher.MASKED_CONTACTS)}


def describe(est: dict, selection: dict, max_usd: float | None) -> list[str]:
    b, price = est["budget"], est["price"]
    lines = [f"ads without a current engine answer that a run would ask about: {est['toAsk']} (planned {est['planned']}; "
             f"excluded by a confirmed cheap gate: " + (", ".join(f"{g} {n}" for g, n in est["excluded"].items()) or "none") + ")",
             f"model: {selection['provider']}/{selection['model']}"]
    if est["costUsd"] is None:
        lines.append("estimated cost: unknown (no price for this model)" if est["toAsk"] else "estimated cost: $0 (nothing to ask)")
    else:
        lines.append(f"estimated cost (upper bound, no cache discount): ${est['costUsd']:.4f} at ${price['inputPerMTok']}/{price['outputPerMTok']} per 1M tokens")
    lines.append(f"budget: today {b['dailySpent']:.4f} of {b['dailyLimit']}; this month {b['monthlySpent']:.4f} of {b['monthlyLimit']}")
    lines.append("privacy scan: " + (f"{len(est['leaks'])} ads hit it and are NOT sent (ids: {', '.join(map(str, est['leaks']))}); the rest pass" if est["leaks"] else "all requests pass"))
    m = matcher.MASKED_CONTACTS
    lines.append(f"contact data masked in ad text before sending: {m['ads']} ads ({m['emails']} e-mail addresses, {m['phones']} phone numbers); the owner-identifier scan is unchanged")
    if max_usd is not None:
        lines.append(f"cap: ${max_usd:.2f}" + (" (the estimate is OVER it: the run would stop part-way)" if est["costUsd"] and est["costUsd"] > max_usd else ""))
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--jobs", type=Path, default=JOBS_PATH)
    ap.add_argument("--max-ads", type=int, default=None, help="ask about at most this many ads, highest score first (default: all)")
    ap.add_argument("--first-ids", type=Path, default=None, help="a JSON file of ad ids (a list, or {\"ids\": [...]}) planned before all other ads, then the rest by score; an id the job list does not hold is read from the job ledger")
    ap.add_argument("--max-usd", type=float, default=None, help="the run's hard stop in US dollars; required with --confirm")
    ap.add_argument("--confirm", action="store_true", help="make the paid calls")
    args = ap.parse_args(argv)
    if args.confirm and args.max_usd is None:
        print("--confirm needs --max-usd", file=sys.stderr)
        return 2
    lock = pipeline_lock.acquire()
    if lock is None:
        print(pipeline_lock.BUSY_MESSAGE, file=sys.stderr)
        return pipeline_lock.EXIT_LOCKED
    try:
        engine, jobs, send, profile, selection = build(args.jobs, args.max_ads, read_ids(args.first_ids) if args.first_ids else None)
        profile = profile
        est = estimate(engine, jobs, send, profile, selection)
        print("\n".join(describe(est, selection, args.max_usd)))
        if not args.confirm:
            print("nothing sent: add --max-usd N --confirm after the estimate is approved")
            return 0
        if est["costUsd"] is None and est["toAsk"]:
            print("stopped: no price for this model; nothing was sent")
            return 1
        if est["costUsd"] is not None and est["costUsd"] > args.max_usd:
            print(f"stopped: estimate ${est['costUsd']:.4f} is over the cap ${args.max_usd:.2f}; nothing was sent. Raise the cap or use --max-ads.")
            return 1
        if not est["toAsk"]:
            print("nothing to ask")
            return 0
        result = run(engine, jobs, est, args.max_usd, profile)
        print(json.dumps(result))
        print("answers are in the engine cache; run Re-score to apply the ceiling")
        return 1 if result.get("stopped") else 0
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
