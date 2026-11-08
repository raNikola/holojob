#!/usr/bin/env python3
"""Dry run of the three-tier role filter over the ads the old filter dropped. Counts only; nothing is written.

    .venv/bin/python scripts/role-tier-dryrun.py [--jobs-dir data/jobs]

Reads data/jobs/filtered_ads.json (every ad a filter dropped: source, title, reason) and re-classifies each ad that the role
filter dropped (reason `title_excluded:*` or `title_not_matched`) with role_filter.role_tier. The file keeps neither the board's
own position nor the run's search terms, so the board position and extra search terms are taken as empty: a position-based
Target or a search-term Near is not counted here, and the numbers are a lower bound. No title is printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python" / "job_discovery"))

from providers import role_filter  # noqa: E402


def classify(ads: dict) -> dict:
    """{(source, old reason): Counter of new tiers} for the ads the role filter dropped."""
    table: dict[tuple[str, str], Counter] = {}
    for ad in ads.values():
        reason = str(ad.get("reason") or "")
        if not (reason.startswith("title_excluded:") or reason == "title_not_matched"):
            continue
        tier, _ = role_filter.role_tier(ad.get("title") or "", "", ())
        table.setdefault((str(ad.get("source") or "?"), reason), Counter())[tier] += 1
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--jobs-dir", default=str(ROOT / "data" / "jobs"))
    args = parser.parse_args()
    path = Path(args.jobs_dir) / "filtered_ads.json"
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read {path.name}: {type(exc).__name__}")
        return 1
    table = classify(store.get("ads") or {})
    total = Counter()
    by_source: dict[str, Counter] = {}
    print("source | old reason | -> target | near | excluded (still dropped)")
    for (source, reason), tiers in sorted(table.items()):
        print(f"{source} | {reason} | {tiers[role_filter.TARGET]} | {tiers[role_filter.NEAR]} | {tiers[role_filter.EXCLUDED]}")
        total.update(tiers)
        by_source.setdefault(source, Counter()).update(tiers)
    dropped = sum(total.values())
    print(f"\nrole-filter drops re-classified: {dropped}")
    print(f"change tier (now kept): near={total[role_filter.NEAR]} target={total[role_filter.TARGET]}; still excluded={total[role_filter.EXCLUDED]}")
    for source, tiers in sorted(by_source.items()):
        print(f"  {source}: {sum(tiers.values())} dropped before, {tiers[role_filter.NEAR] + tiers[role_filter.TARGET]} kept now")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
