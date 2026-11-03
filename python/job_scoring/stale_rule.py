"""When an ad is Stale (slice S5f): a flag, never a deletion. Stdlib only and pure, so the importer, the view and the route share one rule.

An ad is Stale when, measured over the ledger's own record of proven runs of its source and search:

    at least STALE_RUNS proven runs came after its last sighting, and
    the newest of them is at least STALE_DAYS after that sighting.

So the gap is what those runs prove, not what the clock says: a pause in scraping proves nothing and flags nothing, and one ledger
always gives one answer, whenever and however often it is read. A closed ad is never Stale; closing keeps its own rules (S5c).

`ledger["sourceRuns"]` is `{provider: {bucket: [{"runId", "at"}, ...]}}`, oldest first, newest MAX_RUNS_KEPT kept. The bucket says which
runs could have seen the ad. A search-based source: the search key the ad was seen under, since an ad of another search proves nothing.
A snapshot source: the board, with no search key (D4), and only for a board proven complete by S5b/S5c. So Ashby, which can never prove
a board, has no such runs and its ads never go Stale. A last sighting is `lastSeen`, or `lastListedAt` if later: a source that still
returns an ad, though a filter now drops it, has seen it.

A ledger with no `sourceRuns`, as every ledger before this slice, has no Stale ad. Runs before it are not counted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

STALE_DAYS = 30
STALE_RUNS = 3
MAX_RUNS_KEPT = 100  # enough to say how many runs passed, in a reason line; the rule itself needs only STALE_RUNS
SNAPSHOT_PROVIDERS = {"greenhouse", "lever", "ashby"}
FIELD = "sourceRuns"
BOARD_PREFIX = "board:"


def _time(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def board_bucket(board) -> str:
    return f"{BOARD_PREFIX}{board}"


def entry_bucket(entry: dict) -> str | None:
    """Which runs could have seen this ad. None when it cannot be said, and then no run counts."""
    if entry.get("provider") in SNAPSHOT_PROVIDERS:
        board = (entry.get("job") or {}).get("source")
        return board_bucket(board) if board else None
    return entry.get("seenUnder") or None


def last_sighting(entry: dict) -> datetime | None:
    moments = [moment for moment in (_time(entry.get("lastSeen")), _time(entry.get("lastListedAt"))) if moment]
    return max(moments) if moments else None


def evidence(entry: dict, source_runs) -> dict | None:
    """`{"days", "runs", "capped"}` when the entry is Stale, else None. `capped`: at least `runs`, the list holds no more."""
    if entry.get("closedAt"):
        return None
    bucket = entry_bucket(entry)
    seen = last_sighting(entry)
    if not bucket or seen is None or not isinstance(source_runs, dict):
        return None
    runs = ((source_runs.get(entry.get("provider")) or {}).get(bucket)) or []
    after = [moment for moment in (_time(run.get("at")) for run in runs if isinstance(run, dict)) if moment and moment > seen]
    if len(after) < STALE_RUNS:
        return None
    gap = max(after) - seen
    if gap < timedelta(days=STALE_DAYS):
        return None
    return {"days": gap.days, "runs": len(after), "capped": len(runs) >= MAX_RUNS_KEPT and len(after) == len(runs)}


def record_run(ledger: dict, provider: str, bucket: str, run_id: str, at: str) -> None:
    """One proven run. The same run twice counts once; the list stays in time order, whatever order runs are imported in."""
    runs = ledger.setdefault(FIELD, {}).setdefault(provider, {}).setdefault(bucket, [])
    if any(run.get("runId") == run_id for run in runs):
        return
    runs.append({"runId": run_id, "at": at})
    runs.sort(key=lambda run: _time(run.get("at")) or datetime.min.replace(tzinfo=timezone.utc))
    del runs[:-MAX_RUNS_KEPT]
