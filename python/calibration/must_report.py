#!/usr/bin/env python3
"""P1 Stage A, step 8 report (read-only): how precise the extracted "must" requirements are, by the owner's own judgment.

    python python/calibration/must_report.py [--out DIR]

Reads must-sample.json and ran-must-labels.json. Writes nothing; prints counts, shares and kinds only, never requirement or
ad text. Only the owner's FIRST (blind) answer for an item is used; a change made after seeing the engine is only counted.
production_like and diagnostic are reported separately and never pooled.

Metrics (items the model marked must, `probe` false):
  precision of must   the share the owner calls "a real must", by kind and for the gate kinds together; raw (with a 95% Wilson
                      interval) and weighted back to the pool by stratum (kind, mode, class), since the sample favours
                      disagreements and rare kinds
  verdict agreement   the engine's MET / PARTIAL / MISSING / UNKNOWN against "do I meet it" (yes / partly / no / unknown), on the
                      items the owner confirms are real musts
  probe items         the share of the model's nice-to-have and preferred items the owner calls real musts (musts the model missed)
  trust per kind      proposed bar: precision of at least 0.9 on at least 8 answered items
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGE_DIR = ROOT / "data" / "calibration" / "stage-a"
MODES = ("production_like", "diagnostic")
GATE_KINDS = ("domain", "education", "certification", "experience")
VERDICT_AS_MEETS = {"MET": "yes", "PARTIAL": "partial", "MISSING": "no", "UNKNOWN": "unknown"}
MEETS = ("yes", "partial", "no", "unknown")
BAR_PRECISION, BAR_MIN_N = 0.9, 8


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def wilson(hits: int, n: int, z: float = 1.96):
    """95% Wilson interval for a share; None for no items."""
    if n == 0:
        return None
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 2), round(min(1.0, centre + half), 2)]


def _share(num: int, den: int):
    return round(num / den, 2) if den else None


def _precision(rows: list[dict]) -> dict:
    yes = sum(1 for r in rows if r["first"]["isMust"] == "yes")
    return {"answered": len(rows), "really_must": yes, "nice_to_have": sum(1 for r in rows if r["first"]["isMust"] == "nice"),
            "not_a_requirement": sum(1 for r in rows if r["first"]["isMust"] == "no"),
            "precision": _share(yes, len(rows)), "wilson95": wilson(yes, len(rows))}


def weighted_precision(rows: list[dict], strata: list[dict]) -> dict:
    """Precision weighted back to the pool: each (kind, mode, class) stratum counts as much as its pool, using the owner's answers
    on the items sampled from it. A stratum with no answered item is left out and the covered share of the pool is reported."""
    answered = defaultdict(list)
    for r in rows:
        answered[(r["item"]["kind"], r["item"]["mode"], r["item"]["class"])].append(r["first"]["isMust"] == "yes")
    pool = {(s["kind"], s["mode"], s["class"]): s["pool"] for s in strata}
    covered = {k: pool[k] for k in answered if k in pool}
    total = sum(covered.values())
    if not total:
        return {"precision": None, "coveredPoolShare": None}
    value = sum(pool[k] * (sum(v) / len(v)) for k, v in answered.items() if k in pool) / total
    return {"precision": round(value, 2), "coveredPoolShare": _share(total, sum(pool.values()))}


def agreement(rows: list[dict]) -> dict:
    """Engine verdict against the owner's "do I meet it", on items the owner confirms are real musts."""
    real = [r for r in rows if r["first"]["isMust"] == "yes"]
    matrix = {m: Counter() for m in MEETS}
    for r in real:
        matrix[r["first"]["meets"]][VERDICT_AS_MEETS[r["item"]["verdict"]["status"]]] += 1
    exact = sum(matrix[m][m] for m in MEETS)
    known = [r for r in real if r["first"]["meets"] != "unknown"]
    return {
        "items": len(real), "exact": exact, "exactShare": _share(exact, len(real)),
        "exactWhereOwnerKnows": sum(1 for r in known if VERDICT_AS_MEETS[r["item"]["verdict"]["status"]] == r["first"]["meets"]),
        "ownerKnows": len(known),
        "engineMissingButOwnerMeetsIt": matrix["yes"]["no"], "engineMetButOwnerDoesNot": matrix["no"]["yes"],
        "matrix (owner row, engine column)": {o: {e: matrix[o][e] for e in MEETS} for o in MEETS},
        "byKind": {k: [sum(1 for r in real if r["item"]["kind"] == k and VERDICT_AS_MEETS[r["item"]["verdict"]["status"]] == r["first"]["meets"]),
                       sum(1 for r in real if r["item"]["kind"] == k)] for k in sorted({r["item"]["kind"] for r in real})},
    }


def trust(kind_rows: dict) -> dict:
    out = {}
    for kind, rows in sorted(kind_rows.items()):
        p = _precision(rows)
        if p["answered"] < BAR_MIN_N:
            out[kind] = f"undecided: only {p['answered']} answered (needs {BAR_MIN_N})"
        else:
            out[kind] = "trusted at the bar" if p["precision"] >= BAR_PRECISION else "not trusted: precision below the bar"
    return out


