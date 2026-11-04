"""The importer: what a staged run would do to the ledger, and the view that follows from it (slice S3).

A pure function of a staging run and the ledger as it stands: `plan_import` reads nothing else, writes nothing and changes
none of its arguments. It reproduces what `run_discovery` did with the same ads, by calling the same code (`dedupe_jobs`,
`job_history.apply_run`, `export_jobs.discovered_payload`); it adds no lifecycle rule. What it adds is checking: every ad is
fully validated before it can touch the ledger, a run whose staging failed is refused, and a source that did not run to its end
can never close or change an ad it did not write.

`derive_view(ledger)` rebuilds discovered_jobs.json from the ledger alone, which is what slice S4a needs to recover a view.
`dry_run` replays a staged run on the ledger as it was before the run, compares the outcome with the files the old commit wrote,
and reports every difference. Nothing here writes a live file; the only file anything may write is the report a caller
asks for, inside the run's own staging folder (`write_report`).

Order of imports is NOT controlled here, on purpose: `apply_run` stamps `lastSeen` with the run's time, so applying an older run
after a newer one moves those ads' `lastSeen` back. That is what the existing rules do (docs/DECISIONS.md, S3 as built).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import filtered_ads
import proof_reasons as proof
import staging
from dedupe_jobs import _collapse, _crosspost_key, _exact_key

_SCORING = Path(__file__).resolve().parents[1] / "job_scoring"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _SCORING / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


job_history = _load("_importer_job_history", "job_history.py")
_atomic = _load("_importer_atomic_write", "atomic_write.py")
view_guard = _load("_importer_view_guard", "view_guard.py")
stale_rule = _load("_importer_stale_rule", "stale_rule.py")
ViewError = view_guard.ViewError
derive_view = view_guard.derive_view  # the view from the ledger alone lives beside the readers that need it
ROW_WARNING = 5000  # rows in discovered_jobs.json past which the log warns; nothing is ever dropped for it (owner, S4a)

REPORT_FILE = "import-report.json"
EXAMPLES = 50  # rejected ads named in a report; the count is always complete

# --- full validation -------------------------------------------------------------------------------------------------

# Every field build_canonical_job sets, and what the commit path reads of it. A staged ad that lacks one is not whole.
TEXT_FIELDS = (
    "jobId", "provider", "source", "title", "company", "location", "site", "jobUrl", "description", "datePosted",
    "salary", "employmentType", "searchTerm", "searchLocation", "scrapedAt", "status",
)
NOT_EMPTY = ("jobId", "provider", "title")
MAX_LENGTH = {
    "jobId": 64, "provider": 40, "source": 200, "title": 500, "company": 300, "location": 500, "site": 200, "jobUrl": 2000,
    "description": 1_000_000, "datePosted": 100, "salary": 200, "employmentType": 200, "searchTerm": 300,
    "searchLocation": 300, "scrapedAt": 64, "status": 40,
}
_URL = re.compile(r"^https?://[^\s/]+\S*$")


def validate_ad(job, source: str) -> list[str]:
    """Why this staged ad cannot be imported; empty when it can. Stable codes, never silent."""
    if not isinstance(job, dict):
        return ["not_an_object"]
    found = []
    for key in TEXT_FIELDS:
        if key not in job:
            found.append(f"missing_field:{key}")
        elif not isinstance(job[key], str):
            found.append(f"not_text:{key}")
        elif key in NOT_EMPTY and not job[key].strip():
            found.append(f"empty:{key}")
        elif len(job[key]) > MAX_LENGTH[key]:
            found.append(f"too_long:{key}")
    if "isRemote" not in job:
        found.append("missing_field:isRemote")
    elif not isinstance(job["isRemote"], bool):
        found.append("not_boolean:isRemote")
    if found:
        return found
    if re.search(r"\s", job["jobId"]):
        found.append("jobid_has_whitespace")
    if job["provider"] != source:
        found.append("provider_mismatch")
    if job["jobUrl"] and not _URL.match(job["jobUrl"]):
        found.append("bad_url")
    if _parse_time(job["scrapedAt"]) is None:
        found.append("bad_scraped_at")
    try:
        json.dumps(job, allow_nan=False)
    except (TypeError, ValueError):
        found.append("not_storable_json")
    return found


def _parse_time(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


# --- the plan --------------------------------------------------------------------------------------------------------


@dataclass
class ImportResult:
    refused: list[str] = field(default_factory=list)  # why nothing would be changed; empty when the plan holds
    ledger: dict = field(default_factory=dict)  # the ledger after the import (a copy; the input is untouched)
    view: dict | None = None  # what the old commit path would have written to discovered_jobs.json
    stats: dict = field(default_factory=dict)  # apply_run's counts
    report: dict = field(default_factory=dict)
    new_by_provider: dict = field(default_factory=dict)  # ads no earlier run recorded, by the provider of the copy that won

    @property
    def ok(self) -> bool:
        return not self.refused


def import_time(run: staging.RunStage) -> str:
    """The time an import of this run is stamped with: the end of its last source, so the same run always gives the same bytes."""
    ends = [s.footer.get("finishedAt") for s in run.sources.values() if s.footer and isinstance(s.footer.get("finishedAt"), str)]
    return max(ends) if ends else str((run.manifest or {}).get("startedAt") or "")


def _previous(previous) -> tuple[dict, dict]:
    """(llmFacts by jobId, when each ad was written) from the discovered file the run replaced, as run_discovery reads it."""
    previous_jobs = previous.get("jobs") if isinstance(previous, dict) else previous
    written = (previous.get("meta") or {}).get("generatedAt") if isinstance(previous, dict) else None
    facts = {j["jobId"]: j["llmFacts"] for j in previous_jobs or [] if j.get("jobId") and j.get("llmFacts")}
    seen = {j["jobId"]: written for j in previous_jobs or [] if j.get("jobId") and written}
    return facts, seen


def board_evidence(run: staging.RunStage, name: str, stage, footer, in_doubt: bool) -> dict:
    """{board: {"complete", "listed"}} for one snapshot source: what `job_history.apply_run` may close on (S5c). A run staged before
    S5b has no `boardsRead`, so it gives none.

    Complete means the provider proved the read (`boardsRead`, S5b) AND this run's files account for every ad of the board. Without
    the second, an ad a filter dropped could look like one the board no longer lists: a discard lost, a torn line or an ad
    that failed staging stops the board from counting. `listed` is every id the board showed: kept, or dropped by a filter.
    """
    rows = (footer or {}).get("boardsRead")
    if not isinstance(rows, list) or not stage or not stage.usable:
        return {}
    kept: dict[str, list] = {}
    read: dict[str, int] = {}
    for batch in stage.batches:
        kept.setdefault(batch.part, []).extend(batch.jobs)
        read[batch.part] = read.get(batch.part, 0) + (batch.read or 0)
    dropped: dict[str, list] = {}
    for record in (run.discards.by_source(name) if run.discards else []):
        dropped.setdefault(record.get("part"), []).append(record)
    damaged = bool(run.discards is None or run.discards.torn or run.discards.unreadable_lines or run.discards.rejected)
    failed = set(footer.get("boardsFailed") or [])
    empty = set(footer.get("boardsEmpty") or [])
    found: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("board"), str):
            continue
        board = row["board"]
        records = dropped.get(board, [])
        counted = [r for r in records if r.get("counted")]
        accounted = (
            read.get(board) == row.get("read") == len(kept.get(board, [])) + len(counted)
            and all(r.get("jobId") for r in counted)
        )
        why = []
        if row.get("complete") is not True:
            why.append(proof.board_reason_code(row.get("reason")))
        if row.get("anomalies"):
            why.append(proof.BOARD_ANOMALIES)
        if board in failed:
            why.append(proof.BOARD_UNREADABLE)
        if board in empty:
            why.append(proof.BOARD_EMPTY)
        if not accounted:
            why.append(proof.FILES_DONT_ADD_UP)
        if in_doubt:
            why.append(proof.SOURCE_IN_DOUBT)
        if damaged:
            why.append(proof.DISCARDS_DAMAGED)
        found[board] = {
            "complete": not why,  # each condition above is one clause of the rule as it always was; `why` only names the ones that failed
            "why": proof.once(why) or [proof.BOARD_COMPLETE],
            "detail": row.get("reason") if isinstance(row.get("reason"), str) else None,
            "listed": {job.get("jobId") for job in kept.get(board, []) if isinstance(job, dict)} | {r["jobId"] for r in records if r.get("jobId")},
        }
    return found


def _search_proof_reasons(run: staging.RunStage, stage, footer, state: str, anomaly_codes: list[str]) -> list[str]:
    """Why a search-based source's run does NOT count towards Stale (S5f); empty means it counts. Every condition of the rule, named.

    The rule: finished with status ok, no ad lost, files that add up, and something actually read. A source can answer ok with nothing
    when it is throttled; that proves nothing."""
    why: list[str] = []
    if state == "unfinished" or not footer:
        why.append(proof.NOT_FINISHED)
    elif state == "failed":
        why.append(proof.SOURCE_FAILED)
    elif state == "partial":
        why.append(proof.SOURCE_PARTIAL)
    elif state == "skipped":
        why.append(proof.SOURCE_SKIPPED)
    why += anomaly_codes
    if stage is not None and stage.torn:
        why.append(proof.FILES_TORN)
    if footer and footer.get("discardMismatch"):
        why.append(proof.DISCARDS_MISMATCH)
    if footer and footer.get("boardsFailed"):
        why.append(proof.PARTS_FAILED)
    if run.discards is None or run.discards.torn or run.discards.unreadable_lines or run.discards.rejected:
        why.append(proof.DISCARDS_DAMAGED)
    if footer and not (footer.get("read") or 0) > 0:
        why.append(proof.NOTHING_READ)
    return proof.once(why)


def _search_run_proven(run: staging.RunStage, stage, footer, state: str, anomalies: list) -> bool:
    """A search-based source's run that counts towards Stale (S5f): `_search_proof_reasons` has nothing to say against it."""
    return not _search_proof_reasons(run, stage, footer, state, [proof.ADS_NOT_WHOLE] if anomalies else [])


