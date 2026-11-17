#!/usr/bin/env python3
"""holdout-v2: a pre-registered, stratified draw of 20 open ads for a blind owner rating. Read-only; no model call.

    .venv/bin/python scripts/select_holdout_v2.py [--data-dir DIR] [--seed N] [--selection OUT.json] [--sheet OUT.md]

The rule (written into the selection file too), fixed before anything is looked at:

  * Pool: the open list = rows of data/jobs/discovered_jobs.json that are not closed and not hand-entered.
  * Excluded: the 45 frozen labelled ads (data/calibration/stage-a/eval-set.json), holdout-v1's 20 ads
    (holdout-ids.json), extract-selection-1's 100 ads, and ads whose description is empty or whitespace.
  * Strata by PUBLIC TITLE only (case-insensitive substring, first match wins): "product" (7); else "program" / "project" /
    "delivery" (7); else other (6).
  * Draw inside a stratum: rank the stratum's ads by sha256("<seed>:<jobId>") and take the first k. No score, rank, cap, band,
    facts, group or any other row field is read for the draw, and the rule does not depend on the Python RNG version.
  * If a stratum has fewer ads than its quota the script stops and reports the counts; it writes nothing.

Writes (mode 600) the selection file and a blind rating sheet in shuffled order (the same hash ranking, another salt).
The sheet holds id, public title, company and ad URL; no score, band, cap or group.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_common as mc  # noqa: E402

DEFAULT_SEED = 20261117
QUOTAS = (("product", 7), ("program_project_delivery", 7), ("other", 6))
PRODUCT_WORDS = ("product",)
DELIVERY_WORDS = ("program", "project", "delivery")
EVAL = mc.EVAL_DIR
LABELLED_PATH = Path("calibration/stage-a/eval-set.json")  # under the data dir
RULE_TEXT = __doc__.split("The rule (written into the selection file too), fixed before anything is looked at:")[1].split("Writes (mode 600)")[0].strip()


def title_class(title: str | None) -> str:
    low = (title or "").lower()
    if any(w in low for w in PRODUCT_WORDS):
        return "product"
    if any(w in low for w in DELIVERY_WORDS):
        return "program_project_delivery"
    return "other"


def rank_key(seed: int, job_id: str, salt: str = "") -> str:
    return hashlib.sha256(f"{salt}{seed}:{job_id}".encode()).hexdigest()


def open_pool(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not r.get("isClosed") and not r.get("manualEntry")]


def candidates(rows: list[dict], excluded: set) -> tuple[list[dict], dict]:
    """(eligible open rows, counts of what was left out and why). Reasons are checked in this order."""
    why = {"closed_or_manual": 0, "excluded_id": 0, "empty_description": 0}
    out = []
    for r in rows:
        if r.get("isClosed") or r.get("manualEntry"):
            why["closed_or_manual"] += 1
        elif r.get("jobId") in excluded:
            why["excluded_id"] += 1
        elif not str(r.get("description") or "").strip():
            why["empty_description"] += 1
        else:
            out.append(r)
    return out, why


def draw(cands: list[dict], seed: int) -> tuple[dict, dict]:
    """({stratum: [rows]}, {stratum: available}). Raises ValueError naming the short stratum."""
    avail = {name: [] for name, _ in QUOTAS}
    for r in cands:
        avail[title_class(r.get("title"))].append(r)
    counts = {k: len(v) for k, v in avail.items()}
    short = {name: (counts[name], quota) for name, quota in QUOTAS if counts[name] < quota}
    if short:
        raise ValueError(f"stratum too small (available, needed): {short}; all strata available: {counts}")
    chosen = {name: sorted(avail[name], key=lambda r: rank_key(seed, r["jobId"]))[:quota] for name, quota in QUOTAS}
    return chosen, counts


def sheet_order(ids: list[str], seed: int) -> list[str]:
    return sorted(ids, key=lambda i: rank_key(seed, i, salt="sheet:"))


def render_sheet(rows_by_id: dict, order: list[str]) -> str:
    out = ["# Holdout v2 — blind rating sheet", "",
           "Rate before any Holojob output is looked at. Fill the empty columns. Rank 1 = best fit, 20 = worst; verdict is "
           "apply / maybe / skip; eligibility is clear / barrier stated / unclear; mark cannot-tell if the ad cannot be judged "
           "without reading it in full.", "",
           "| # | id | title | company | ad URL | fit verdict | rank 1-20 | eligibility | cannot tell without reading | one-line reason |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for n, i in enumerate(order, 1):
        r = rows_by_id[i]
        cell = lambda v: str(v or "").replace("|", "/").replace("\n", " ")  # noqa: E731
        out.append(f"| {n} | {i} | {cell(r.get('title'))} | {cell(r.get('company'))} | {cell(r.get('jobUrl'))} |  |  |  |  |  |")
    out += ["", "## Success criterion", "", "(Owner: write the criterion here before any comparison is run. Left empty on purpose.)", ""]
    return "\n".join(out)


def read_ids(path: Path) -> list[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = data.get("ids") if isinstance(data, dict) else data
    return [i if isinstance(i, str) else (i.get("id") or i.get("jobId")) for i in ids or []]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data-dir", type=Path, default=None)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--selection", type=Path, default=EVAL / "holdout-v2-selection.json")
    p.add_argument("--sheet", type=Path, default=EVAL / "holdout-v2-rating-sheet.md")
    p.add_argument("--labelled", type=Path, default=None, help="default <data-dir>/calibration/stage-a/eval-set.json")
    p.add_argument("--holdout-v1", type=Path, default=EVAL / "holdout-ids.json")
    p.add_argument("--extract-selection", type=Path, default=EVAL / "extract-selection-1.json")
    args = p.parse_args(argv)

    data_dir = args.data_dir or mc.default_data_dir()
    doc = json.loads((data_dir / "jobs" / "discovered_jobs.json").read_text(encoding="utf-8"))
    rows = doc["jobs"] if isinstance(doc, dict) else doc
    labelled = set(json.loads((args.labelled or data_dir / LABELLED_PATH).read_text(encoding="utf-8"))["ads"])
    v1 = set(read_ids(args.holdout_v1))
    ex1 = set(read_ids(args.extract_selection))
    excluded = labelled | v1 | ex1

    cands, why = candidates(rows, excluded)
    try:
        chosen, avail = draw(cands, args.seed)
    except ValueError as exc:
        print(f"stopped, nothing written: {exc}", file=sys.stderr)
        return 1

    ids = [r["jobId"] for stratum in chosen.values() for r in stratum]
    by_id = {r["jobId"]: r for stratum in chosen.values() for r in stratum}
    selection = {
        "version": 1, "seed": args.seed, "rule": RULE_TEXT,
        "drawMethod": "per stratum, ascending sha256('<seed>:<jobId>'), first k",
        "pool": {"openRows": len(open_pool(rows)), "eligibleAfterExclusions": len(cands), "leftOut": why,
                 "excludedLists": {"labelled45": len(labelled), "holdoutV1": len(v1), "extractSelection1": len(ex1), "unionIds": len(excluded)}},
        "availablePerStratum": avail,
        "countsPerStratum": {name: len(chosen[name]) for name, _ in QUOTAS},
        "strata": {name: [r["jobId"] for r in chosen[name]] for name, _ in QUOTAS},
        "ids": ids,
        "idsSha256": hashlib.sha256(json.dumps(ids).encode()).hexdigest(),
        "idsSha256Of": "json.dumps(ids) with ids in the order listed (strata in the order product, program_project_delivery, other)",
    }
    mc.write_private(args.selection, json.dumps(selection, indent=1) + "\n")
    mc.write_private(args.sheet, render_sheet(by_id, sheet_order(ids, args.seed)))
    print(json.dumps({k: selection[k] for k in ("seed", "pool", "availablePerStratum", "countsPerStratum", "idsSha256")}, indent=1))
    for name, _ in QUOTAS:
        for r in chosen[name]:
            print(f"{name:26} {r['jobId']}  {r.get('title')}")
    print(f"wrote {args.selection} and {args.sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
