#!/usr/bin/env python3
"""What the S5 lifecycle rules WOULD do, from the ledger and the staged runs (slice S5a). Changes no behaviour and writes nothing.

`simulate` and `build_report` are pure: they take the data, mutate none of it, and do no I/O. This is an estimate, separate from
the live rules: S5c built snapshot closing in `job_history.apply_run` (which uses the S5b proof), and this report does not read it. `import_run.py --lifecycle-report` gathers the inputs and prints.

Closing is simulated twice, because a board's read is not yet proven complete (owner, D7: read == kept + dropped alone is not
enough, a provider may stop early):
  * strict:   what S5 could do today. No board has that proof, so no snapshot ad is missed or closed.
  * ifProven: what S5 would do if every board with read == kept + dropped and known ids had the proof.

The search-key state of an older-key row is a measurement here, not a decision (owner, D3 is open): `olderKey` rows are never
absent or Stale in the simulation, and `olderKeyOptions` prices each way of treating them.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import importer
import staging
from dedupe_jobs import _collapse, _crosspost_key, _exact_key

SNAPSHOT = frozenset({"greenhouse", "lever", "ashby"})
UNCLASSIFIED = frozenset({"infostud"})
STALE_DAYS = 30  # temporary values, owner 2026-11-03
STALE_RUNS = 3
DEFAULT_LIST_DAYS = 14  # D1: temporary, to be confirmed after this report
GROWTH_DAYS = 30
CLOSED_KEEP_DAYS = importer.job_history.CLOSED_KEEP_DAYS
AGE_BUCKETS = ((0, 7, "0-7d"), (8, 14, "8-14d"), (15, 30, "15-30d"), (31, 10**6, "31d+"))

# What each provider can prove about a complete read: read from the provider code, checked by one live GET per provider on 2026-11-03.
BOARD_EVIDENCE = {
    "greenhouse": {
        "provesToday": ["HTTP 200 and the whole body parsed as JSON (_fetch_board raises otherwise)", "read == kept + dropped for the board"],
        "cannotProveToday": ["that a run staged before S5b read the whole board: `meta.total` is staged only since S5b"],
        "couldProve": "Since S5b: `meta.total` is staged per board and must equal the postings read (seen: jobs 40, meta.total 40).",
    },
    "lever": {
        "provesToday": ["HTTP 200 and the whole body parsed as a JSON list", "read == kept + dropped for the board"],
        "cannotProveToday": ["that the list is the whole board: no total in the answer, and the API does take skip and limit, so before S5b a server-side cap could not be told from the end"],
        "couldProve": "Since S5b: a second request `skip=<read>&limit=1` must return an empty list (seen: skip=1000 gives [], limit=2 gives 2 rows). One request per board.",
    },
    "ashby": {
        "provesToday": ["HTTP 200 and the whole body parsed as JSON", "read == kept + dropped for the board"],
        "cannotProveToday": ["that the list is the whole board: the answer has only `jobs` and `apiVersion`, no total and no paging field"],
        "couldProve": "Nothing from the answer itself, so no right to close (D7). Since S5b a paging field appearing is recorded as an anomaly.",
    },
}

# Where the owner's work lives, checked in the code on 2026-11-03. A data file: no Python names the application store
# (tests/python/test_application_store_isolation.py), and this only says where it is.
STORAGE_MAP = json.loads(Path(__file__).with_name("lifecycle_storage_map.json").read_text(encoding="utf-8"))


def source_class(provider) -> str:
    if provider in SNAPSHOT:
        return "snapshot"
    return "unclassified" if provider in UNCLASSIFIED else "search"


def _time(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


@dataclass
class Board:
    read: int = 0
    kept: int = 0
    dropped: int = 0
    uncounted: int = 0
    listed: set = field(default_factory=set)  # every jobId the board showed: kept or dropped by a filter
    ids_known: bool = True
    failed: bool = False
    empty: bool = False

    @property
    def balanced(self) -> bool:
        return self.read == self.kept + self.dropped

    @property
    def read_ok(self) -> bool:
        return not self.failed and not self.empty


@dataclass
class SourceFacts:
    name: str
    state: str  # complete, partial, failed, skipped, unfinished
    clean: bool  # complete with nothing doubtful: this is the "successful run" of the Stale rule
    doubtful: bool = False  # ads lost or not accounted for: the source is no evidence of anything, as in the importer
    boards: dict = field(default_factory=dict)


def source_facts(run: staging.RunStage) -> tuple[dict, list, set]:
    """Per source: how it ended and, for a snapshot source, each board. Also the whole valid ads and their ids and roles."""
    facts: dict = {}
    ads: list = []
    for name in [p for p in (run.manifest or {}).get("providers") or [] if isinstance(p, str)]:
        stage = run.sources.get(name)
        footer = stage.footer if stage and stage.usable else None
        status = footer.get("status") if footer else None
        state = {"ok": "complete", "partial": "partial", "failed": "failed", "skipped": "skipped"}.get(status, "unfinished") if footer else "unfinished"
        jobs = stage.jobs if stage and stage.usable else []
        valid = [job for job in jobs if not importer.validate_ad(job, name)]
        doubtful = (len(valid) != len(jobs)) or bool(stage and stage.rejected_ads) or bool(footer and (footer.get("invalid") or footer.get("mismatch") or footer.get("discardMismatch")))
        ads.extend(valid)
        entry = facts[name] = SourceFacts(name, state, state == "complete" and not doubtful, doubtful)
        if name not in SNAPSHOT or not stage or not stage.usable:
            continue
        for batch in stage.batches:
            board = entry.boards.setdefault(batch.part or "all", Board())
            board.read += batch.read or 0
            board.kept += len(batch.jobs)
            board.listed.update(job.get("jobId") for job in batch.jobs if isinstance(job, dict))
        for record in (run.discards.by_source(name) if run.discards else []):
            board = entry.boards.setdefault(record.get("part") or "all", Board())
            if not record.get("counted"):
                board.uncounted += 1
                continue
            board.dropped += 1
            if record.get("jobId"):
                board.listed.add(record["jobId"])
            else:
                board.ids_known = False
        for part in (footer or {}).get("boardsFailed") or []:
            entry.boards.setdefault(part, Board()).failed = True
        for part in (footer or {}).get("boardsEmpty") or []:
            entry.boards.setdefault(part, Board()).empty = True
    deduped = _collapse(_collapse(ads, _exact_key), _crosspost_key)
    return facts, deduped, {_crosspost_key(job) for job in deduped}


def _new_entry(job: dict, moment: str, key: str, run_id: str) -> dict:
    return {
        "firstSeen": moment, "lastSeen": moment, "closedAt": None, "llmFacts": None, "provider": job.get("provider"),
        "roleKey": _crosspost_key(job), "seenUnder": key, "job": job, "lastRunId": run_id,
    }


def simulate(start_ledger: dict, runs: list, *, trust_balanced: bool) -> dict:
    """Replay `runs` (oldest first) on a copy of `start_ledger` under the S5 rules. Returns {"runs": [...], "state": {jobId: ...}, "entries"}.

    `trust_balanced` False is the strict case: no board counts as proven, so nothing is missed. True takes a balanced board with
    known ids as proven (the ifProven case). The ledger passed in is not changed.
    """
    entries = copy.deepcopy(start_ledger.get("jobs") or {})
    state = {
        job_id: {"absentRuns": 0, "absentSince": None, "lastMissRun": None, "staleSince": None, "seenAt": 0, "found": False, "last": None}
        for job_id in entries
    }
    source_runs: dict = {}
    out = []
    for run in runs:
        manifest = run.manifest or {}
        run_id, key = run.run_id, manifest.get("searchKey") or ""
        moment = importer.import_time(run)
        now = _time(moment)
        facts, found, found_roles = source_facts(run)
        for name, source in facts.items():
            if source.clean:
                source_runs[(name, key)] = source_runs.get((name, key), 0) + 1
        counts: dict = {}

        def bump(cls: str, name: str) -> None:
            bucket = counts.setdefault(cls, {})
            bucket[name] = bucket.get(name, 0) + 1

        found_ids = set()
        for job in found:
            job_id = job["jobId"]
            found_ids.add(job_id)
            cls = source_class(job.get("provider"))
            bump(cls, "active")
            entry = entries.get(job_id)
            if entry is None:
                entries[job_id] = _new_entry(job, moment, key, run_id)
                state[job_id] = {"absentRuns": 0, "absentSince": None, "lastMissRun": None, "staleSince": None, "seenAt": 0, "found": True, "last": "found"}
                bump(cls, "new")
            elif entry.get("closedAt"):
                entry["closedAt"] = None
                bump(cls, "reopened")
            if state[job_id]["staleSince"]:
                bump(cls, "staleCleared")
            entry = entries[job_id]
            entry.update(lastSeen=moment, seenUnder=key, job=job, provider=job.get("provider"), roleKey=_crosspost_key(job))
            state[job_id].update(absentRuns=0, absentSince=None, staleSince=None, found=True, last="found",
                                 seenAt=source_runs.get((job.get("provider"), key), 0))

        for job_id, entry in entries.items():
            one = state[job_id]
            if job_id in found_ids:
                continue
            one["found"] = False
            provider = entry.get("provider")
            cls = source_class(provider)
            if entry.get("closedAt"):
                one["last"] = "closed"
                bump(cls, "closedTotal")
                continue
            if entry.get("roleKey") in found_roles:
                one["last"] = "crossPost"
                bump(cls, "crossPostListed")
                continue
            source = facts.get(provider)
            if source is None or source.state in ("failed", "skipped", "unfinished") or source.doubtful or (not source.clean and cls != "snapshot"):
                one["last"] = "held"
                bump(cls, "heldSourceDidNotRun")
                continue
            if cls == "snapshot":
                board = source.boards.get((entry.get("job") or {}).get("source"))
                if board is None:
                    one["last"] = "held"
                    bump(cls, "heldBoardNotRead")
                    continue
                if not board.read_ok:
                    one["last"] = "held"
                    bump(cls, "heldBoardFailedOrEmpty")
                    continue
                if job_id in board.listed:
                    one.update(absentRuns=0, absentSince=None, last="listedFiltered")
                    bump(cls, "listedButFiltered")
                    continue
                if not (trust_balanced and board.balanced and board.ids_known):
                    one["last"] = "noEvidence"
                    bump(cls, "noEvidenceOfCompleteRead")
                    continue
                if one["lastMissRun"] != run_id:
                    one["lastMissRun"] = run_id
                    one["absentRuns"] += 1
                if one["absentRuns"] >= 2:
                    entry["closedAt"] = moment
                    one["last"] = "closed"
                    bump(cls, "closed")
                    continue
                one["last"] = "absent"
                if not one["absentSince"]:
                    one["absentSince"] = moment
                    bump(cls, "absentNew")
                bump(cls, "absentTotal")
                continue
            if entry.get("seenUnder") != key:
                one["last"] = "olderKey"
                bump(cls, "olderKey")
                continue
            one["last"] = "absent"
            if not one["absentSince"]:
                one["absentSince"] = moment
                bump(cls, "absentNew")
            bump(cls, "absentTotal")
            last_seen = _time(entry.get("lastSeen"))
            since = source_runs.get((provider, key), 0) - one["seenAt"]
            if last_seen and now and now - last_seen >= timedelta(days=STALE_DAYS) and since >= STALE_RUNS:
                if not one["staleSince"]:
                    one["staleSince"] = moment
                    bump(cls, "staleNew")
                bump(cls, "staleTotal")
        out.append({"runId": run_id, "at": moment, "searchKey": key, "transitions": counts,
                    "sources": {n: {"state": s.state, "successful": s.clean} for n, s in facts.items()}})
    return {"runs": out, "state": state, "entries": entries}


def board_table(runs: list) -> list:
    """Per snapshot board, per run: what the staged run shows about the read. Counts only."""
    rows = []
    for run in runs:
        facts, _, _ = source_facts(run)
        for name, source in facts.items():
            for part, board in sorted(source.boards.items()):
                rows.append({
                    "runId": run.run_id, "provider": name, "board": part, "read": board.read, "kept": board.kept, "dropped": board.dropped,
                    "balanced": board.balanced, "idsKnown": board.ids_known, "failed": board.failed, "empty": board.empty,
                    "reportedTotalStaged": False, "reliableProof": False,
                })
    return rows


def _row_sizes(job: dict) -> tuple[int, int]:
    """(full, slim) in the indented JSON a file holds. Slim leaves the description out."""
    full = len(json.dumps(job, indent=2))
    return full, full - len(json.dumps(job.get("description") or ""))


def job_key(job_id: str) -> str:
    """The AI findings store's key for a job: see scripts/ai-findings-store.js jobEntityKey."""
    return hashlib.sha256(str(job_id).encode()).hexdigest()[:16]