def _filter_reasons(run: staging.RunStage, name: str) -> dict[str, int]:
    """How many ads this source's filters dropped, by reason (the part before a colon: `title_excluded:x` counts as `title_excluded`)."""
    counts: dict[str, int] = {}
    for reason, number in (run.discards.reasons(name) if run.discards else {}).items():
        key = reason.split(":", 1)[0]
        counts[key] = counts.get(key, 0) + number
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    top = dict(ordered[:MAX_FILTER_REASONS])
    rest = sum(number for _, number in ordered[MAX_FILTER_REASONS:])
    return {**top, **({"other": rest} if rest else {})}


def _source_proof(name: str, state: str, anomaly_codes: list[str], evidence_for_source: dict | None, search_reasons: list[str] | None, key: str) -> dict:
    """The proof of one source as the run record keeps it: {"proven": bool, "why": [codes], "boards": [...]}. Names the decision, makes none."""
    if search_reasons is not None:
        why = list(search_reasons) + ([proof.NO_SEARCH_KEY] if not key else [])  # with no key `_record_stale_evidence` records nothing
        return {"proven": not why, "why": why or [proof.PROVEN], "boards": []}
    why = []
    if state == "unfinished":
        why.append(proof.NOT_FINISHED)
    elif state in ("failed", "partial", "skipped"):
        why.append({"failed": proof.SOURCE_FAILED, "partial": proof.SOURCE_PARTIAL, "skipped": proof.SOURCE_SKIPPED}[state])
    why += anomaly_codes
    boards = evidence_for_source or {}
    if state == "complete" and not boards:
        why.append(proof.NO_BOARD_EVIDENCE)
    if boards and not all(one["complete"] for one in boards.values()):
        why.append(proof.BOARDS_NOT_PROVEN)
    rows = [{"board": str(board)[:60], "proven": one["complete"], "why": list(one["why"]), "detail": one.get("detail")}
            for board, one in sorted(boards.items(), key=lambda item: str(item[0]))[:MAX_BOARDS_KEPT]]
    return {"proven": not why and bool(boards), "why": proof.once(why) or [proof.BOARD_COMPLETE], "boards": rows}


