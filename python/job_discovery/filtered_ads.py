"""data/jobs/filtered_ads.json: every ad a source returned and a filter dropped, kept after its staging run is pruned (slice S5e1).

One record per jobId, updated in place, so the file grows with the number of different ads and not with the number of runs. It is
a separate file on purpose: every reader of the ledger assumes an entry holds a full ad, and these have no description (the
staging reader refuses a discard line that has one, and only the fields in `_SHOWN` are copied).

Independent of the ledger's generation. The real import writes it after the ledger and before the run's `imported.json`, so a stop
anywhere leaves it behind or ahead of the marker and a repeat fixes that: `appliedRuns` holds the id of every run already counted,
so A, B, A counts A once. `lastRunId` alone could not say that. A run with its id in the list changes no counter. The list only
grows, by an id a run, so a run folder restored from a copy still counts once.

Nothing here removes a record. An ad the ledger also holds keeps its record, marked `inLedger`: readers show it once, from the ledger.

Time is the run's own (`importer.import_time`), not the clock, so a run gives the same record whenever it is applied, and a run
older than what a record has seen can only move `firstSeen` back, never `lastSeen`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import staging

VERSION = 1
FILE_NAME = "filtered_ads.json"
_SHOWN = ("source", "title", "company", "location", "url", "externalId", "reason")


class FilteredAdsError(Exception):
    """The file is there but cannot be used. It is never overwritten then: nothing here can tell what it held."""


def file_path(root: Path) -> Path:
    return staging.jobs_dir(Path(root)) / FILE_NAME


def empty() -> dict:
    return {"version": VERSION, "appliedRuns": [], "ads": {}}


def load(root: Path) -> dict:
    """The store, or an empty one when there is no file yet. Raises FilteredAdsError when the file cannot be used."""
    path = file_path(root)
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty()
    except (OSError, ValueError) as exc:
        raise FilteredAdsError(f"{path.name} cannot be read: {type(exc).__name__}") from exc
    if not (isinstance(store, dict) and store.get("version") == VERSION
            and isinstance(store.get("appliedRuns"), list) and isinstance(store.get("ads"), dict)):
        raise FilteredAdsError(f"{path.name} is not a version {VERSION} store")
    return store


def _bytes(store: dict) -> str:
    # ASCII: an odd character in an ad's title can then never stop the write, and with it the pruning of the run.
    return json.dumps(store, indent=1) + "\n"


def save(root: Path, store: dict) -> bool:
    """Atomic. A store with nothing new is not written, so a repeat leaves the file and its time alone. True when written."""
    path = file_path(root)
    text = _bytes(store)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except FileNotFoundError:
        pass
    staging._atomic.write_text_atomic(path, text)
    return True


def _when(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _shown(record: dict) -> dict:
    return {name: record.get(name) for name in _SHOWN}


def apply_run(store: dict, run_id: str, moment: str, search_key: str, records: list[dict]) -> dict:
    """Count one run's discard lines into `store`. Pure apart from `store`; a run already counted changes nothing."""
    stats = {"alreadyApplied": False, "lines": len(records), "noId": 0, "ads": 0, "new": 0, "moved": 0, "older": 0}
    if run_id in store["appliedRuns"]:
        stats["alreadyApplied"] = True
        return stats
    at = _when(moment)
    if at is None:
        raise ValueError(f"run {run_id} has no usable time")
    ads = store["ads"]
    seen: set[str] = set()
    for record in records:
        job_id = record.get("jobId")
        if not isinstance(job_id, str) or not job_id:
            stats["noId"] += 1
            continue
        if job_id in seen:  # one ad under several searches: one sighting, the first line's reason
            continue
        seen.add(job_id)
        ad = ads.get(job_id)
        if ad is None:
            ads[job_id] = {**_shown(record), "firstSeen": moment, "lastSeen": moment, "lastRunId": run_id, "timesSeen": 1,
                           "searchKey": search_key, "inLedger": False}
            stats["new"] += 1
            continue
        ad["timesSeen"] += 1
        if at < _when(ad["firstSeen"]):
            ad["firstSeen"] = moment
        if at > _when(ad["lastSeen"]):
            ad.update(_shown(record), lastSeen=moment, lastRunId=run_id, searchKey=search_key)
            stats["moved"] += 1
        else:
            stats["older"] += 1
    stats["ads"] = len(seen)
    store["appliedRuns"].append(run_id)
    return stats


