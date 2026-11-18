#!/usr/bin/env python3
"""W5 optimization loop, DEVELOPMENT DIAGNOSTICS on the 45 labelled ads (no pass threshold). NO model call, offline, writes nothing.

    .venv/bin/python scripts/check_fit3_dev.py --ids dev45-ids.json --pass1 dev-store-i0.json --pass2 dev-classification-i0-p2.json

Reads the stored passes under <scratch>/fit3/ and the owner's labels from data/calibration/stage-a/eval-set.json (READ ONLY; --eval-set). Prints AGGREGATES only
(counts, rates, correlations): never an owner label next to an ad id. --pass1 should be a store merged with the matcher answers (merge_fit3_answers.py), --pass2 may be a
bare classification (role and core overlap need no answers).

Reports: role-class availability and mix; role class x owner functionFit counts; core overlap between the passes (median Jaccard, share of ads with a core mark);
B4-style missing-quote share; and the system order against the owner `overall` level per variant: Spearman rho over the ranked ads and the share of
ordered pairs (different overall) the system ranks the same way (tie in the order key = half).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_fit3_bars as bars  # noqa: E402
import measure_common as mc  # noqa: E402
import measure_fit3 as m3  # noqa: E402


def _avg_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out, i = [0.0] * len(values), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None
    rx, ry = _avg_ranks(x), _avg_ranks(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return None if den == 0 else round(num / den, 4)


def order_vs_levels(rows: list[dict], levels: dict[str, int], variant: str) -> dict:
    from match_engine import fit3
    ranked = fit3.rank(rows, variant)
    keys = {r["id"]: fit3.order_key(r["fit3"], variant) for r in ranked["ranked"]}
    ids = [r["id"] for r in ranked["ranked"] if r["id"] in levels]
    position = {r["id"]: n for n, r in enumerate(ranked["ranked"])}
    rho = spearman([-position[i] for i in ids], [levels[i] for i in ids])  # better rank = higher number
    agree = pairs = 0.0
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            i, j = ids[a], ids[b]
            if levels[i] == levels[j]:
                continue
            hi, lo = (i, j) if levels[i] > levels[j] else (j, i)
            pairs += 1
            agree += 1.0 if keys[hi] < keys[lo] else 0.5 if keys[hi] == keys[lo] else 0.0  # smaller key = ranked better
    return {"ranked": len(ranked["ranked"]), "insufficient": len(ranked["insufficient"]), "comparedWithLevel": len(ids), "spearman": rho,
            "pairConcordance": None if not pairs else round(agree / pairs, 4), "pairs": int(pairs)}


def build(ads, passes, eval_ads, candidate_industries, level) -> dict:
    from match_engine import fit3
    from match_engine.fit3_industry import ad_industries
    p1 = passes[0]
    out = {"adsWithText": len(ads), "pass1Classified": len(p1), "roleAvailability": [], "roleMix": [], "roleVsFunctionFit": {}}
    for p in passes:
        classes = Counter(bars.role_class(a) for a in p.values())
        out["roleAvailability"].append(round(1 - classes.get(bars.NOT_AVAILABLE, 0) / len(ads), 4) if ads else None)
        out["roleMix"].append(dict(classes))
    table: Counter = Counter()
    for i, a in p1.items():
        table[f"{(eval_ads.get(i) or {}).get('functionFit')}|{bars.role_class(a)}"] += 1
    out["roleVsFunctionFit"] = dict(sorted(table.items()))
    if len(passes) > 1:
        out["coreOverlap"] = bars.b3(p1, passes[1], len(ads))
    out["missingQuotes"] = bars.b4(passes)
    rows = [{"id": i, "fit3": fit3.fit3(a["anchored"], a["answers"], ad_industries(ads[i]["posting"], ads[i]["facts"]), candidate_industries,
                                        ad_level=ads[i]["facts"].get("seniority"), candidate_level=level)} for i, a in p1.items()]
    if rows and any(r["fit3"]["requirements"]["coreCounts"]["answered"] for r in rows):
        levels = {i: int(v["overall"]) for i, v in eval_ads.items() if isinstance(v.get("overall"), int)}
        out["orderVsOwnerLevel"] = {v: order_vs_levels(rows, levels, v) for v in fit3.VARIANTS}
    else:
        out["orderVsOwnerLevel"] = "NOT EVALUABLE: pass 1 carries no matcher answers"
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--scratch", type=Path, default=m3.DEFAULT_SCRATCH)
    p.add_argument("--ids", type=Path, required=True)
    p.add_argument("--pass1", required=True)
    p.add_argument("--pass2", default=None)
    p.add_argument("--eval-set", type=Path, default=None)
    p.add_argument("--candidate", type=Path, default=None)
    args = p.parse_args(argv)
    if args.candidate:
        from match_engine import fit3
        fit3.use_candidate(args.candidate)
    from match_engine.fit3_industry import candidate_industries
    ids = list(dict.fromkeys(i for i in json.loads(args.ids.read_text(encoding="utf-8")) if isinstance(i, str)))
    ads = bars.load_ads(args.scratch, ids)
    docs = [json.loads((args.scratch / m3.OUT_DIR / n).read_text(encoding="utf-8")) for n in (args.pass1, args.pass2) if n]
    passes = [bars.anchored_pass(d, ads) for d in docs]
    eval_path = args.eval_set or Path(mc.default_data_dir()) / "calibration" / "stage-a" / "eval-set.json"
    eval_ads = json.loads(eval_path.read_text(encoding="utf-8"))["ads"]
    intel = json.loads((args.scratch / "intelligence" / "candidate-intelligence.json").read_text(encoding="utf-8"))
    level = str((intel.get("candidateSummary") or {}).get("seniorityLevel") or "").strip().lower() or None
    print(json.dumps(build(ads, passes, eval_ads, candidate_industries(intel), level), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