MAX_FILTER_REASONS = 12
MAX_BOARDS_KEPT = 60


def _record_stale_evidence(ledger: dict, run: staging.RunStage, moment: str, key: str, proven_searches: list, evidence: dict) -> list[str]:
    """The ledger's record for `stale_rule.py`: this run's proven sources and boards, and when a filter-dropped ad the ledger holds was last
    listed. Additive: `lastSeen` and the rest of an entry's history do not change. Returns what was counted, for the report."""
    counted = []
    if key:
        for name in proven_searches:
            stale_rule.record_run(ledger, name, key, run.run_id, moment)
            counted.append(name)
    for name, boards in evidence.items():
        for board, one in boards.items():
            if one["complete"]:
                stale_rule.record_run(ledger, name, stale_rule.board_bucket(board), run.run_id, moment)
                counted.append(f"{name}/{board}")
    for record in (run.discards.records if run.discards else []):
        entry = ledger["jobs"].get(record.get("jobId"))
        if entry is not None and moment > (entry.get("lastListedAt") or ""):
            entry["lastListedAt"] = moment
    return counted


PARTIAL_RUNS_KEPT = 200
NO_USABLE_SOURCE = "no_usable_source"  # report["nothingSaved"] of a run that got no usable source (S8b)


def _plan_partial(result: "ImportResult", report: dict, run: staging.RunStage, manifest: dict, deduped: list[dict], moment: str) -> "ImportResult":
    """What importing a CANCELLED run does (S6): save the ads it validly collected, change nothing else.

    A cancelled run saw only part of the world, so it must not rebuild the list. `plan_import` assumes a complete run in these places,
    none of which run here: the second half of `apply_run` (every entry not found is kept, marked absent, missed or closed), the
    rewrite of `lastImport` (the view is derived from it, so it would make this run's partial list *the* list), the proven runs for the
    Stale rule and `lastListedAt`, and `filtered_ads.appliedRuns`. Here the ledger gets only `job_history.apply_partial`: each collected
    ad is added or refreshed and joins the last complete run's list. Nothing is saved when nothing was collected, when no complete run
    exists to add to, or when the run searched something other than that list did.
    """
    ledger = result.ledger
    report.update(cancelled=True, complete=False, provenRuns=[], saved=0, rejected=report.get("rejected", 0))
    for one in (report.get("proof") or {}).values():  # a cancelled run proves nothing, whatever its footers say
        one["proven"] = False
        one["why"] = proof.once([code for code in one["why"] if code not in (proof.PROVEN, proof.BOARD_COMPLETE)] + [proof.RUN_CANCELLED])
        for board in one["boards"]:
            board["proven"] = False
            board["why"] = proof.once([code for code in board["why"] if code != proof.BOARD_COMPLETE] + [proof.RUN_CANCELLED])
    info = ledger.get("lastImport")
    key = manifest.get("searchKey") or ""
    reason = None
    if not deduped:
        reason = "no_valid_ads"
    elif not isinstance(info, dict) or not info.get("runId"):
        reason = "no_complete_run"
    else:
        current = {e.get("seenUnder") for e in ledger["jobs"].values() if e.get("lastRunId") == info["runId"]}
        if len(current) == 1 and key not in current:
            reason = "other_search"
    if reason:
        report["nothingSaved"] = reason
        return result
    for job in deduped:
        if job["jobId"] not in ledger["jobs"]:
            result.new_by_provider[job.get("provider")] = result.new_by_provider.get(job.get("provider"), 0) + 1
    stats = job_history.apply_partial(ledger, deduped, now=moment, key=key, role_key=_crosspost_key, list_run_id=info["runId"])
    ledger["partialRuns"] = ((ledger.get("partialRuns") or []) + [run.run_id])[-PARTIAL_RUNS_KEPT:]
    ledger["generation"] = (ledger.get("generation") or 0) + 1
    ledger["updatedAt"] = moment
    result.stats = stats
    result.view = view_guard.derive_view(ledger)
    report.update(saved=len(deduped), ledgerChanges={k: stats[k] for k in ("new", "known", "reopened", "changed", "carriedFacts")})
    return result