def build(out: Path) -> dict:
    sample, labels_doc = _load(out / "must-sample.json"), _load(out / "ran-must-labels.json")
    labels = (labels_doc or {}).get("labels") or {}
    report = {"sampled": len(sample["items"]), "answered": sum(1 for i in sample["items"] if i["itemId"] in labels),
              "changedAfterReveal": sum(1 for lb in labels.values() if lb.get("changedAfterReveal")),
              "bar": {"precision": BAR_PRECISION, "minAnswered": BAR_MIN_N}, "modes": {}}
    for mode in MODES:
        items = [i for i in sample["items"] if i["mode"] == mode]
        rows = [{"item": i, "first": labels[i["itemId"]]["first"]} for i in items if i["itemId"] in labels]
        musts = [r for r in rows if not r["item"]["probe"]]
        probes = [r for r in rows if r["item"]["probe"]]
        by_kind = defaultdict(list)
        for r in musts:
            by_kind[r["item"]["kind"]].append(r)
        gate = [r for r in musts if r["item"]["kind"] in GATE_KINDS]
        mode_strata = [s for s in sample["strata"] if s["mode"] == mode]
        report["modes"][mode] = {
            "sampledMust": sum(1 for i in items if not i["probe"]), "answeredMust": len(musts),
            "precision": {**_precision(musts), "weighted": weighted_precision(musts, mode_strata)},
            "gateKinds": {**_precision(gate), "weighted": weighted_precision(gate, mode_strata),
                          "meetsBar": bool(gate) and _precision(gate)["precision"] >= BAR_PRECISION and len(gate) >= BAR_MIN_N},
            "byKind": {k: _precision(v) for k, v in sorted(by_kind.items())},
            "trust": trust(by_kind), "verdictAgreement": agreement(musts),
            "probe": {"sampled": sum(1 for i in items if i["probe"]), "answered": len(probes),
                      "calledRealMust": sum(1 for r in probes if r["first"]["isMust"] == "yes"),
                      "calledNice": sum(1 for r in probes if r["first"]["isMust"] == "nice"),
                      "calledNotRequirement": sum(1 for r in probes if r["first"]["isMust"] == "no")},
        }
    return report


def render(report: dict) -> list[str]:
    lines = [f"must-have precision: {report['answered']} of {report['sampled']} sampled items answered; "
             f"{report['changedAfterReveal']} changed after seeing the engine (the first, blind answer is used)",
             f"proposed bar: precision {report['bar']['precision']} on at least {report['bar']['minAnswered']} answered items; "
             "production_like and diagnostic are reported separately, never pooled"]
    for mode in MODES:
        m = report["modes"][mode]
        tag = "[what production would show]" if mode == MODES[0] else "[DIAGNOSTIC ONLY: production would skip these ads]"
        p, g, a, pr = m["precision"], m["gateKinds"], m["verdictAgreement"], m["probe"]
        lines += [f"\n== {mode.upper()} {tag}: {m['answeredMust']} of {m['sampledMust']} must items answered",
                  f"  precision of must: {p['really_must']}/{p['answered']} = {p['precision']} (95% interval {p['wilson95']}); "
                  f"weighted to the pool {p['weighted']['precision']} (pool covered {p['weighted']['coveredPoolShare']}); "
                  f"nice-to-have {p['nice_to_have']}, not a requirement {p['not_a_requirement']}",
                  f"  gate kinds (domain, education, certification, experience): {g['really_must']}/{g['answered']} = {g['precision']} "
                  f"(interval {g['wilson95']}), weighted {g['weighted']['precision']}; meets the bar: {g['meetsBar']}"]
        for kind, row in m["byKind"].items():
            lines.append(f"    {kind:14} {row['really_must']}/{row['answered']} = {row['precision']} (interval {row['wilson95']})  -> {m['trust'][kind]}")
        lines.append(f"  engine verdict vs 'do I meet it' on {a['items']} real musts: exact {a['exact']} ({a['exactShare']}); "
                     f"where you know the answer {a['exactWhereOwnerKnows']}/{a['ownerKnows']}; "
                     f"engine MISSING but you meet it {a['engineMissingButOwnerMeetsIt']}; engine MET but you do not {a['engineMetButOwnerDoesNot']}")
        lines.append("    by kind [agree, real musts]: " + ", ".join(f"{k} {v}" for k, v in a["byKind"].items()))
        lines.append(f"  probe items (the model's nice-to-have or preferred): {pr['answered']}/{pr['sampled']} answered; "
                     f"real must {pr['calledRealMust']}, nice-to-have {pr['calledNice']}, not a requirement {pr['calledNotRequirement']}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=STAGE_DIR)
    print("\n".join(render(build(ap.parse_args(argv).out))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