def _user_kinds(job_id: str, user: dict) -> list:
    return [kind for kind, ids in user.items() if job_id in ids]


def build_report(start_ledger: dict, ledger: dict, runs: list, *, view_bytes: int, view_rows: int, scored_bytes: int, scored_rows: int,
                 user_data: dict, as_of: str, measured: dict | None = None, applications_joined: bool = True) -> dict:
    """The whole report. `user_data` maps a kind to the jobIds the backend holds work for. Pure: nothing is written or changed."""
    strict = simulate(start_ledger, runs, trust_balanced=False)
    proven = simulate(start_ledger, runs, trust_balanced=True)
    entries, state = strict["entries"], strict["state"]
    now = _time(as_of)
    last_key = ((runs[-1].manifest or {}).get("searchKey") or "") if runs else ""

    per_key: dict = {}
    for job_id, entry in entries.items():
        one = state[job_id]
        provider, key = entry.get("provider"), entry.get("seenUnder") or ""
        row = per_key.setdefault((provider, key), {
            "provider": provider, "class": source_class(provider), "searchKey": key, "current": key == last_key, "rows": 0, "found": 0, "open": 0,
            "closed": 0, "withFacts": 0, "userData": 0, "fullBytes": 0, "slimBytes": 0, "ages": {label: 0 for _, _, label in AGE_BUCKETS},
        })
        row["rows"] += 1
        row["found"] += bool(one["found"])
        row["closed"] += bool(entry.get("closedAt"))
        row["open"] += not entry.get("closedAt")
        row["withFacts"] += bool(entry.get("llmFacts"))
        row["userData"] += bool(_user_kinds(job_id, user_data))
        full, slim = _row_sizes(entry.get("job") or {})
        row["fullBytes"] += full
        row["slimBytes"] += slim
        seen = _time(entry.get("lastSeen"))
        age = (now - seen).days if seen and now else None
        if age is not None:
            for low, high, label in AGE_BUCKETS:
                if low <= age <= high:
                    row["ages"][label] += 1

    def rows_where(test) -> list:
        return [(job_id, entries[job_id], state[job_id]) for job_id in entries if test(job_id, entries[job_id], state[job_id])]

    def within(entry, days) -> bool:
        seen = _time(entry.get("lastSeen"))
        return bool(seen and now and now - seen <= timedelta(days=days))

    def closed_shown(entry) -> bool:
        closed = _time(entry.get("closedAt"))
        return bool(closed and now and now - closed <= timedelta(days=CLOSED_KEEP_DAYS))

    # Under S5 these stay in results as absent: what no evidence says is gone. A cross-post still listed under another copy has its row.
    SHOWN_ABSENT = ("absent", "held", "noEvidence")
    found_rows = rows_where(lambda _i, _e, s: s["found"])
    closed_rows = rows_where(lambda _i, e, s: s["last"] == "closed" and closed_shown(e))
    current_absent = rows_where(lambda _i, _e, s: s["last"] in SHOWN_ABSENT)
    older_rows = rows_where(lambda _i, _e, s: s["last"] == "olderKey")

    def size(rows, index=0) -> int:
        return sum(_row_sizes(e.get("job") or {})[index] for _, e, _ in rows)

    found_bytes = size(found_rows) + size(closed_rows)
    base_overhead = 2000
    scored_extra = max(0, (scored_bytes / scored_rows) - (view_bytes / view_rows)) if scored_rows and view_rows else 0

    # Growth: rows a day first seen over the ledger's whole span, measured, assumed to go on and never be seen again.
    firsts = [t for t in (_time(e.get("firstSeen")) for e in entries.values() if not e.get("seeded")) if t]
    span_days = max(1.0, (max(firsts) - min(firsts)).total_seconds() / 86400) if firsts else 1.0
    rate = len(firsts) / span_days
    avg_full = (size(found_rows + current_absent + older_rows) / max(1, len(found_rows + current_absent + older_rows)))
    avg_slim = (size(found_rows + current_absent + older_rows, 1) / max(1, len(found_rows + current_absent + older_rows)))
    grown = rate * GROWTH_DAYS

    def scenario(name, rows, bytes_):
        return {"scenario": name, "rows": int(rows), "discoveredBytes": int(bytes_ + base_overhead), "scoredBytes": int(bytes_ + base_overhead + rows * scored_extra)}

    shown_now = len(found_rows) + len(closed_rows)
    older_full, older_slim = size(older_rows), size(older_rows, 1)
    absent_full, absent_slim = size(current_absent), size(current_absent, 1)
    sizes = [
        {"scenario": "today (measured)", "rows": view_rows, "discoveredBytes": view_bytes, "scoredBytes": scored_bytes},
        scenario("S5, full rows, older-key rows kept", shown_now + len(current_absent) + len(older_rows), found_bytes + absent_full + older_full),
        scenario("S5, full rows, older-key rows out", shown_now + len(current_absent), found_bytes + absent_full),
        scenario("S5, slim absent rows, older-key rows kept", shown_now + len(current_absent) + len(older_rows), found_bytes + absent_slim + older_slim),
        scenario("S5, slim absent rows, older-key rows out", shown_now + len(current_absent), found_bytes + absent_slim),
        scenario(f"+{GROWTH_DAYS} days, full rows, nothing leaves", shown_now + len(current_absent) + len(older_rows) + grown,
                 found_bytes + absent_full + older_full + grown * avg_full),
        scenario(f"+{GROWTH_DAYS} days, slim rows, nothing leaves", shown_now + len(current_absent) + len(older_rows) + grown,
                 found_bytes + absent_slim + older_slim + grown * (avg_slim)),
        scenario(f"+{GROWTH_DAYS} days, slim rows, today's absent rows gone Stale and out of the file (D2)", shown_now + grown,
                 found_bytes + grown * avg_slim),
    ]

    def recent(rows, days=DEFAULT_LIST_DAYS) -> int:
        return sum(within(e, days) for _, e, _ in rows)

    default_base = shown_now + recent(current_absent)
    older_user = sum(bool(_user_kinds(i, user_data)) for i, _, _ in older_rows)
    older_options = {
        "rows": len(older_rows), "withinDefaultWindow": recent(older_rows), "withFacts": sum(bool(e.get("llmFacts")) for _, e, _ in older_rows),
        "withBackendUserData": older_user, "fullBytes": older_full, "slimBytes": older_slim,
        "options": [
            {"option": "keep as absent", "fileRowsAdded": len(older_rows), "fileBytesFull": older_full, "fileBytesSlim": older_slim,
             "defaultListRows": default_base + recent(older_rows), "note": "They count as absent though no run of their search looked. They never go Stale: no run of that key will happen."},
            {"option": "flag (in the file, marked 'other search', hidden by default)", "fileRowsAdded": len(older_rows), "fileBytesFull": older_full, "fileBytesSlim": older_slim,
             "defaultListRows": default_base, "note": "Honest about why they are absent. The file carries them with no end unless a later rule says so."},
            {"option": "leave the file (ledger keeps them, a filter brings them back)", "fileRowsAdded": 0, "fileBytesFull": 0, "fileBytesSlim": 0,
             "defaultListRows": default_base, "note": "This is where they are today. Needs the same ledger-backed route as 'Include stale' (D2)."},
        ],
    }

    # When today's absent rows could first go Stale, if 3 successful runs of their search also happen by then.
    stale_after = {}
    for days in (20, 25, 30):
        then = now + timedelta(days=days) if now else None
        stale_after[str(days)] = sum(
            1 for _, e, _ in current_absent
            if then and _time(e.get("lastSeen")) and then - _time(e.get("lastSeen")) >= timedelta(days=STALE_DAYS)
        )
    measured = dict(measured or {})
    if measured.get("allOpenRows") and measured.get("allOpenScoringSeconds"):
        per_row = measured["allOpenScoringSeconds"] / measured["allOpenRows"]
        measured["secondsPerRow"] = round(per_row, 4)
        measured["estimates"] = {row["scenario"]: round(row["rows"] * per_row, 1) for row in sizes}

    user_rows = []
    for job_id, entry in entries.items():
        kinds = _user_kinds(job_id, user_data)
        if not kinds:
            continue
        one = state[job_id]
        where = one["last"] if one["last"] not in SHOWN_ABSENT else "absent"
        user_rows.append({"jobId": job_id, "provider": entry.get("provider"), "class": source_class(entry.get("provider")), "wouldBe": where, "kinds": kinds})
    held_outside = {kind: sorted(ids - set(entries)) for kind, ids in user_data.items()}
    user_summary: dict = {}
    for row in user_rows:
        user_summary[row["wouldBe"]] = user_summary.get(row["wouldBe"], 0) + 1

    return {
        "asOf": as_of, "currentSearchKey": last_key, "runsReplayed": [r.run_id for r in runs],
        "ledger": {"entries": len(ledger.get("jobs") or {}), "startEntries": len(start_ledger.get("jobs") or {})},
        "transitions": {"strict": strict["runs"], "ifProven": proven["runs"]},
        "perKey": sorted(per_key.values(), key=lambda r: (not r["current"], r["provider"] or "", r["searchKey"])),
        "olderKey": older_options,
        "sizes": sizes,
        "growth": {"rowsPerDay": round(rate, 1), "spanDays": round(span_days, 1), "avgFullRowBytes": int(avg_full), "avgSlimRowBytes": int(avg_slim),
                   "scoredExtraBytesPerRow": int(scored_extra), "assumes": "the rate goes on and no new ad is ever seen again: an upper bound"},
        "defaultList": {"rowsToday": view_rows, "rowsUnderS5OlderKeyOut": default_base, "rowsUnderS5OlderKeyKept": default_base + recent(older_rows), "windowDays": DEFAULT_LIST_DAYS},
        "scoring": measured,
        "staleProjection": {"daysFromNow": stale_after, "rows": len(current_absent), "assumes": "3 successful runs of the same search by then; rows under an older key are not counted, they cannot reach it"},
        "boards": board_table(runs),
        "boardEvidence": BOARD_EVIDENCE,
        "storage": STORAGE_MAP,
        "userData": {"backendOnly": True, "applicationsJoined": applications_joined, "byState": user_summary, "rows": user_rows, "notInLedger": {k: len(v) for k, v in held_outside.items()}},
    }