def evidence_block(report: dict, stats: dict) -> dict:
    """The `import` block of a new run record (S7a): what the import saved, and what it knew about each source. Report only: it reads the
    plan's answers and makes none. Counts only; no ad, title, link or description is in it.

    kind: `complete` (an ordinary import), `partial` (a cancelled run, S6), `nothing` (a cancelled run that saved nothing).
    saved is every ad written to the list (collected, whole, not a duplicate), refreshed ones included; new is the part the ledger had
    never seen; refreshed is the rest.
    """
    kind = "nothing" if report.get("nothingSaved") else "partial" if report.get("cancelled") else "complete"
    saved = int(report.get("saved") or 0)
    new = min(saved, int(stats.get("new") or 0))
    block = {
        "kind": kind, "complete": bool(report.get("complete")), "saved": saved, "new": new, "refreshed": saved - new,
        "duplicatesRemoved": int(report.get("duplicatesRemoved") or 0), "crosspostsMerged": int(report.get("crosspostsMerged") or 0),
        "rejected": int(report.get("rejected") or 0),
        "sources": [
            {"name": name, "proof": one, "filterReasons": (report.get("filterReasons") or {}).get(name, {})}
            for name, one in (report.get("proof") or {}).items()
        ],
    }
    if kind == "complete":
        block["ledger"] = {key: int(stats.get(key) or 0) for key in ("closed", "absent", "reopened", "changed", "known")}
    if report.get("nothingSaved"):
        block["nothingSaved"] = str(report["nothingSaved"])
    return block


