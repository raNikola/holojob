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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from match_engine.specificity import GENERIC_COMPETENCY_IDS, SPECIFIC_KINDS, is_specific  # noqa: E402,F401  the one rule, shared with the engine

BUCKETS = (("1.0", 1.0, None), ("0.8-<1.0", 0.8, 1.0), ("0.6-<0.8", 0.6, 0.8), ("0.4-<0.6", 0.4, 0.6), ("<0.4", None, 0.4))
VERSION_WANTED = 1


def is_specific_must(unit: dict) -> bool:
    """A must unit that the specificity rule (python/match_engine/specificity.py) keeps."""
    key = unit.get("key") or ""
    competency_id = key[2:] if key.startswith("c:") else None
    return unit.get("importance") == "must" and is_specific(unit.get("kind"), competency_id, bool(unit.get("canonical")))


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


def responsibility_stability(doc: dict) -> dict | None:
    """The responsibilities class (extract-7 runs only): Jaccard overlap of the passes' responsibility keys, a separate class from
    the requirement units. None when the file has none (an extract-6 run)."""
    keys = doc.get("responsibilityKeys")
    if not isinstance(keys, dict) or not keys:
        return None
    means, undefined = {}, []
    for job_id, passes in sorted(keys.items()):
        res = ad_overlap(passes) if len(passes) >= 2 else None
        if res is None:
            undefined.append(job_id)
        else:
            means[job_id] = res["mean"]
    return {**distribution(means), "adsUndefined": len(undefined), "undefinedIds": undefined,
            "lowestIds": [i for i, _ in sorted(means.items(), key=lambda kv: (kv[1], kv[0]))[:5]]}


def det_stability(doc: dict) -> dict | None:
    """The d: class (W3/W4): Fit 2.0/2.1's deterministic units, from `detUnitKeys` = {jobId: [per pass {"units": [{key, importance, kind}],
    "unmapped": {"must": n, "other": n}}]} (a dict per pass, not a list). Jaccard overlap of the d:<id> keys for all units and for non-generic
    must units, plus the per-ad share of must lines left unmapped (unmapped must / (must units + unmapped must)). None when the file has none."""
    keys = doc.get("detUnitKeys")
    if not isinstance(keys, dict) or not keys:
        return None
    passes_of = {i: [p.get("units") or [] for p in passes] for i, passes in keys.items()}
    classes = {}
    for name, keep in (("allUnits", lambda u: True),
                       ("nonGenericMustUnits", lambda u: u.get("importance") == "must" and u["key"][2:] not in GENERIC_COMPETENCY_IDS)):
        means, undefined = {}, []
        for job_id, passes in sorted(passes_of.items()):
            res = ad_overlap(passes, keep) if len(passes) >= 2 else None
            if res is None:
                undefined.append(job_id)
            else:
                means[job_id] = res["mean"]
        classes[name] = {**distribution(means), "adsUndefined": len(undefined), "undefinedIds": undefined,
                         "lowestIds": [i for i, _ in sorted(means.items(), key=lambda kv: (kv[1], kv[0]))[:5]]}
    shares = {}
    for job_id, passes in sorted(keys.items()):
        vals = []
        for p in passes:
            must_units = sum(1 for u in p.get("units") or [] if u.get("importance") == "must" and u["key"][2:] not in GENERIC_COMPETENCY_IDS)
            unmapped = (p.get("unmapped") or {}).get("must", 0)
            if must_units + unmapped:
                vals.append(unmapped / (must_units + unmapped))
        if vals:
            shares[job_id] = sum(vals) / len(vals)
    return {"classes": classes, "unmappedMustShare": {**distribution(shares), "ads": len(shares)}}


def read_doc(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load(path: Path) -> dict:
    doc = read_doc(path)
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


def causes(unit_keys: dict) -> dict:
    """INFORMATIONAL, never a criterion: why specific-must overlap is low, per ad. Per ad: mean units per pass split into
    canonical (c:) and quote-keyed (q:) units, and the mean pairwise overlap of each part on its own. A low q-only
    overlap with a high c-only overlap says the same competency is asked but the extractor quotes it differently."""
    out = {}
    for job_id, passes in sorted(unit_keys.items()):
        if len(passes) < 2:
            continue
        row = {"unitsPerPass": round(sum(sum(1 for u in p if is_specific_must(u)) for p in passes) / len(passes), 1)}
        for name, prefix in (("canonical", "c:"), ("quoteKeyed", "q:")):
            keep = lambda u, prefix=prefix: is_specific_must(u) and u["key"].startswith(prefix)  # noqa: E731
            row[name + "PerPass"] = round(sum(sum(1 for u in p if keep(u)) for p in passes) / len(passes), 1)
            res = ad_overlap(passes, keep)
            row[name + "Overlap"] = None if res is None else round(res["mean"], 3)
        out[job_id] = row
    return out


def render_causes(rows: dict) -> list[str]:
    out = ["### causes (informational, not a criterion)", "| ad | specific musts/pass | canonical/pass | overlap | quote-keyed/pass | overlap |", "|---|---:|---:|---:|---:|---:|"]
    for job_id, r in rows.items():
        out.append(f"| {job_id} | {r['unitsPerPass']} | {r['canonicalPerPass']} | {r['canonicalOverlap']} | {r['quoteKeyedPerPass']} | {r['quoteKeyedOverlap']} |")
    return out + [""]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("variance", type=Path)
    p.add_argument("--json", action="store_true")
    p.add_argument("--causes", action="store_true", help="add the informational per-ad breakdown (canonical vs quote-keyed units)")
    args = p.parse_args(argv)
    try:
        keys = load(args.variance)
        report = stability(keys)
    except (OSError, ValueError) as exc:
        print(f"cannot read {args.variance}: {exc}", file=sys.stderr)
        return 2
    if args.causes:
        report["causes"] = causes(keys)
    if (resp := responsibility_stability(read_doc(args.variance))) is not None:
        report["responsibilities"] = resp
    if (det := det_stability(read_doc(args.variance))) is not None:
        report["deterministic"] = det
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        extra = [] if "responsibilities" not in report else [
            "### responsibilities (extract-7, separate class)", json.dumps(report["responsibilities"]), ""]
        if "deterministic" in report:
            extra += ["### deterministic units (d: keys, Fit 2.0/2.1 resolver, separate class)", json.dumps(report["deterministic"]), ""]
        print("\n".join(render(report) + (render_causes(report["causes"]) if args.causes else []) + extra))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
