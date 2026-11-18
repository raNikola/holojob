#!/usr/bin/env python3
"""W5 step 4: ONE signal, embedding similarity, against the role-class-only baseline. Experiment only: shadow, offline, no scoring change.
Pre-registered in ~/holojob-eval/w5-embedding-plan.md (read it before any `embed` run).

    .venv/bin/python scripts/measure_embedding_signal.py step0                       # counts only, no call
    .venv/bin/python scripts/measure_embedding_signal.py embed --estimate            # token count and price, no call
    .venv/bin/python scripts/measure_embedding_signal.py embed --confirm --max-usd 0.20
    .venv/bin/python scripts/measure_embedding_signal.py evaluate                    # offline: AUC, CI, verdict

Sends ONLY the cleaned public text (title, company, description: HTML-unescaped, markup stripped) of the LABELLED ads: the holdout-v1 ads the owner rated
and the applications. Never a profile, label, rating, application field or note. Vectors are stored in the scratch dir (mode 600), never committed.
Console output: counts, ad ids and public company names; never an owner label next to an ad id.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_fit3_bars as bars  # noqa: E402
import measure_common as mc  # noqa: E402
import measure_fit3 as m3  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EVAL = Path(mc.EVAL_DIR)
RATINGS = EVAL / "holdout-ratings-v1-2026-11-17.md"
APPLICATIONS = mc.default_data_dir() / "applications" / "applications.json"  # read only
CANDIDATE = ROOT / "python" / "match_engine" / "fit3_candidates" / "i1"
STORE_PASS = "i1-store-p1.json"
OUT_NAME = "embeddings"

# The owner's FIT-skip grouping (plan w5-plan.md Addendum A3), by ad id: the seven skips whose driver is the fit, not the eligibility.
FIT_SKIPS = set(bars.A3_ROLE_SKIPS) | set(bars.A3_INDUSTRIAL_SKIPS)


# --- cleaning ----------------------------------------------------------------------------------------------------------------------------------

def clean_text(text: str) -> str:
    """HTML-unescaped, markup stripped, whitespace collapsed. Public ad text only."""
    text = html.unescape(text or "")
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</(p|li|div|h\d|tr)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)  # a second pass: double-escaped entities
    return re.sub(r"[ \t\r\f\v ]+", " ", re.sub(r"\n\s*", "\n", text)).strip()


def normal_title(title: str) -> str:
    """Duplicate-group title key: case and diacritics folded, punctuation dropped, whitespace collapsed."""
    folded = unicodedata.normalize("NFKD", (title or "").casefold())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", "".join(c for c in folded if not unicodedata.combining(c))).split())


def normal_company(company: str) -> str:
    return normal_title(company)


def group_key(company: str, title: str) -> str:
    return f"{normal_company(company)}|{normal_title(title)}"


# --- the labelled set --------------------------------------------------------------------------------------------------------------------------

def read_ratings(path: Path = RATINGS) -> dict[str, dict]:
    """{ad id: {"verdict": apply|maybe|skip, "driver": "FIT, ELIG"}} from the owner's rating table (kept outside the repo)."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) > 6 and re.fullmatch(r"\d+", cells[1]) and re.fullmatch(r"[0-9a-f]{16}", cells[3]):
            out[cells[3]] = {"verdict": cells[2].lower(), "driver": cells[5]}
    return out


def read_applied(path: Path = APPLICATIONS) -> dict[str, dict]:
    """{ad id: public posting} of the applications the owner actually sent (an applied date on the attempt)."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for app in (doc.get("applications") or {}).values():
        if (app.get("attempt") or {}).get("appliedDate"):
            p = app.get("posting") or {}
            out[p.get("jobId") or app.get("id")] = {"id": p.get("jobId") or app.get("id"), "title": p.get("title") or "",
                                                     "company": p.get("company") or "", "description": p.get("description") or ""}
    return out


def label_of(rating: dict, ad_id: str) -> str:
    """apply | maybe | fit_skip | elig_skip. A skip is a FIT-skip only by the owner's grouping (FIT_SKIPS); every other skip is eligibility-driven."""
    if rating["verdict"] == "skip":
        return "fit_skip" if ad_id in FIT_SKIPS else "elig_skip"
    return rating["verdict"]