def plan_import(
    run: staging.RunStage, ledger: dict, previous=None, *, now: str | None = None, force: bool = False,
    allow_older: bool = False, require_usable: bool = False,
) -> ImportResult:
    """What importing this staged run would do. `ledger` is the ledger as it stands, `previous` the discovered file the run
    replaced (None: there was none, or it is not known; then `report["replayExact"]` says so). Nothing is written or mutated.

    A ledger whose last import is this very run is returned as it is (`report["alreadyImported"]`): the same run twice gives the same
    bytes. That is the only memory the importer keeps, and it is not an ordering rule: any other run is applied as `apply_run` applies
    it. `force` applies the run again anyway (the tests use it to show that apply_run alone is idempotent).

    **Order guard (S4a, owner decision):** a run that started before `ledger.lastImport.startedAt` is refused (`older_run`), because
    applying it would move `lastSeen` back. `allow_older=True` is the explicit override for recovery; nothing else passes it.

    **No usable source (S8b, owner decision):** with `require_usable`, a run that was not cancelled, asked at least one source to run and got
    no usable source (every one failed, partial, unfinished, skipped or held as not run) changes nothing: `report["nothingSaved"]` is
    `no_usable_source` and the ledger comes back as it went in. Such a run has seen nothing, so it must not hold, close or rebuild anything.
    Opt-in: the live path and `import_run.py --import` pass it; the plan itself, and every older caller, behave as before.
    """
    result = ImportResult(ledger=copy.deepcopy(ledger))
    report = result.report = {"runId": run.run_id, "sources": [], "reasons": {}, "rejectedExamples": []}
    manifest = run.manifest
    if not isinstance(manifest, dict):
        result.refused.append("no_manifest: the run's run.json is missing or unreadable")
        return result
    if manifest.get("version") != staging.VERSION:
        result.refused.append(f"unsupported_version: {manifest.get('version')!r}")
        return result
    if run.status is not None and run.status.get("ok") is False:
        problems = "; ".join(str(p) for p in (run.status.get("problems") or [])[:3])
        result.refused.append(f"staging_failed: this run's staging did not work, so it is not a complete scrape ({problems})")
        return result
    report["stagingStatus"] = "ok" if run.status else "unfinished"  # no status.json: the run never reached its end
    last = ledger.get("lastImport") if isinstance(ledger, dict) else None
    if run.cancelled is not None and not force and run.run_id in (ledger.get("partialRuns") or []):
        report.update(alreadyImported=True, complete=None, cancelled=True, saved=0)
        return result
    if not force and isinstance(last, dict) and last.get("runId") == run.run_id:
        report.update(alreadyImported=True, complete=None)
        result.stats = copy.deepcopy((last.get("meta") or {}).get("history") or {})
        result.view = derive_view(result.ledger)
        return result
    this_start, last_start = _parse_time(manifest.get("startedAt")), _parse_time((last or {}).get("startedAt"))
    if not allow_older and not force and isinstance(last, dict) and this_start and last_start and this_start < last_start:
        result.refused.append(
            f"older_run: run {run.run_id} started {manifest.get('startedAt')}, before the last imported run "
            f"{last.get('runId')} ({last.get('startedAt')}). Importing it would move lastSeen backwards and could reopen ads "
            "the newer run closed. Recovery only: pass allow_older (import_run.py --allow-older)."
        )
        return result

    moment = now or import_time(run)
    if _parse_time(moment) is None:
        result.refused.append("no_import_time: the run has no usable start or end time to stamp an import with")
        return result
    providers = [p for p in manifest.get("providers") or [] if isinstance(p, str)]
    reasons: dict[str, int] = {}
    all_jobs: list[dict] = []
    provider_counts: dict[str, int] = {}
    failed_boards: dict[str, set[str] | None] = {}
    empty_boards: dict[str, set[str]] = {}
    not_run: set[str] = set()
    evidence: dict[str, dict] = {}
    proven_searches: list[str] = []
    rejected_total = 0

    for name in providers:
        stage = run.sources.get(name)
        footer = stage.footer if stage and stage.usable else None
        status = footer.get("status") if footer else None
        state = (
            "unfinished" if footer is None
            else {"ok": "complete", "partial": "partial", "failed": "failed", "skipped": "skipped"}.get(status, "unfinished")
        )
        valid, rejected = [], []
        for job in (stage.jobs if stage and stage.usable else []):
            found = validate_ad(job, name)
            if found:
                rejected.append((job, found))
            else:
                valid.append(job)
        for job, found in rejected:
            for code in found:
                reasons[f"invalid:{code}"] = reasons.get(f"invalid:{code}", 0) + 1
            if len(report["rejectedExamples"]) < EXAMPLES:
                report["rejectedExamples"].append({
                    "source": name, "jobId": job.get("jobId") if isinstance(job, dict) else None,
                    "title": job.get("title") if isinstance(job, dict) else None, "reasons": found,
                })
        rejected_total += len(rejected)
        lost = (stage.rejected_ads if stage else 0) + (footer.get("invalid", 0) if footer else 0) + len(rejected)
        anomalies = []
        anomaly_codes = []
        if footer and footer.get("mismatch"):
            anomalies.append("staged ads differ from what the provider returned")
            anomaly_codes.append(proof.STAGED_DIFFERS)
        if lost:
            anomalies.append(f"{lost} ads not whole")
            anomaly_codes.append(proof.ADS_NOT_WHOLE)
        # A source that did not run to its end, or whose staged ads are not all there, is not evidence that any other ad is gone.
        if state in ("unfinished", "failed", "skipped") or anomalies:
            not_run.add(name)
        if name in job_history.CLOSURE_PROVIDERS:
            in_doubt = name in not_run or bool(stage and stage.torn) or bool(footer and footer.get("discardMismatch"))
            evidence[name] = board_evidence(run, name, stage, footer, in_doubt)
        else:
            search_reasons = _search_proof_reasons(run, stage, footer, state, anomaly_codes)
            if not search_reasons:
                proven_searches.append(name)
        if footer:
            if footer.get("boardsFailed"):
                failed_boards[name] = set(footer["boardsFailed"])
            elif status == "failed":
                failed_boards[name] = None
            if footer.get("boardsEmpty"):
                empty_boards[name] = set(footer["boardsEmpty"])
        provider_counts[name] = len(valid)
        all_jobs.extend(valid)
        report.setdefault("proof", {})[name] = _source_proof(
            name, state, anomaly_codes, evidence.get(name), None if name in job_history.CLOSURE_PROVIDERS else search_reasons,
            manifest.get("searchKey") or "",
        )
        report.setdefault("filterReasons", {})[name] = _filter_reasons(run, name)
        report["sources"].append({
            "name": name, "state": state, "staged": len(stage.jobs) if stage and stage.usable else 0,
            "imported": len(valid), "rejected": len(rejected), "heldAsNotRun": name in not_run, "anomalies": anomalies,
            "torn": bool(stage and stage.torn),
        })
    extra = sorted(set(run.sources) - set(providers))
    if extra:
        report["unlistedSourceFiles"] = extra  # files the run's manifest does not name: ignored

    after_exact = _collapse(all_jobs, _exact_key)
    deduped = _collapse(after_exact, _crosspost_key)
    report["duplicatesRemoved"] = len(all_jobs) - len(after_exact)
    report["crosspostsMerged"] = len(after_exact) - len(deduped)

    if run.cancelled is not None:
        return _plan_partial(result, report, run, manifest, deduped, moment)

    # Usable: the source ran to its end (state complete) and its ads are whole (not held as not run). Failed, partial, skipped and unfinished are not.
    if require_usable and providers and not any(one["state"] == "complete" and not one["heldAsNotRun"] for one in report["sources"]):
        report.update(complete=False, saved=0, provenRuns=[], nothingSaved=NO_USABLE_SOURCE)
        for one in (report.get("proof") or {}).values():
            one["proven"] = False
        result.ledger = copy.deepcopy(ledger)  # whatever was worked out above is dropped: this run changes nothing
        return result

    previous_facts, seen_before = _previous(previous)
    for job in deduped:
        if job["jobId"] not in result.ledger["jobs"]:
            result.new_by_provider[job.get("provider")] = result.new_by_provider.get(job.get("provider"), 0) + 1
    to_write, stats = job_history.apply_run(
        result.ledger, deduped, now=moment, providers_returned=provider_counts, key=manifest.get("searchKey") or "",
        role_key=_crosspost_key, previous_facts=previous_facts, seen_before=seen_before, failed_boards=failed_boards,
        empty_boards=empty_boards, sources_not_run=not_run, run_id=run.run_id, prune=False, board_evidence=evidence,
    )
    result.stats = stats
    report["provenRuns"] = _record_stale_evidence(result.ledger, run, moment, manifest.get("searchKey") or "", proven_searches, evidence)
    meta = {
        "searchTerms": manifest.get("terms") or [], "locations": manifest.get("locations") or [],
        "remoteFilters": manifest.get("remoteFilters") or [], "country": manifest.get("country") or "",
        "providers": providers, "providerCounts": provider_counts, "rawCount": len(all_jobs),
        "dedupedCount": len(deduped), "history": stats, "sourceRunId": run.run_id,
    }
    generation = (result.ledger.get("generation") or 0) + 1
    result.ledger["generation"] = generation
    result.ledger["lastImport"] = {"runId": run.run_id, "at": moment, "startedAt": manifest.get("startedAt"), "meta": meta, "marksNotFound": True}
    result.ledger["updatedAt"] = moment
    result.view = view_guard.view_payload(to_write, meta, moment, generation)
    if len(to_write) > ROW_WARNING:
        report["warnings"] = [f"discovered_jobs.json would hold {len(to_write)} rows (more than {ROW_WARNING}); nothing is dropped for it"]

    report.update(
        rejected=rejected_total,
        saved=len(deduped),
        thinDescriptionReplaced=stats.get("keptFullerDescription", 0),
        heldFailedBoard=stats.get("keptFailedBoard", 0),
        heldEmptyBoard=stats.get("keptEmptyBoard", 0),
        heldSourceNotRun=stats.get("keptSourceNotRun", 0),
        heldUnproven=stats.get("keptUnproven", 0),
        heldBoardNotRead=stats.get("keptBoardNotRead", 0),
        listedButFiltered=stats.get("listedButFiltered", 0),
        boardsProvenComplete=sorted(f"{name}/{board}" for name, boards in evidence.items() for board, one in boards.items() if one["complete"]),
        incompleteSources=[s["name"] for s in report["sources"] if s["state"] != "complete" or s["anomalies"]],
        ledgerChanges={k: stats[k] for k in ("new", "known", "reopened", "changed", "absent", "closed", "carriedFacts")},
        reasons=dict(sorted(reasons.items())),
        complete=not rejected_total and not any(s["state"] != "complete" or s["anomalies"] for s in report["sources"])
        and report["stagingStatus"] == "ok",
    )
    return result


