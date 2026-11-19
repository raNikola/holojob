#!/usr/bin/env python3
"""Experiment B (AI fit rating), owner-run. Pre-registered in ~/holojob-eval/exp-b-plan.md; read its sha256 first. EVALUATION ONLY: this writes nothing
under data/ and changes no score. Prints counts, ad ids and numbers; never ad text, summary text, names or labels with their ads' text.

    .venv/bin/python scripts/measure_fit_b.py summary  --scope public_cv --out DIR [--public-cv FILE]
    .venv/bin/python scripts/measure_fit_b.py estimate --scope public_cv --ids FILE --out DIR
    .venv/bin/python scripts/measure_fit_b.py run      --scope public_cv --ids FILE --out DIR --label dev-run1 --max-usd N --confirm    # PAID
    .venv/bin/python scripts/measure_fit_b.py labels   --ids FILE --out FILE [--v2-sheet FILE]
    .venv/bin/python scripts/measure_fit_b.py evaluate --ratings FILE --baseline FILE --labels FILE --delta X [--gpt-csv FILE]

--out DIR is refused when it is, or sits inside, the real data dir. A paid run needs --confirm AND --max-usd; every call, a retry included, is counted at its
worst case against the cap before it is made; the AI gate (feature fit-b-experiment, real ledger) still enforces the owner's daily and monthly limits.
Nothing here is called by a pipeline run, and the code makes no provider call without --confirm.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("cv_analysis", "llm", "job_scoring"):
    sys.path.insert(0, str(ROOT / "python" / sub))
sys.path.append(str(ROOT / "python"))

REAL_DATA = Path("/srv/holojob/data")
PROFILE = REAL_DATA / "profile" / "candidate-profile.json"
INTELLIGENCE = REAL_DATA / "intelligence" / "candidate-intelligence.json"
SCORED = REAL_DATA / "jobs" / "scored_jobs.json"
EVAL_SET = REAL_DATA / "calibration" / "stage-a" / "eval-set.json"
APPLICATIONS = REAL_DATA / "applications" / "applications.json"
EVAL_DIR = Path.home() / "holojob-eval"


def refuse_real(path: Path) -> Path:
    resolved = path.resolve()
    for real in (REAL_DATA, ROOT / "data"):
        if resolved == real.resolve() or real.resolve() in resolved.parents:
            raise SystemExit(f"refused: {path} is inside a real data dir")
    return resolved


def load_inputs():
    from redact import identity_of
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    intelligence = json.loads(INTELLIGENCE.read_text(encoding="utf-8"))
    return profile, intelligence, identity_of(profile)


def load_ads(ids: list[str]) -> dict[str, dict]:
    """Ad rows by id: the scored file first, then the job history ledger (read-only) for ads no longer in the view."""
    rows = {r["jobId"]: r for r in json.loads(SCORED.read_text(encoding="utf-8"))["jobs"] if r.get("jobId") in set(ids)}
    missing = [i for i in ids if i not in rows]
    if missing:
        import job_history
        ledger = job_history.load(job_history.ledger_path(REAL_DATA / "jobs" / "discovered_jobs.json"), read_only=True).get("jobs") or {}
        for i in missing:
            entry = ledger.get(i)
            if isinstance(entry, dict) and isinstance(entry.get("job"), dict):
                rows[i] = {**entry["job"], "jobId": i}
    return rows


def read_ids(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("ids") if isinstance(data, dict) else data)


def summary_for(scope: str):
    from calibration import fit_b
    profile, intelligence, identity = load_inputs()
    import profile_enrichment
    return fit_b.build_summary(scope, profile, intelligence, identity, profile_enrichment.load()), profile


def cmd_summary(args) -> int:
    from calibration import fit_b
    out = refuse_real(args.out)
    summary, _ = summary_for(args.scope)
    path = out / f"summary-{args.scope}-v{fit_b.SUMMARY_VERSION}-{summary['sha256'][:12]}.json"
    fit_b.write_private_json(path, summary)
    print(json.dumps({"file": str(path), "scope": args.scope, "sha256": summary["sha256"], "counts": summary["counts"]}))
    if args.public_cv:
        print("public CV coverage:", json.dumps(fit_b.public_cv_coverage(summary["text"], Path(args.public_cv).read_text(encoding="utf-8"))))
    return 0


def build_requests(args):
    """(summary, profile, {id: prompt}, truncated count, missing ids, leaks): every request built and scanned; nothing is sent."""
    from calibration import fit_b
    from calibration.prelabel import owner_leaks
    from redact import identity_of
    summary, profile = summary_for(args.scope)
    identity = identity_of(profile)
    ids = read_ids(args.ids)
    ads = load_ads(ids)
    prompts, truncated, leaks = {}, 0, []
    for i in ids:
        if i not in ads or not (ads[i].get("description") or "").strip():
            continue
        prompts[i] = fit_b.build_prompt(summary, ads[i], identity)
        truncated += fit_b.ad_text(ads[i])[2]
        if owner_leaks(prompts[i], profile):
            leaks.append(i)
    return summary, profile, prompts, truncated, [i for i in ids if i not in prompts], leaks


def price_of(prompts: dict):
    import ai_gate
    from ai_selection import require
    from llm_client import reasoning_options, service_tier_for
    selection = require()
    provider, model = selection["provider"], selection["model"]
    price = ai_gate.classify(provider, model, selection.get("baseUrl") or None, tier=service_tier_for(provider))
    out_tokens = (reasoning_options(model).get("max_completion_tokens") if provider == "openai" else None) or 1200
    from calibration.engine_sample import tokens_of
    cost = None
    if price.get("priceKnown") and prompts:
        cost = round(sum(tokens_of(len(p)) * price["inputPerMTok"] / 1e6 + out_tokens * price["outputPerMTok"] / 1e6 for p in prompts.values()), 4)
    return selection, price, out_tokens, cost


def cmd_estimate(args) -> int:
    refuse_real(args.out)
    summary, _, prompts, truncated, missing, leaks = build_requests(args)
    selection, price, out_tokens, cost = price_of(prompts)
    import ai_gate
    totals = ai_gate.totals(None, ai_gate.load_settings())
    print(json.dumps({"ads": len(prompts), "withoutText": missing, "truncated": truncated, "privacyScanHits": leaks,
                      "model": f"{selection['provider']}/{selection['model']}", "worstCaseOutputTokensPerCall": out_tokens,
                      "estimatedUpperBoundUsd": cost, "spentToday": totals["today"]["cost"], "spentThisMonth": totals["thisMonth"]["cost"],
                      "summarySha256": summary["sha256"]}))
    print("nothing sent. The paid run needs --max-usd N --confirm.")
    return 0


def cmd_run(args) -> int:
    if not (args.confirm and args.max_usd):
        print("a paid run needs --confirm and --max-usd", file=sys.stderr)
        return 2
    import ai_gate
    from calibration import fit_b
    from calibration.engine_sample import tokens_of
    from calibration.prelabel import owner_leaks
    from llm_client import GuardrailRefused, complete_json, preflight
    out = refuse_real(args.out)
    summary, profile, prompts, truncated, missing, leaks = build_requests(args)
    for i in leaks:
        prompts.pop(i, None)
    selection, price, out_tokens, cost = price_of(prompts)
    if cost is None and prompts:
        print("stopped: no price for this model; nothing was sent")
        return 1
    if cost is not None and cost > args.max_usd:
        print(f"stopped: upper-bound estimate ${cost:.4f} is over --max-usd ${args.max_usd:.2f}; nothing was sent")
        return 1
    path = out / f"ratings-{args.label}.json"
    store = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"summarySha256": summary["sha256"], "promptVersion": fit_b.PROMPT_VERSION, "ratings": {}}
    if store.get("summarySha256") != summary["sha256"]:
        print("stopped: this ratings file was made from another summary; use a new --label")
        return 1
    todo = [i for i in prompts if i not in store["ratings"]]
    if not todo:
        print("nothing to ask")
        return 0
    os.environ[ai_gate.TRIGGER_ENV] = ai_gate.MANUAL
    with ai_gate.context(feature=fit_b.FEATURE):
        decision = preflight(max(len(prompts[i]) for i in todo), selection["provider"], selection["model"])
    if not decision.allowed:
        ai_gate.record_refused(decision, skipped=len(todo))
        print(f"stopped: AI gate refused: {decision.reason}")
        return 1
    spent, lock, stop = {"usd": 0.0, "calls": 0, "reason": None}, threading.Lock(), threading.Event()

    def guarded(prompt, schema=None, model=None, provider=None):
        if owner_leaks(prompt, profile):
            stop.set()
            raise GuardrailRefused("privacy scan hit on an outgoing request")
        worst = tokens_of(len(prompt)) * price["inputPerMTok"] / 1e6 + out_tokens * price["outputPerMTok"] / 1e6
        with lock:
            if spent["usd"] + worst > args.max_usd:
                stop.set()
                spent["reason"] = f"the next call could pass the ${args.max_usd:.2f} cap"
                raise GuardrailRefused(spent["reason"])
            spent["usd"] += worst
            spent["calls"] += 1
        return complete_json(prompt, schema=schema, model=model, provider=provider)

    def one(i: str) -> str:
        if stop.is_set():
            return "refused"
        try:
            with ai_gate.context(feature=fit_b.FEATURE, job_id=i):
                reply = guarded(prompts[i], schema=fit_b.SCHEMA, model=selection["model"], provider=selection["provider"])
        except GuardrailRefused:
            return "refused"
        except Exception:  # a failed call is counted, not retried here; nothing of the reply or the error text is printed
            return "failed"
        rating = fit_b.valid_rating(reply)
        if rating is None:
            return "invalid"
        with lock:
            store["ratings"][i] = {"output": rating, "model": selection["model"]}
            fit_b.write_private_json(path, store)
        return "ok"

    counts = {"ok": 0, "failed": 0, "invalid": 0, "refused": 0}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for r in pool.map(one, todo):
            counts[r] += 1
    print(json.dumps({"asked": len(todo), **counts, "modelCalls": spent["calls"], "worstCaseUsd": round(spent["usd"], 4), "stopped": spent["reason"], "file": str(path)}))
    return 1 if spent["reason"] else 0


def cmd_labels(args) -> int:
    """Gains per ad id. Dev: eval-set `overall` (0..3). Holdout-v2: the owner's filled sheet (apply/maybe/skip). Applied ads: gain 3 (max rule)."""
    from calibration import fit_b_metrics as m
    labels = {}
    es = json.loads(EVAL_SET.read_text(encoding="utf-8"))["ads"]
    ids = set(read_ids(args.ids))
    for i in ids & set(es):
        labels[i] = {"gain": float(es[i]["overall"]), "source": "dev-level"}
    if args.v2_sheet:
        for line in Path(args.v2_sheet).read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 8 and re.fullmatch(r"[0-9a-f]{16}", cells[1]) and cells[1] in ids and cells[5].lower() in m.VERDICT_GAIN:
                elig_only = cells[5].lower() == "skip" and cells[7].lower() == "barrier stated"
                labels[cells[1]] = {"gain": None if elig_only else m.VERDICT_GAIN[cells[5].lower()], "source": "v2-verdict", "eligibilitySkip": elig_only}
    apps = json.loads(APPLICATIONS.read_text(encoding="utf-8"))["applications"]
    applied = {a["posting"].get("jobId") for a in apps.values() if a.get("posting", {}).get("jobId")}
    for i in ids & applied:
        base = labels.get(i, {}).get("gain")
        labels[i] = {**labels.get(i, {}), "gain": m.combined_gain(base, True), "applied": True}
    out = {"gains": {i: v["gain"] for i, v in labels.items()}, "sources": {i: v.get("source", "applied") for i, v in labels.items()}}
    path = refuse_real(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    os.chmod(path, 0o600)
    print(json.dumps({"ids": len(ids), "labelled": sum(1 for v in out["gains"].values() if v is not None), "excludedEligibilitySkips": sum(1 for v in labels.values() if v.get("eligibilitySkip")),
                      "applied": len(ids & applied), "file": str(path)}))
    return 0


def cmd_evaluate(args) -> int:
    from calibration import fit_b_metrics as m
    gains = {i: g for i, g in json.loads(Path(args.labels).read_text(encoding="utf-8"))["gains"].items() if g is not None}
    scores_b = {i: r["output"]["score"] for i, r in json.loads(Path(args.ratings).read_text(encoding="utf-8"))["ratings"].items()}
    scores_base = {i: float(s) for i, s in json.loads(Path(args.baseline).read_text(encoding="utf-8")).items()}
    ids = [i for i in gains if i in scores_b and i in scores_base]
    gains = {i: gains[i] for i in ids}
    result = m.verdict(scores_b, scores_base, gains, args.delta)
    secondary = {"ndcg20_B": m.ndcg_of(scores_b, gains, 20), "ndcg20_base": m.ndcg_of(scores_base, gains, 20),
                 "precision10_B": m.precision_at(scores_b, gains, 10), "precision10_base": m.precision_at(scores_base, gains, 10),
                 "tieShare_B": m.tie_share({i: scores_b[i] for i in ids}), "tieShare_base": m.tie_share({i: scores_base[i] for i in ids})}
    if args.gpt_csv and Path(args.gpt_csv).exists():
        gpt = {}
        for row in csv.DictReader(Path(args.gpt_csv).open(encoding="utf-8")):
            gpt[row.get("url") or row.get("URL") or ""] = row
        secondary["gptCsv"] = f"{len(gpt)} rows; Spearman needs the URL-to-id map (not built here)"
    else:
        secondary["gptSpearman"] = "skipped: file not available; no effect on the win rule"
    print(json.dumps({"n": result.pop("n"), **{k: v for k, v in result.items()}, "secondary": secondary}, default=str))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("summary", "estimate", "run"):
        p = sub.add_parser(name)
        p.add_argument("--scope", choices=("public_cv", "public_cv_plus_confirmed_C"), default="public_cv")
        p.add_argument("--out", type=Path, required=True)
        if name != "summary":
            p.add_argument("--ids", type=Path, required=True)
        else:
            p.add_argument("--public-cv", type=Path, default=None, help="the public CV text saved to a file, for the coverage check")
        if name == "run":
            p.add_argument("--label", required=True)
            p.add_argument("--max-usd", type=float, default=None)
            p.add_argument("--confirm", action="store_true")
            p.add_argument("--workers", type=int, default=4)
    p = sub.add_parser("labels")
    p.add_argument("--ids", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--v2-sheet", type=Path, default=None)
    p = sub.add_parser("evaluate")
    p.add_argument("--ratings", required=True)
    p.add_argument("--baseline", required=True)
    p.add_argument("--labels", required=True)
    p.add_argument("--delta", type=float, required=True)
    p.add_argument("--gpt-csv", default=None)
    args = ap.parse_args(argv)
    return {"summary": cmd_summary, "estimate": cmd_estimate, "run": cmd_run, "labels": cmd_labels, "evaluate": cmd_evaluate}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
