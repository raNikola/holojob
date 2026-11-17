#!/usr/bin/env python3
"""Package B, item 3: gate confusion on the owner's 45 labelled ads. Counts only. Regression use only.

    .venv/bin/python scripts/measure_gate_confusion.py [--data-dir DIR] [--scored FILE] [--json]

Cross-tabulates what the system says about an ad against what the owner labelled, using the FROZEN label set
(data/calibration/stage-a/eval-set.json, never the live label files):

  * eligibility (pass / unknown / fail)  x  owner `hardRequirements`
  * eligibility                          x  owner `overall`
  * score band (insufficient data apart) x  owner `overall`

Eligibility is the worst of the work-authorisation, location and language gates (match_engine.gates, the same functions the
engine and calibration use). If the profile cannot be read it falls back to the scorer's own work-authorisation status and says so.

This tool measures; it suggests no threshold and tunes nothing. The 45 ads are a small, purpose-chosen sample labelled by one
person: read every cell with its n.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_common as mc  # noqa: E402

ELIGIBILITY_GATES = ("work_authorization", "location", "language")
RANK = {"pass": 0, "unknown": 1, "fail": 2}
FALLBACK = {"authorized": "pass", "sponsored": "pass", "unknown": "unknown", "needs_visa_silent": "unknown",
            "needs_visa_refused": "fail", "outside_allowed": "fail"}


def load_candidate(data_dir: Path):
    """The engine's candidate (gates), built read-only from the profile, intelligence and confirmed facts; None if unreadable."""
    try:
        import confirmed_facts
        from evidence_index import build_candidate
        profile = json.loads((data_dir / "profile" / "candidate-profile.json").read_text(encoding="utf-8"))
        intelligence = json.loads((data_dir / "intelligence" / "candidate-intelligence.json").read_text(encoding="utf-8"))
        return build_candidate(profile, intelligence, confirmed_facts.load(data_dir / "profile" / "confirmed-facts.json"))
    except (OSError, ValueError, ImportError, KeyError, TypeError):
        return None


def eligibility(row: dict, candidate) -> tuple[str, dict]:
    """(worst gate result, {gate: result}) for one scored row."""
    if candidate is None:
        verdict = FALLBACK.get(mc.auth_of(row).get("status"), "unknown")
        return verdict, {"work_authorization_status": verdict}
    from match_engine import gates
    reqs = (row.get("llmFacts") or {}).get("requirements")
    results = {g["gate"]: g["result"] for g in gates.gate_results(row, candidate, None, reqs)}
    per = {g: results[g] for g in ELIGIBILITY_GATES}
    return max(per.values(), key=RANK.__getitem__), per


def system_band(row: dict) -> str:
    return mc.INSUFFICIENT if row.get("dataStatus") in mc.NOT_READ_STATUSES else mc.band_of(row)


def crosstab(pairs: list[tuple[str, str]], rows_order: list[str], cols_order: list[str]) -> dict:
    cells = {(r, c): 0 for r in rows_order for c in cols_order}
    for r, c in pairs:
        cells[(r, c)] = cells.get((r, c), 0) + 1
    return {"rows": rows_order, "cols": cols_order, "cells": {f"{r}|{c}": n for (r, c), n in cells.items()}}


