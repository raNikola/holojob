"""Ad text the owner pasted for a discovered ad whose description was empty or thin (package 12 of PACKAGES_PLAN).

Discovery rewrites the ledger and the job list, so the pasted text lives in its own owner file, `data/jobs/pasted_descriptions.json`
(`{"version": 1, "ads": {jobId: {"text", "pastedAt", "source"?, "previous"?}}}`, 600), which no discovery code writes. Every step reads the
ad through `description_overlay.effective` (the one place the overlay is applied): the pasted text replaces the scraped one, and the scraped
text stays untouched in the ledger. `previous` is the entry this one replaced (one level, never more).
An overlaid row is `descriptionStatus: complete`, `descriptionSource: pasted`. Nothing here calls a model or the network, and the text
is never logged or echoed: errors carry a field name only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from atomic_write import write_private_text
from description_overlay import JOB_ID, SOURCE, SOURCES, effective, kind, kind as _kind, load as _load_overlay  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
PASTED_PATH = ROOT / "data" / "jobs" / "pasted_descriptions.json"
MAX_TEXT = 200_000
MIN_TEXT = 40  # a few words is not an ad
FILE_MODE = 0o600


class InvalidPaste(ValueError):
    """A paste the server will not take. `field` names the problem; the text is never quoted."""

    def __init__(self, field: str):
        super().__init__(field)
        self.field = field


def path_for(jobs_path: Path) -> Path:
    """The overlay file beside a job list, as `job_history.ledger_path` does for the ledger: a step given a temp jobs file reads the temp
    folder's overlay and never the real one."""
    return Path(jobs_path).parent / PASTED_PATH.name


def load(path: Path = PASTED_PATH) -> dict:
    """See `description_overlay.load`."""
    return _load_overlay(path)


def _save(ads: dict, path: Path) -> None:
    write_private_text(Path(path), json.dumps({"version": 1, "ads": ads}, indent=2))


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
    """Store the overlay text. An earlier entry (a paste, or text accepted from the employer) is kept as `previous`, one level: what was
    `previous` before is dropped. The same text from the same source again changes nothing, so a repeat never pushes the real earlier
    text out of the history."""
    if not isinstance(job_id, str) or not JOB_ID.match(job_id):
        raise InvalidPaste("jobId")
    ads = load(path)
    new_text = clean(text)
    before = ads.get(job_id)
    if before is not None and before["text"] == new_text and _kind(before.get("source")) == _kind(source):
        return
    entry = {"text": new_text, "pastedAt": now or datetime.now(timezone.utc).isoformat()}
    if source in SOURCES:  # package 13: "employer" for text the owner accepted from the employer's page
        entry["source"] = source
    if before is not None:
        prior = {"text": before["text"], "pastedAt": before.get("pastedAt"), "source": _kind(before.get("source"))}
        entry["previous"] = prior
    ads[job_id] = entry
    _save(ads, path)


def restore(job_id: str, entry: dict | None, path: Path = PASTED_PATH) -> None:
    """Put back exactly the entry `load` returned before a change (history included), or remove the id when there was none. A rollback
    after a failed re-score must not create a history entry of its own."""
    ads = load(path)
    if entry is None:
        ads.pop(job_id, None)
    else:
        ads[job_id] = entry
    _save(ads, path)


def remove(job_id: str, path: Path = PASTED_PATH) -> bool:
    ads = load(path)
    if job_id not in ads:
        return False
    del ads[job_id]
    _save(ads, path)
    return True


def effective_for(job: dict, jobs_path: Path) -> dict:
    """`effective` for a caller with one job and the job list's path (reads the file each call: for a few rows only)."""
    return effective(job, load(path_for(jobs_path)))


def apply(rows: list[dict], path: Path = PASTED_PATH, *, ads: dict | None = None) -> int:
    """`effective` for rows that exist in memory only (scoring, Fit 3 planning): the fields are replaced in place. Returns how many rows
    changed. Never use it on a row that is written back to the job list or the ledger; use `effective` there."""
    ads = load(path) if ads is None else ads
    changed = 0
    for row in rows:
        view = effective(row, ads)
        if view is not row:
            row.update(description=view["description"], descriptionStatus=view["descriptionStatus"], descriptionSource=view["descriptionSource"])
            changed += 1
    return changed
