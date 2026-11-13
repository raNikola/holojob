#!/usr/bin/env python3
"""P1 Stage A report (read-only): the owner's confirmed labels against the system's score bands, the engine, and the AI.

    python python/calibration/report.py [--out DIR] [--extra NAME=scored_jobs.json ...]

The owner's labels (ran-labels.json) are the only ground truth; the AI proposals are compared against them, never the
other way round. Prints ids, public ad titles, levels, bands and counts only. Writes nothing.

Levels: the owner's `overall` 0-3 (0 not relevant, 1 weak option, 2 relevant, 3 strong) against the system's band:
Reject = 0, Weak = 1, Good = 2, Strong and Excellent = 3; the engine's label: Weak = 0, Partial = 1, Good = 2, Strong = 3
(Incomplete is left out and counted).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGE_DIR = ROOT / "data" / "calibration" / "stage-a"

BAND_LEVEL = {"Reject": 0, "Weak": 1, "Good": 2, "Strong": 3, "Excellent": 3}
ENGINE_LEVEL = {"Weak": 0, "Partial": 1, "Good": 2, "Strong": 3}
JUDGMENTS = (("functionFit", "function"), ("hardRequirements", "requirements"), ("overall", "overall"))


def _load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation with tied ranks averaged; None when fewer than 3 pairs or one side is constant."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx, vy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    return None if vx == 0 or vy == 0 else round(cov / (vx * vy) ** 0.5, 3)


def _cap(row: dict) -> str:
    for text in row.get("reasons") or []:
        if text.startswith("Capped:"):
            return ("title" if "title matches no" in text else "track" if "the ad describes" in text
                    else "language" if "the ad requires" in text else "authorization")
        if text.startswith("Red flag"):
            return "red_flag"
    return "none"


def _raw(row: dict, dim: str):
    return ((row.get("scoreBreakdown") or {}).get(dim) or {}).get("raw")


def error_category(label: dict, row: dict, system_level: int) -> str | None:
    """A mechanical reading of one disagreement from the owner's sub-judgments and the system's fields; not the owner's."""
    ran = label["overall"]
    if system_level == ran:
        return None
    if system_level > ran:
        if label["functionFit"] == "no":
            return "over: wrong kind of work scored high"
        if label["hardRequirements"] in ("no", "partial"):
            return "over: requirements not met, scored high"
        return "over: other"
    if label["functionFit"] in ("yes", "partial"):
        if _cap(row) == "title":
            return "under: unrelated-title cap on a relevant function"
        if _cap(row) == "authorization":
            return "under: authorization cap"
        if (_raw(row, "skillMatch") or 100) < 40 and label["functionFit"] == "yes":
            return "under: low keyword skill score on a relevant function"
    return "under: other"


def confusion(pairs: list[tuple[int, int]]) -> dict:
    """{ran level: {system level: n}} plus exact and within-one agreement."""
    matrix: dict[int, Counter] = defaultdict(Counter)
    for ran, system in pairs:
        matrix[ran][system] += 1
    n = len(pairs)
    return {
        "matrix": {r: {s: matrix[r][s] for s in range(4)} for r in range(4)},
        "n": n,
        "exact": sum(r == s for r, s in pairs),
        "withinOne": sum(abs(r - s) <= 1 for r, s in pairs),
        "over": sum(s > r for r, s in pairs),
        "under": sum(s < r for r, s in pairs),
        "irrelevantAtGoodOrAbove": sum(r == 0 and s >= 2 for r, s in pairs),
        "relevantAtWeakOrBelow": sum(r >= 2 and s <= 1 for r, s in pairs),
    }


def compare_system(labels: dict, rows: dict, level_of) -> dict:
    """The owner's labels against one scored file. `level_of(row)` is the system's 0-3 level or None (left out)."""
    pairs, scores, ran_levels, errors, left_out = [], [], [], defaultdict(list), []
    for job_id, label in labels.items():
        row = rows.get(job_id)
        level = level_of(row) if row else None
        if level is None:
            left_out.append(job_id)
            continue
        pairs.append((label["overall"], level))
        if row.get("matchScore") is not None:
            scores.append(row["matchScore"])
            ran_levels.append(label["overall"])
        category = error_category(label, row, level)
        if category:
            errors[category].append(job_id)
    result = confusion(pairs)
    result.update(spearman=spearman([float(x) for x in ran_levels], [float(x) for x in scores]) if len(scores) == len(ran_levels) else None,
                  errors={k: v for k, v in sorted(errors.items())}, leftOut=left_out)
    return result


def sub_judgment_views(labels: dict, rows: dict) -> dict:
    """How the system treated ads by the kind of problem the owner found (relevant function failing requirements vs wrong function)."""
    groups = {"wrong function": lambda lb: lb["functionFit"] == "no",
              "relevant function, requirements not met": lambda lb: lb["functionFit"] in ("yes", "partial") and lb["hardRequirements"] in ("no", "partial"),
              "relevant function, requirements met or unknown": lambda lb: lb["functionFit"] in ("yes", "partial") and lb["hardRequirements"] in ("yes", "unknown")}
    out = {}
    for name, test in groups.items():
        ids = [j for j, lb in labels.items() if test(lb) and j in rows]
        out[name] = {"n": len(ids), "systemBands": dict(Counter(rows[j].get("matchLabel") for j in ids)),
                     "unrelatedTitleCap": sum(_cap(rows[j]) == "title" for j in ids)}
    return out


