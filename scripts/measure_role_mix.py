#!/usr/bin/env python3
"""Role-mix validation, step 2 (offline, no model): Role Fit from the responsibilities of the extract-7 read, against the owner's holdout-v1 verdicts.

    .venv/bin/python scripts/measure_role_mix.py [--scratch DIR] [--ratings FILE] [--ids FILE]

Reads <scratch>/extract7/facts.json (written by scripts/measure_holdout_extract7.py, the owner's paid read). Responsibility text stays in
that scratch file: this prints, per ad, the role-mix counts, the cue families that fired (counts) and the owner's verdict and driver
tags from the ratings file, never a responsibility, a quote or a reason. It puts no role/domain label on any skip.

Pre-registered pass bar (~/holojob-eval/w4-plan.md section 5, written before anything ran): Role Fit must place each READABLE APPLY ad
(a defined, not-insufficient Role Fit; Monzo has an empty description: Not read, not counted as a failure) STRICTLY above every ad in BAR_SKIP_IDS.
BAR_SKIP_IDS = the FIT-skip ads whose owner reason names a software-engineering or non-PM role: Nebius only. The other FIT skips are TPM/PM
ads whose stated gap is domain or qualification: the role mix is not expected to separate them, and they are listed as "not separable by
role mix", never as failures. A tie is a fail. If Nebius or an APPLY ad has no defined Role Fit the bar is "not evaluable", never a pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import measure_common as mc  # noqa: E402
import measure_holdout_compare as hc  # noqa: E402
from match_engine.role_mix import role_mix  # noqa: E402

DEFAULT_SCRATCH = mc.EVAL_DIR / "holdout-scratch-data"
DEFAULT_RATINGS = mc.EVAL_DIR / "holdout-ratings-v1-2026-11-17.md"
DEFAULT_IDS = mc.EVAL_DIR / "holdout-ids-18.json"
BAR_SKIP_IDS = ("2fa17cc182518736",)  # Nebius: the owner's reason names a hands-on engineering role, outside the PM path


def evaluate_bar(mixes: dict, apply_ids: list[str], bar_skip_ids=BAR_SKIP_IDS) -> dict:
    """mixes: {jobId: role_mix(...) or None (not read)}. {"verdict": pass|fail|not evaluable, "readable", "unreadable", "belowOrTied"}."""
    def value(i):
        m = mixes.get(i)
        return m["roleFit"] if m and m["available"] and not m["insufficient"] else None
    readable = [i for i in apply_ids if value(i) is not None]
    unreadable = [i for i in apply_ids if value(i) is None]
    skip_values = {i: value(i) for i in bar_skip_ids}
    if not readable or any(v is None for v in skip_values.values()):
        return {"verdict": "not evaluable", "readable": readable, "unreadable": unreadable, "belowOrTied": []}
    bad = [(a, s) for a in readable for s in bar_skip_ids if not value(a) > skip_values[s]]
    return {"verdict": "fail" if bad else "pass", "readable": readable, "unreadable": unreadable, "belowOrTied": bad}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH)
    p.add_argument("--ratings", type=Path, default=DEFAULT_RATINGS)
    p.add_argument("--ids", type=Path, default=DEFAULT_IDS)
    args = p.parse_args(argv)
    path = args.scratch / "extract7" / "facts.json"
    if not path.exists():
        print(f"no {path}: run scripts/measure_holdout_extract7.py --confirm first (the owner's paid read)", file=sys.stderr)
        return 2
    facts = json.loads(path.read_text(encoding="utf-8"))["facts"]
    ratings, crit = hc.parse_ratings(args.ratings.read_text(encoding="utf-8"))
    fit_skip = hc.fit_skip_ids(crit["items"][2], ratings)
    mixes = {r["id"]: (role_mix(facts[r["id"]]["responsibilities"]) if r["id"] in facts else None) for r in ratings}
    print("| rank | verdict | driver | id | company / title | responsibilities | classified | product | program | engineering | operations | ambiguous | unclassified | Role Fit | insufficient |")
    print("|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in ratings:
        m = mixes[r["id"]]
        if m is None:
            print(f"| {r['rank']} | {r['verdict']} | {r['driver']} | `{r['id']}` | {r['name']} | Not read | | | | | | | | | |")
            continue
        c = m["counts"]
        print(f"| {r['rank']} | {r['verdict']} | {r['driver']} | `{r['id']}` | {r['name']} | {m['total']} | {m['classified']} | {c['product']} | {c['program']} | "
              f"{c['engineering']} | {c['operations']} | {c['ambiguous']} | {c['unclassified']} | {m['roleFit'] if m['available'] else 'not available'} | "
              f"{'YES ' + '; '.join(m['reasons']) if m['insufficient'] else 'no'} |")
    print("\ncues fired (responsibilities in which the family fired), per ad:")
    for r in ratings:
        if mixes[r["id"]]:
            print(f"  {r['id']}: {mixes[r['id']]['cuesFired']}")
    apply_ids = [r["id"] for r in ratings if r["verdict"] == "apply"]
    bar = evaluate_bar(mixes, apply_ids)
    print(f"\npre-registered bar (APPLY strictly above {', '.join(BAR_SKIP_IDS)}): **{bar['verdict'].upper()}**; readable APPLY {bar['readable']}; "
          f"unreadable {bar['unreadable']}; at or below the bar skip: {bar['belowOrTied']}")
    others = [i for i in fit_skip if i not in BAR_SKIP_IDS]
    print(f"FIT skips the role mix is not expected to separate (domain or qualification gaps; not counted as failures): {', '.join(others)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