def labelled_ads(scratch: Path = m3.DEFAULT_SCRATCH) -> dict[str, dict]:
    """{id: {"id", "title", "company", "description" (cleaned), "label", "set"}} for the holdout-v1 ads the owner rated and that have text, plus the
    applications not already rated (set "applied"). Ad text comes from the scratch data copy / the application snapshot, never from a model."""
    ratings = read_ratings()
    ids = list(ratings)
    import measure_extraction_variance as mv
    rows, _missing = mv.load_jobs(scratch, ids)
    out = {}
    for r in rows:
        p = m3.posting_of(r)
        if (p["description"] or "").strip():
            out[p["id"]] = {**p, "rawDescription": p["description"], "description": clean_text(p["description"]), "label": label_of(ratings[p["id"]], p["id"]), "set": "holdout"}
    for i, p in read_applied().items():
        if i in out:
            out[i]["alsoApplied"] = True
        elif (p["description"] or "").strip():
            out[i] = {**p, "description": clean_text(p["description"]), "label": "applied", "set": "applied"}
    return out


def groups_of(ads: dict[str, dict]) -> dict[str, list[str]]:
    """Duplicate groups: the same company and normalised title; an ad with no twin is its own group. Leave-one-group-out folds are these."""
    out: dict[str, list[str]] = {}
    for i, a in sorted(ads.items()):
        out.setdefault(group_key(a["company"], a["title"]), []).append(i)
    return out


