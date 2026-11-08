#!/usr/bin/env python3
"""Per-category yield of Infostud's listing. Read-only; counts only; writes nothing. Owner-run (it reads the public site).

    .venv/bin/python scripts/infostud-coverage-probe.py [--no-combined] [--terms "product manager,..."]

For each of the six categories discovery reads, it fetches that category alone and counts how many of its ads pass the role filter
(Target, Near) and why the rest are dropped; then it fetches the one combined query discovery uses and says whether the two agree.
It changes nothing: no category is added or removed because of one probe. Read it again over several runs before deciding.
About 1.5 s per page, 7 reads: a few minutes. No ad title or link is printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python" / "job_discovery"))

from providers import infostud_client, infostud_probe  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--no-combined", action="store_true", help="skip the read of the combined query")
    parser.add_argument("--terms", default="", help="comma separated search terms, as the role filter gets them from the profile")
    args = parser.parse_args()
    terms = tuple(t.strip() for t in args.terms.split(",") if t.strip())

    per_category = {}
    for category in infostud_client.DEFAULT_CATEGORIES:
        raw, reported = infostud_client.fetch_raw((category,))
        per_category[category] = ([infostud_client.normalize(r) for r in raw], reported)
        print(f"read category {category} ({infostud_client.CATEGORIES[category]}): {len(raw)} of {reported}", file=sys.stderr)
    combined = None
    if not args.no_combined:
        raw, reported = infostud_client.fetch_raw(infostud_client.DEFAULT_CATEGORIES)
        combined = ([infostud_client.normalize(r) for r in raw], reported)
    result = infostud_probe.summarize(per_category, terms, combined)
    labelled = {f"{c} {infostud_client.CATEGORIES[c]}": v for c, v in result["categories"].items()}
    print(json.dumps({**result, "categories": labelled}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
