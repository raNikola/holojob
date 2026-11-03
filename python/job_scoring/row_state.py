"""Which rows of the job list were not found by the run that wrote it (slice S5d).

A row in discovered_jobs.json is one of: found by this run; closed and still shown; or kept open though this run did not find it,
either marked absent or held (its source or board could say nothing). Rows of the last kind must not cost anything or move anything:
no model call, and no part in the term rarity every other ad is scored with.

A held row has no mark of its own, so it is told by its date: the importer stamps every row it finds with `lastSeen` equal to the
view's `meta.generatedAt`. That holds for a view the importer wrote (`meta.ledgerGeneration`); a view without it says nothing, so
nothing counts as not found. A closed row and a hand-entered row are never counted here.
"""

from __future__ import annotations

MARK = "notFoundThisRun"


def found_stamp(meta) -> str | None:
    """The `lastSeen` every found row of this view carries, or None when the view cannot say."""
    if isinstance(meta, dict) and meta.get("ledgerGeneration") is not None:
        return meta.get("generatedAt") or None
    return None


def not_found(row: dict, stamp: str | None) -> bool:
    if row.get("isClosed") or row.get("manualEntry"):
        return False
    if row.get("isAbsent") or row.get("isStale"):
        return True
    return bool(stamp) and row.get("lastSeen") != stamp


def mark(rows: list[dict], meta) -> list[dict]:
    """The rows for scoring, with MARK on those not found. The rows passed in are not changed; a found row is the same object."""
    stamp = found_stamp(meta)
    return [{**row, MARK: True} if not_found(row, stamp) else row for row in rows]


def inactive(row: dict) -> bool:
    """For a marked row, or one already scored: no model call, no part in the corpus. A closed row has its own handling."""
    return bool(row.get(MARK) or row.get("isAbsent") or row.get("isStale")) and not row.get("isClosed") and not row.get("manualEntry")


def counts(rows: list[dict], meta) -> dict:
    """How many rows of a view are found, absent, held and closed."""
    stamp = found_stamp(meta)
    out = {"found": 0, "absent": 0, "held": 0, "closed": 0}
    for row in rows:
        if row.get("isClosed"):
            out["closed"] += 1
        elif row.get("isAbsent"):
            out["absent"] += 1
        elif not_found(row, stamp):
            out["held"] += 1
        else:
            out["found"] += 1
    return out