# --- gathering (reads only) ----------------------------------------------------------------------------------------------


def backend_user_data(root: Path, ledger_ids, application_ids=None) -> dict:
    """The jobIds the backend holds the owner's work for. Browser-only work cannot be seen from here: see STORAGE_MAP.

    Python never reads the application store (TRACKER_PLAN 6a), so `application_ids` is what the caller hands in, or None when
    it was not given: the report then says applications were not joined.
    """
    data = Path(root) / "data"
    found = {"applications": set(application_ids or ()), "tailoredDocuments": set(), "outreachContacts": set(), "aiFindings": set(), "tailoredLinkInScored": set()}
    for kind, folder in (("tailoredDocuments", data / "resumes"), ("outreachContacts", data / "outreach")):
        if folder.is_dir():
            found[kind].update(p.name for p in folder.iterdir() if p.is_dir())
    findings = data / "ai" / "findings" / "job"
    if findings.is_dir():
        keys = {p.stem for p in findings.glob("*.json")}
        found["aiFindings"].update(job_id for job_id in ledger_ids if job_key(job_id) in keys)
    try:
        scored = json.loads((data / "jobs" / "scored_jobs.json").read_text(encoding="utf-8"))
        found["tailoredLinkInScored"].update(j["jobId"] for j in scored.get("jobs") or [] if j.get("tailoredAssets") and j.get("jobId"))
    except (OSError, ValueError, AttributeError, KeyError):
        pass
    return found