def ledger_bytes(ledger: dict) -> bytes:
    """The ledger exactly as the commit writes it."""
    return view_guard.serialize_ledger(ledger).encode("utf-8")


# --- the dry run -----------------------------------------------------------------------------------------------------

LEDGER_STAMPS = ("lastRunId", "lastRunPos", "heldRunId", "lastListedAt")  # what the importer adds to an entry
EXCLUDED = [
    "ledger.updatedAt (the time of the save)", "ledger.lastImport (the importer's own record of the run)",
    "ledger.jobs.*.lastRunId / lastRunPos / heldRunId / lastListedAt (the importer's stamps, from which the view is derived)",
    "ledger.sourceRuns (the importer's record of proven runs for the Stale rule; absent before S5f)",
    "discovered_jobs.json jobs.*.isStale (derived from that record; absent before S5f)",
    "ledger.generation / discovered_jobs.json meta.ledgerGeneration (the counter that keeps the two together; absent before S4a)",
    "discovered_jobs.json meta.generatedAt (the time of the save)",
    "discovered_jobs.json jobs.*.notFoundThisRun (derived from the importer's stamps; absent before S5d2)",
    "discovered_jobs.json meta.sourceRunId (checked to be the run's id instead)",
]
MAX_STORED_DIFFERENCES = 500


class Differences:
    def __init__(self) -> None:
        self.total = 0
        self.items: list[str] = []

    def add(self, text: str) -> None:
        self.total += 1
        if len(self.items) < MAX_STORED_DIFFERENCES:
            self.items.append(text)


def _show(value, limit: int = 90) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def diff_json(a, b, path: str, out: Differences, label_a: str, label_b: str) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in a.keys() - b.keys():
            out.add(f"{path}.{key}: only in {label_a}")
        for key in b.keys() - a.keys():
            out.add(f"{path}.{key}: only in {label_b}")
        for key in a.keys() & b.keys():
            diff_json(a[key], b[key], f"{path}.{key}", out, label_a, label_b)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.add(f"{path}: {len(a)} items in {label_a}, {len(b)} in {label_b}")
        for index, (x, y) in enumerate(zip(a, b)):
            diff_json(x, y, f"{path}[{index}]", out, label_a, label_b)
    elif a != b or type(a) is not type(b):
        out.add(f"{path}: {label_a}={_show(a)} {label_b}={_show(b)}")


def normalized_ledger(ledger: dict) -> dict:
    out = copy.deepcopy(ledger)
    for key in ("updatedAt", "lastImport", "generation", stale_rule.FIELD):
        out.pop(key, None)
    for entry in out.get("jobs", {}).values():
        for stamp in LEDGER_STAMPS:
            entry.pop(stamp, None)
    return out


def compare_ledgers(a: dict, b: dict, label_a: str, label_b: str) -> Differences:
    out = Differences()
    a, b = normalized_ledger(a), normalized_ledger(b)
    diff_json({k: v for k, v in a.items() if k != "jobs"}, {k: v for k, v in b.items() if k != "jobs"}, "ledger", out, label_a, label_b)
    ja, jb = a.get("jobs", {}), b.get("jobs", {})
    for job_id in sorted(ja.keys() - jb.keys()):
        out.add(f"ledger.jobs.{job_id}: only in {label_a}")
    for job_id in sorted(jb.keys() - ja.keys()):
        out.add(f"ledger.jobs.{job_id}: only in {label_b}")
    for job_id in sorted(ja.keys() & jb.keys()):
        diff_json(ja[job_id], jb[job_id], f"ledger.jobs.{job_id}", out, label_a, label_b)
    if ja.keys() == jb.keys() and list(ja) != list(jb):
        out.add("ledger.jobs: the entries are in a different order")
    return out


