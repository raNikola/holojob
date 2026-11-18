#!/usr/bin/env python3
"""Holdout-v1 matcher run, INFORMATIONAL ONLY: the evidence matcher on the read holdout ads, inside the SCRATCH data dir.

THE PAID RUN CALLS A MODEL PROVIDER (and bills it) ONLY WITH --confirm. Without it, it prepares the inputs (free) and prints the
estimate and the hard cap, and stops.

    .venv/bin/python scripts/measure_holdout_matcher.py --max-usd 0.10              # estimate only
    .venv/bin/python scripts/measure_holdout_matcher.py --max-usd 0.10 --confirm    # the run

--ids FILE      default /home/ranikola/holojob-eval/holdout-ids-18.json (the 19 holdout-v1 ads that have been read).
--scratch DIR   default /home/ranikola/holojob-eval/holdout-scratch-data (made by measure_holdout_extract.py). Refused if it is, or
                sits inside, the real data dir. Facts are read from its ledger (job_history.json) and view; a copy of the real
                requirement remap is the only thing read from the real data dir.
--out DIR       default <scratch>/matcher: review-items.json, enrichment-facts.json, requirement-remap.json, engine-shadow.json.
--responsibilities  the matcher over the RESPONSIBILITIES (W4): each responsibility of <scratch>/extract7/facts.json (measure_holdout_extract7.py)
                is sent as one requirement row (kind experience, importance nice, its own quote), no prompt change. The default --out is then
                <scratch>/matcher-resp, never <scratch>/matcher: that folder is the step-2 input and is not overwritten. Rows map back to
                their r:<hash> unit key through postingQuote (match_engine.fit21.quote_key).
--fit3          the matcher over the Fit 3 competency rows (W5): each core / secondary competency anchored from <scratch>/fit3/classification.json
                (measure_fit3.py) is one requirement row (id = the competency id, text = its definition, its ad quote). Default --out <scratch>/matcher-fit3,
                never <scratch>/matcher. Layer (b) of Fit 3: a competency with no answer stays UNKNOWN.
--max-usd X     required; the runner's hard stop (engine_sample counts every call at its worst case).

It runs python/calibration/engine_sample.py (match_posting only: not the fit judge, no score, no label, no production cache) with
the profile, intelligence, confirmed facts, AI settings and AI ledger of the scratch dir, so nothing is written under the real data
dir, and the gate sees only the scratch copy of past spend (not the real ledger). The result is the verdict file in --out; it
changes no score and is not an input to any decision.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_common as mc  # noqa: E402

DEFAULT_IDS = mc.EVAL_DIR / "holdout-ids-18.json"
DEFAULT_SCRATCH = mc.EVAL_DIR / "holdout-scratch-data"


def facts_from_scratch(scratch: Path, ids: list[str]) -> tuple[list[dict], dict, dict]:
    """(ad rows without facts, {jobId: facts}, counts). The view wins over the ledger; no text is printed."""
    view = json.loads((scratch / "jobs" / "discovered_jobs.json").read_text(encoding="utf-8"))
    rows = {j.get("jobId"): j for j in (view.get("jobs") if isinstance(view, dict) else view) or []}
    import job_history
    ledger = job_history.load(job_history.ledger_path(scratch / "jobs" / "discovered_jobs.json"), read_only=True)
    entries = ledger.get("jobs") or {}
    items, facts = [], {}
    counts = {"ids": len(ids), "found": 0, "noFacts": 0, "noRequirements": 0, "prepared": 0}
    for i in ids:
        row = rows.get(i) or ((entries.get(i) or {}).get("job") if isinstance(entries.get(i), dict) else None)
        if not isinstance(row, dict):
            continue
        counts["found"] += 1
        llm = (rows.get(i) or {}).get("llmFacts") or (entries.get(i) or {}).get("llmFacts")
        if not llm:
            counts["noFacts"] += 1
        elif not llm.get("requirements"):
            counts["noRequirements"] += 1
        else:
            items.append({k: v for k, v in {**row, "jobId": i}.items() if k != "llmFacts"})
            facts[i] = llm
    counts["prepared"] = len(items)
    return items, facts, counts


def responsibility_requirements(responsibilities: list[dict]) -> list[dict]:
    """Each responsibility as a requirement row for the matcher: kind experience, importance nice, provisional id from its text."""
    from requirement_ids import provisional_id
    rows, seen = [], set()
    for r in responsibilities or []:
        text, quote = (r.get("text") or "").strip(), r.get("postingQuote")
        if not text or not quote or text in seen:
            continue
        seen.add(text)
        rows.append({"id": provisional_id(text), "text": text, "kind": "experience", "importance": "nice", "postingQuote": quote,
                     "qualifier": None, "provisional": True})
    return rows


def facts_from_extract7(scratch: Path, items: list[dict], facts: dict) -> tuple[list[dict], dict, dict]:
    """The scratch ads (their extract-6 facts keep the gate fields) with `requirements` replaced by the extract-7 responsibilities."""
    path = scratch / "extract7" / "facts.json"
    if not path.exists():
        raise SystemExit(f"no {path}: run scripts/measure_holdout_extract7.py --confirm first (the owner's paid read)")
    doc = json.loads(path.read_text(encoding="utf-8"))["facts"]
    out_items, out_facts, none = [], {}, 0
    for item in items:
        rows = responsibility_requirements((doc.get(item["jobId"]) or {}).get("responsibilities"))
        if not rows:
            none += 1
            continue
        out_items.append(item)
        out_facts[item["jobId"]] = {**facts[item["jobId"]], "requirements": rows}
    return out_items, out_facts, {"noResponsibilities": none, "responsibilityRows": sum(len(f["requirements"]) for f in out_facts.values())}


def facts_from_fit3(scratch: Path, items: list[dict], facts: dict) -> tuple[list[dict], dict, dict]:
    """The scratch ads with `requirements` replaced by the anchored Fit 3 competency rows (fit3.matcher_requirements)."""
    from match_engine import fit3
    path = scratch / "fit3" / "classification.json"
    if not path.exists():
        raise SystemExit(f"no {path}: run scripts/measure_fit3.py --confirm first (the owner's paid read)")
    entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
    roles, comps = fit3.load_roles(), fit3.closed_competencies()
    out_items, out_facts, none = [], {}, 0
    for item in items:
        posting = {"id": item["jobId"], "title": item.get("title") or "", "company": item.get("company") or "", "description": item.get("description") or ""}
        entry = entries.get(fit3.classification_key(posting, roles, comps))
        rows = fit3.matcher_requirements(fit3.anchor(entry["reply"], posting["description"], roles, comps), comps) if entry else []
        if not rows:
            none += 1
            continue
        out_items.append(item)
        out_facts[item["jobId"]] = {**facts[item["jobId"]], "requirements": rows}
    return out_items, out_facts, {"noFit3Rows": none, "fit3Rows": sum(len(f["requirements"]) for f in out_facts.values())}


def prepare(scratch: Path, out: Path, ids: list[str], real_data: Path, responsibilities: bool = False, fit3_rows: bool = False) -> dict:
    from calibration.enrich_sample import FACTS_NAME
    from competency_mapping import load_remap
    items, facts, counts = facts_from_scratch(scratch, ids)
    if responsibilities:
        items, facts, extra = facts_from_extract7(scratch, items, facts)
        counts = {**counts, **extra, "prepared": len(items)}
    if fit3_rows:
        items, facts, extra = facts_from_fit3(scratch, items, facts)
        counts = {**counts, **extra, "prepared": len(items)}
    mc.write_private(out / "review-items.json", json.dumps({"version": 1, "items": items}, ensure_ascii=False))
    mc.write_private(out / FACTS_NAME, json.dumps({"version": 1, "facts": facts}, ensure_ascii=False))
    remap = load_remap(real_data / "requirement-remap.json")
    mc.write_private(out / "requirement-remap.json", json.dumps(remap, ensure_ascii=False, sort_keys=True))
    return {**counts, "remapEntries": len(remap)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ids", type=Path, default=DEFAULT_IDS)
    p.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--max-usd", type=float, required=True)
    p.add_argument("--responsibilities", action="store_true", help="ask the matcher about the extract-7 responsibilities (default --out <scratch>/matcher-resp)")
    p.add_argument("--fit3", action="store_true", help="ask the matcher about the anchored Fit 3 competency rows (default --out <scratch>/matcher-fit3)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--data-dir", type=Path, default=None, help="the real data dir (only the remap and, for a run, the key store)")
    p.add_argument("--confirm", action="store_true", help="REQUIRED to call the provider")
    args = p.parse_args(argv)
    if args.max_usd <= 0:
        print("--max-usd must be positive", file=sys.stderr)
        return 2
    real = (args.data_dir or mc.default_data_dir()).resolve()
    scratch = args.scratch.resolve()
    if scratch == real or real in scratch.parents:
        print("the scratch dir is, or sits inside, the real data dir: refused", file=sys.stderr)
        return 2
    if args.fit3 and args.responsibilities:
        print("--fit3 and --responsibilities are separate runs", file=sys.stderr)
        return 2
    out = (args.out or scratch / ("matcher-fit3" if args.fit3 else "matcher-resp" if args.responsibilities else "matcher")).resolve()
    if (args.responsibilities or args.fit3) and out == (scratch / "matcher").resolve():
        print("--responsibilities / --fit3 must not write to <scratch>/matcher (the step-2 input): refused", file=sys.stderr)
        return 2
    if real in out.parents or out == real:
        print("--out is inside the real data dir: refused", file=sys.stderr)
        return 2
    for need in ("profile/candidate-profile.json", "intelligence/candidate-intelligence.json", "config/ai-settings.json", "jobs/discovered_jobs.json"):
        if not (scratch / need).exists():
            print(f"the scratch dir has no {need}; run scripts/measure_holdout_extract.py first", file=sys.stderr)
            return 2

    # Everything engine_sample reads comes from the scratch dir; only the key store (for a paid run) is the real one.
    os.environ["HOLOJOB_CONFIG_DIR"] = str(scratch / "config")
    os.environ["HOLOJOB_AI_DIR"] = str(scratch / "ai")
    os.environ.setdefault("HOLOJOB_SECRETS_DIR", str(real / "secrets"))
    from calibration import engine_sample as es
    import confirmed_facts
    es.PROFILE_PATH = scratch / "profile" / "candidate-profile.json"
    es.INTELLIGENCE_PATH = scratch / "intelligence" / "candidate-intelligence.json"
    es.load_confirmed_facts = lambda: confirmed_facts.load(scratch / "profile" / "confirmed-facts.json")

    ids = json.loads(args.ids.read_text(encoding="utf-8"))
    ids = ids.get("ids") if isinstance(ids, dict) else ids
    counts = prepare(scratch, out, list(dict.fromkeys(i for i in ids or [] if isinstance(i, str))), real, args.responsibilities, args.fit3)
    print(json.dumps({"prepared": counts, "out": str(out)}))
    profile = json.loads(es.PROFILE_PATH.read_text(encoding="utf-8"))
    intelligence = json.loads(es.INTELLIGENCE_PATH.read_text(encoding="utf-8"))
    plan = es.plan(out, profile, intelligence, False, args.max_usd)
    print("\n".join(es.describe(plan)))
    worst = None if plan["costUsd"] is None else round(plan["costUsd"] * 2, 4)
    if plan["leaks"]:
        print("privacy scan failed: nothing will be sent", file=sys.stderr)
        return 1
    if not args.confirm:
        print(f"\nNothing was called. Estimated ${plan['costUsd']} (worst case with one retry per call about ${worst}); cap --max-usd {args.max_usd}. "
              "Add --confirm to run it.")
        return 0
    if plan["costUsd"] is None:
        print("the price is unknown to the budget gate: refusing.", file=sys.stderr)
        return 1
    result = es.run(out, profile, intelligence, args.workers, cap=args.max_usd)
    print(json.dumps(result))
    return 1 if result.get("stopped") else 0


if __name__ == "__main__":
    raise SystemExit(main())
