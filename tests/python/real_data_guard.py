"""No test may change the owner's real data (2026-11-09 incident: a test run emptied data/profile/candidate-profile.json).

The Python tests already point each writer at a temp directory; this is the check that catches the one that does not. At the start of
the session the owner-private paths below are listed with their size and modification time (os.stat only: no file is opened or read), and
at the end the session fails if any of them changed. Pipeline-written files (discovered/scored jobs, the ledger, caches) are not
listed: the owner's own scrape may change them while the tests run.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARDED_DIRS = ("data/profile", "data/intelligence", "data/applications")
GUARDED_FILES = ("data/jobs/manual_jobs.json", "data/jobs/job-state.json")


def fingerprint(root: Path = ROOT) -> dict[str, tuple[int, int]]:
    """{relative path: (size, mtime_ns)} of every guarded file. Never opens a file."""
    found: dict[str, tuple[int, int]] = {}

    def add(path: Path) -> None:
        try:
            stat = path.stat()
        except OSError:
            return
        found[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)

    for directory in GUARDED_DIRS:
        base = root / directory
        for current, _dirs, files in os.walk(base):
            for name in files:
                add(Path(current) / name)
    for file in GUARDED_FILES:
        add(root / file)
    return found


def changes(before: dict, after: dict) -> list[str]:
    """Paths that were added, removed or changed between two fingerprints (names only)."""
    return sorted(
        f"{'added' if path not in before else 'removed' if path not in after else 'changed'}: {path}"
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )
