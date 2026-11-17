#!/usr/bin/env python3
"""Package B, item 1: the baseline snapshot. Read-only; no model call; counts only.

    .venv/bin/python scripts/measure_baseline.py [--data-dir DIR] [--save PATH] [--json]

Measures the current tree by running the Re-score path in memory (measure_common.rescore) and also the stored
scored_jobs.json next to it, so a stored file that predates the current code is visible rather than assumed equal.
--save writes the frozen snapshot (id -> score, band, caps; mode 600) that measure_rescore_impact.py later diffs against.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_common as mc  # noqa: E402
from job_fingerprint import job_fingerprint  # noqa: E402

TIE_GROUPS = 10


def facts_state(row: dict) -> str:
    """read: facts present and for this exact ad text; stale: facts present but for other text; absent: no facts."""
    facts = row.get("llmFacts")
    if not facts:
        return "absent"
    return "read" if facts.get("_fingerprint") == job_fingerprint(row) else "stale"


def snapshot(rows: list[dict], meta: dict) -> dict:
    """Every count of item 1 for one set of scored rows."""
    rated = [r for r in rows if r.get("dataStatus") not in mc.NOT_READ_STATUSES]
    fired, binding = {c: 0 for c in mc.CAP_ORDER}, {c: 0 for c in mc.CAP_ORDER}
    for row in rows:
        f, b = mc.caps_of(row)
        for name in f:
            fired[name] += 1
        for name in b:
            binding[name] += 1
    scores = mc.tally(r.get("matchScore") for r in rated)
    ties = sorted(scores.items(), key=lambda kv: (-kv[1], -kv[0]))[:TIE_GROUPS]
    before = mc.tally(r.get("scoreBeforeCaps") for r in rated)
    ties_before = sorted(before.items(), key=lambda kv: (-kv[1], -kv[0]))[:TIE_GROUPS]
    statuses = [mc.auth_of(r).get("status") for r in rows]
    silent = [r for r in rows if mc.auth_of(r).get("status") == "needs_visa_silent"]
    return {
        "adsTotal": len(rows),
        "adsByScoringVersion": {str(meta.get("scoringVersion")): len(rows)},  # the version is stored once per file, never per row
        "bands": mc.tally(mc.band_of(r) for r in rows),
        "ratedAds": len(rated),
        "largestTieGroups": [{"score": s, "count": n} for s, n in ties],
        "largestTieGroupsBeforeCaps": [{"score": s, "count": n} for s, n in ties_before],
        "capsFired": {k: v for k, v in fired.items()},
        "capsBinding": {k: v for k, v in binding.items()},
        "workAuthorizationStatus": mc.tally(statuses),
        "readBasis": mc.tally(mc.auth_of(r).get("basis") or "(no basis field)" for r in rows),
        "notRead": sum(1 for r in rows if mc.auth_of(r).get("basis") == "not_read"),
        "insufficientData": sum(1 for r in rows if r.get("dataStatus") in mc.NOT_READ_STATUSES),
        "silentVisa": {"total": len(silent), "byBasis": mc.tally(mc.auth_of(r).get("basis") or "(no basis field)" for r in silent)},
        "extractionFacts": mc.tally(facts_state(r) for r in rows),
        "aiEnrichmentField": mc.tally(r.get("aiEnrichment") or "(unset)" for r in rows),
        "confidence": mc.tally((r.get("confidence") or {}).get("level") for r in rows),
    }


def build(data_dir: Path) -> dict:
    stored_doc = mc.load_scored(data_dir / "jobs" / "scored_jobs.json")
    stored_meta = stored_doc.get("meta") or {}
    current_doc = mc.rescore(data_dir)
    current_meta = current_doc.get("meta") or {}
    return {
        "stamp": {
            **mc.git_stamp(), "scoringVersion": current_meta.get("scoringVersion"),
            "takenAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "storedFile": mc.meta_stamp(stored_meta), "currentRun": mc.meta_stamp(current_meta),
            "storedRowsWithBasisField": sum(1 for r in stored_doc["jobs"] if "basis" in mc.auth_of(r)),
        },
        "stored": snapshot(stored_doc["jobs"], stored_meta),
        "current": snapshot(current_doc["jobs"], current_meta),
        "rows": mc.snapshot_rows(current_doc["jobs"]),
        "titles": {j["jobId"]: (None if j.get("manualEntry") else j.get("title")) for j in current_doc["jobs"]},
    }


def render(result: dict) -> list[str]:
    stamp, out = result["stamp"], []
    out += ["## 1. Baseline snapshot", "",
            f"Commit `{stamp['commit']}`{' (working tree has uncommitted changes)' if stamp['dirty'] else ''}; current scoringVersion "
            f"**{stamp['scoringVersion']}**; taken {stamp['takenAt']}.", "",
            f"Stored `scored_jobs.json`: scoringVersion {stamp['storedFile']['scoringVersion']}, generated {stamp['storedFile']['generatedAt']}, "
            f"{stamp['storedFile']['jobCount']} ads, {stamp['storedRowsWithBasisField']} of them carry the read-basis field (written by 1.4 code). "
            f"Inputs stored: intelligence {stamp['storedFile']['intelligenceGeneratedAt']}, discovery {stamp['storedFile']['discoveryGeneratedAt']}. "
            f"Inputs now: intelligence {stamp['currentRun']['intelligenceGeneratedAt']}, discovery {stamp['currentRun']['discoveryGeneratedAt']}.", "",
            "Columns: **stored** = the file on disk as the owner left it; **current tree** = a Re-score of this commit (no model call, cached "
            "judgements re-applied). Counts of the current-tree column are the baseline later packages compare against.", ""]
    s, c = result["stored"], result["current"]

    def row(label, a, b):
        return f"| {label} | {a} | {b} |"

    def table(title, key, order=None, fmt=lambda v: v):
        keys = order or sorted(set(s[key]) | set(c[key]), key=str)
        lines = [f"**{title}**", "", "| | stored | current tree |", "|---|---:|---:|"]
        lines += [row(k, s[key].get(k, 0), c[key].get(k, 0)) for k in keys]
        return lines + [""]

    out += ["**Totals**", "", "| | stored | current tree |", "|---|---:|---:|",
            row("ads total", s["adsTotal"], c["adsTotal"]),
            row("ads by scoringVersion", json.dumps(s["adsByScoringVersion"]), json.dumps(c["adsByScoringVersion"])),
            row("rated ads (not insufficient data)", s["ratedAds"], c["ratedAds"]), ""]
    bands = ["Excellent", "Strong", "Good", "Weak", "Reject", mc.INSUFFICIENT, mc.NOT_READ]
    out += table("Score bands (labels; insufficient data is a state, not a band)", "bands", bands + [b for b in set(s["bands"]) | set(c["bands"]) if b not in bands])
    for title, key in (("Largest tie groups, final score, rated ads (score: count)", "largestTieGroups"),
                       ("Largest tie groups, score before caps, rated ads (score: count)", "largestTieGroupsBeforeCaps")):
        out += [f"**{title}**", "", "| rank | stored | current tree |", "|---:|---|---|"]
        for i in range(TIE_GROUPS):
            a = s[key][i] if i < len(s[key]) else None
            b = c[key][i] if i < len(c[key]) else None
            if a is None and b is None:
                break
            cell = lambda g: f"{g['score']}: {g['count']}" if g else ""  # noqa: E731
            out.append(f"| {i + 1} | {cell(a)} | {cell(b)} |")
        out.append("")
    out += ["**Caps** (fired = the rule applies to the ad; binding = the final score sits at that cap, below the score before caps)", "",
            "| cap (lowers to) | stored fired | stored binding | current fired | current binding |", "|---|---:|---:|---:|---:|"]
    for name in mc.CAP_ORDER:
        value = f" ({mc.CAP_VALUES[name]})"
        out.append(f"| {name}{value} | {s['capsFired'][name]} | {s['capsBinding'][name]} | {c['capsFired'][name]} | {c['capsBinding'][name]} |")
    out += ["", "Cap values are read from `scorer.py`; the red-flag cap (54) only applies above 55. Insufficient-data rows are counted by state "
            "(their score is clamped to 5 and scoreBeforeCaps with it). Caps can fire together on one ad, so the rows do not add to a total.", ""]
    out += table("Work authorisation status (all ads)", "workAuthorizationStatus")
    out += table("Read basis of the visa check (ad_read: the extraction read the ad; not_read: no facts, every visa statement unverified)", "readBasis")
    out += ["**Named counts**", "", "| | stored | current tree |", "|---|---:|---:|",
            row("not_read", s["notRead"], c["notRead"]),
            row("insufficient data", s["insufficientData"], c["insufficientData"]),
            row("silent visa (needs_visa_silent), all", s["silentVisa"]["total"], c["silentVisa"]["total"])]
    for basis in sorted(set(s["silentVisa"]["byBasis"]) | set(c["silentVisa"]["byBasis"])):
        out.append(row(f"&nbsp;&nbsp;of which basis {basis}", s["silentVisa"]["byBasis"].get(basis, 0), c["silentVisa"]["byBasis"].get(basis, 0)))
    out += [""]
    out += table("Extraction status (facts on the ad: read = for this exact text, stale = for older text, absent = never read)", "extractionFacts", ["read", "stale", "absent"])
    out += table("`aiEnrichment` field (set only when scoring found the facts missing)", "aiEnrichmentField")
    out += table("Confidence level", "confidence")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data-dir", type=Path, default=None)
    p.add_argument("--save", type=Path, default=None, help="write the frozen snapshot here (mode 600)")
    p.add_argument("--json", action="store_true", help="print the counts as JSON instead of markdown")
    args = p.parse_args(argv)
    result = build(args.data_dir or mc.default_data_dir())
    if args.save:
        mc.write_private(args.save, json.dumps(result, indent=1, sort_keys=True))
    print(json.dumps({k: v for k, v in result.items() if k in ("stamp", "stored", "current")}, indent=1) if args.json else "\n".join(render(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
