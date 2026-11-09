#!/usr/bin/env python3
"""Remove old `older_key` rows from the job-history ledger. A DRY RUN unless --apply. The owner runs --apply; nothing else calls this.

    # 1. application job ids (Python may not read the store); an empty file is a valid list
    podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm \\
        node scripts/export-application-job-ids.js data/backups/application-job-ids.txt
    # 2. browser-only ids (Keep, statuses, AI insights, outreach, hand-entered jobs): see the console snippet in scripts/older-key-report.py
    # 3. the dry run: prints counts only
    .venv/bin/python scripts/prune-older-key.py --days 180 --application-job-ids data/backups/application-job-ids.txt --protect-ids data/backups/protect-ids.txt
    # 4. only after reading it:  the same command plus --apply

--days has no default: the window is the owner's decision (180 days recommended). --apply needs both id files, and the application ids must have been exported from the applications.json that is on disk at apply time
(the `# store-sha256` header is compared with the live file; any mismatch, a missing header or a missing file refuses), takes the pipeline
lock, backs the ledger up to data/backups/older-key-<time>/ (git-ignored, 700 / 600) with the removed ids and a manifest, and refuses
to write if removing the rows would change the derived view. To undo, copy the backed-up job_history.json back while no run is active.
The browser's Keep, statuses and hand-entered jobs are invisible to the server: ids not exported are not protected.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for part in ("python/job_discovery", "python/job_scoring", "python"):
    sys.path.insert(0, str(ROOT / part))

import older_key_retention as retention  # noqa: E402


def main(argv=None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--days", type=int, required=True, help="remove older_key rows last seen more than this many days ago")
    parser.add_argument("--application-job-ids", type=Path)
    parser.add_argument("--protect-ids", type=Path)
    parser.add_argument("--apply", action="store_true", help="make the change (dry run without it)")
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be at least 1")
    result = retention.prune(
        root, days=args.days, now=datetime.now(timezone.utc), application_ids=retention.parse_ids(args.application_job_ids),
        protect_ids=retention.parse_ids(args.protect_ids), apply=args.apply,
        store_sha=retention.parse_store_sha(args.application_job_ids),
    )
    shown = {k: v for k, v in result.items() if k != "candidates"}
    shown["wouldRemove"] = len(result["candidates"])
    print(json.dumps(shown, indent=2))
    if not args.apply:
        print("DRY RUN: nothing was changed.", file=sys.stderr)
    if not result["applicationsJoined"] or not result["protectIdsGiven"]:
        print("NOTE: " + retention.BROWSER_NOTE, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
