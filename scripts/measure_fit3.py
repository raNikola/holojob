#!/usr/bin/env python3
"""W5 Fit 3 (shadow), the classification read: the model classifies each ad into the CLOSED role and competency lists, ONE pass, into a scratch file.

THIS SCRIPT CALLS A MODEL PROVIDER (and bills it) ONLY WITH --confirm. Without it, it prints the estimate and the hard cap and stops.

    .venv/bin/python scripts/measure_fit3.py --max-usd 0.50              # estimate only
    .venv/bin/python scripts/measure_fit3.py --max-usd 0.50 --confirm    # the run

Sends the ad (title, description) and the two closed lists (match_engine/fit3_roles.json, src/data/competencies/product.json). NO candidate data.
--ids FILE      the ads to classify (default the holdout-v1 id file). Their text is read from the real data dir, read only.
--scratch DIR   default /home/ranikola/holojob-eval/holdout-scratch-data. Refused if it is, or sits inside, the real data dir. The AI ledger and settings are its copies.
--out-name NAME the file name under <scratch>/fit3/ (default classification.json). A second pass for the stability bars is a run with another name,
                e.g. --out-name classification-pass2.json; an existing file is never overwritten.
--max-usd X     required; the run is refused when the worst case is above X, and a spend guard enforces X per call.

Writes only <scratch>/fit3/<out-name> (directory 700, file 600): {"version": 1, "entries": {<classification key>: {"reply": <raw model reply>, "answers": null}}}.
The reply holds ad quotes only; the console gets counts and cost. Code anchors the reply on every read (match_engine/fit3.anchor).
Next: scripts/measure_holdout_matcher.py --fit3 (the matcher over the marked competencies, layer b), then the stored file can be copied to data/cache/fit3.json by the owner.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_common as mc  # noqa: E402
import measure_extraction_variance as mv  # noqa: E402
from measure_holdout_extract7 import check_scratch  # noqa: E402

DEFAULT_IDS = mc.EVAL_DIR / "holdout-ids-18.json"
DEFAULT_SCRATCH = mc.EVAL_DIR / "holdout-scratch-data"
OUT_DIR = "fit3"
OUT_NAME = "classification.json"
FEATURE = "fit3-classify"
UPPER_CHARS_PER_TOKEN = 3.0


def fit3_prompt_version() -> int:
    from match_engine import fit3
    return fit3.PROMPT_VERSION


def fit3_layout_version() -> int:
    from match_engine import fit3
    return fit3.LAYOUT_VERSION


def posting_of(job: dict) -> dict:
    return {"id": job.get("jobId") or "", "title": job.get("title") or "", "company": job.get("company") or "",
            "description": job.get("description") or ""}


def estimate(jobs: list[dict], provider, model) -> dict:
    """Prompt-size and price estimate for one pass; calls nothing."""
    import ai_gate
    import ai_selection
    from llm_client import LlmUnavailable, reasoning_options, service_tier_for
    from match_engine import fit3

    selection = ai_selection.read()["selection"] or {}
    name, resolved = provider or selection.get("provider"), model or selection.get("model")
    if not name or not resolved:
        raise LlmUnavailable("no provider and model selected in Settings, and none given")
    price = ai_gate.classify(name, resolved, selection.get("baseUrl") or None, tier=service_tier_for(name))
    if not price.get("priceKnown"):
        return {"priceKnown": False, "provider": name, "model": resolved}
    roles, comps = fit3.load_roles(), fit3.closed_competencies()
    chars = [len(fit3.build_prompt(posting_of(j), roles, comps)) for j in jobs]
    max_out = int(reasoning_options(resolved).get("max_completion_tokens") or selection.get("maxTokens") or ai_selection.DEFAULTS["maxTokens"])
    in_typical, in_worst = sum(chars) / 4, sum(chars) / UPPER_CHARS_PER_TOKEN
    return {"priceKnown": True, "provider": name, "model": resolved, "ads": len(jobs), "calls": len(jobs), "inputTokensTypical": int(in_typical),
            "maxOutputTokensPerCall": max_out, "inputOnlyUsd": round(in_typical * price["inputPerMTok"] / 1e6, 4),
            "worstCaseUsd": round((in_worst * price["inputPerMTok"] + len(jobs) * max_out * price["outputPerMTok"]) / 1e6, 4)}


def run(jobs: list[dict], provider, model, guard, workers: int) -> tuple[dict, dict]:
    from collections import Counter
    from llm_client import GuardrailRefused, LlmRefused, LlmUnavailable, complete_json
    from match_engine import fit3

    roles, comps = fit3.load_roles(), fit3.closed_competencies()
    failures: Counter = Counter()
    seen: set = set()

    def gated(prompt, schema=None, model=None, provider=None):
        worst = guard.reserve(prompt)
        try:
            return complete_json(prompt, schema=schema, model=model, provider=provider)
        finally:
            guard.release(worst)

    def one(job):
        posting = posting_of(job)
        try:
            reply = fit3.classify(posting, confirmed=True, provider=provider, model=model, complete=gated, roles=roles, comps=comps)
        except GuardrailRefused as exc:
            return None, f"refused:{type(exc).__name__}"
        except (LlmUnavailable, LlmRefused, fit3.Fit3Error) as exc:
            # Class name for the counter; the first 160 characters of the message go to stderr once per distinct text (the payload is a public ad
            # and the closed lists, no candidate data), so config, schema, privacy and provider failures can be told apart.
            note = f"{type(exc).__name__}: {str(exc)[:160]}"
            if note not in seen:
                seen.add(note)
                print(f"  first failure of this kind, ad {posting['id']}: {note}", file=sys.stderr)
            return None, f"failed:{type(exc).__name__}"
        return (fit3.classification_key(posting, roles, comps), {"reply": reply, "answers": None}), None

    entries = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for item, failure in pool.map(one, jobs):
            if item:
                entries[item[0]] = item[1]
            else:
                failures[failure] += 1
    return entries, dict(failures)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ids", type=Path, default=DEFAULT_IDS)
    p.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH)
    p.add_argument("--out-name", default=OUT_NAME)
    p.add_argument("--max-usd", type=float, required=True)
    p.add_argument("--provider", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--data-dir", type=Path, default=None, help="the real data dir (read only); default as the other measure scripts")
    p.add_argument("--confirm", action="store_true", help="REQUIRED to call the provider")
    p.add_argument("--candidate", type=Path, default=None, help="a Fit 3 candidate directory (prompt, prompt version, competency wording); default the repo prompt")
    args = p.parse_args(argv)
    if args.candidate:
        from match_engine import fit3 as _fit3
        _fit3.use_candidate(args.candidate)
    if args.max_usd <= 0:
        print("--max-usd must be positive", file=sys.stderr)
        return 2
    if Path(args.out_name).name != args.out_name or not args.out_name.endswith(".json"):
        print("--out-name must be a plain *.json file name", file=sys.stderr)
        return 2
    out_path = args.scratch / OUT_DIR / args.out_name
    if out_path.exists():
        print(f"{out_path} exists: refusing to overwrite a stored pass", file=sys.stderr)
        return 2
    data_dir = Path(args.data_dir or mc.default_data_dir())
    check_scratch(args.scratch, data_dir)
    for var, sub in (("HOLOJOB_CONFIG_DIR", "config"), ("HOLOJOB_AI_DIR", "ai"), ("HOLOJOB_SECRETS_DIR", "secrets")):
        os.environ[var] = str(data_dir / sub)
    before = mc.data_fingerprint(data_dir)
    jobs, missing = mv.load_jobs(data_dir, mv.read_ids(args.ids))
    no_text = list(missing) + [j["jobId"] for j in jobs if not (j.get("description") or "").strip()]
    if no_text:
        print(f"refusing: ad text is unavailable for {len(no_text)} ids: {', '.join(no_text)}", file=sys.stderr)
        return 1
    from llm_client import LlmUnavailable
    try:
        est = estimate(jobs, args.provider, args.model)
    except LlmUnavailable as exc:
        print(f"cannot price the run, so nothing is called: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"estimate": est, "hardCapUsd": args.max_usd, "writes": str(out_path)}, indent=1))
    if not est.get("priceKnown"):
        print("the price of this provider/model is unknown to the budget gate: refusing.", file=sys.stderr)
        return 1
    if not args.confirm:
        print(f"\nNothing was called and nothing was written. Estimated worst case ${est['worstCaseUsd']:.4f} for {est['calls']} calls "
              f"(input-only floor ${est['inputOnlyUsd']:.4f}); hard cap --max-usd {args.max_usd}. Add --confirm to run it.")
        return 0
    if est["worstCaseUsd"] > args.max_usd:
        print(f"refusing: worst case ${est['worstCaseUsd']:.4f} is above --max-usd {args.max_usd}", file=sys.stderr)
        return 1

    os.environ["HOLOJOB_CONFIG_DIR"] = str(args.scratch / "config")
    os.environ["HOLOJOB_AI_DIR"] = str(args.scratch / "ai")
    import ai_gate
    import enrich_jobs
    from llm_client import LlmRefused

    class Guard(enrich_jobs.SpendGuard):
        """SpendGuard counts the `enrichment` feature; this run's calls are `fit3-classify`."""

        def spent(self) -> float:
            rows = ai_gate.read_ledger()
            started = {r.get("id") for r in rows if r.get("type") == "call" and r.get("feature") == FEATURE and r.get("decision") == "allowed"
                       and enrich_jobs.datetime.fromisoformat(r["ts"]) >= self.started_at}
            return sum(float(r.get("cost") or 0) for r in rows if r.get("type") == "result" and r.get("id") in started)

    os.environ[ai_gate.TRIGGER_ENV] = ai_gate.MANUAL
    try:
        base = enrich_jobs.make_guard(args.max_usd, args.provider, args.model)
    except (LlmUnavailable, LlmRefused) as exc:
        print(f"spend guard refused: {exc}", file=sys.stderr)
        return 1
    guard = Guard(base.cap, base.price, base.max_output)
    entries, failures = run(jobs, args.provider, args.model, guard, args.workers)
    mc.write_private(out_path, json.dumps({"version": 1, "promptVersion": fit3_prompt_version(), "layoutVersion": fit3_layout_version(), "entries": entries}, ensure_ascii=False))
    changed = mc.fingerprint_changes(before, mc.data_fingerprint(data_dir))
    print(f"classified {len(entries)} of {len(jobs)} ads; failures: {failures or 'none'}; spent ${guard.spent():.4f} of the ${args.max_usd:.2f} cap")
    print(f"real data dir changed by this run: {'NO' if not changed else changed}")
    return 0 if len(entries) == len(jobs) and not changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
