#!/usr/bin/env python3
"""List-cleanup brief, item 1: what the Active list holds after the latest scan, by tier, and what the paid steps did to it.

Read only. No model call, no network, no write, no copy of data: the real files are opened in place and only counts are printed (a job id
is never printed). The Active list and its groups come from the screen's own code (`scripts/list-active-groups.js`, run through
`scripts/node-sandbox`, or by podman with the same image as CLAUDE.md); the scored rows and the latest run record are read here.

  1. Active by group: Strong, Possible, Weak fit, Not read, and the rest (blocked, closed, not scored). Strong share against the baseline
     (Strong 413 of 966 in Active, about 43%): both as a share of every Active row and of the rated rows (Strong + Possible + Weak).
  2. The Not read rows: no row has a stored score (matchScore is null on all of them), so "high preliminary score" cannot be read off the
     data. What the data holds is the role class (Fit 3, paid) and whether the ad was read (llmFacts). So each Not read row is placed by
     the step that did not reach it, and the latest run's stop codes say whether a limit was hit (budget) or no limit was involved (the
     ad was not selected: reading takes Target / Adjacent ads only).
  3. Per tier: how many passed classification (a role class other than "not available"), reading (aiEnrichment is not "missing") and
     the engine fill (engineCoverage answered), and how many passed all three.
  4. Per tier: how many rows carry each cap (the reasons that start with "Capped:", plus the red-flag cap, which leaves no reason).

Usage: .venv/bin/python scripts/measure_list_tiers.py [--active-json FILE]   (FILE: the output of list-active-groups.js, instead of running it)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path("/srv/holojob/data")
BASELINE = (413, 966)
TIERS = ("strong", "possible", "weak")
CAP_RULES = (
    ("unrelated-title", re.compile(r"^Capped: the title matches no ")),
    ("role-ceiling (class other)", re.compile(r"^Capped: role class is ")),
    ("location scope", re.compile(r"^Capped: onsite or hybrid job outside")),
    ("no profile stack", re.compile(r"^Capped: no profile stack")),
    ("unmet musts (engine)", re.compile(r"^Capped: \d+ of \d+ must requirements")),
)
OFF_TRACK = re.compile(r"^Capped: the ad describes (\S+),")


def active_groups(path: str | None) -> list[list]:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    sandbox = ROOT / "scripts" / "node-sandbox"
    cmd = [str(sandbox), "node", "scripts/list-active-groups.js"]
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit("could not build the Active list (run scripts/list-active-groups.js and pass --active-json): " + done.stderr.strip()[:200])
    return json.loads(done.stdout)


def latest_run() -> dict:
    names = sorted(p for p in (DATA / "analytics" / "runs").glob("*.json") if not p.name.endswith(".events.jsonl"))
    return json.loads(names[-1].read_text(encoding="utf-8")) if names else {}


def cap_labels(row: dict) -> list[str]:
    out = []
    for reason in row.get("reasons") or []:
        if not isinstance(reason, str) or not reason.startswith("Capped:"):
            continue
        track = OFF_TRACK.match(reason)
        if track:
            out.append(f"off-track ({track.group(1)})")
            continue
        out.append(next((name for name, rule in CAP_RULES if rule.match(reason)), "other cap"))
    before, now = row.get("scoreBeforeCaps"), row.get("matchScore")
    if row.get("redFlags") and isinstance(before, (int, float)) and before > 55 and isinstance(now, (int, float)) and now <= 54:
        out.append("red flag (54)")
    return out


def passed(row: dict) -> dict[str, bool]:
    return {
        "classified": row.get("roleClass") not in (None, "not available"),
        "read": row.get("aiEnrichment") != "missing",
        "engine": (row.get("engineCoverage") or {}).get("status") == "answered",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--active-json", help="the output of scripts/list-active-groups.js")
    args = ap.parse_args()

    scored = {str(r.get("jobId")): r for r in json.loads((DATA / "jobs" / "scored_jobs.json").read_text(encoding="utf-8")).get("jobs") or [] if isinstance(r, dict)}
    active = active_groups(args.active_json)
    groups = Counter(group for _, group in active)
    total = len(active)
    rated = sum(groups[t] for t in TIERS)

    print(f"== 1. Active list: {total} ads")
    for group in (*TIERS, "notRead", "blocked", "closed", "unscored"):
        print(f"   {group:9} {groups[group]:5}  ({groups[group] / total:.1%} of Active)" if total else f"   {group}: 0")
    base_n, base_d = BASELINE
    strong = groups["strong"]
    print(f"   Strong share: {strong / total:.1%} of Active, {strong / rated:.1%} of rated rows ({rated}); baseline {base_n} of {base_d} = {base_n / base_d:.1%}")

    print("\n== 2. Not read rows")
    not_read = [(i, scored.get(i)) for i, g in active if g == "notRead"]
    in_file = [(i, r) for i, r in not_read if r]
    print(f"   {len(not_read)} in Active, {len(in_file)} with a scored row; stored matchScore on them: {sum(1 for _, r in in_file if r.get('matchScore') is not None)} (none: a preliminary score is not stored)")
    where = Counter()
    for _, row in in_file:
        cls, facts = row.get("roleClass"), row.get("aiEnrichment") != "missing"
        if cls in (None, "not available"):
            where["not classified (Fit 3 never reached it)"] += 1
        elif cls not in ("target", "adjacent"):
            where[f"classified '{cls}': reading takes Target / Adjacent only (not selected)"] += 1
        elif not facts:
            where["Target / Adjacent, not read yet (reading waiting or failed)"] += 1
        else:
            where["read, but still no usable text"] += 1
    for label, n in where.most_common():
        print(f"   {n:5}  {label}")
    run = latest_run()
    print(f"   latest run record: status {run.get('status')}, started {str(run.get('startedAt'))[:10]}")
    classification = run.get("classification")
    if isinstance(classification, dict):
        print("   classification: " + ", ".join(f"{k}={classification.get(k)}" for k in ("candidates", "classified", "left", "stopped", "maxAds") if k in classification))
    paid = run.get("paid")
    if isinstance(paid, dict):
        print(f"   paid steps: limits {paid.get('limits')}, waiting {paid.get('waiting')}")
        for group, steps in (paid.get("groups") or {}).items():
            for step, one in (steps or {}).items():
                if isinstance(one, dict):
                    print(f"     {group}/{step}: candidates {one.get('candidates')}, done {one.get('done')}, waiting {one.get('waiting')}, stopped {one.get('stopped')}")
    if not isinstance(classification, dict) and not isinstance(paid, dict):
        print("   the latest run record holds no paid-step block (a scan, not a Re-scrape): the stop codes are not recorded for it")

    print("\n== 3. Paid steps passed, per tier (classification / reading / engine fill / all three)")
    for tier in TIERS:
        rows = [scored[i] for i, g in active if g == tier and i in scored]
        flags = [passed(r) for r in rows]
        every = sum(1 for f in flags if all(f.values()))
        print(f"   {tier:9} {len(rows):5} with a scored row: classified {sum(f['classified'] for f in flags)}, read {sum(f['read'] for f in flags)}, "
              f"engine {sum(f['engine'] for f in flags)}, all three {every}")

    print("\n== 4. Caps per rule, by tier (a row can carry several)")
    table: dict[str, Counter] = defaultdict(Counter)
    for tier in TIERS:
        for i, g in active:
            if g == tier and i in scored:
                for label in set(cap_labels(scored[i])):
                    table[label][tier] += 1
    for label in sorted(table, key=lambda k: -sum(table[k].values())):
        counts = table[label]
        print(f"   {label:34} strong {counts['strong']:4}  possible {counts['possible']:4}  weak {counts['weak']:4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