def mark_ledger(store: dict, ledger_ids) -> int:
    """`inLedger` on every record, from the ledger as it stands. Returns how many are in it."""
    held = 0
    for job_id, ad in store["ads"].items():
        ad["inLedger"] = job_id in ledger_ids
        held += ad["inLedger"]
    return held


def _discards_of(run: staging.RunStage) -> list[dict]:
    """The run's whole, valid discard lines. A file that is there but cannot be read is an error, not a run that dropped nothing."""
    path = run.dir / staging.DISCARDS
    try:
        with open(path, "rb"):
            pass
    except FileNotFoundError:
        return []
    return run.discards.records if run.discards else []


def record_run(root: Path, run: staging.RunStage, moment: str, ledger_ids) -> dict:
    """The import's write: this run's dropped ads, and the ledger marks as they now are. Raises when it could not be written."""
    store = load(root)
    stats = apply_run(store, run.run_id, moment, (run.manifest or {}).get("searchKey") or "", _discards_of(run))
    mark_ledger(store, ledger_ids)
    stats["written"] = save(root, store)
    return stats


def unrecorded(root: Path) -> set[str]:
    """Staged runs whose dropped ads are not in the file. Pruning one would lose them, so `staging.prune` leaves these alone.

    A store that cannot be read says nothing was recorded. A run with no discards file has nothing to lose.
    """
    try:
        applied = set(load(root)["appliedRuns"])
    except FilteredAdsError:
        applied = set()
    base = staging.staging_dir(Path(root))
    # A cancelled run (S6) is never counted, so it is never waiting either: its dropped ads are deliberately left out.
    return {run_id for run_id in staging.list_runs(root) if run_id not in applied and (base / run_id / staging.DISCARDS).is_file()
            and not (base / run_id / staging.CANCELLED).exists()}


def _ledger_ids(root: Path) -> set[str]:
    """Read only. Unlike job_history.load this never sets a bad ledger aside: a backfill must not touch it."""
    path = staging.jobs_dir(Path(root)) / "job_history.json"
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except (OSError, ValueError) as exc:
        raise FilteredAdsError(f"the ledger cannot be read: {type(exc).__name__}") from exc
    jobs = ledger.get("jobs") if isinstance(ledger, dict) else None
    if not isinstance(jobs, dict):
        raise FilteredAdsError("the ledger holds no jobs")
    return set(jobs)


def backfill(root: Path, time_of, *, dry_run: bool = False) -> dict:
    """Count every staged run's dropped ads, oldest first, imported or not. Writes this one file and nothing else; never imports,
    scores or marks a run. A second pass changes nothing. Counts only in the answer. `time_of(run)` gives a run's time."""
    root = Path(root)
    store = load(root)
    ledger_ids = _ledger_ids(root)
    before = set(store["ads"])
    report = {"dryRun": dry_run, "runs": [], "applied": 0, "alreadyApplied": 0, "noDiscards": 0, "noTime": 0}
    base = staging.staging_dir(root)
    for run_id in reversed(staging.list_runs(root)):
        run = staging.read_run(root, run_id)
        if run is None:
            continue
        line = {"runId": run_id, "imported": staging.is_imported(root, run_id)}
        report["runs"].append(line)
        if run.cancelled is not None:
            line["state"] = "cancelled run: not counted"
            report["cancelled"] = report.get("cancelled", 0) + 1
            continue
        if not (base / run_id / staging.DISCARDS).is_file():
            report["noDiscards"] += 1
            line["state"] = "no discards file"
            continue
        moment = time_of(run)
        if _when(moment) is None:
            report["noTime"] += 1
            line["state"] = "no usable time"
            continue
        discards = run.discards
        stats = apply_run(store, run_id, moment, (run.manifest or {}).get("searchKey") or "", _discards_of(run))
        line.update(stats, state="already counted" if stats["alreadyApplied"] else "counted", at=moment,
                    torn=bool(discards and discards.torn), unreadable=discards.unreadable_lines if discards else 0,
                    rejected=discards.rejected if discards else 0)
        report["alreadyApplied" if stats["alreadyApplied"] else "applied"] += 1
    in_ledger = mark_ledger(store, ledger_ids)
    by_source: dict[str, int] = {}
    for ad in store["ads"].values():
        by_source[str(ad.get("source"))] = by_source.get(str(ad.get("source")), 0) + 1
    report.update(ads=len(store["ads"]), newAds=len(store["ads"].keys() - before), inLedger=in_ledger, bySource=dict(sorted(by_source.items())),
                  appliedRuns=len(store["appliedRuns"]), bytes=len(_bytes(store).encode("utf-8")), written=False)
    if not dry_run:
        report["written"] = save(root, store)
    return report
