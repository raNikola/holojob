"""Which rows of the job list the run that wrote it did not find (slices S5d, S5d2).

A row in discovered_jobs.json is one of: found by this run; closed and still shown; or kept open though this run did not find it,
either marked absent or held (its source or board could say nothing). Rows of the last kind must not cost anything or move anything:
no model call, and no part in the term rarity every other ad is scored with.

Such a row says so itself: `notFoundThisRun`, written by `job_history.apply_run` and by `view_guard.derive_view` from the entry's
`heldRunId == lastImport.runId`. That stamp is on the ledger, so the mark stays right whatever rewrites the view. A ledger whose last
import predates the mark (no `lastImport.marksNotFound`) gives no mark, and nothing counts as held until proven: such a row is
treated as it always was. `isAbsent` and `isStale` are marks of their own. A closed row and a hand-entered row are never counted.
"""

from __future__ import annotations

MARK = "notFoundThisRun"


def not_found(row: dict) -> bool:
    if row.get("isClosed") or row.get("manualEntry"):
        return False
    return bool(row.get(MARK) or row.get("isAbsent") or row.get("isStale"))


def in_idf_corpus(row: dict) -> bool:
    """Whether a row counts toward term rarity (IDF). A closed ad is a finished listing and a row a run
    did not find is unproven, so neither moves another ad's score; both are still scored. A hand-entered job is
    always in."""
    if row.get("manualEntry"):
        return True
    return not row.get("isClosed") and not not_found(row)


def counts(rows: list[dict]) -> dict:
    """How many rows of a view are found, absent, held and closed."""
    out = {"found": 0, "absent": 0, "held": 0, "closed": 0}
    for row in rows:
        if row.get("isClosed"):
            out["closed"] += 1
        elif row.get("isAbsent"):
            out["absent"] += 1
        elif not_found(row):
            out["held"] += 1
        else:
            out["found"] += 1
    return out
