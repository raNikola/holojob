"""Ad text the owner pasted for a discovered ad whose description was empty or thin (package 12 of PACKAGES_PLAN).

Discovery rewrites the ledger and the job list, so the pasted text lives in its own owner file, `data/jobs/pasted_descriptions.json`
(`{"version": 1, "ads": {jobId: {"text", "pastedAt"}}}`, 600), which no discovery code writes. Scoring overlays it onto the row with
the same id (`apply`): the pasted text replaces the scraped one for scoring, and the scraped text stays untouched in the ledger.
An overlaid row is `descriptionStatus: complete`, `descriptionSource: pasted`. Nothing here calls a model or the network, and the text
is never logged or echoed: errors carry a field name only.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from atomic_write import write_text_atomic

ROOT = Path(__file__).resolve().parents[2]
PASTED_PATH = ROOT / "data" / "jobs" / "pasted_descriptions.json"
JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_TEXT = 200_000
MIN_TEXT = 40  # a few words is not an ad
FILE_MODE = 0o600
SOURCE = "pasted"
SOURCES = ("pasted", "employer")


class InvalidPaste(ValueError):
    """A paste the server will not take. `field` names the problem; the text is never quoted."""

    def __init__(self, field: str):
        super().__init__(field)
        self.field = field


def load(path: Path = PASTED_PATH) -> dict:
    """{jobId: {"text", "pastedAt"}}; a missing or unreadable file is empty."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ads = doc.get("ads") if isinstance(doc, dict) else None
    if not isinstance(ads, dict):
        return {}
    return {k: v for k, v in ads.items() if isinstance(k, str) and JOB_ID.match(k) and isinstance(v, dict) and isinstance(v.get("text"), str)}


def _save(ads: dict, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(Path(path), json.dumps({"version": 1, "ads": ads}, indent=2), FILE_MODE)


def clean(text) -> str:
    if not isinstance(text, str):
        raise InvalidPaste("text")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) < MIN_TEXT:
        raise InvalidPaste("text_too_short")
    if len(text) > MAX_TEXT:
        raise InvalidPaste("text_too_long")
    return text


def put(job_id: str, text, path: Path = PASTED_PATH, *, now: str | None = None, source: str | None = None) -> None:
    if not isinstance(job_id, str) or not JOB_ID.match(job_id):
        raise InvalidPaste("jobId")
    ads = load(path)
    ads[job_id] = {"text": clean(text), "pastedAt": now or datetime.now(timezone.utc).isoformat()}
    if source in SOURCES:  # package 13: "employer" for text the owner accepted from the employer's page
        ads[job_id]["source"] = source
    _save(ads, path)


def remove(job_id: str, path: Path = PASTED_PATH) -> bool:
    ads = load(path)
    if job_id not in ads:
        return False
    del ads[job_id]
    _save(ads, path)
    return True


def apply(rows: list[dict], path: Path = PASTED_PATH) -> int:
    """Put the pasted text on every row it belongs to (in place). Returns how many rows changed. A hand-entered row is never touched."""
    ads = load(path)
    changed = 0
    for row in rows:
        entry = None if row.get("manualEntry") else ads.get(row.get("jobId"))
        if entry:
            row["description"] = entry["text"]
            row["descriptionStatus"] = "complete"
            row["descriptionSource"] = entry.get("source") if entry.get("source") in SOURCES else SOURCE
            changed += 1
    return changed
