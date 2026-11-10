#!/usr/bin/env python3
"""P1 Stage B, S0 + S1: one local command that measures systems against the frozen test set. Read-only; no model call.

    python python/calibration/eval_report.py [--split all|dev|test] [--out DIR]

Ad level, per mode (production_like and diagnostic are never pooled): matchScore (the re-scored bands), the engine as stored in
Step 7, and the offline aggregation preview (aggregation_preview.py), each against ran's overall level: n, Spearman, exact,
within one, over, under, label distribution. Preview extras: confidence, unconfirmed musts, critical-unconfirmed ads, fit range.
Line level, per mode: must precision and verdict agreement for ran's 56-line sample, and what the new verdict typing does to those lines.

Prints counts and rates, never ad, requirement, profile or CV text.

READ WITH EVERY NUMBER: 45 ads and 70 lines, purpose-chosen, one labeller. A diagnostic, not proof of reliability for all professions.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))

from calibration import aggregation_preview as ap  # noqa: E402
from calibration.eval_set import CAVEAT, STAGE_DIR, drift, load  # noqa: E402
from calibration.must_report import _precision, agreement  # noqa: E402
from calibration.report import BAND_LEVEL, ENGINE_LEVEL, confusion, spearman  # noqa: E402

MODES = ("production_like", "diagnostic")
PREVIEW_LEVEL = {"Weak": 0, "Partial": 1, "Good": 2, "Strong": 3}
PROFILE_PATH = ROOT / "data" / "profile" / "candidate-profile.json"
INTELLIGENCE_PATH = ROOT / "data" / "intelligence" / "candidate-intelligence.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def profile_sections() -> dict[str, int]:
    """How many entries the profile holds per closed-world kind. Counts only; nothing of the profile is kept or printed."""
    profile, intelligence = _load(PROFILE_PATH) or {}, _load(INTELLIGENCE_PATH) or {}
    parsed = ((profile.get("resume") or {}).get("parsedData")) or {}
    count = lambda v: len([x for x in v if str(x or "").strip()]) if isinstance(v, list) else 0
    return {"education": count(parsed.get("education")), "certification": count(parsed.get("certifications")),
            "language": count(intelligence.get("languages"))}


def _median(values):
    return statistics.median(values) if values else None


def _share(num, den):
    return round(num / den, 2) if den else None


def ad_systems(entry: dict, row: dict | None, sections: dict) -> dict:
    """{system: (level or None, number or None)} for one engine ad."""
    shadow = preview = (None, None)
    if entry["label"] in ENGINE_LEVEL:
        shadow = (ENGINE_LEVEL[entry["label"]], entry["fit"])
    pv = ap.preview(entry["output"]["requirements"], entry["gates"], sections, entry.get("bucket", "apply"))
    if pv["label"] in PREVIEW_LEVEL:
        preview = (PREVIEW_LEVEL[pv["label"]], pv["fit"])
    score = (BAND_LEVEL.get(row.get("matchLabel")), row.get("matchScore")) if row else (None, None)
    return {"matchScore": score, "engine": shadow, "preview": preview, "_preview": pv}


def system_metrics(owner: dict, results: dict) -> dict:
    """Metrics of one system over the ads where it has a level and a number."""
    ids = [j for j, (lv, num) in results.items() if lv is not None and num is not None]
    pairs = [(owner[j], results[j][0]) for j in ids]
    c = confusion(pairs)
    return {"n": len(ids), "exact": c["exact"], "withinOne": c["withinOne"], "over": c["over"], "under": c["under"],
            "spearman": None if len(ids) < 3 else (round(spearman([float(owner[j]) for j in ids], [float(results[j][1]) for j in ids]), 2)),
            "levels": dict(sorted(Counter(lv for lv, _ in (results[j] for j in ids)).items())),
            "noEstimate": len(results) - len(ids)}


def ad_report(frozen: dict, ads: dict, rows: dict, sections: dict, split: str) -> dict:
    report = {}
    for mode in MODES:
        ids = [j for j, e in ads.items() if e["mode"] == mode and j in frozen["ads"] and split in ("all", frozen["ads"][j]["split"])]
        owner = {j: frozen["ads"][j]["overall"] for j in ids}
        per = {j: ad_systems(ads[j], rows.get(j), sections) for j in ids}
        systems = {name: system_metrics(owner, {j: per[j][name] for j in ids}) for name in ("matchScore", "engine", "preview")}
        pv = [per[j]["_preview"] for j in ids]
        floor = {j: (0, ap.fit_of(ads[j]["output"]["requirements"], sections, "zero")) for j in ids}
        ceil = {j: (0, ap.fit_of(ads[j]["output"]["requirements"], sections, "full")) for j in ids}
        weighted = {j: (0, (p["fit"] or 0) * p["confidence"]) for j, p in zip(ids, pv)}
        rank = lambda r: system_metrics(owner, r)["spearman"]
        report[mode] = {
            "ads": len(ids), "systems": systems,
            "previewDetail": {
                "labels": dict(Counter(p["label"] for p in pv)),
                "confidenceMedian": _median([p["confidence"] for p in pv]), "confidenceBelowHalf": sum(1 for p in pv if p["confidence"] < 0.5),
                "adsWithUnconfirmedMusts": sum(1 for p in pv if p["unconfirmedMusts"]),
                "unconfirmedMustsMedian": _median([p["unconfirmedMusts"] for p in pv]),
                "criticalUnconfirmedAds": sum(1 for p in pv if p["criticalUnconfirmed"]),
                "heldAtCheckFirst": sum(1 for j, p in zip(ids, pv) if p["bucket"] != ads[j].get("bucket", "apply")),
                "contradictedRequirements": sum(p["contradicted"] for p in pv),
                "rangeWidthMedian": _median([p["fitRange"][1] - p["fitRange"][0] for p in pv if None not in p["fitRange"]]),
                "spearmanIfSilenceCountedAsZero (information only, not a shown score)": rank(floor),
                "spearmanIfSilenceCountedAsFull (information only)": rank(ceil),
                "spearmanOfFitTimesConfidence (a possible list order, not a score)": rank(weighted),
            },
        }
    return report


def line_rows(frozen: dict, sample: dict, split: str) -> dict:
    items = {i["itemId"]: i for i in sample["items"]}
    out = {m: [] for m in MODES}
    for item_id, line in frozen["lines"].items():
        if split != "all" and line["split"] != split:
            continue
        item = items[item_id]
        out[line["mode"]].append({"item": {**item, "probe": line["probe"]}, "first": line["first"], "line": line})
    return out


def line_report(frozen: dict, sample: dict, sections: dict, split: str) -> dict:
    report = {}
    for mode, rows in line_rows(frozen, sample, split).items():
        musts = [r for r in rows if not r["item"]["probe"]]
        real = [r for r in musts if r["first"]["isMust"] == "yes"]
        typed = Counter()
        for r in real:
            status = ap.typed_status({"status": r["item"]["verdict"]["status"], "kind": r["item"]["kind"]}, sections)
            typed[(status, r["first"]["meets"])] += 1
        harmful = sum(n for (s, m), n in typed.items() if s == ap.CONTRADICTED and m in ("yes", "partial"))
        report[mode] = {
            "mustLines": len(musts), "precision": _precision(musts) if musts else None, "verdictAgreement": agreement(musts) if musts else None,
            "newTyping": {"contradictedButOwnerMeetsIt (fit-lowering error)": harmful,
                          "contradictedAndOwnerDoesNot": typed[(ap.CONTRADICTED, "no")],
                          "notEvidencedOwnerMeetsIt": typed[(ap.NOT_EVIDENCED, "yes")] + typed[(ap.NOT_EVIDENCED, "partial")],
                          "notEvidencedOwnerDoesNot (missed contradiction)": typed[(ap.NOT_EVIDENCED, "no")],
                          "realMusts": len(real)},
            "probeLines": len([r for r in rows if r["item"]["probe"]]),
        }
    return report


def build(out: Path, split: str = "all", sections: dict | None = None) -> dict:
    frozen = load(out)
    sections = profile_sections() if sections is None else sections
    ads = (_load(out / "engine-shadow.json") or {}).get("ads") or {}
    rows = {r["jobId"]: r for r in ((_load(out / "rescored" / "scored_jobs.json") or {}).get("jobs") or [])}
    sample = _load(out / "must-sample.json")
    return {"split": split, "counts": frozen["counts"], "caveat": CAVEAT, "labelFilesChangedSinceFreeze": drift(out, frozen),
            "sections": sections, "ads": ad_report(frozen, ads, rows, sections, split), "lines": line_report(frozen, sample, sections, split)}


def render(report: dict) -> list[str]:
    c = report["counts"]
    lines = [f"EVAL REPORT, split = {report['split']}  (frozen set: {c['ads']} ads {c['adsBySplit']}, {c['lines']} lines {c['linesBySplit']})",
             f"CAVEAT: {report['caveat']}",
             "profile sections the closed-world rule can use (entries): " + ", ".join(f"{k} {v}" for k, v in report["sections"].items())]
    if report["labelFilesChangedSinceFreeze"]:
        lines.append("WARNING: live label files changed since the freeze: " + ", ".join(report["labelFilesChangedSinceFreeze"]))
    for mode in MODES:
        a = report["ads"][mode]
        tag = "[what production would show]" if mode == MODES[0] else "[DIAGNOSTIC ONLY: production would skip these ads]"
        lines.append(f"\n== {mode.upper()} {tag}: {a['ads']} ads")
        for name in ("matchScore", "engine", "preview"):
            s = a["systems"][name]
            lines.append(f"  {name:10} n {s['n']:2}  Spearman {s['spearman']}  exact {s['exact']}  within one {s['withinOne']}  over {s['over']}  under {s['under']}  "
                         f"levels {s['levels']}" + (f"  no estimate {s['noEstimate']}" if s["noEstimate"] else ""))
        d = a["previewDetail"]
        lines.append(f"  preview labels {d['labels']}; confidence median {d['confidenceMedian']}, below 0.5 on {d['confidenceBelowHalf']} ads; "
                     f"ads with unconfirmed musts {d['adsWithUnconfirmedMusts']} (median {d['unconfirmedMustsMedian']} per ad); "
                     f"critical unconfirmed on {d['criticalUnconfirmedAds']} ads (held at check_first {d['heldAtCheckFirst']}); "
                     f"contradicted requirements {d['contradictedRequirements']}; fit range width median {d['rangeWidthMedian']}")
        lines.append("  Spearman if silence were counted as zero / as full (information only): "
                     f"{d['spearmanIfSilenceCountedAsZero (information only, not a shown score)']} / {d['spearmanIfSilenceCountedAsFull (information only)']}; "
                     f"fit x confidence as a list order: {d['spearmanOfFitTimesConfidence (a possible list order, not a score)']}")
    for mode in MODES:
        r = report["lines"][mode]
        lines.append(f"\n-- lines, {mode}: {r['mustLines']} must lines, {r['probeLines']} probe lines")
        if r["precision"]:
            p, v, t = r["precision"], r["verdictAgreement"], r["newTyping"]
            lines.append(f"  must precision {p['really_must']}/{p['answered']} = {p['precision']}; false-must {p['nice_to_have'] + p['not_a_requirement']}")
            lines.append(f"  verdict agreement (real musts) exact {v['exact']}/{v['items']}; engine MISSING but owner meets it {v['engineMissingButOwnerMeetsIt']}")
            lines.append("  new typing on the real musts: " + "; ".join(f"{k} {n}" for k, n in t.items()))
    return lines


def main(argv=None) -> int:
    ap_ = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap_.add_argument("--split", choices=("all", "dev", "test"), default="all")
    ap_.add_argument("--out", type=Path, default=STAGE_DIR)
    args = ap_.parse_args(argv)
    print("\n".join(render(build(args.out, args.split))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