def ai_agreement(labels: dict, proposals: dict) -> dict:
    """The AI proposal against the owner's label, per judgment. Only ads with a valid proposal and a label count."""
    both = [(labels[j], p) for j, p in proposals.items() if p.get("status") == "ok" and j in labels]
    result = {"n": len(both), "invalid": sum(p.get("status") == "invalid" for p in proposals.values()),
              "sources": dict(Counter(lb.get("source") for lb in labels.values()))}
    for field, name in JUDGMENTS:
        result[name] = round(sum(lb[field] == p[field] for lb, p in both) / len(both), 3) if both else None
    result["overallWithinOne"] = round(sum(abs(lb["overall"] - p["overall"]) <= 1 for lb, p in both) / len(both), 3) if both else None
    by_conf = defaultdict(list)
    for lb, p in both:
        by_conf[p.get("confidence")].append(lb["overall"] == p["overall"])
    result["overallAgreementByConfidence"] = {c: [sum(v), len(v)] for c, v in sorted(by_conf.items(), key=lambda kv: str(kv[0]))}
    return result


def build(out: Path, extra: dict[str, Path] | None = None) -> dict:
    labels_doc = _load(out / "ran-labels.json", {"labels": {}})
    labels = labels_doc.get("labels") or {}
    sample = _load(out / "sample.json", {"jobIds": []})
    proposals = (_load(out / "ai-proposals.json", {"proposals": {}}) or {}).get("proposals") or {}
    files = {"matchScore (re-score of the frozen baseline)": out / "rescored" / "scored_jobs.json", **(extra or {})}
    systems = {}
    for name, path in files.items():
        doc = _load(path)
        rows = {r["jobId"]: r for r in ((doc or {}).get("jobs") or []) if isinstance(r, dict) and r.get("jobId")}
        if not rows:
            systems[name] = None
            continue
        systems[name] = {
            "bands": compare_system(labels, rows, lambda r: BAND_LEVEL.get(r.get("matchLabel"))),
            "views": sub_judgment_views(labels, rows),
        }
        shadows = [r for r in rows.values() if isinstance(r.get("engineShadow"), dict) and r["engineShadow"].get("label")]
        if shadows:
            systems[name]["engine"] = compare_system(
                labels, rows, lambda r: ENGINE_LEVEL.get((r.get("engineShadow") or {}).get("label")))
            systems[name]["engineIncomplete"] = sum(r["engineShadow"]["label"] == "Incomplete" for r in shadows)
        else:
            systems[name]["engine"] = None
    titles = {}
    for doc_path in files.values():
        for r in ((_load(doc_path) or {}).get("jobs") or []):
            titles.setdefault(r.get("jobId"), r.get("title"))
    return {"sampleSize": len(sample.get("jobIds") or []), "labelled": len(labels), "revision": labels_doc.get("revision"),
            "systems": systems, "ai": ai_agreement(labels, proposals), "titles": titles,
            "holdout": "not drawn; excludes the sample by id and by title + company (sample.json: holdoutExclusions)"}


def _matrix_lines(c: dict) -> list[str]:
    lines = ["      system level:  0   1   2   3"]
    for ran in range(4):
        lines.append(f"  owner level {ran}:  " + "  ".join(f"{c['matrix'][ran][s]:>2}" for s in range(4)))
    return lines


def _compare_lines(title: str, c: dict, titles: dict) -> list[str]:
    n = c["n"]
    lines = [f"{title}: {n} ads compared, {len(c['leftOut'])} left out"]
    if not n:
        return lines
    lines += _matrix_lines(c)
    lines.append(f"  exact {c['exact']}/{n}, within one level {c['withinOne']}/{n}, over {c['over']}, under {c['under']}, "
                 f"owner-irrelevant at Good or above {c['irrelevantAtGoodOrAbove']}, owner-relevant at Weak or below "
                 f"{c['relevantAtWeakOrBelow']}, rank correlation (Spearman) {c['spearman']}")
    for category, ids in c["errors"].items():
        lines.append(f"  {category}: {len(ids)}  " + "; ".join(f"{j[:10]} {str(titles.get(j))[:40]}" for j in ids[:8]))
    return lines


def render(report: dict) -> list[str]:
    lines = [f"labelled {report['labelled']} of {report['sampleSize']} sampled ads (labels revision {report['revision']})"]
    if report["labelled"] == 0:
        return lines + ["no confirmed labels yet: nothing to compare"]
    for name, system in report["systems"].items():
        lines.append(f"\n== {name}")
        if system is None:
            lines.append("  file not found or empty")
            continue
        lines += _compare_lines("system band vs owner", system["bands"], report["titles"])
        for group, view in system["views"].items():
            lines.append(f"  {group}: {view['n']} ads; system bands {view['systemBands']}; unrelated-title cap on {view['unrelatedTitleCap']}")
        if system["engine"]:
            lines += _compare_lines("engine (shadow) vs owner", system["engine"], report["titles"])
            lines.append(f"  engine Incomplete: {system['engineIncomplete']}")
        else:
            lines.append("engine (shadow): not available in this file (no engineShadow on any ad)")
    ai = report["ai"]
    lines.append(f"\n== AI proposal vs owner ({ai['n']} ads with a valid proposal; {ai['invalid']} invalid answers)")
    lines.append(f"  label sources: {ai['sources']}")
    for _, name in JUDGMENTS:
        lines.append(f"  agreement on {name}: {ai[name]}")
    lines.append(f"  overall within one level: {ai['overallWithinOne']}; overall agreement by AI confidence [agree, total]: {ai['overallAgreementByConfidence']}")
    lines.append(f"\nholdout: {report['holdout']}")
    return lines


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", type=Path, default=STAGE_DIR)
    p.add_argument("--extra", action="append", default=[], metavar="NAME=FILE", help="another scored file to compare")
    args = p.parse_args(argv)
    extra = {n: Path(f) for n, _, f in (e.partition("=") for e in args.extra)}
    print("\n".join(render(build(args.out, extra))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