def build(frozen: dict, rows_by_id: dict, candidate) -> dict:
    labelled = frozen["ads"]
    present = sorted(i for i in labelled if i in rows_by_id)
    missing = sorted(i for i in labelled if i not in rows_by_id)
    elig, per_gate, bands = {}, {}, {}
    for i in present:
        elig[i], per_gate[i] = eligibility(rows_by_id[i], candidate)
        bands[i] = system_band(rows_by_id[i])
    hard_values = sorted({labelled[i]["hardRequirements"] for i in present}, key=str)
    overall_values = sorted({labelled[i]["overall"] for i in present})
    band_order = ["Excellent", "Strong", "Good", "Weak", "Reject", mc.INSUFFICIENT, mc.NOT_READ]
    gate_tables = {g: mc.tally(per_gate[i].get(g) for i in present if g in per_gate[i]) for g in ELIGIBILITY_GATES}
    return {
        "labelled": len(labelled), "present": len(present), "missingIds": missing,
        "scoredFromLedger": sum(1 for i in present if rows_by_id[i].get("keptRescore")),
        "eligibilityBasis": "gates" if candidate is not None else "work-authorisation status only (profile unreadable)",
        "eligibilityByGate": gate_tables,
        "eligibilityVsHardRequirements": crosstab([(elig[i], str(labelled[i]["hardRequirements"])) for i in present],
                                                  ["pass", "unknown", "fail"], [str(v) for v in hard_values]),
        "eligibilityVsOverall": crosstab([(elig[i], str(labelled[i]["overall"])) for i in present],
                                         ["pass", "unknown", "fail"], [str(v) for v in overall_values]),
        "bandVsOverall": crosstab([(bands[i], str(labelled[i]["overall"])) for i in present], band_order, [str(v) for v in overall_values]),
    }


def _table(title: str, ct: dict, row_label: str, col_label: str) -> list[str]:
    head = f"| {row_label} \\ {col_label} | " + " | ".join(ct["cols"]) + " | total |"
    out = [f"**{title}**", "", head, "|---|" + "---:|" * (len(ct["cols"]) + 1)]
    for r in ct["rows"]:
        vals = [ct["cells"][f"{r}|{c}"] for c in ct["cols"]]
        out.append(f"| {r} | " + " | ".join(str(v) for v in vals) + f" | {sum(vals)} |")
    totals = [sum(ct["cells"][f"{r}|{c}"] for r in ct["rows"]) for c in ct["cols"]]
    out.append("| total | " + " | ".join(str(t) for t in totals) + f" | {sum(totals)} |")
    return out + [""]


def render(result: dict, heading: str = "## 3. Gate confusion on the owner's labelled ads") -> list[str]:
    out = [heading, "",
           f"{result['present']} of the {result['labelled']} frozen labelled ads were scored"
           + (f"; not found anywhere (ids): {', '.join(f'`{i}`' for i in result['missingIds'])}" if result["missingIds"] else "")
           + f". {result['scoredFromLedger']} of them have left the job list and were scored from the history ledger the way a kept ad is "
           "(outside the term-rarity corpus, so no other ad's score moves; the stored extraction facts on the ledger entry are carried since the ledger_row fix, so their visa check is `ad_read` where the ledger holds facts).",
           f"Eligibility basis: {result['eligibilityBasis']}. Regression use only: a cell is a count, not a target; no threshold is suggested. "
           "Small, purpose-chosen sample, one labeller.", ""]
    for gate, counts in result["eligibilityByGate"].items():
        out.append(f"- gate `{gate}`: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    out.append("")
    out += _table("Eligibility (rows: system) x owner hardRequirements (columns)", result["eligibilityVsHardRequirements"], "system", "owner")
    out += _table("Eligibility (rows: system) x owner overall level (columns)", result["eligibilityVsOverall"], "system", "owner")
    out += _table("Score band (rows: system) x owner overall level (columns)", result["bandVsOverall"], "system", "owner")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data-dir", type=Path, default=None)
    p.add_argument("--scored", type=Path, default=None, help="use this scored_jobs.json instead of a fresh Re-score of this tree")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    data_dir = args.data_dir or mc.default_data_dir()
    frozen = json.loads((data_dir / "calibration" / "stage-a" / "eval-set.json").read_text(encoding="utf-8"))
    # Labelled ads that have left the job list are scored from the ledger (as a kept ad is), so none is dropped silently.
    doc = mc.load_scored(args.scored) if args.scored else mc.rescore(data_dir, extra_ids=set(frozen["ads"]))
    result = build(frozen, {j["jobId"]: j for j in doc["jobs"]}, load_candidate(data_dir))
    print(json.dumps(result, indent=1) if args.json else "\n".join(render(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
