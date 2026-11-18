#!/usr/bin/env python3
"""W5 step 3, Part 2: the PRE-REGISTERED comparison of Fit 3 order variants (~/holojob-eval/w5-benchmark-ranking.md). OFFLINE: no model call, no provider, writes nothing.

    .venv/bin/python scripts/eval_fit3_orders.py --labels ~/holojob-eval/w5-labels.json

Reads the stored i1 passes under <scratch>/fit3/ (holdout v1: i1-store-p1 / i1-store-p2; dev: dev-store-i1, pass 1) with `--candidate python/match_engine/fit3_candidates/i1`,
the owner's labels (kept outside the repo) and the owner's levels (data/calibration/stage-a/eval-set.json, read only). Prints AGGREGATES only: counts, rates, correlations,
never an owner label next to an ad id. Orders: baseline v0 / v1 (`fit3.order_key`) and the shadow variants c1, c2, c3 (`match_engine/fit3_orders.py`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_fit3_bars as bars  # noqa: E402
import check_fit3_dev as dev  # noqa: E402
import measure_common as mc  # noqa: E402
import measure_fit3 as m3  # noqa: E402

TOP = 6
EVAL = Path(mc.EVAL_DIR)
ORDER_NAMES = ("v0", "v1", "c1", "c2", "c3")


def ranker(name: str):
    """(rank function, key function) for an order name; the key excludes the id."""
    from match_engine import fit3, fit3_orders
    if name in fit3.VARIANTS:
        return (lambda rows: fit3.rank(rows, name)), (lambda block: fit3.order_key(block, name))
    return (lambda rows: fit3_orders.rank(rows, name)), (lambda block: fit3_orders.order_key(block, name))


def block_rows(passed: dict, ads: dict, intel_industries, level) -> list[dict]:
    from match_engine import fit3
    from match_engine.fit3_industry import ad_industries
    return [{"id": i, "fit3": fit3.fit3(a["anchored"], a["answers"], ad_industries(ads[i]["posting"], ads[i]["facts"]), intel_industries,
                                       ad_level=ads[i]["facts"].get("seniority"), candidate_level=level)} for i, a in passed.items()]


def stability(rows1: list[dict], rows2: list[dict], name: str) -> dict:
    rank, _ = ranker(name)
    o1, o2 = ([r["id"] for r in rank(rows)["ranked"]] for rows in (rows1, rows2))
    overlap = len(set(o1[:TOP]) & set(o2[:TOP])) / TOP
    both = [i for i in o1 if i in set(o2)]
    p1, p2 = ({i: n for n, i in enumerate(o)} for o in (o1, o2))
    rho = dev.spearman([p1[i] for i in both], [p2[i] for i in both])
    return {"top6Overlap": round(overlap, 4), "spearman": rho, "adsInBoth": len(both), "ranked": [len(o1), len(o2)]}


def b5(rows: list[dict], ads, labels, name: str) -> dict:
    """check_fit3_bars.b5 rules, with the order injected."""
    rank, key = ranker(name)
    apply_ids = {n: bars.match_company(ads, n) for n in labels.get("apply") or []}
    skip_ids = [i for n in labels.get("fitSkip") or [] for i in bars.match_company(ads, n)]
    ranked = rank(rows)
    order = [r["id"] for r in ranked["ranked"]]
    keys = {r["id"]: key(r["fit3"]) for r in ranked["ranked"]}
    applies = [i for ids in apply_ids.values() for i in ids]
    pairable = [a for a in applies if a in keys]
    top = sum(1 for i in applies if i in order[:TOP])
    above = [s for s in skip_ids if s in keys and any(keys[s] <= keys[a] for a in pairable if a != s)]
    return {"applyInTop6": top, "of": len(apply_ids), "skipsAboveApply": len(above), "criterion1": top >= 3, "criterion2": not above,
            "insufficient": len(ranked["insufficient"])}


def dev_concordance(rows: list[dict], levels: dict[str, int], name: str) -> dict:
    """check_fit3_dev.order_vs_levels with the order injected (a tie in the key = half; Spearman over final positions)."""
    rank, key = ranker(name)
    ranked = rank(rows)
    keys = {r["id"]: key(r["fit3"]) for r in ranked["ranked"]}
    ids = [r["id"] for r in ranked["ranked"] if r["id"] in levels]
    position = {r["id"]: n for n, r in enumerate(ranked["ranked"])}
    rho = dev.spearman([-position[i] for i in ids], [levels[i] for i in ids])
    agree = pairs = 0.0
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            i, j = ids[a], ids[b]
            if levels[i] == levels[j]:
                continue
            hi, lo = (i, j) if levels[i] > levels[j] else (j, i)
            pairs += 1
            agree += 1.0 if keys[hi] < keys[lo] else 0.5 if keys[hi] == keys[lo] else 0.0
    return {"ranked": len(ranked["ranked"]), "insufficient": len(ranked["insufficient"]), "compared": len(ids), "spearman": rho,
            "pairConcordance": None if not pairs else round(agree / pairs, 4), "pairs": int(pairs)}


def verdict(base: dict, cand: dict) -> dict:
    """The pre-registered rule. (a) improves: overlap >= and Spearman >= (3 decimals) with at least one strictly greater; (c) not worse (4 decimals); (d) by construction."""
    a_o, a_s = round(cand["a"]["top6Overlap"], 3), round(cand["a"]["spearman"], 3)
    b_o, b_s = round(base["a"]["top6Overlap"], 3), round(base["a"]["spearman"], 3)
    a_ok = a_o >= b_o and a_s >= b_s and (a_o > b_o or a_s > b_s)
    c_ok = cand["c"]["pairConcordance"] >= base["c"]["pairConcordance"] and cand["c"]["spearman"] >= base["c"]["spearman"]
    d_ok = cand["d"] == base["d"]
    return {"aImproves": a_ok, "cNotWorse": c_ok, "dNotWorse": d_ok, "BETTER": a_ok and c_ok and d_ok}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--scratch", type=Path, default=m3.DEFAULT_SCRATCH)
    p.add_argument("--holdout-ids", type=Path, default=m3.DEFAULT_IDS)
    p.add_argument("--dev-ids", type=Path, default=EVAL / "dev44-ids.json")
    p.add_argument("--holdout-pass1", default="i1-store-p1.json")
    p.add_argument("--holdout-pass2", default="i1-store-p2.json")
    p.add_argument("--dev-pass1", default="dev-store-i1.json")
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--candidate", type=Path, default=Path(__file__).resolve().parents[1] / "python" / "match_engine" / "fit3_candidates" / "i1")
    p.add_argument("--eval-set", type=Path, default=None)
    args = p.parse_args(argv)
    from match_engine import fit3
    from match_engine.fit3_industry import candidate_industries
    fit3.use_candidate(args.candidate)

    def ids_of(path):
        raw = json.loads(path.read_text(encoding="utf-8"))
        return list(dict.fromkeys(i for i in (raw.get("ids") if isinstance(raw, dict) else raw) or [] if isinstance(i, str)))

    intel = json.loads((args.scratch / "intelligence" / "candidate-intelligence.json").read_text(encoding="utf-8"))
    industries = candidate_industries(intel)
    level = str((intel.get("candidateSummary") or {}).get("seniorityLevel") or "").strip().lower() or None
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    load = lambda name: json.loads((args.scratch / m3.OUT_DIR / name).read_text(encoding="utf-8"))  # noqa: E731

    h_ads = bars.load_ads(args.scratch, ids_of(args.holdout_ids))
    h1, h2 = (bars.anchored_pass(load(n), h_ads) for n in (args.holdout_pass1, args.holdout_pass2))
    rows_h1, rows_h2 = block_rows(h1, h_ads, industries, level), block_rows(h2, h_ads, industries, level)

    d_ads = bars.load_ads(args.scratch, ids_of(args.dev_ids))
    d1 = bars.anchored_pass(load(args.dev_pass1), d_ads)
    rows_d = block_rows(d1, d_ads, industries, level)
    eval_path = args.eval_set or Path(mc.default_data_dir()) / "calibration" / "stage-a" / "eval-set.json"
    levels = {i: int(v["overall"]) for i, v in json.loads(eval_path.read_text(encoding="utf-8"))["ads"].items() if isinstance(v.get("overall"), int)}

    out = {"holdout": {"adsWithText": len(h_ads), "classified": [len(h1), len(h2)]}, "dev": {"adsWithText": len(d_ads), "classifiedPass1": len(d1),
           "note": "stability (a) not evaluable on dev: pass 2 has no matcher answers"}, "orders": {}}
    for name in ORDER_NAMES:
        entry = {"a": stability(rows_h1, rows_h2, name), "b": [b5(rows_h1, h_ads, labels, name), b5(rows_h2, h_ads, labels, name)],
                 "c": dev_concordance(rows_d, levels, name)}
        entry["d"] = {"devInsufficient": entry["c"]["insufficient"], "devOf": len(rows_d), "holdoutInsufficient": [entry["b"][0]["insufficient"], entry["b"][1]["insufficient"]]}
        out["orders"][name] = entry
    base = out["orders"]["v0"]
    for name in ("c1", "c2", "c3"):
        out["orders"][name]["verdict"] = verdict(base, out["orders"][name])
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
