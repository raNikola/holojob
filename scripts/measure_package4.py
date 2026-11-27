#!/usr/bin/env python3
"""Package 4 round-2 measurement: the text rules (language, years, on-site only, visa, employment type) replayed on the must-keep set
and the ledger. "Before" is the round-1 decision (`role_filter._title_decision`, same text); "after" is `role_filter.assess`.

No model call, no network, no write: real data is read-only. Output: counts, ids and public ad titles only.
Usage: HOLOJOB_APPLICATION_JOB_IDS=FILE .venv/bin/python scripts/measure_package4.py [--examples N]
Pattern: scripts/measure_package3.py.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_package3 as m3  # noqa: E402  (sets HOLOJOB_AI_DIR and the import paths)

rf = m3.rf
tr = rf.text_rules
FILTERED = m3.FILTERED_SOURCES


def decide(job: dict, terms: tuple):
    title, position, text = job.get("title") or "", job.get("standardizedPosition") or "", job.get("description") or ""
    return rf._title_decision(title, position, terms, text), rf.assess(title, position, terms, text)


def change(old, new) -> str:
    if (old.reason is None) == (new.reason is None):
        if new.labels != old.labels:
            return "kept, new label only" if new.reason is None else "dropped, new label only"
        return "unchanged"
    return "kept -> dropped" if new.reason else "dropped -> kept"


def rules_of(old, new) -> set:
    return {label.split(":")[0] for label in new.labels if label not in old.labels}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--examples", type=int, default=4)
    args = parser.parse_args()
    ledger = m3._read("jobs/job_history.json").get("jobs") or {}
    keep, note = m3.must_keep()
    keep = {k: v for k, v in keep.items() if not k.startswith("#")}  # the applied-ids file carries comment lines (hashes)
    terms = m3.search_terms()
    print("classes:", dict(tr.TEXT_RULE_CLASSES))
    print(f"must-keep ids: {len(keep)} ({Counter(s for v in keep.values() for s in v)}); {note}")

    # 1. Must-keep set: kept before and after, one count per ad.
    kept_before, kept_after, missing = [], [], []
    labels = Counter()
    for job_id in sorted(keep):
        entry = ledger.get(job_id)
        if entry is None:
            missing.append(job_id)
            continue
        old, new = decide(entry.get("job") or {}, ())
        if (entry.get("job") or {}).get("provider") not in FILTERED:  # greenhouse and ashby never call role_filter: kept
            old = new = rf.Decision(rf.TARGET, None, None)
        if old.reason is None:
            kept_before.append(job_id)
        if new.reason is None:
            kept_after.append(job_id)
        labels.update(rules_of(old, new))
    print("\n1. must-keep set (ledger ads; the rest never reach the role filter or are not in the ledger)")
    print(f"   in ledger: {len(keep) - len(missing)}, not in ledger: {len(missing)} {missing} (manual ads bypass the role filter: kept)")
    print(f"   kept before: {len(kept_before) + len(missing)} of {len(keep)} {kept_before + missing}")
    print(f"   kept after:  {len(kept_after) + len(missing)} of {len(keep)} {kept_after + missing}")
    print(f"   kept before, dropped after (STOP RULE if > 0): {sorted(set(kept_before) - set(kept_after))}")
    print(f"   new labels by rule: {dict(labels)}")

    # 2. Ledger ads of the title-filtered sources: decision change per rule and in total.
    total, per_rule, alone = Counter(), Counter(), Counter()
    examples: dict[str, list] = {}
    n = 0
    for entry in ledger.values():
        job = entry.get("job") or {}
        if job.get("provider") not in FILTERED:
            continue
        n += 1
        old, new = decide(job, terms)
        kind = change(old, new)
        total[kind] += 1
        fired = rules_of(old, new)
        for rule in fired:
            per_rule[rule] += 1
            examples.setdefault(rule, []).append(job.get("title"))
        if len(fired) == 1:
            alone[next(iter(fired))] += 1
    print(f"\n2. ledger ads of the title-filtered sources: {n} (search terms {len(terms)})")
    print("   decision change, total:", dict(total))
    print("   ads touched by each rule:", dict(per_rule))
    print("   ads touched by that rule alone:", dict(alone))
    for rule, titles in sorted(examples.items()):
        print(f"   examples {rule}: {titles[: args.examples]}")

    # 3. filtered_ads.json keeps no text: the text rules cannot run on a filtered row (unknown, no label). Reported as such.
    filtered = m3._read("jobs/filtered_ads.json").get("ads") or {}
    print(f"\n3. filtered rows: {len(filtered)}; they keep no ad text, so every text rule is unknown on them: 0 change decision")
    return 0


if __name__ == "__main__":
    sys.exit(main())