def company_groups(ads: dict[str, dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for i, a in sorted(ads.items()):
        out.setdefault(normal_company(a["company"]), []).append(i)
    return out


def role_classes(scratch: Path, ads: dict[str, dict]) -> dict[str, str]:
    """{id: target|adjacent|other} from the stored i1 pass 1 for the holdout ads that have an answer. The classification key hashes the raw text."""
    from match_engine import fit3
    fit3.use_candidate(CANDIDATE)
    holdout = {i: {"posting": {**m3.posting_of(a), "description": a["rawDescription"]}} for i, a in ads.items() if a["set"] == "holdout"}
    doc = json.loads((scratch / m3.OUT_DIR / STORE_PASS).read_text(encoding="utf-8"))
    return {i: bars.role_class(a) for i, a in bars.anchored_pass(doc, holdout).items()}


# --- evaluation (pure functions, numpy only) ---------------------------------------------------------------------------------------------------

CLASS_RANK = {"target": 2, "adjacent": 1, "other": 0}
BOOTSTRAP_B = 10000
BOOTSTRAP_SEED = 20261118


def _unit(vector):
    import numpy as np
    v = np.asarray(vector, dtype=float)
    return v / np.linalg.norm(v)


def crossfit_scores(vectors: dict[str, list], labels: dict[str, str], companies: dict[str, str]) -> dict[str, float | None]:
    """Leave-one-company-group-out: each ad's score = cos(x, mean of unit Apply vectors) - cos(x, mean of unit FIT-skip vectors), the means over the Apply and
    FIT-skip ads of OTHER companies. None when that training set has no Apply or no FIT-skip ad. Maybe, eligibility skips and Applied are never trained on."""
    import numpy as np
    unit = {i: _unit(v) for i, v in vectors.items()}
    out: dict[str, float | None] = {}
    for i, x in unit.items():
        pos = [unit[j] for j in unit if labels.get(j) == "apply" and companies[j] != companies[i]]
        neg = [unit[j] for j in unit if labels.get(j) == "fit_skip" and companies[j] != companies[i]]
        out[i] = None if not pos or not neg else float(x @ np.mean(pos, axis=0) - x @ np.mean(neg, axis=0))
    return out


def pair_value(a: str, b: str, classes: dict[str, str], scores: dict[str, float | None] | None) -> float:
    """1 / 0.5 / 0: is positive a ranked above negative b. Role class first; inside the same class the score if `scores` is given (a missing score = tie)."""
    ca, cb = CLASS_RANK.get(classes.get(a), -1), CLASS_RANK.get(classes.get(b), -1)
    if ca != cb:
        return 1.0 if ca > cb else 0.0
    if scores is None or scores.get(a) is None or scores.get(b) is None or scores[a] == scores[b]:
        return 0.5
    return 1.0 if scores[a] > scores[b] else 0.0


def auc(pos: list[str], neg: list[str], classes, scores) -> float | None:
    if not pos or not neg:
        return None
    return sum(pair_value(a, b, classes, scores) for a in pos for b in neg) / (len(pos) * len(neg))


def mean_percentile(pos: list[str], pool: list[str], classes, scores) -> float | None:
    """Mean over the positives of (pool ads ranked strictly lower + half the ties) / (pool size - 1); higher is better; the pool contains the positive."""
    if not pos or len(pool) < 2:
        return None
    values = [sum(pair_value(a, b, classes, scores) for b in pool if b != a) / (len(pool) - 1) for a in pos]
    return sum(values) / len(values)


def metrics(ids: list[str], labels, classes, scores) -> dict | None:
    """Baseline and tie-break AUC (Apply vs FIT-skip) and mean percentile over the list `ids` (repeats allowed: a bootstrap resample)."""
    pos = [i for i in ids if labels[i] == "apply"]
    neg = [i for i in ids if labels[i] == "fit_skip"]
    if not pos or not neg:
        return None
    pool = [i for i in ids if labels[i] in ("apply", "maybe", "fit_skip", "elig_skip")]
    base, tie = auc(pos, neg, classes, None), auc(pos, neg, classes, scores)
    return {"aucBaseline": base, "aucTieBreak": tie, "gain": tie - base,
            "percentileBaseline": mean_percentile(pos, pool, classes, None), "percentileTieBreak": mean_percentile(pos, pool, classes, scores)}


def _draw(rng, groups: dict[str, list[str]], marked: set[str]) -> list[str]:
    """Stratified grouped resample: marked groups and the others are each drawn with replacement, as many as there are of them."""
    strata = [[g for g in sorted(groups) if g in marked], [g for g in sorted(groups) if g not in marked]]
    ids: list[str] = []
    for stratum in strata:
        for _ in stratum:
            ids.extend(groups[rng.choice(stratum)])
    return ids


def bootstrap(groups: dict[str, list[str]], marked: set[str], stat, b: int = BOOTSTRAP_B, seed: int = BOOTSTRAP_SEED) -> dict:
    """`stat(ids)` -> dict of floats or None (a degenerate resample: it is discarded and redrawn, and counted). 95% percentile intervals per key."""
    import random
    rng = random.Random(seed)
    draws: dict[str, list[float]] = {}
    kept = discarded = 0
    while kept < b:
        result = stat(_draw(rng, groups, marked))
        if result is None:
            discarded += 1
            if discarded > 100 * b:
                raise RuntimeError("too many degenerate resamples")
            continue
        kept += 1
        for k, v in result.items():
            draws.setdefault(k, []).append(v)
    import numpy as np
    return {"B": b, "seed": seed, "discardedResamples": discarded,
            "ci95": {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] for k, v in draws.items()}}


def verdict_of(ci: list[float]) -> str:
    """The pre-registered rule on the CI of the AUC gain over role-only."""
    if ci[0] > 0:
        return "WIN"
    if ci[1] < 0:
        return "NO HELP"
    return "INCONCLUSIVE"


def evaluate(ads: dict[str, dict], classes: dict[str, str], vectors: dict[str, list]) -> dict:
    labels = {i: a["label"] for i, a in ads.items()}
    companies = {i: normal_company(a["company"]) for i, a in ads.items()}
    scores = crossfit_scores(vectors, labels, companies)
    rated = {i: a for i, a in ads.items() if a["set"] == "holdout"}
    groups: dict[str, list[str]] = {}
    for i in sorted(rated):
        groups.setdefault(companies[i], []).append(i)
    marked = {g for g, ids in groups.items() if any(labels[i] == "apply" for i in ids)}
    point = metrics(sorted(rated), labels, classes, scores)
    boot = bootstrap(groups, marked, lambda ids: metrics(ids, labels, classes, scores))
    # Applied: embedding only (no role class for them), versus the FIT-skip ads, separate positive set, no verdict
    sub = {i: a for i, a in ads.items() if a["label"] in ("applied", "fit_skip")}
    a_groups: dict[str, list[str]] = {}
    for i in sorted(sub):
        a_groups.setdefault(companies[i], []).append(i)
    a_marked = {g for g, ids in a_groups.items() if any(labels[i] == "applied" for i in ids)}

    def applied_auc(ids):
        pos, neg = [i for i in ids if labels[i] == "applied"], [i for i in ids if labels[i] == "fit_skip"]
        if not pos or not neg:
            return None
        return {"auc": sum(0.5 if scores[a] is None or scores[b] is None or scores[a] == scores[b] else float(scores[a] > scores[b]) for a in pos for b in neg) / (len(pos) * len(neg))}
    return {"counts": {k: sum(1 for i in rated if labels[i] == k) for k in ("apply", "maybe", "fit_skip", "elig_skip")} | {"applied": sum(1 for i in ads if labels[i] == "applied")},
            "unscoredAds": sum(1 for v in scores.values() if v is None), "point": point, "bootstrap": boot,
            "verdict": verdict_of(boot["ci95"]["gain"]),
            "applied": {"embeddingOnlyAucVsFitSkip": applied_auc(sorted(sub))["auc"], "bootstrap": bootstrap(a_groups, a_marked, applied_auc)}}


# --- embed -------------------------------------------------------------------------------------------------------------------------------------

def embed_text(ad: dict) -> str:
    """What is sent for one ad: its title and its cleaned description. No company, label, rating or application field."""
    return f"{ad['title'].strip()}\n{ad['description']}"


def run_embed(args) -> int:
    import os
    data_dir = Path(args.data_dir or mc.default_data_dir())
    from measure_holdout_extract7 import check_scratch
    check_scratch(args.scratch, data_dir)
    out_path = args.scratch / OUT_NAME / "vectors.json"
    if out_path.exists():
        print(f"{out_path} exists: refusing to overwrite stored vectors", file=sys.stderr)
        return 2
    ads = labelled_ads(args.scratch)
    ids = sorted(ads)
    texts = [embed_text(ads[i]) for i in ids]
    # The estimate and the call both use the scratch copies of the AI settings and ledger; only the key store is the real one (read only).
    os.environ["HOLOJOB_CONFIG_DIR"] = str(args.scratch / "config")
    os.environ["HOLOJOB_AI_DIR"] = str(args.scratch / "ai")
    os.environ["HOLOJOB_SECRETS_DIR"] = str(data_dir / "secrets")
    import llm_client
    _, cut = llm_client.embed_prepare(texts)
    decision = llm_client.embed_preflight(texts)
    row = decision.row
    print(json.dumps({"texts": len(texts), "characters": sum(len(t) for t in texts), "truncatedAboveCap": len(cut), "capChars": llm_client.EMBED_MAX_CHARS,
                      "model": llm_client.EMBEDDING_MODEL, "estimatedInputTokens": row.get("inputTokens"), "estimatedUsd": row.get("cost"),
                      "gateAllows": decision.allowed, "gateReason": decision.reason, "hardCapUsd": args.max_usd, "writes": str(out_path)}, indent=1))
    if args.estimate or not args.confirm:
        print("\nNothing was called and nothing was written." + ("" if args.estimate else " Add --confirm to run it."))
        return 0
    if not decision.allowed or (row.get("cost") or 0) > args.max_usd:
        print("refusing: the gate does not allow it, or the estimate is above --max-usd", file=sys.stderr)
        return 1
    import ai_gate
    os.environ[ai_gate.TRIGGER_ENV] = ai_gate.MANUAL
    before = mc.data_fingerprint(data_dir)
    result = llm_client.embed(texts, confirm=True, max_usd=args.max_usd)
    mc.write_private(out_path, json.dumps({"version": 1, "model": llm_client.EMBEDDING_MODEL, "capChars": llm_client.EMBED_MAX_CHARS,
                                           "truncated": [ids[i] for i in result["truncated"]], "inputTokens": result["inputTokens"],
                                           "vectors": dict(zip(ids, result["vectors"]))}))
    changed = mc.fingerprint_changes(before, mc.data_fingerprint(data_dir))
    print(f"embedded {len(result['vectors'])} ads; truncated {len(result['truncated'])}; input tokens {result['inputTokens']}; spent ${result['costUsd']:.6f} of the ${args.max_usd:.2f} cap")
    print(f"real data dir changed by this run: {'NO' if not changed else changed}")
    return 0 if not changed else 1


def run_evaluate(args) -> int:
    ads = labelled_ads(args.scratch)
    classes = role_classes(args.scratch, ads)
    doc = json.loads((args.scratch / OUT_NAME / "vectors.json").read_text(encoding="utf-8"))
    vectors = doc["vectors"]
    if set(vectors) != set(ads):
        print("the stored vectors do not match the labelled ads", file=sys.stderr)
        return 1
    print(json.dumps({"truncatedInputs": len(doc.get("truncated") or []), "inputTokens": doc.get("inputTokens"), **evaluate(ads, classes, vectors)}, indent=1))
    return 0

def step0(scratch: Path) -> dict:
    ratings = read_ratings()
    applied = read_applied()
    ads = labelled_ads(scratch)
    verdicts = {}
    for i, r in ratings.items():
        verdicts.setdefault(r["verdict"], []).append(i)
    classes = role_classes(scratch, ads)
    per_class: dict[str, dict[str, int]] = {}
    for i, a in ads.items():
        if a["set"] != "holdout":
            continue
        role = classes.get(i, "no stored i1 answer")
        per_class.setdefault(role, {}).setdefault(a["label"], 0)
        per_class[role][a["label"]] += 1
    by_label = {k: sum(1 for a in ads.values() if a["label"] == k) for k in ("apply", "maybe", "fit_skip", "elig_skip", "applied")}
    # cross-check of the owner's A3 grouping against the driver tags of the rating table (reported, never used to relabel)
    skip_ids = [i for i, r in ratings.items() if r["verdict"] == "skip"]
    tag_fit_only = {i for i in skip_ids if ratings[i]["driver"] == "FIT"}
    labels_file = json.loads((EVAL / "w5-labels.json").read_text(encoding="utf-8"))
    from_labels = {i for n in labels_file.get("fitSkip") or [] for i in bars.match_company({i: {"posting": a} for i, a in ads.items()}, n)}
    v2 = json.loads((EVAL / "holdout-v2-selection.json").read_text(encoding="utf-8"))
    v2_ids = set(v2.get("ids") or [])
    if v2_ids & set(ads):
        raise SystemExit("refused: a labelled ad is in holdout v2")
    return {
        "w5LabelsFitSkipResolveToSameIdsAsOwnerGrouping": from_labels == FIT_SKIPS, "holdoutV2Overlap": len(v2_ids & set(ads)),
        "ratedAds": len(ratings), "ratedByVerdict": {k: len(v) for k, v in sorted(verdicts.items())},
        "fitSkipsByOwnerGrouping": len([i for i in skip_ids if i in FIT_SKIPS]), "eligibilityDrivenSkips": len([i for i in skip_ids if i not in FIT_SKIPS]),
        "skipDriverTagCrossCheck": {"driverTagFITonly": len(tag_fit_only), "inOwnerFitSkipGroup": len(tag_fit_only & FIT_SKIPS),
                                    "tagFITonlyButNotInGroup": len(tag_fit_only - FIT_SKIPS), "inGroupButTagNotFITonly": len(FIT_SKIPS & set(skip_ids) - tag_fit_only)},
        "appliedApplications": len(applied), "appliedAlsoRated": len(set(applied) & set(ratings)),
        "labelledAdsWithText": len(ads), "withTextByLabel": by_label, "ratedWithoutText": len(set(ratings) - set(ads)),
        "appliedWithText": sum(1 for a in ads.values() if a["set"] == "applied" or a.get("alsoApplied")),
        "roleClassFromStoredI1ByLabel": per_class,
        "appliedWithStoredI1Answer": 0,  # the stored i1 passes cover holdout v1 and dev only; an application outside them has no role class
        "duplicateGroups": {"groups": len(groups_of(ads)), "groupsWithMoreThanOneAd": sum(1 for g in groups_of(ads).values() if len(g) > 1),
                            "companyGroups": len(company_groups(ads)), "companyGroupsWithMoreThanOneAd": sum(1 for g in company_groups(ads).values() if len(g) > 1)},
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("command", choices=["step0", "embed", "evaluate"])
    p.add_argument("--scratch", type=Path, default=m3.DEFAULT_SCRATCH)
    p.add_argument("--data-dir", type=Path, default=None, help="the real data dir (read only); default as the other measure scripts")
    p.add_argument("--estimate", action="store_true", help="embed: price it through the gate, call nothing")
    p.add_argument("--confirm", action="store_true", help="embed: REQUIRED to send the ad text to the provider")
    p.add_argument("--max-usd", type=float, default=0.0)
    args = p.parse_args(argv)
    if args.command == "step0":
        print(json.dumps(step0(args.scratch), indent=1))
        return 0
    if args.command == "evaluate":
        return run_evaluate(args)
    if args.confirm and args.max_usd <= 0:
        print("--max-usd must be positive with --confirm", file=sys.stderr)
        return 2
    return run_embed(args)


if __name__ == "__main__":
    raise SystemExit(main())