def compare_views(a: dict, b: dict, label_a: str, label_b: str) -> Differences:
    out = Differences()
    meta_a = {k: v for k, v in (a.get("meta") or {}).items() if k not in ("generatedAt", "sourceRunId", "ledgerGeneration")}
    meta_b = {k: v for k, v in (b.get("meta") or {}).items() if k not in ("generatedAt", "sourceRunId", "ledgerGeneration")}
    diff_json(meta_a, meta_b, "discovered.meta", out, label_a, label_b)

    def keyed(jobs):
        seen: dict[str, int] = {}
        keys, by_key = [], {}
        for job in jobs:
            base = str(job.get("jobId"))
            seen[base] = seen.get(base, 0) + 1
            key = base if seen[base] == 1 else f"{base}#{seen[base]}"
            keys.append(key)
            by_key[key] = {k: v for k, v in job.items() if k not in (job_history.NOT_FOUND_MARK, job_history.STALE_MARK)}
        return keys, by_key

    keys_a, map_a = keyed(a.get("jobs") or [])
    keys_b, map_b = keyed(b.get("jobs") or [])
    for key in keys_a:
        if key not in map_b:
            out.add(f"discovered.jobs.{key}: only in {label_a}")
    for key in keys_b:
        if key not in map_a:
            out.add(f"discovered.jobs.{key}: only in {label_b}")
    for key in keys_a:
        if key in map_b:
            diff_json(map_a[key], map_b[key], f"discovered.jobs.{key}", out, label_a, label_b)
    if set(keys_a) == set(keys_b) and keys_a != keys_b:
        out.add("discovered.jobs: the same ads in a different order")
    return out


def _load_json(path: Path | None):
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@dataclass
class DryRun:
    run_id: str
    errors: list[str] = field(default_factory=list)
    result: ImportResult | None = None
    comparable: bool = False  # the committed files are this run's
    committed_run_id: str | None = None
    replay_exact: bool = True
    time_used: str = ""
    ledger_diff: Differences = field(default_factory=Differences)
    view_diff: Differences = field(default_factory=Differences)
    derived_vs_replay: Differences = field(default_factory=Differences)
    derived_vs_committed: Differences = field(default_factory=Differences)
    usage: dict = field(default_factory=dict)

    @property
    def difference_count(self) -> int:
        return sum(d.total for d in (self.ledger_diff, self.view_diff, self.derived_vs_replay, self.derived_vs_committed))


def _infer_commit_time(committed_ledger: dict) -> str | None:
    """The `now` the commit used: the importer records it (`lastImport.at`); for a ledger the old path wrote, every ad found in
    that run has it as `lastSeen` and nothing is later."""
    recorded = (committed_ledger.get("lastImport") or {}).get("at")
    if isinstance(recorded, str):
        return recorded
    stamps = []
    for entry in (committed_ledger.get("jobs") or {}).values():
        for key in ("lastSeen", "closedAt"):
            if isinstance(entry.get(key), str):
                stamps.append(entry[key])
    return max(stamps) if stamps else None


def dry_run(root: Path, run_id: str) -> DryRun:
    """Replay a staged run on the ledger as it was before the run and compare with what the old commit wrote. Writes nothing."""
    root = Path(root)
    out = DryRun(run_id=run_id, usage=staging.usage(root))
    run = staging.read_run(root, run_id)
    if run is None:
        out.errors.append(f"no staging folder for run {run_id!r}")
        return out
    manifest = run.manifest or {}
    if "ledgerBefore" not in manifest:
        out.errors.append("this run's staging does not say what the ledger was before it")
        return out
    if manifest["ledgerBefore"] is None:
        ledger_before = job_history.empty_ledger()
    else:
        ledger_before = _load_json(run.ledger_before)
        if not isinstance(ledger_before, dict) or not isinstance(ledger_before.get("jobs"), dict):
            out.errors.append("the ledger as it was before the run is missing or unreadable in staging")
            return out
    if "discoveredBefore" not in manifest:
        previous = None
        out.replay_exact = False  # staged before the discovered file was kept: llmFacts and first-seen dates may differ
    elif manifest["discoveredBefore"] is None:
        previous = None
    else:
        previous = _load_json(run.discovered_before)
        if previous is None:
            out.errors.append("the discovered file as it was before the run is missing or unreadable in staging")
            return out

    jobs_dir = staging.jobs_dir(root)
    committed_view = _load_json(jobs_dir / "discovered_jobs.json")
    committed_ledger = _load_json(jobs_dir / "job_history.json")
    out.committed_run_id = ((committed_view or {}).get("meta") or {}).get("sourceRunId") if isinstance(committed_view, dict) else None
    out.comparable = bool(
        isinstance(committed_view, dict) and isinstance(committed_ledger, dict) and out.committed_run_id == run_id
    )
    now = (_infer_commit_time(committed_ledger) if out.comparable else None) or import_time(run)
    out.time_used = now

    result = out.result = plan_import(run, ledger_before, previous, now=now)
    if not result.ok:
        out.errors += result.refused
        return out

    try:
        derived = derive_view(result.ledger)
        out.derived_vs_replay = compare_views(derived, result.view, "derived", "replay")
        again = derive_view(result.ledger)
        if json.dumps(derived, sort_keys=False) != json.dumps(again, sort_keys=False):
            out.derived_vs_replay.add("derive_view gave two different answers for one ledger")
    except ViewError as exc:
        out.errors.append(str(exc))
        derived = None
    if out.comparable:
        out.ledger_diff = compare_ledgers(result.ledger, committed_ledger, "replay", "committed")
        out.view_diff = compare_views(result.view, committed_view, "replay", "committed")
        if derived is not None:
            out.derived_vs_committed = compare_views(derived, committed_view, "derived", "committed")
    return out


