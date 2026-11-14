#!/usr/bin/env python3
"""Pick the ads the next paid extraction should read: counts, ids and public ad titles only.

    .venv/bin/python scripts/select-extraction-ads.py --scored RESCORED.json --applied-ids IDS.txt --out SEL.json [--top 100]

Open rows of a scored file (made by a local re-score on a copy, so every row carries `scoreBeforeCaps`) that enrichment would still
read: not closed or hand-entered, not rejected (data/jobs/job-state.json), not applied (an id file from
scripts/export-application-job-ids.js), no facts on the row or in the ledger for its current content, and not outside the allowed
places. Ranked by scoreBeforeCaps (then matchScore, then id). Writes {"ids": [...]} with mode 600. Reads, never writes, data/.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("job_scoring", ""):
    sys.path.insert(0, str(ROOT / "python" / sub) if sub else str(ROOT / "python"))
import job_history  # noqa: E402
import row_state  # noqa: E402
from job_fingerprint import job_fingerprint  # noqa: E402
from work_authorization import outside_allowed_before_enrichment  # noqa: E402


def rejected_ids(state: dict) -> set:
    return {e["jobId"] for e in (state.get("jobs") or {}).values() if e.get("status") == "rejected" and e.get("jobId")}


def select(rows, ledger, prefs, excluded, top):
    """(chosen rows, counts of what was left out and why)."""
    why = {"closed_or_manual": 0, "rejected_or_applied": 0, "has_facts": 0, "outside_allowed": 0}
    ranked = []
    for job in rows:
        if job.get("isClosed") or job.get("manualEntry") or row_state.not_found(job):
            why["closed_or_manual"] += 1
        elif job.get("jobId") in excluded:
            why["rejected_or_applied"] += 1
        elif (job.get("llmFacts") or {}).get("_fingerprint") == job_fingerprint(job) or job_history.facts_for(ledger, job):
            why["has_facts"] += 1
        elif outside_allowed_before_enrichment(job, prefs):
            why["outside_allowed"] += 1
        else:
            ranked.append(job)
    ranked.sort(key=lambda j: (-(j.get("scoreBeforeCaps") or 0), -(j.get("matchScore") or 0), str(j.get("jobId"))))
    return ranked[:top], len(ranked), why


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scored", type=Path, required=True)
    ap.add_argument("--applied-ids", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--data-root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    rows = json.loads(a.scored.read_text(encoding="utf-8"))["jobs"]
    if not all("scoreBeforeCaps" in r for r in rows):
        print("a row has no scoreBeforeCaps: re-score a copy first", file=sys.stderr)
        return 1
    data = a.data_root / "data"
    ledger = job_history.load(data / "jobs/job_history.json")
    prefs = (json.loads((data / "intelligence/candidate-intelligence.json").read_text(encoding="utf-8")).get("jobFitPreferences")) or {}
    state_file = data / "jobs/job-state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    applied = {l.strip() for l in a.applied_ids.read_text().splitlines() if l.strip() and not l.startswith("#")}
    chosen, eligible, why = select(rows, ledger, prefs, applied | rejected_ids(state), a.top)
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"ids": [j["jobId"] for j in chosen], "rankedBy": "scoreBeforeCaps"}, fh, indent=1)
    os.chmod(a.out, 0o600)
    print(f"rows {len(rows)}, eligible {eligible}, left out {why}, selected {len(chosen)}")
    if chosen:
        print(f"scoreBeforeCaps {chosen[0]['scoreBeforeCaps']} .. {chosen[-1]['scoreBeforeCaps']}; "
              f"matchScore {min(j['matchScore'] for j in chosen)} .. {max(j['matchScore'] for j in chosen)}")
    for rank, j in enumerate(chosen[:10], 1):
        print(f"{rank:>3}  {j['scoreBeforeCaps']:>5}  {j['matchScore']:>3}  {(j.get('title') or '')[:70]} | {(j.get('company') or '')[:30]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
