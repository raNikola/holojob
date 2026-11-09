#!/usr/bin/env python3
"""Read-only: which generated documents under data/resumes have a passing fact-gate verdict, and which must be checked again.

Prints counts and job ids only (no file contents, no names, no paths of the owner's). Deletes and changes nothing. A document
without a verdict is not deleted; it cannot be attached to an application until it is generated again (Phase 4).

Usage: .venv/bin/python scripts/inspect-document-verdicts.py [--root DIR]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python" / "resume_generator"))
sys.path.insert(0, str(ROOT / "python" / "job_scoring"))

import verdicts  # noqa: E402

def inspect(resumes_root: Path) -> tuple[Counter, dict[str, list[str]]]:
    counts: Counter = Counter()
    jobs_by_status: dict[str, list[str]] = {}
    for folder in sorted(p for p in resumes_root.iterdir() if p.is_dir()) if resumes_root.is_dir() else []:
        seen = set()
        for file in sorted(folder.iterdir()):
            if file.is_file() and verdicts.is_document(file.name):
                state = verdicts.status(folder, file.name)
                counts[state] += 1
                seen.add(state)
        for state in seen - {"verified"}:
            jobs_by_status.setdefault(state, []).append(folder.name)
    return counts, jobs_by_status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT / "data" / "resumes")
    args = parser.parse_args()
    counts, jobs = inspect(args.root)
    print(f"documents: {sum(counts.values())}")
    for state in ("verified", "missing", "changed", "old_gate", "failed"):
        print(f"  {state}: {counts.get(state, 0)}")
    for state in ("missing", "changed", "old_gate", "failed"):
        if jobs.get(state):
            print(f"jobs with a {state} document ({len(jobs[state])}): {', '.join(jobs[state])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
