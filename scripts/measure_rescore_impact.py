#!/usr/bin/env python3
"""Package B, item 2: re-score impact. Compares a baseline against the current tree's Re-score. No model call; read-only.

    .venv/bin/python scripts/measure_rescore_impact.py --baseline FILE [--current scored_jobs.json] [--data-dir DIR] [--json]

--baseline   a frozen snapshot (measure_baseline.py --save) or any scored_jobs.json. Reuse it in a later package by freezing
             a snapshot BEFORE the change and diffing after it; the stored scored_jobs.json is not a stable baseline because the
             owner can regenerate it.
--current    a scored_jobs.json (or snapshot) to compare with; default is a fresh Re-score of this tree (measure_common.rescore).

Reports counts of ads with a changed score and a changed band, their ids and public titles (never a manual ad's title), and
names what differs between the two runs' stamps (scoring version, intelligence, discovery list) so a non-zero difference can
be read as "code changed" or "inputs changed".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_common as mc  # noqa: E402


def compare(baseline: dict, current: dict) -> dict:
    """baseline / current: {jobId: row snapshot} (measure_common.snapshot_rows)."""
    both = sorted(set(baseline) & set(current))
    score_changed = [i for i in both if baseline[i]["score"] != current[i]["score"]]
    band_changed = [i for i in both if baseline[i]["band"] != current[i]["band"]]
    cap_changed = [i for i in both if baseline[i]["capsFired"] != current[i]["capsFired"]]
    deltas = mc.tally(current[i]["score"] - baseline[i]["score"] for i in score_changed
                      if isinstance(baseline[i]["score"], (int, float)) and isinstance(current[i]["score"], (int, float)))
    moves = mc.tally(f"{baseline[i]['band']} -> {current[i]['band']}" for i in band_changed)
    return {
        "compared": len(both), "onlyInBaseline": sorted(set(baseline) - set(current)), "onlyInCurrent": sorted(set(current) - set(baseline)),
        "scoreChanged": score_changed, "bandChanged": band_changed, "capsFiredChanged": cap_changed,
        "scoreDeltaCounts": dict(sorted(deltas.items())), "bandMoves": moves,
    }


def input_drift(stamp_a: dict, stamp_b: dict) -> list[str]:
    """What differs between the two runs' inputs and code, from the stamps only."""
    notes = []
    for label, key in (("scoringVersion", "scoringVersion"), ("intelligence", "intelligenceGeneratedAt"), ("discovery list", "discoveryGeneratedAt")):
        a, b = (stamp_a or {}).get(key), (stamp_b or {}).get(key)
        if a is not None and b is not None and a != b:
            notes.append(f"{label} differs: {a} vs {b}")
    return notes


def render(result: dict, titles: dict, drift: list[str], heading: str = "## 2. Re-score impact (baseline vs current tree)") -> list[str]:
    out = [heading, ""]
    out.append(f"Compared {result['compared']} ads present in both. Only in baseline: {len(result['onlyInBaseline'])}; only in current: {len(result['onlyInCurrent'])}.")
    out += ["", "Input / code differences between the two runs: " + (
        "; ".join(drift) if drift else "none visible in the stamps (a non-zero diff then comes from the code, or from term rarity moving with the corpus, by up to about 2 points)") + ".", ""]
    out += [f"- ads with a **changed score**: {len(result['scoreChanged'])}",
            f"- ads with a **changed band**: {len(result['bandChanged'])}",
            f"- ads whose set of fired caps changed: {len(result['capsFiredChanged'])}", ""]
    if result["scoreDeltaCounts"]:
        out += ["Score change (new minus old): " + ", ".join(f"{d:+d}: {n}" for d, n in result["scoreDeltaCounts"].items()), ""]
    if result["bandMoves"]:
        out += ["Band moves: " + "; ".join(f"{m}: {n}" for m, n in result["bandMoves"].items()), ""]
    for title, key in (("Ids with a changed score", "scoreChanged"), ("Ids with a changed band", "bandChanged")):
        ids = result[key]
        out += [f"**{title}** ({len(ids)})", ""]
        out += [f"- `{i}` {titles.get(i) or ''}".rstrip() for i in ids] or ["- none"]
        out.append("")
    return out


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
        cur_stamp = cur["stamp"].get("currentRun") or cur["stamp"].get("meta") or {}
    else:
        doc = mc.rescore(args.data_dir or mc.default_data_dir())
        cur = {"rows": mc.snapshot_rows(doc["jobs"]),
               "titles": {j["jobId"]: (None if j.get("manualEntry") else j.get("title")) for j in doc["jobs"]}}
        cur_stamp = mc.meta_stamp(doc["meta"])
    base_stamp = base["stamp"].get("currentRun") or base["stamp"].get("meta") or {}
    result = compare(base["rows"], cur["rows"])
    titles = {**(base.get("titles") or {}), **(cur.get("titles") or {})}
    drift = input_drift(base_stamp, cur_stamp)
    print(json.dumps({**result, "drift": drift}, indent=1) if args.json else "\n".join(render(result, titles, drift)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
