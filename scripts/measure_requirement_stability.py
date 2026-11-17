#!/usr/bin/env python3
"""Requirement-set stability across extraction passes: per-ad Jaccard overlap of unit keys. Read-only; no model call.

    .venv/bin/python scripts/measure_requirement_stability.py VARIANCE.json [--json]

VARIANCE.json is the --out file of scripts/measure_extraction_variance.py (its `unitKeys`: per ad, per pass, the requirement
unit keys). For every ad with two or more passes it computes the Jaccard overlap of the passes' unit-key sets for each pair of
passes, and the ad's mean over pairs; then the distribution over ads. It does this twice:

  * all units, and
  * specific must units only: importance "must" AND (a canonical competency id OR a kind in SPECIFIC_KINDS).

The specific-must definition is code on extractor fields (plan 3.3: kind + competency id), provisional until the owner decides
the specificity rule. A pair where both passes hold no unit of the class has no overlap value (0/0): it is left out of that
ad's mean, and an ad with no defined pair is listed as undefined, not counted as 0 or 1.

Prints counts, ids and numbers only. The input holds hashes and competency ids, never ad text, and nothing is written.
Count flips (a number moves) are not this metric: two passes can split one sentence differently and still ask the same thing.
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
import sys
from pathlib import Path

SPECIFIC_KINDS = frozenset({"skill", "domain", "certification", "language"})
BUCKETS = (("1.0", 1.0, None), ("0.8-<1.0", 0.8, 1.0), ("0.6-<0.8", 0.6, 0.8), ("0.4-<0.6", 0.4, 0.6), ("<0.4", None, 0.4))
VERSION_WANTED = 1


def is_specific_must(unit: dict) -> bool:
    return unit.get("importance") == "must" and (bool(unit.get("canonical")) or unit.get("kind") in SPECIFIC_KINDS)


def jaccard(a: set, b: set) -> float | None:
    """|a & b| / |a | b|, or None when both are empty."""
    union = a | b
    return len(a & b) / len(union) if union else None


def ad_overlap(passes: list[list[dict]], keep=lambda unit: True) -> dict | None:
    """{"pairs": [values], "mean": float} over the defined pairs of passes for one ad; None when fewer than two passes
    or no pair is defined."""
    if len(passes) < 2:
        return None
    sets = [{u["key"] for u in units if keep(u)} for units in passes]
    pairs = [v for a, b in itertools.combinations(sets, 2) if (v := jaccard(a, b)) is not None]
    return {"pairs": pairs, "mean": sum(pairs) / len(pairs)} if pairs else None


def bucket_of(value: float) -> str:
    for name, low, high in BUCKETS:
        if (low is None or value >= low) and (high is None or value < high):
            return name
    return BUCKETS[-1][0]


def distribution(means: dict) -> dict:
    """{ads, adsAtOne, buckets, min, p25, median, p75, max, mean} of the per-ad mean overlaps."""
    values = sorted(means.values())
    if not values:
        return {"ads": 0}
    quartiles = statistics.quantiles(values, n=4, method="inclusive") if len(values) > 1 else [values[0]] * 3
    buckets = {name: 0 for name, _, _ in BUCKETS}
    for v in values:
        buckets[bucket_of(v)] += 1
    return {
        "ads": len(values), "adsAtOne": sum(1 for v in values if v == 1.0), "buckets": buckets,
        "min": round(values[0], 3), "p25": round(quartiles[0], 3), "median": round(quartiles[1], 3),
        "p75": round(quartiles[2], 3), "max": round(values[-1], 3), "mean": round(sum(values) / len(values), 3),
    }


def stability(unit_keys: dict) -> dict:
    """The full report for {jobId: [pass unit lists]}."""
    out = {"adsGiven": len(unit_keys), "classes": {}}
    out["adsWithTooFewPasses"] = sorted(i for i, p in unit_keys.items() if len(p) < 2)
    for name, keep in (("allUnits", lambda u: True), ("specificMustUnits", is_specific_must)):
        means, undefined = {}, []
        for job_id, passes in sorted(unit_keys.items()):
            if len(passes) < 2:
                continue
            res = ad_overlap(passes, keep)
            if res is None:
                undefined.append(job_id)
            else:
                means[job_id] = res["mean"]
        out["classes"][name] = {
            **distribution(means), "adsUndefined": len(undefined), "undefinedIds": undefined,
            "perAdMean": {i: round(v, 3) for i, v in means.items()},
            "lowestIds": [i for i, _ in sorted(means.items(), key=lambda kv: (kv[1], kv[0]))[:5]],
        }
    return out


def load(path: Path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    keys = doc.get("unitKeys")
    if not isinstance(keys, dict) or not keys:
        raise ValueError("no unitKeys in this file: it was written before the stability tool existed; re-run "
                         "measure_extraction_variance.py --out with the current script")
    if doc.get("unitKeysVersion") != VERSION_WANTED:
        raise ValueError(f"unitKeysVersion {doc.get('unitKeysVersion')!r}, this tool reads {VERSION_WANTED}")
    return keys


def render(report: dict) -> list[str]:
    out = [f"## Requirement-set stability: {report['adsGiven']} ads, {len(report['adsWithTooFewPasses'])} with fewer than two passes", ""]
    for name, c in report["classes"].items():
        out.append(f"### {name}")
        if not c["ads"]:
            out += [f"no ad has a defined overlap ({c['adsUndefined']} undefined)", ""]
            continue
        out.append(f"{c['ads']} ads scored, {c['adsUndefined']} undefined (no pair with a unit in either pass); "
                   f"{c['adsAtOne']} at overlap 1.0")
        out.append(f"per-ad mean overlap: min {c['min']}, p25 {c['p25']}, median {c['median']}, p75 {c['p75']}, max {c['max']}, mean {c['mean']}")
        out.append("| bucket | ads |")
        out.append("|---|---:|")
        out += [f"| {b} | {n} |" for b, n in c["buckets"].items()]
        out += [f"lowest: {', '.join(c['lowestIds'])}", ""]
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("variance", type=Path)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        report = stability(load(args.variance))
    except (OSError, ValueError) as exc:
        print(f"cannot read {args.variance}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=1) if args.json else "\n".join(render(report)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
