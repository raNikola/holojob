#!/usr/bin/env python3
"""Role-mix validation, step 1: an extract-7 read (prompt 7: requirements AND responsibilities) of the read holdout ads, ONE pass, into a SEPARATE scratch file.

THIS SCRIPT CALLS A MODEL PROVIDER (and bills it) ONLY WITH --confirm. Without it, it prints the estimate and the hard cap and stops.

    .venv/bin/python scripts/measure_holdout_extract7.py --max-usd 0.15              # estimate only
    .venv/bin/python scripts/measure_holdout_extract7.py --max-usd 0.15 --confirm    # the run

--ids FILE      default /home/ranikola/holojob-eval/holdout-ids-18.json (the 19 holdout-v1 ads that have a description; Monzo has none).
--scratch DIR   default /home/ranikola/holojob-eval/holdout-scratch-data. Refused if it is, or sits inside, the real data dir.
--max-usd X     required; with --confirm the run is refused when the worst case is above X, and SpendGuard enforces X per call.

Differences from measure_holdout_extract.py (which cannot do this job): it has no prompt-7 switch, it skips every ad that already holds facts,
and it overwrites `llmFacts` in the scratch ledger, the extract-6 facts behind the stored matcher answers. THIS script ignores "already read",
never touches the scratch ledger or the view, and writes only <scratch>/extract7/facts.json (directory 700, file 600):
{"version": 1, "promptVersion": 7, "facts": {jobId: {"responsibilities": [{"text", "postingQuote"}], "responsibilitiesDropped": n, "requirements": n}}}.
The responsibility text stays in that scratch file; the console gets counts and cost only. The spend is recorded in the scratch copy of the AI ledger.
Next: scripts/measure_role_mix.py reads that file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_common as mc  # noqa: E402
import measure_extraction_variance as mv  # noqa: E402

DEFAULT_IDS = mc.EVAL_DIR / "holdout-ids-18.json"
DEFAULT_SCRATCH = mc.EVAL_DIR / "holdout-scratch-data"
OUT_NAME = "extract7/facts.json"


def check_scratch(scratch: Path, data_dir: Path) -> None:
    s, d = Path(scratch).resolve(), Path(data_dir).resolve()
    if s == d or d in s.parents or s in d.parents:
        raise SystemExit(f"refusing: scratch dir {s} is, contains or sits inside the real data dir {d}")


def facts_record(results: dict) -> dict:
    """{jobId: {responsibilities, responsibilitiesDropped, requirements}} from one pass per ad; an ad with no successful pass is left out."""
    out = {}
    for job_id, runs in results.items():
        if not runs:
            continue
        facts = runs[0]
        out[job_id] = {
            "responsibilities": [{"text": r.get("text"), "postingQuote": r.get("postingQuote")} for r in facts.get("responsibilities") or []],
            "responsibilitiesDropped": facts.get("responsibilitiesDropped", 0),
            "requirements": len(facts.get("requirements") or []),
        }
    return out


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
    for var, sub in (("HOLOJOB_CONFIG_DIR", "config"), ("HOLOJOB_AI_DIR", "ai"), ("HOLOJOB_SECRETS_DIR", "secrets")):
        os.environ[var] = str(data_dir / sub)
    before = mc.data_fingerprint(data_dir)

    ids = mv.read_ids(args.ids)
    jobs, missing = mv.load_jobs(data_dir, ids)
    no_text = list(missing) + [j["jobId"] for j in jobs if not (j.get("description") or "").strip()]
    if no_text:
        print(f"refusing: ad text is unavailable for {len(no_text)} ids: {', '.join(no_text)}", file=sys.stderr)
        return 1

    import competency_mapping
    from llm_client import LlmUnavailable
    intelligence = data_dir / "intelligence" / "candidate-intelligence.json"
    family = (json.loads(intelligence.read_text(encoding="utf-8")).get("roleFamily") or None) if intelligence.exists() else None
    mapper = competency_mapping.load_mapper(family)  # mapper.save() is never called
    try:
        est = mv.estimate(jobs, 1, args.provider, args.model, None, mapper, True)
    except LlmUnavailable as exc:
        print(f"cannot price the run, so nothing is called: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"estimate": est, "adsToRead": len(jobs), "hardCapUsd": args.max_usd,
                      "writes": str(args.scratch / OUT_NAME)}, indent=1))
    if not est.get("priceKnown"):
        print("the price of this provider/model is unknown to the budget gate, so the cost cannot be bounded: refusing.", file=sys.stderr)
        return 1
    if not args.confirm:
        print(f"\nNothing was called and nothing was written. Estimated worst case ${est['worstCaseUsd']:.4f} for {est['calls']} calls "
              f"(input-only floor ${est['inputOnlyUsd']:.4f}); hard cap --max-usd {args.max_usd}. Add --confirm to run it.")
        if est["worstCaseUsd"] > args.max_usd:
            print("NOTE: the worst case is above the cap, so --confirm would be refused at this --max-usd.")
        return 0
    if est["worstCaseUsd"] > args.max_usd:
        print(f"refusing: worst case ${est['worstCaseUsd']:.4f} is above --max-usd {args.max_usd}", file=sys.stderr)
        return 1

    # Confirmed: the gate's ledger and settings are the scratch copies; the key store stays the real one (read only).
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
    results, failures = mv.run_extractions(jobs, 1, args.provider, args.model, guard, args.workers, None, mapper, True)
    record = facts_record(results)
    mc.write_private(args.scratch / OUT_NAME, json.dumps({"version": 1, "promptVersion": 7, "facts": record}, ensure_ascii=False))
    changed = mc.fingerprint_changes(before, mc.data_fingerprint(data_dir))
    n_resp = sum(len(v["responsibilities"]) for v in record.values())
    print(f"read {len(record)} of {len(jobs)} ads; {n_resp} responsibilities kept, "
          f"{sum(v['responsibilitiesDropped'] for v in record.values())} dropped (quote not in the ad); failures: {failures or 'none'}; "
          f"spent ${guard.spent():.4f} of the ${args.max_usd:.2f} cap")
    print(f"real data dir changed by this run: {'NO' if not changed else changed}")
    print(f"next: .venv/bin/python scripts/measure_role_mix.py --scratch {args.scratch}")
    return 0 if len(record) == len(jobs) and not changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