def measure_scoring(root: Path) -> dict:
    """Time reading the ledger and scoring, in a child process: job_scoring's modules would shadow this package's. Writes nothing."""
    import subprocess

    try:
        done = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--measure-scoring", str(root)], capture_output=True, text=True, timeout=1800)
        return json.loads(done.stdout.strip().splitlines()[-1]) if done.returncode == 0 else {"error": f"exit {done.returncode}: {done.stderr.strip()[-200:]}"}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _measure_child(root: Path) -> dict:
    scoring = Path(__file__).resolve().parents[1] / "job_scoring"
    sys.path = [str(scoring), str(scoring.parent)] + [p for p in sys.path if Path(p or ".").resolve() != Path(__file__).resolve().parent]
    from scorer import score_jobs  # noqa: PLC0415

    jobs_dir = root / "data" / "jobs"
    started = time.perf_counter()
    ledger = json.loads((jobs_dir / "job_history.json").read_text(encoding="utf-8"))
    read_ledger = time.perf_counter() - started
    intelligence = json.loads((root / "data" / "intelligence" / "candidate-intelligence.json").read_text(encoding="utf-8"))
    view = json.loads((jobs_dir / "discovered_jobs.json").read_text(encoding="utf-8"))["jobs"]
    entries = ledger["jobs"]
    open_rows = [{**e["job"], **({"llmFacts": e["llmFacts"]} if e.get("llmFacts") else {})} for e in entries.values() if not e.get("closedAt")]

    def timed(rows) -> float:
        begin = time.perf_counter()
        score_jobs(copy.deepcopy(rows), intelligence)
        return time.perf_counter() - begin

    return {
        "ledgerReadSeconds": round(read_ledger, 2), "viewRows": len(view), "viewScoringSeconds": round(timed(view), 2),
        "allOpenRows": len(open_rows), "allOpenScoringSeconds": round(timed(open_rows), 2),
    }