def write_report(root: Path, run_id: str, dry: DryRun) -> Path:
    """The one file a dry run may write, and only when asked: staging/<runId>/import-report.json (600, atomic)."""
    folder = staging.staging_dir(Path(root)) / run_id
    if not folder.is_dir() or not staging.RUN_ID.match(run_id):
        raise ValueError("no staging folder for this run")
    body = {
        "runId": run_id, "errors": dry.errors, "comparable": dry.comparable, "committedRunId": dry.committed_run_id,
        "replayExact": dry.replay_exact, "timeUsed": dry.time_used, "differences": dry.difference_count,
        "excluded": EXCLUDED, "report": dry.result.report if dry.result else None,
        "ledgerDifferences": dry.ledger_diff.items, "viewDifferences": dry.view_diff.items,
        "derivedVsReplay": dry.derived_vs_replay.items, "derivedVsCommitted": dry.derived_vs_committed.items,
    }
    path = folder / REPORT_FILE
    _atomic.write_text_atomic(path, json.dumps(body, indent=2, default=str), _atomic.PRIVATE_FILE_MODE)
    return path


# --- the real import --------------------------------------------------------------------------------------------------------


@dataclass
class ImportOutcome:
    ok: bool
    run_id: str
    refused: list[str] = field(default_factory=list)
    result: ImportResult | None = None
    committed: bool = False  # the ledger and the view were written
    saved: int = 0  # a cancelled run: how many collected ads were saved
    generation: int | None = None
    pruned: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def import_staged_run(root: Path, run_id: str, *, allow_older: bool = False, require_usable: bool = False) -> ImportOutcome:
    """Import a staged run for real: the one commit of the live path. The caller holds the pipeline lock.

    Read the ledger and the discovered file the run replaced, plan the import (full validation, the order guard, the same rules
    as ever), write the ledger and then the view derived from it (inside the view lock), record the run's dropped ads
    (filtered_ads.py), mark the run imported, prune old staging. Refusals change nothing. A stop between the two writes leaves a view
    one generation behind; the next reader rebuilds it. A stop after them is finished by importing the run again, which counts its
    dropped ads once. Dropped ads that cannot be recorded never stop an import: the run stays out of pruning, so they are not lost.
    Import is final: scoring does not undo it, and a failed scoring is redone with Re-score alone.
    """
    root = Path(root)
    out = ImportOutcome(ok=False, run_id=run_id)
    run = staging.read_run(root, run_id)
    if run is None:
        out.refused.append(f"no_staging: there is no staging folder for run {run_id!r}")
        return out
    jobs_file = staging.jobs_dir(root) / "discovered_jobs.json"
    ledger_file = job_history.ledger_path(jobs_file)
    ledger = job_history.load(ledger_file)  # an unreadable ledger is set aside, as it always was; the run then starts from none
    manifest = run.manifest or {}
    previous = None
    if manifest.get("discoveredBefore"):
        previous = _load_json(run.discovered_before)
    result = out.result = plan_import(run, ledger, previous, allow_older=allow_older, require_usable=require_usable)
    if not result.ok:
        out.refused += result.refused
        return out
    unusable = result.report.get("nothingSaved") == NO_USABLE_SOURCE and run.cancelled is None
    nothing = bool(run.cancelled is not None and result.report.get("nothingSaved")) or unusable
    out.saved = int(result.report.get("saved") or 0)
    if nothing:
        pass  # a cancelled run that collected nothing usable, or a run with no usable source: no write at all, not even a generation
    elif not result.report.get("alreadyImported"):
        view_guard.commit(result.ledger, jobs_file, ledger_file)
        out.committed = True
    else:
        view_guard.ensure(jobs_file, ledger_file)
    out.generation = result.ledger.get("generation")
    try:
        if unusable:
            pass  # nothing was imported, so its dropped ads are not counted either
        elif run.cancelled is None:
            filtered_ads.record_run(root, run, import_time(run), result.ledger["jobs"])
        elif out.saved or result.report.get("alreadyImported"):
            # A cancelled run's dropped ads are saved once, under `partialRuns`; `appliedRuns` never holds its id.
            filtered_ads.record_run(root, run, import_time(run), result.ledger["jobs"], partial=True)
    except Exception as exc:  # noqa: BLE001 - the ledger is written and stays written; only the pruning of this run waits
        out.warnings.append(f"The dropped ads of run {run_id} were not recorded ({type(exc).__name__}).")
    staging.mark_imported(root, run_id, {"generation": out.generation, "committed": out.committed, **({"cancelled": True, "saved": out.saved} if run.cancelled is not None else {}), **({"nothing": NO_USABLE_SOURCE} if unusable else {})})
    waiting = filtered_ads.unrecorded(root)
    held = sorted(r for r in waiting if staging.is_imported(root, r))
    if held:
        out.warnings.append(f"{len(held)} imported run(s) are not in {filtered_ads.FILE_NAME} and stay in staging; import_run.py --backfill-filtered records them.")
    out.pruned = staging.prune(root, protect=waiting)
    out.usage = staging.usage(root)
    out.ok = True
    return out
