#!/usr/bin/env python3
"""Step 2 impact: which ads a change moved, and whether each belongs to the class the change was meant to touch.

    .venv/bin/python scripts/measure_step2_impact.py --baseline SNAPSHOT [--current SNAPSHOT_OR_SCORED] [--data-dir DIR] [--json]

Compares a frozen baseline (measure_baseline.py --save, taken BEFORE the change) with the current tree's Re-score
(no model call, read-only; measure_common.rescore) or a second snapshot. Every ad whose score, band, read status or
eligibility changed is classified from the FROZEN snapshot's own `capsFired`:

  visa_or_language   the baseline row carried a visa cap (25 / 40 / 45) or the language cap
  insufficient_data  the baseline row was in the 1.4 "Insufficient data" state (cap 5)
  other              anything else: a change outside the intended classes. The tool exits 1 when there is one.

Prints counts, ids, public ad titles (never a manual ad's), a histogram of score deltas and band moves. No threshold or
weight suggestion is made. No ad text, profile or CV value is read into the output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_common as mc  # noqa: E402
import measure_rescore_impact as impact  # noqa: E402

VISA_OR_LANGUAGE = "visa_or_language"
INSUFFICIENT = "insufficient_data"
OTHER = "other"


def classify(baseline_row: dict) -> str:
    caps = set(baseline_row.get("capsFired") or [])
    if any(c.startswith("visa:") or c == "language" for c in caps):
        return VISA_OR_LANGUAGE
    if "insufficient_data" in caps:
        return INSUFFICIENT
    return OTHER


def changed_ids(baseline: dict, current: dict) -> list[str]:
    both = sorted(set(baseline) & set(current))
    keys = ("score", "band", "dataStatus")
    return [i for i in both if any(baseline[i].get(k) != current[i].get(k) for k in keys)]


# Caps that still exist in 1.5 and can lower a score (names as measure_common.caps_of writes them).
STILL_CAPS = ("red_flag", "off_track", "unrelated_title")


def explain(baseline: dict, current: dict) -> dict:
    """The discriminating check: nothing may move an ad's score except a removed cap.

    1. `scoreBeforeCaps` must be the same in both runs (a judge adjustment on a row no cap lowered shifts it by that amount: accepted
       and counted); the old "Insufficient data" rows were clamped to 5 and are skipped.
    2. Every changed ad's new score must equal the old scoreBeforeCaps lowered only by the caps still firing in the NEW row
       (red flag, off-track, unrelated title, no profile stack). The rest is a cached fit-judge adjustment, counted and listed apart:
       the judge may lift an ad that is no longer hardCapped. Anything else is `unexplained`: a stop.
    """
    out = {"sbcChanged": [], "explainedByCaps": 0, "judgeExplained": [], "unexplained": [], "oldInsufficientSkipped": 0, "newNotRead": []}
    for i in sorted(set(baseline) & set(current)):
        b, c = baseline[i], current[i]
        if b.get("dataStatus") in mc.NOT_READ_STATUSES:
            out["oldInsufficientSkipped"] += 1
            continue
        if c.get("dataStatus") == "not_read":
            out["newNotRead"].append(i)
            continue
        adj = c.get("judgeAdjustment") or 0
        if c.get("scoreBeforeCaps") != b.get("scoreBeforeCaps") and not (adj and c.get("scoreBeforeCaps") - adj == b.get("scoreBeforeCaps")):
            out["sbcChanged"].append(i)
        if b.get("score") == c.get("score") and b.get("band") == c.get("band"):
            continue
        caps = [mc.CAP_VALUES[n] for n in c.get("capsFired") or [] if n in STILL_CAPS]
        if c.get("profileGuard") == "no_profile_stack":
            caps.append(50)
        expected = min([b["scoreBeforeCaps"], *caps])
        if c["score"] == expected:
            out["explainedByCaps"] += 1
        elif adj and (c["score"] - adj == expected or c["score"] == min(expected, expected + adj) or c["score"] == expected + adj):
            out["judgeExplained"].append(i)
        else:
            out["unexplained"].append(i)
    return out


def run(baseline: dict, current: dict) -> dict:
    ids = changed_ids(baseline, current)
    classes: dict[str, list[str]] = {VISA_OR_LANGUAGE: [], INSUFFICIENT: [], OTHER: []}
    for i in ids:
        classes[classify(baseline[i])].append(i)
    compared = impact.compare(baseline, current)
    explained = explain(baseline, current)
    return {"compared": compared["compared"], "changed": len(ids), "classes": {k: len(v) for k, v in classes.items()}, "explain": explained,
            "otherIds": classes[OTHER], "scoreDeltaCounts": compared["scoreDeltaCounts"], "bandMoves": compared["bandMoves"],
            "onlyInBaseline": compared["onlyInBaseline"], "onlyInCurrent": compared["onlyInCurrent"]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--current", type=Path, default=None)
    p.add_argument("--data-dir", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    base = mc.read_snapshot(args.baseline)
    if args.current:
        cur = mc.read_snapshot(args.current)
    else:
        doc = mc.rescore(args.data_dir or mc.default_data_dir())
        cur = {"rows": mc.snapshot_rows(doc["jobs"]), "titles": {j["jobId"]: (None if j.get("manualEntry") else j.get("title")) for j in doc["jobs"]}}
    result = run(base["rows"], cur["rows"])
    titles = {**(base.get("titles") or {}), **(cur.get("titles") or {})}
    result["otherTitles"] = {i: titles.get(i) for i in result["otherIds"]}
    print(json.dumps(result, indent=1))
    return 1 if result["otherIds"] or result["explain"]["unexplained"] or result["explain"]["sbcChanged"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
