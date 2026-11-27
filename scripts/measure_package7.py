#!/usr/bin/env python3
"""Package 7 measurement: the repost counter on the real ledger (counts only; no model call, no network, no write).

Reports, per window, how many ledger ads sit in a repost group and how many groups there are, plus the SimHash note pairs.
Ids and counts only: no title or company.
Usage: .venv/bin/python scripts/measure_package7.py [--data DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python" / "job_scoring"))
import repost_counter as rc  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="/srv/holojob/data")
    args = parser.parse_args()
    ledger = json.loads((Path(args.data) / "jobs" / "job_history.json").read_text(encoding="utf-8")).get("jobs") or {}
    print("ledger ads:", len(ledger))
    for window in (30, 90, 180):
        result = rc.count_reposts(ledger, window_days=window)
        sizes = sorted((g["count"] for g in result["groups"]), reverse=True)
        print("window", window, "d: groups", len(result["groups"]), ", ads in a group", len(result["repostsOf"]), ", largest", sizes[:5])
    full = rc.count_reposts(ledger, with_similar=True)
    grouped = {i for g in full["groups"] for i in g["ids"]}
    both = sum(1 for a, b in full["similarText"] if a in grouped and b in grouped)
    print("simhash note pairs:", len(full["similarText"]), "; both ads in a repost group:", both)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
