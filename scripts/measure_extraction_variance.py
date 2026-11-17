#!/usr/bin/env python3
"""Package B, item 4: extraction variance. Runs the extraction N times per ad and reports the per-field flip rate.

THIS SCRIPT CALLS A MODEL PROVIDER (and bills it) ONLY WITH --confirm. Without it, it prints the estimated cost and stops.
Package B delivered it written and dry-run tested; the owner runs it.

    # 1. estimate only (calls nothing, writes nothing):
    .venv/bin/python scripts/measure_extraction_variance.py --ids ids.json --runs 5 --max-usd 2.00
    # 2. the same command with --confirm calls the provider selected in Settings, through the AI budget gate:
    .venv/bin/python scripts/measure_extraction_variance.py --ids ids.json --runs 5 --max-usd 2.00 --confirm --out variance.json

--ids FILE         {"ids": [...]} or a list of jobIds, looked up in data/jobs/discovered_jobs.json (the view).
--runs N           extraction passes per ad (2 to 20).
--max-usd X        hard cap, enforced per call by enrich_jobs.SpendGuard (worst case, in-flight calls included). Required.
--previous-frames  none (default): every pass is a fresh read, which measures the model's own variance.
                   production: pass the ad's stored requirement frame like a real run does; frames bias requirement ids toward
                   stability, so a production-mode flip rate is a lower bound on the raw one. Recorded in the output.
--confirm          required to make any call. Also needs a provider selected in Settings and a price known to the gate.

It uses enrich_jobs.extract() only: nothing is written to the ledger, the job list, the requirement frames or the competency
cache. The result file (mode 600) holds counts, ids and field names; never evidence text or posting quotes. It also keeps, per ad and
pass, the requirement unit keys (a canonical competency id, or a short hash of the normalised quote) that
scripts/measure_requirement_stability.py reads.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_common as mc  # noqa: E402

# Fields compared. Enum and set fields only: evidence and quote text is never compared or printed.
SCALAR_FIELDS = ("workMode", "roleTrack", "seniority", "yearsRequired", "jobCountry", "visaSponsorship")
SET_FIELDS = ("remoteEligibility", "listingFlags")


def signature(facts: dict) -> dict:
    """The comparable, text-free shape of one extraction."""
    reqs = facts.get("requirements") or []
    out = {f: facts.get(f) for f in SCALAR_FIELDS}
    out.update({f: tuple(sorted(str(v) for v in (facts.get(f) or []))) for f in SET_FIELDS})
    out["requirementCount"] = len(reqs)
    out["mustCount"] = sum(1 for r in reqs if r.get("importance") == "must")
    out["kindImportanceMix"] = tuple(sorted(Counter((r.get("kind"), r.get("importance")) for r in reqs).items(), key=str))
    return out


UNIT_KEYS_VERSION = 1
_IMPORTANCE_RANK = {"must": 2, "preferred": 1, "nice": 0}


def normalize_quote(quote: str | None) -> str:
    """Lower-case, punctuation to spaces, whitespace collapsed: the same sentence read twice gives the same string."""
    return " ".join(re.sub(r"[^\w]+", " ", (quote or "").lower()).split())


def unit_keys(facts: dict) -> list[dict]:
    """One entry per requirement unit of one pass: {"key", "canonical", "kind", "importance"}. Holds no ad text.

    key = "c:<competency id>" when the requirement resolved to a canonical competency (requirement `provisional` false),
    else "q:<first 12 hex of sha256 of the normalised posting quote>". A unit seen twice in one pass is kept once at its
    highest importance (design note rule 1), so a split line cannot inflate the set. The hash keeps the quote's words out of
    the result file; two passes that quote the same sentence share a key.
    """
    best: dict[str, dict] = {}
    for r in facts.get("requirements") or []:
        canonical = bool(r.get("id")) and r.get("provisional") is False
        norm = normalize_quote(r.get("postingQuote"))
        if canonical:
            key = f"c:{r['id']}"
        elif norm:
            key = "q:" + hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]
        else:
            continue
        unit = {"key": key, "canonical": canonical, "kind": r.get("kind"), "importance": r.get("importance")}
        have = best.get(key)
        if have is None or _IMPORTANCE_RANK.get(unit["importance"], -1) > _IMPORTANCE_RANK.get(have["importance"], -1):
            best[key] = unit
    return [best[k] for k in sorted(best)]


def unit_keys_by_ad(runs_by_ad: dict) -> dict:
    """{jobId: [one unit list per successful pass]}, for the stability tool."""
    return {i: [unit_keys(f) for f in runs] for i, runs in runs_by_ad.items() if runs}


def responsibility_keys(facts: dict) -> list[dict]:
    """One entry per responsibility of one pass (prompt 7): {"key": "r:<12 hex of sha256 of the normalised quote>"}. A separate class
    from the requirement units: a responsibility is what the person will do, not what they must have. Holds no ad text."""
    keys = set()
    for r in facts.get("responsibilities") or []:
        norm = normalize_quote(r.get("postingQuote"))
        if norm:
            keys.add("r:" + hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12])
    return [{"key": k} for k in sorted(keys)]


def responsibility_keys_by_ad(runs_by_ad: dict) -> dict:
    return {i: [responsibility_keys(f) for f in runs] for i, runs in runs_by_ad.items() if runs}


def flip_report(runs_by_ad: dict) -> dict:
    """runs_by_ad: {jobId: [facts, ...]}. Ads with fewer than two successful passes are listed, not counted."""
    sigs = {i: [signature(f) for f in runs] for i, runs in runs_by_ad.items() if len(runs) >= 2}
    fields = list(SCALAR_FIELDS) + list(SET_FIELDS) + ["requirementCount", "mustCount", "kindImportanceMix"]
    per_field = {}
    for field in fields:
        flipped = [i for i, s in sigs.items() if len({x[field] for x in s}) > 1]
        pair_total = pair_diff = 0
        for s in sigs.values():
            for a, b in itertools.combinations(s, 2):
                pair_total += 1
                pair_diff += a[field] != b[field]
        per_field[field] = {
            "adsFlipped": len(flipped), "ads": len(sigs), "adFlipRate": round(len(flipped) / len(sigs), 3) if sigs else None,
            "pairDisagreementRate": round(pair_diff / pair_total, 3) if pair_total else None, "flippedIds": sorted(flipped),
        }
    return {"adsCompared": len(sigs), "adsWithTooFewPasses": sorted(i for i, r in runs_by_ad.items() if len(r) < 2), "fields": per_field}


# --- estimate -----------------------------------------------------------------------------------------------------

def estimate(jobs: list[dict], runs: int, provider, model, previous_for=None, mapper=None, responsibilities: bool = False) -> dict:
    """Prompt-size and price estimate. Imports are local so `--help` and the tests need no provider set-up. Calls nothing."""
    import ai_gate
    import enrich_jobs
    from llm_client import LlmUnavailable, reasoning_options, service_tier_for
    import ai_selection

    # The target comes from the stored selection (data/config/ai-settings.json), not from llm_client.call_target: that one
    # checks for the API key and records a refusal in the AI ledger when it is missing, and an estimate needs neither.
    selection = ai_selection.read()["selection"]
    name = provider or (selection or {}).get("provider")
    resolved_model = model or (selection or {}).get("model")
    base_url = (selection or {}).get("baseUrl") or None
    if not name or not resolved_model:
        raise LlmUnavailable("no provider and model selected in Settings, and none given")
    price = ai_gate.classify(name, resolved_model, base_url, tier=service_tier_for(name))
    if not price.get("priceKnown"):
        return {"priceKnown": False, "provider": name, "model": resolved_model}
    selection = selection or {}
    max_out = int(reasoning_options(resolved_model).get("max_completion_tokens") or selection.get("maxTokens") or ai_selection.DEFAULTS["maxTokens"])
    chars = [len(enrich_jobs.build_prompt(j, previous_for(j) if previous_for else None, mapper, responsibilities)) for j in jobs]
    in_typical = sum(chars) / 4 * runs  # characters / 4, as enrich_jobs --dry-run states it
    in_worst = sum(chars) / enrich_jobs.UPPER_CHARS_PER_TOKEN * runs
    calls = len(jobs) * runs
    per_m_in, per_m_out = price["inputPerMTok"], price["outputPerMTok"]
    return {
        "priceKnown": True, "provider": name, "model": resolved_model, "ads": len(jobs), "runsPerAd": runs, "calls": calls,
        "promptCharsTotalPerPass": sum(chars), "inputTokensTypical": int(in_typical), "maxOutputTokensPerCall": max_out,
        "inputOnlyUsd": round(in_typical * per_m_in / 1e6, 4),
        "worstCaseUsd": round((in_worst * per_m_in + calls * max_out * per_m_out) / 1e6, 4),
        "note": "inputOnlyUsd is a floor (answers cost extra); worstCaseUsd assumes every call returns the maximum output and is what --max-usd is checked against",
    }


def load_jobs(data_dir: Path, ids: list[str]) -> tuple[list[dict], list[str]]:
    doc = json.loads((data_dir / "jobs" / "discovered_jobs.json").read_text(encoding="utf-8"))
    rows = {j.get("jobId"): j for j in (doc.get("jobs") if isinstance(doc, dict) else doc) or []}
    wanted = [i for i in ids if i not in rows]
    if wanted:  # ads that have left the list are still in the history ledger; read it without touching it
        import job_history
        import kept_ads
        ledger = job_history.load(job_history.ledger_path(data_dir / "jobs" / "discovered_jobs.json"), read_only=True)
        for i in wanted:
            row = kept_ads.ledger_row(ledger, i)
            if row:
                rows[i] = row
    return [rows[i] for i in ids if i in rows], [i for i in ids if i not in rows]


def read_ids(path: Path) -> list[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = data.get("ids") if isinstance(data, dict) else data
    out, seen = [], set()
    for i in ids or []:
        if isinstance(i, str) and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def run_extractions(jobs, runs, provider, model, guard, workers, previous_for, mapper, responsibilities=False) -> tuple[dict, dict]:
    import enrich_jobs
    from llm_client import GuardrailRefused, LlmRefused, LlmUnavailable

    results = {j["jobId"]: [] for j in jobs}
    failures = Counter()

    def one(job):
        try:
            return job["jobId"], enrich_jobs.extract(job, model, provider, previous_for(job) if previous_for else None, mapper, guard,
                                                       **({"responsibilities": True} if responsibilities else {}))
        except GuardrailRefused:
            return job["jobId"], "refused"
        except (LlmUnavailable, LlmRefused):
            return job["jobId"], "failed"

    work = [job for job in jobs for _ in range(runs)]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for job_id, outcome in pool.map(one, work):
            if isinstance(outcome, dict):
                results[job_id].append(outcome)
            else:
                failures[outcome] += 1
    return results, dict(failures)


def render(report: dict, meta: dict) -> list[str]:
    out = ["## 4. Extraction variance", ""]
    out += [f"{meta['ads']} ads x {meta['runs']} passes, previous frames: **{meta['previousFrames']}**, provider/model {meta['provider']}/{meta['model']}. "
            f"{report['adsCompared']} ads had two or more successful passes. Failures: {meta.get('failures') or 'none'}.", "",
            "| field | ads flipped | ad flip rate | pair disagreement |", "|---|---:|---:|---:|"]
    for field, r in report["fields"].items():
        out.append(f"| {field} | {r['adsFlipped']} / {r['ads']} | {r['adFlipRate']} | {r['pairDisagreementRate']} |")
    return out + [""]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ids", type=Path, required=True)
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--max-usd", type=float, required=True)
    p.add_argument("--previous-frames", choices=("none", "production"), default="none")
    p.add_argument("--prompt", type=int, choices=(6, 7), default=6,
                   help="extraction prompt: 6 is the pipeline's; 7 also lists responsibilities (opt-in, never changes the pipeline)")
    p.add_argument("--provider", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--data-dir", type=Path, default=None)
    p.add_argument("--out", type=Path, default=None, help="write the flip report here (mode 600); only with --confirm")
    p.add_argument("--confirm", action="store_true", help="REQUIRED to call the provider; without it only the estimate is printed")
    args = p.parse_args(argv)

    if not 2 <= args.runs <= 20:
        print("--runs must be between 2 and 20", file=sys.stderr)
        return 2
    if args.max_usd <= 0:
        print("--max-usd must be positive", file=sys.stderr)
        return 2
    data_dir = args.data_dir or mc.default_data_dir()
    # Settings, the AI ledger and the key store of the owner's data directory, not of whichever checkout this runs from.
    for var, sub in (("HOLOJOB_CONFIG_DIR", "config"), ("HOLOJOB_AI_DIR", "ai"), ("HOLOJOB_SECRETS_DIR", "secrets")):
        os.environ.setdefault(var, str(data_dir / sub))
    ids = read_ids(args.ids)
    jobs, missing = load_jobs(data_dir, ids)
    if not jobs:
        print(f"none of the {len(ids)} ids is in the job list", file=sys.stderr)
        return 2

    import competency_mapping
    import requirement_frames
    from llm_client import LlmUnavailable

    intelligence = data_dir / "intelligence" / "candidate-intelligence.json"
    family = (json.loads(intelligence.read_text(encoding="utf-8")).get("roleFamily") or None) if intelligence.exists() else None
    mapper = competency_mapping.load_mapper(family)  # read-only here: mapper.save() is never called
    previous_for = None
    if args.previous_frames == "production":
        frames = requirement_frames.load(data_dir / "cache" / "requirement-frames.json")
        remap = mapper.remap if mapper else competency_mapping.load_remap(data_dir / "requirement-remap.json")
        previous_for = lambda job: requirement_frames.previous_for(frames, job, remap)  # noqa: E731

    try:
        est = estimate(jobs, args.runs, args.provider, args.model, previous_for, mapper, args.prompt == 7)
    except LlmUnavailable as exc:
        print(f"cannot price the run, so nothing is called: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"estimate": est, "idsGiven": len(ids), "idsNotInJobList": len(missing), "previousFrames": args.previous_frames,
                      "maxUsd": args.max_usd}, indent=1))
    if not est.get("priceKnown"):
        print("the price of this provider/model is unknown to the budget gate, so the cost cannot be bounded: refusing.", file=sys.stderr)
        return 1
    if not args.confirm:
        print(f"\nNothing was called. Estimated worst case ${est['worstCaseUsd']:.2f} for {est['calls']} calls (cap --max-usd {args.max_usd}). "
              "Add --confirm to run it.")
        return 0
    if est["worstCaseUsd"] > args.max_usd:
        print(f"worst case ${est['worstCaseUsd']:.2f} is above --max-usd {args.max_usd}: the spend guard may stop the run part-way "
              "(finished calls are kept). Continuing, because the guard bounds the spend per call.", file=sys.stderr)

    import ai_gate
    import enrich_jobs
    from llm_client import LlmRefused

    os.environ[ai_gate.TRIGGER_ENV] = ai_gate.MANUAL
    try:
        guard = enrich_jobs.make_guard(args.max_usd, args.provider, args.model)
    except (LlmUnavailable, LlmRefused) as exc:
        print(f"spend guard refused: {exc}", file=sys.stderr)
        return 1
    results, failures = run_extractions(jobs, args.runs, args.provider, args.model, guard, args.workers, previous_for, mapper, args.prompt == 7)
    report = flip_report(results)
    meta = {"ads": len(jobs), "runs": args.runs, "previousFrames": args.previous_frames, "provider": est["provider"], "model": est["model"],
            "failures": failures, "spentUsd": round(guard.spent(), 4), "maxUsd": args.max_usd}
    print("\n".join(render(report, meta)))
    print(f"spent ${meta['spentUsd']:.4f} of the ${args.max_usd:.2f} cap")
    if args.out:
        mc.write_private(args.out, json.dumps({"meta": meta, "report": report, "unitKeysVersion": UNIT_KEYS_VERSION,
                                              "unitKeys": unit_keys_by_ad(results),
                                              **({"responsibilityKeys": responsibility_keys_by_ad(results)} if args.prompt == 7 else {})}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