def gather(root: Path, run_id: str | None, *, as_of: str, measure: bool = True, application_ids=None) -> dict:
    """Read what the report needs and build it. Nothing is written."""
    root = Path(root)
    jobs_dir = root / "data" / "jobs"
    all_ids = sorted(staging.list_runs(root))
    runs = []
    for one in all_ids:
        run = staging.read_run(root, one)
        if isinstance(run.manifest, dict) and not (run.status is not None and run.status.get("ok") is False):
            runs.append(run)
    runs.sort(key=lambda r: (r.manifest.get("startedAt") or "", r.run_id))
    if run_id:
        index = next((i for i, r in enumerate(runs) if r.run_id == run_id), None)
        if index is None:
            raise ValueError(f"no usable staged run {run_id}")
        runs = runs[: index + 1]
    if not runs:
        raise ValueError("no usable staged run")
    ledger = json.loads((jobs_dir / "job_history.json").read_text(encoding="utf-8"))
    before = runs[0].ledger_before
    start = json.loads(before.read_text(encoding="utf-8")) if before else ledger
    view_file, scored_file = jobs_dir / "discovered_jobs.json", jobs_dir / "scored_jobs.json"
    view = json.loads(view_file.read_text(encoding="utf-8")) if view_file.exists() else {"jobs": []}
    scored = json.loads(scored_file.read_text(encoding="utf-8")) if scored_file.exists() else {"jobs": []}
    return build_report(
        start, ledger, runs, view_bytes=view_file.stat().st_size if view_file.exists() else 0, view_rows=len(view.get("jobs") or []),
        scored_bytes=scored_file.stat().st_size if scored_file.exists() else 0, scored_rows=len(scored.get("jobs") or []),
        user_data=backend_user_data(root, set(ledger.get("jobs") or {}), application_ids), as_of=as_of, measured=measure_scoring(root) if measure else {},
        applications_joined=application_ids is not None,
    )


