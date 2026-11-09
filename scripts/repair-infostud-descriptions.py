#!/usr/bin/env python3
"""Fetch the full text of Infostud ads stored with a cut-off description. A DRY RUN unless --apply. The owner runs --apply; nothing else calls this.

    .venv/bin/python scripts/repair-infostud-descriptions.py            # dry run: counts only, no request is made
    .venv/bin/python scripts/repair-infostud-descriptions.py --apply    # only after reading it; at most --limit (default 20) polite requests

--apply takes the pipeline lock, backs the ledger up to data/backups/infostud-description-<time>/ (git-ignored, 700 / 600), reads each ad's
public detail page once (no retry, delay with jitter, stops at 403 / 429 / 503), and stores the text with its status. Ads whose text
changed lose their cached requirement facts, so the next scoring run reads them again. Re-run Re-score afterwards. Counts only are printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for part in ("python/job_discovery", "python/job_scoring", "python"):
    sys.path.insert(0, str(ROOT / part))

import infostud_repair as repair  # noqa: E402


def main(argv=None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, default=repair.DEFAULT_LIMIT, help="most ads to fetch in one run (default 20)")
    parser.add_argument("--delay", type=float, default=repair.DEFAULT_DELAY, help="seconds between requests (default 3, plus jitter)")
    parser.add_argument("--apply", action="store_true", help="fetch and write (dry run without it)")
    args = parser.parse_args(argv)
    if args.delay < 1:
        parser.error("--delay must be at least 1 second")
    print(json.dumps(repair.repair(root, limit=args.limit, delay=args.delay, apply=args.apply), indent=2))
    if not args.apply:
        print("DRY RUN: nothing was fetched or changed.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
