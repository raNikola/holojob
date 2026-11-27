"""The one place the owner's description overlay is read and applied to a job (packages 12 and 13 of PACKAGES_PLAN).

No imports from the project, so `job_history.py` and `importer.py`, which load their helpers by file path, can load it too.
`pasted_descriptions.py` owns the writes (put, remove, restore); this module reads the file and applies a loaded `{jobId: entry}` map.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

NAME = "pasted_descriptions.json"
JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SOURCE = "pasted"
SOURCES = ("pasted", "employer")


def kind(source) -> str:
    return source if source in SOURCES else SOURCE


def path_for(jobs_path: Path) -> Path:
    """The overlay file beside a job list, as `job_history.ledger_path` does for the ledger: a step given a temp jobs file reads the temp
    folder's overlay and never the real one."""
    return Path(jobs_path).parent / NAME


def load(path: Path) -> dict:
    """{jobId: {"text", "pastedAt", optional "source", optional "previous"}}; a missing or unreadable file is empty."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ads = doc.get("ads") if isinstance(doc, dict) else None
    if not isinstance(ads, dict):
        return {}
    return {k: v for k, v in ads.items() if isinstance(k, str) and JOB_ID.match(k) and isinstance(v, dict) and isinstance(v.get("text"), str)}


def effective(job: dict, ads: dict) -> dict:
    """The job as every step must read it. The job itself when no overlay entry belongs to it, else a copy with the owner's text
    (`descriptionStatus: complete`, `descriptionSource: pasted|employer`). It never mutates: the scraped text stays in the ledger and the
    job list, and a step that writes a row back writes the original. A hand-entered job is never overlaid."""
    entry = None if job.get("manualEntry") else (ads or {}).get(job.get("jobId"))
    if not entry:
        return job
    return {**job, "description": entry["text"], "descriptionStatus": "complete", "descriptionSource": kind(entry.get("source"))}
