#!/usr/bin/env python3
"""List-cleanup follow-up: how reliable is "Strong", and where would other thresholds put the owner's ads. Read only.

No model call, no network, no write, no copy of data: the real files are opened in place, only counts, job ids and scores are printed
(no title, company or text). The Active list's groups come from the screen's own code (`scripts/list-active-groups.js`) and the owner's
statuses from `scripts/list-owner-states.js` (both through `scripts/node-sandbox`), or from files passed with --active-json / --states-json.

  a. Strong by engine coverage. Order in `run_scoring`: scorer caps, role ceiling (54), then the engine ceiling (69, only for an ad with
     an engine answer). Every other cap is 54 or lower, so an ad the engine ceiling lowered had no other cap and its `scoreBeforeCaps` is
     its score just before the engine answer. The ceiling's reason ("Capped: N of M must requirements ...") marks the rows it lowered. A
     "before engine" score of 70+ with an answer is therefore either kept (no unmet share) or lowered to 69. For an ad with no answer
     (`not_evaluated`) the data holds no answer, so what the answer would have done is unknown.
  b. The two title-side caps: unrelated title (40) and off-track "project_delivery" (50): rows capped, and the owner's Applied / Saved /
     Rejected / Keep ads among them, with the score before the cap.
  c. Strong threshold 70 / 75 / 80 against the owner's statuses: lowest and median final score of Applied and Saved ads; per threshold,
     how many of the Active Strong group stay Strong and how many Applied / Saved ads stay or are lost. Measurement only.

Usage: .venv/bin/python scripts/measure_strong_reliability.py [--active-json FILE] [--states-json FILE]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path("/srv/holojob/data")
ENGINE_CAP = re.compile(r"^Capped: \d+ of \d+ must requirements")
TITLE_CAP = re.compile(r"^Capped: the title matches no ")
OFF_TRACK = re.compile(r"^Capped: the ad describes (\S+),")
THRESHOLDS = (70, 75, 80)


def node_json(script: str, given: str | None):
    if given:
        return json.loads(Path(given).read_text(encoding="utf-8"))
    done = subprocess.run([str(ROOT / "scripts" / "node-sandbox"), "node", script], cwd=ROOT, capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(f"could not run {script}: {done.stderr.strip()[:200]}")
    return json.loads(done.stdout)


def num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def reasons_of(row: dict) -> list[str]:
    return [r for r in row.get("reasons") or [] if isinstance(r, str)]


def owner_sets(states: list) -> dict[str, set[str]]:
    sets: dict[str, set[str]] = {"Applied": set(), "Saved": set(), "Rejected": set(), "Keep": set()}
    for job_id, status, keep, applied in states:
        if applied or status == "applied_manually":
            sets["Applied"].add(job_id)
        if status == "saved":
            sets["Saved"].add(job_id)
        if status == "rejected":
            sets["Rejected"].add(job_id)
        if keep:
            sets["Keep"].add(job_id)
    return sets


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--active-json")
    ap.add_argument("--states-json")
    args = ap.parse_args()

    scored = {str(r.get("jobId")): r for r in json.loads((DATA / "jobs" / "scored_jobs.json").read_text(encoding="utf-8")).get("jobs") or [] if isinstance(r, dict)}
    active = node_json("scripts/list-active-groups.js", args.active_json)
    owner = owner_sets(node_json("scripts/list-owner-states.js", args.states_json))
    strong_ids = [i for i, g in active if g == "strong"]
    print(f"Active list: {len(active)} ads, Strong group {len(strong_ids)} (the population below), scored file {len(scored)} rows")
    print("Owner ads (all lists): " + ", ".join(f"{k} {len(v)}" for k, v in owner.items()) + "  <- small samples: read every owner figure as an anecdote")

    # ---- a
    print("\n== a. Strong by engine coverage (Active Strong group)")
    rows = [scored[i] for i in strong_ids if i in scored]
    cover = Counter((r.get("engineCoverage") or {}).get("status", "?") for r in rows)
    print(f"   {len(rows)} Strong rows with a stored row; engineCoverage: " + ", ".join(f"{k} {v}" for k, v in cover.most_common()))
    lowered_all = [(i, r) for i, r in scored.items() if any(ENGINE_CAP.match(x) for x in reasons_of(r))]
    print(f"   whole scored file: the engine ceiling lowered {len(lowered_all)} rows (all lists); those still in the Active Strong group: "
          f"{sum(1 for i, _ in lowered_all if i in set(strong_ids))} (a lowered row scores 69, so none is Strong)")
    answered = [r for r in scored.values() if (r.get("engineCoverage") or {}).get("status") == "answered" and num(r.get("scoreBeforeCaps")) is not None]
    pre70 = [r for r in answered if r["scoreBeforeCaps"] >= 70]
    fired = [r for r in pre70 if any(ENGINE_CAP.match(x) for x in reasons_of(r))]
    other = [r for r in fired if any(x.startswith("Capped:") and not ENGINE_CAP.match(x) for x in reasons_of(r))]
    print(f"   rows with an engine answer and a score of 70+ just before it: {len(pre70)}; the answer lowered {len(fired)} of them to 69 "
          f"({len(fired) / len(pre70):.1%})" if pre70 else "   no row with an engine answer and a pre-engine score of 70+")
    if fired:
        drops = [r["scoreBeforeCaps"] - 69 for r in fired]
        print(f"   size of the drop (before - 69): min {min(drops)}, median {statistics.median(drops)}, max {max(drops)}; fired rows that also carry another cap (should be 0): {len(other)}")
        print(f"   kept at 70+ by the answer: {len(pre70) - len(fired)}")
    unanswered = [r for r in scored.values() if (r.get("engineCoverage") or {}).get("status") == "not_evaluated" and num(r.get("matchScore")) is not None and r["matchScore"] >= 70]
    unanswered_strong = [r for r in unanswered if str(r.get("jobId")) in set(strong_ids)]
    print(f"   Strong rows with NO engine answer (not_evaluated): {len(unanswered_strong)} in the Active Strong group ({len(unanswered)} in the whole file). "
          "What an answer would do to them is unknown: the data holds no answer for them. The rate above comes only from ads that got one "
          "(engine fill picks Strong and Possible ads under a budget, so those are not a random sample).")
    not_app = [r for r in rows if (r.get("engineCoverage") or {}).get("status") == "not_applicable"]
    print(f"   Strong rows where the engine is not applicable (no requirements extracted / not read): {len(not_app)}")

    # rescore history: do the pre-rescore backups hold an earlier score for the same ad?
    backups = sorted((DATA / "backups" / "auto" / "scored_jobs.json").glob("*-pre-rescore.json"))
    print(f"   rescore history: {len(backups)} pre-rescore copies exist (last 3 kept); they hold scores of earlier scoring runs, not a separate 'before the engine' value, so scoreBeforeCaps is the only before-engine number")

    # ---- b
    print("\n== b. Title-side caps")
    tracks = Counter()
    for r in scored.values():
        for x in reasons_of(r):
            m = OFF_TRACK.match(x)
            if m:
                tracks[m.group(1)] += 1
    print("   off-track tracks in the scored file: " + (", ".join(f"{k} {v}" for k, v in tracks.most_common()) or "none"))
    rules = {
        "unrelated-title (40)": lambda r: any(TITLE_CAP.match(x) for x in reasons_of(r)),
        "off-track project_delivery (50)": lambda r: any((OFF_TRACK.match(x) or [None, None])[1] == "project_delivery" for x in reasons_of(r) if OFF_TRACK.match(x)),
    }
    active_ids = {i for i, _ in active}
    for name, hit in rules.items():
        capped = {i: r for i, r in scored.items() if hit(r)}
        print(f"   {name}: caps {len(capped)} rows in the scored file, {sum(1 for i in capped if i in active_ids)} of them in Active")
        for label, ids in owner.items():
            mine = sorted(i for i in ids if i in capped)
            print(f"      {label:9} {len(ids):3} ads, capped by this rule: {len(mine)}")
            for i in mine:
                print(f"         {i}  before cap {capped[i].get('scoreBeforeCaps')}, final {capped[i].get('matchScore')}")

    # ---- c
    print("\n== c. Strong threshold against the owner's statuses")
    for label in ("Applied", "Saved"):
        scores = sorted(s for i in owner[label] if (s := num((scored.get(i) or {}).get("matchScore"))) is not None)
        missing = len(owner[label]) - len(scores)
        if scores:
            print(f"   {label:7} {len(owner[label])} ads, {len(scores)} with a final score: lowest {scores[0]}, median {statistics.median(scores)}, highest {scores[-1]}"
                  + (f"; {missing} with no stored score" if missing else ""))
        else:
            print(f"   {label:7} {len(owner[label])} ads, none with a final score")
    pool = [num((scored.get(i) or {}).get("matchScore")) for i in strong_ids]
    pool = [s for s in pool if s is not None]
    both = owner["Applied"] | owner["Saved"]
    print(f"   {'threshold':>9} | Active Strong group stays | Applied+Saved ({len(both)}) stay Strong | lost | no score")
    for t in THRESHOLDS:
        stays = sum(1 for s in pool if s >= t)
        ss = [num((scored.get(i) or {}).get("matchScore")) for i in both]
        have = [s for s in ss if s is not None]
        kept = sum(1 for s in have if s >= t)
        print(f"   {t:>9} | {stays:5} of {len(pool)} ({stays / len(pool):.0%}) | {kept:3} | {len(have) - kept:3} | {len(ss) - len(have)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