# --- printing ------------------------------------------------------------------------------------------------------------


def _mb(value) -> str:
    return f"{value / 1_000_000:.1f} MB"


def render(report: dict) -> list:
    lines = ["Lifecycle report (S5a): what the S5 rules WOULD do. Read-only; nothing was written.", ""]
    lines.append(f"As of {report['asOf']}; current search key {report['currentSearchKey']}; ledger {report['ledger']['entries']} entries.")
    lines.append(f"Runs replayed, oldest first: {', '.join(report['runsReplayed'])} (from {report['ledger']['startEntries']} entries)")
    for name, label in (("strict", "STRICT, what S5 could do today: no board has proof of a complete read"), ("ifProven", "IF PROVEN: balanced boards with known ids count as proven")):
        lines += ["", f"Transitions, {label}"]
        for run in report["transitions"][name]:
            lines.append(f"  run {run['runId']}")
            for cls, counts in sorted(run["transitions"].items()):
                main = {key: counts.get(key, 0) for key in ("active", "new", "absentNew", "absentTotal", "closed", "closedTotal", "reopened", "staleNew", "staleTotal")}
                rest = {k: v for k, v in sorted(counts.items()) if k not in main}
                lines.append(f"    {cls:<13}" + ", ".join(f"{k} {v}" for k, v in main.items()))
                if rest:
                    lines.append(f"    {'':<13}held or no change: " + ", ".join(f"{k} {v}" for k, v in rest.items()))
    lines += ["", "Rows per source and search key (ages are days since lastSeen)"]
    for row in report["perKey"]:
        ages = " ".join(f"{k}:{v}" for k, v in row["ages"].items())
        lines.append(f"  {row['provider'] or '?':<11}{row['searchKey']:<14}{'current' if row['current'] else 'older':<8}rows {row['rows']:>5}  found {row['found']:>4}  open {row['open']:>5}  "
                     f"closed {row['closed']:>3}  facts {row['withFacts']:>4}  owner {row['userData']:>3}  {_mb(row['fullBytes'])} full, {_mb(row['slimBytes'])} slim  [{ages}]")
    old = report["olderKey"]
    lines += ["", f"Older-key rows (D3, not decided): {old['rows']} rows, {old['withinDefaultWindow']} last seen within {report['defaultList']['windowDays']} days, "
              f"{old['withFacts']} with facts, {old['withBackendUserData']} with the owner's work on the backend"]
    for option in old["options"]:
        lines.append(f"  {option['option']}: file +{option['fileRowsAdded']} rows, +{_mb(option['fileBytesFull'])} full or +{_mb(option['fileBytesSlim'])} slim, default list {option['defaultListRows']} rows. {option['note']}")
    growth = report["growth"]
    lines += ["", f"Sizes. Growth {growth['rowsPerDay']} rows a day over {growth['spanDays']} days; {growth['avgFullRowBytes']} B a full row, {growth['avgSlimRowBytes']} B slim; scored adds {growth['scoredExtraBytesPerRow']} B a row. Assumes {growth['assumes']}."]
    for row in report["sizes"]:
        lines.append(f"  {row['scenario']:<84}{row['rows']:>6} rows  discovered {_mb(row['discoveredBytes']):>9}  scored {_mb(row['scoredBytes']):>9}")
    listed = report["defaultList"]
    lines.append(f"Default list ({listed['windowDays']}-day window, D1): {listed['rowsToday']} rows today, {listed['rowsUnderS5OlderKeyOut']} with older-key rows out, {listed['rowsUnderS5OlderKeyKept']} with them in.")
    stale = report["staleProjection"]
    lines.append(f"Stale projection, of {stale['rows']} absent rows: " + ", ".join(f"{v} in {k} days" for k, v in stale["daysFromNow"].items()) + f". Assumes {stale['assumes']}.")
    scoring = report["scoring"]
    lines += ["", "Scoring time (measured, no model call, nothing written)"]
    if scoring.get("error") or not scoring:
        lines.append(f"  not measured: {scoring.get('error', 'skipped')}")
    else:
        lines.append(f"  reading the ledger: {scoring['ledgerReadSeconds']} s")
        lines.append(f"  today's {scoring['viewRows']} rows: {scoring['viewScoringSeconds']} s; all {scoring['allOpenRows']} open rows with descriptions: {scoring['allOpenScoringSeconds']} s ({scoring['secondsPerRow']} s a row)")
        for name, seconds in scoring["estimates"].items():
            lines.append(f"    {name}: about {seconds} s")
    lines += ["", "Snapshot boards: what each provider can prove"]
    for provider, evidence in report["boardEvidence"].items():
        lines.append(f"  {provider}")
        lines.append("    proves today: " + "; ".join(evidence["provesToday"]))
        lines.append("    cannot prove: " + "; ".join(evidence["cannotProveToday"]))
        lines.append("    could prove:  " + evidence["couldProve"])
    latest = report["runsReplayed"][-1] if report["runsReplayed"] else None
    lines.append(f"  per board, run {latest} (this report does not read the S5b proof in boardsRead: the balance below is not proof)")
    for row in [b for b in report["boards"] if b["runId"] == latest]:
        lines.append(f"    {row['provider']:<11}{row['board']:<18} read {row['read']:>4} = kept {row['kept']:>3} + dropped {row['dropped']:>4}: {'balanced' if row['balanced'] else 'NOT BALANCED'}"
                     + (", ids known" if row["idsKnown"] else ", IDS MISSING") + (", failed" if row["failed"] else "") + (", empty" if row["empty"] else ""))
    lines += ["", "Where the owner's work is stored"]
    for item in report["storage"]:
        lines.append(f"  [{item['where']}] {item['what']}: {item['file']}")
        lines.append(f"      code: {item['code']}. Backend can protect: {item['protect']}")
    user = report["userData"]
    lines += ["", "Ads with the owner's work visible on the backend (browser-only status, insights and outreach cannot be seen here)"]
    if not user["applicationsJoined"]:
        lines.append("  APPLICATIONS NOT JOINED: Python does not read the application store. Pass the job ids with --application-job-ids FILE (see docs/DECISIONS.md, S5a).")
    lines.append("  would be: " + (", ".join(f"{k} {v}" for k, v in sorted(user["byState"].items())) or "none"))
    for row in user["rows"]:
        if row["wouldBe"] != "found":
            lines.append(f"    {row['jobId']} {row['provider']} ({row['class']}): {row['wouldBe']}; {', '.join(row['kinds'])}")
    lines.append("  held for a job no longer in the ledger: " + ", ".join(f"{k} {v}" for k, v in user["notInLedger"].items()))
    return lines


def write_report_file(root: Path, run_id: str, report: dict) -> Path:
    """The one file this may write, and only when asked: staging/<runId>/lifecycle-report.json (600, atomic)."""
    folder = staging.staging_dir(Path(root)) / run_id
    if not folder.is_dir() or not staging.RUN_ID.match(run_id):
        raise ValueError("no staging folder for this run")
    path = folder / "lifecycle-report.json"
    importer._atomic.write_text_atomic(path, json.dumps(report, indent=2), importer._atomic.PRIVATE_FILE_MODE)
    return path


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--measure-scoring":
    print(json.dumps(_measure_child(Path(sys.argv[2]))))
