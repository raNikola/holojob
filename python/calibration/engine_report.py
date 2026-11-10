#!/usr/bin/env python3
"""P1 Stage A, step 7 report (read-only): the engine's results on the review sample against the owner's labels and matchScore.

    python python/calibration/engine_report.py [--out DIR]

Reads ran-labels.json, engine-shadow.json and rescored/scored_jobs.json. Writes nothing; prints counts and ad ids only.
production_like (no confirmed cheap-gate fail: production would send the ad) and diagnostic (production would skip it) are
never pooled: each is reported on its own, and a pooled line is not printed.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))

from calibration.report import BAND_LEVEL, ENGINE_LEVEL, _load, confusion, spearman  # noqa: E402

STAGE_DIR = ROOT / "data" / "calibration" / "stage-a"
MODES = ("production_like", "diagnostic")
GATE_KINDS = ("domain", "education", "certification", "experience")


def _share(num: int, den: int):
    return round(num / den, 2) if den else None


def requirement_view(entries: dict, labels: dict) -> dict:
    """Per owner hard-requirements label: how many ads, and the engine's verdict shares over their must requirements
    (UNKNOWN left out of the share). Counts and shares only."""
    out = {}
    for value in ("yes", "partial", "no", "unknown"):
        ids = [j for j in entries if labels[j]["hardRequirements"] == value]
        if not ids:
            continue
        status = Counter()
        gate_missing = 0
        for j in ids:
            must = [q for q in entries[j]["output"]["requirements"] if q["importance"] == "must"]
            status.update(q["status"] for q in must)
            gate_missing += any(q["status"] == "MISSING" and q["kind"] in GATE_KINDS for q in must)
        judged = status["MET"] + status["PARTIAL"] + status["MISSING"]
        out[value] = {"ads": len(ids), "must": sum(status.values()), "MET": status["MET"], "PARTIAL": status["PARTIAL"],
                      "MISSING": status["MISSING"], "UNKNOWN": status["UNKNOWN"],
                      "metShare": _share(status["MET"], judged), "missingShare": _share(status["MISSING"], judged),
                      "adsWithMissingGateKindMust": gate_missing}
    return out


def level_view(entries: dict, labels: dict, rows: dict) -> dict:
    """Engine label and the band of matchScore, each against the owner's overall level, on the same ads."""
    ids = [j for j in entries if ENGINE_LEVEL.get(entries[j]["label"]) is not None and j in rows
           and BAND_LEVEL.get(rows[j].get("matchLabel")) is not None]
    owner = [labels[j]["overall"] for j in ids]
    engine = [ENGINE_LEVEL[entries[j]["label"]] for j in ids]
    band = [BAND_LEVEL[rows[j]["matchLabel"]] for j in ids]
    fit = [float(entries[j]["fit"]) for j in ids]
    score = [float(rows[j]["matchScore"]) for j in ids]
    view = {"ads": len(ids), "engineIncomplete": sum(1 for j in entries if entries[j]["label"] == "Incomplete")}
    for name, system, number in (("engine", engine, fit), ("matchScore", band, score)):
        c = confusion(list(zip(owner, system)))
        view[name] = {"exact": c["exact"], "withinOne": c["withinOne"], "over": c["over"], "under": c["under"],
                      "ownerIrrelevantAtGoodOrAbove": sum(1 for o, s in zip(owner, system) if o == 0 and s >= 2),
                      "ownerRelevantAtWeakOrBelow": sum(1 for o, s in zip(owner, system) if o >= 2 and s <= 1),
                      "spearmanVsOwner": spearman([float(o) for o in owner], number)}
    view["engineVsMatchScoreSpearman"] = spearman(fit, score)
    view["sameLevel"] = sum(1 for e, b in zip(engine, band) if e == b)
    view["engineHigher"] = sum(1 for e, b in zip(engine, band) if e > b)
    view["engineLower"] = sum(1 for e, b in zip(engine, band) if e < b)
    return view


def build(out: Path) -> dict:
    labels = (_load(out / "ran-labels.json") or {}).get("labels") or {}
    labels = labels if isinstance(labels, dict) else {x["jobId"]: x for x in labels}
    ads = (_load(out / "engine-shadow.json") or {}).get("ads") or {}
    rows = {r["jobId"]: r for r in ((_load(out / "rescored" / "scored_jobs.json") or {}).get("jobs") or [])}
    report = {"engineAds": len(ads), "modes": {}}
    for mode in MODES:
        entries = {j: e for j, e in ads.items() if e.get("mode") == mode and j in labels}
        report["modes"][mode] = {
            "ads": len(entries), "labels": dict(Counter(e["label"] for e in entries.values())),
            "excludedBy": dict(Counter(g for e in entries.values() for g in e.get("excludedBy") or [])),
            "levels": level_view(entries, labels, rows), "requirements": requirement_view(entries, labels),
        }
    return report


def render(report: dict) -> list[str]:
    lines = [f"engine results: {report['engineAds']} ads (production_like and diagnostic are reported separately, never pooled)"]
    for mode in MODES:
        m = report["modes"][mode]
        lines += [f"\n== {mode.upper()}: {m['ads']} ads" + ("  [what production would show]" if mode == MODES[0] else
                  "  [DIAGNOSTIC ONLY: production would skip these on a confirmed gate fail]"),
                  f"  engine labels: {m['labels']}" + (f"; gates that would exclude: {m['excludedBy']}" if m["excludedBy"] else "")]
        v = m["levels"]
        lines.append(f"  overall level vs owner on {v['ads']} ads ({v['engineIncomplete']} engine Incomplete left out):")
        for name in ("engine", "matchScore"):
            s = v[name]
            lines.append(f"    {name:10} exact {s['exact']}, within one {s['withinOne']}, over {s['over']}, under {s['under']}, "
                         f"owner-irrelevant at Good+ {s['ownerIrrelevantAtGoodOrAbove']}, owner-relevant at Weak- {s['ownerRelevantAtWeakOrBelow']}, "
                         f"Spearman vs owner {s['spearmanVsOwner']}")
        lines.append(f"    engine vs matchScore band on the same ads: same {v['sameLevel']}, engine higher {v['engineHigher']}, "
                     f"engine lower {v['engineLower']}, Spearman between the two numbers {v['engineVsMatchScoreSpearman']}")
        lines.append("  engine verdicts on must requirements by the owner's hard-requirements label:")
        for value, r in m["requirements"].items():
            lines.append(f"    owner {value:8} ads {r['ads']:2}  must {r['must']:3}  MET {r['MET']} PARTIAL {r['PARTIAL']} MISSING {r['MISSING']} UNKNOWN {r['UNKNOWN']}"
                         f"  metShare {r['metShare']} missingShare {r['missingShare']}  ads with a MISSING gate-kind must {r['adsWithMissingGateKindMust']}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=STAGE_DIR)
    print("\n".join(render(build(ap.parse_args(argv).out))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
