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

import staging
from dedupe_jobs import _collapse, _crosspost_key, _exact_key
from export_jobs import discovered_payload

_SCORING = Path(__file__).resolve().parents[1] / "job_scoring"
_history_spec = importlib.util.spec_from_file_location("_importer_job_history", _SCORING / "job_history.py")
job_history = importlib.util.module_from_spec(_history_spec)
_history_spec.loader.exec_module(job_history)
_atomic_spec = importlib.util.spec_from_file_location("_importer_atomic_write", _SCORING / "atomic_write.py")
_atomic = importlib.util.module_from_spec(_atomic_spec)
_atomic_spec.loader.exec_module(_atomic)

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


class ViewError(Exception):
    """The ledger cannot give a view: it has never been imported from a run."""


@dataclass
class ImportResult:
    refused: list[str] = field(default_factory=list)  # why nothing would be changed; empty when the plan holds
    ledger: dict = field(default_factory=dict)  # the ledger after the import (a copy; the input is untouched)
    view: dict | None = None  # what the old commit path would have written to discovered_jobs.json
    stats: dict = field(default_factory=dict)  # apply_run's counts
    report: dict = field(default_factory=dict)

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


def plan_import(
    run: staging.RunStage, ledger: dict, previous=None, *, now: str | None = None, force: bool = False
) -> ImportResult:
    """What importing this staged run would do. `ledger` is the ledger as it stands, `previous` the discovered file the run
    replaced (None: there was none, or it is not known; then `report["replayExact"]` says so). Nothing is written or mutated.

    A ledger whose last import is this very run is returned as it is (`report["alreadyImported"]`): the same run twice gives the same
    bytes. That is the only memory the importer keeps, and it is not an ordering rule: any other run is applied as `apply_run` applies
    it, in whatever order it is given. `force` applies the run again anyway (the tests use it to show that apply_run alone is idempotent).
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
    if not force and isinstance(last, dict) and last.get("runId") == run.run_id:
        report.update(alreadyImported=True, complete=None)
        result.stats = copy.deepcopy((last.get("meta") or {}).get("history") or {})
        result.view = derive_view(result.ledger)
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
        if footer and footer.get("mismatch"):
            anomalies.append("staged ads differ from what the provider returned")
        if lost:
            anomalies.append(f"{lost} ads not whole")
        # A source that did not run to its end, or whose staged ads are not all there, is not evidence that any other ad is gone.
        if state in ("unfinished", "failed", "skipped") or anomalies:
            not_run.add(name)
        if footer:
            if footer.get("boardsFailed"):
                failed_boards[name] = set(footer["boardsFailed"])
            elif status == "failed":
                failed_boards[name] = None
            if footer.get("boardsEmpty"):
                empty_boards[name] = set(footer["boardsEmpty"])
        provider_counts[name] = len(valid)
        all_jobs.extend(valid)
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

    previous_facts, seen_before = _previous(previous)
    to_write, stats = job_history.apply_run(
        result.ledger, deduped, now=moment, providers_returned=provider_counts, key=manifest.get("searchKey") or "",
        role_key=_crosspost_key, previous_facts=previous_facts, seen_before=seen_before, failed_boards=failed_boards,
        empty_boards=empty_boards, sources_not_run=not_run, run_id=run.run_id,
    )
    result.stats = stats
    meta = {
        "searchTerms": manifest.get("terms") or [], "locations": manifest.get("locations") or [],
        "remoteFilters": manifest.get("remoteFilters") or [], "country": manifest.get("country") or "",
        "providers": providers, "providerCounts": provider_counts, "rawCount": len(all_jobs),
        "dedupedCount": len(deduped), "history": stats, "sourceRunId": run.run_id,
    }
    result.ledger["lastImport"] = {"runId": run.run_id, "at": moment, "startedAt": manifest.get("startedAt"), "meta": meta}
    result.ledger["updatedAt"] = moment
    result.view = _view_from(to_write, meta, moment)

    report.update(
        rejected=rejected_total,
        thinDescriptionReplaced=stats.get("keptFullerDescription", 0),
        heldFailedBoard=stats.get("keptFailedBoard", 0),
        heldEmptyBoard=stats.get("keptEmptyBoard", 0),
        heldSourceNotRun=stats.get("keptSourceNotRun", 0),
        incompleteSources=[s["name"] for s in report["sources"] if s["state"] != "complete" or s["anomalies"]],
        ledgerChanges={k: stats[k] for k in ("new", "known", "reopened", "changed", "closed", "carriedFacts")},
        reasons=dict(sorted(reasons.items())),
        complete=not rejected_total and not any(s["state"] != "complete" or s["anomalies"] for s in report["sources"])
        and report["stagingStatus"] == "ok",
    )
    return result


def _view_from(jobs: list[dict], meta: dict, generated_at: str) -> dict:
    return discovered_payload(
        jobs, search_terms=meta["searchTerms"], locations=meta["locations"], remote_filters=meta["remoteFilters"],
        raw_count=meta["rawCount"], country=meta["country"], source_run_id=meta["sourceRunId"], providers=meta["providers"],
        provider_counts=meta["providerCounts"], deduped_count=meta["dedupedCount"], history=meta["history"],
        generated_at=generated_at,
    )


def ledger_bytes(ledger: dict) -> bytes:
    """The ledger exactly as job_history.save writes it."""
    return json.dumps(ledger, indent=2).encode("utf-8")


# --- the view, from the ledger alone ----------------------------------------------------------------------------------


def derive_view(ledger: dict) -> dict:
    """discovered_jobs.json as it follows from this ledger: the same jobs, in the same order, as the import that left it.

    Reads only the ledger (the stamps `apply_run(run_id=...)` and `lastImport`). Mutates nothing; the same ledger always gives the same
    output. Raises ViewError for a ledger that no import has produced.
    """
    info = ledger.get("lastImport") if isinstance(ledger, dict) else None
    if not isinstance(info, dict) or not info.get("runId") or not isinstance(info.get("meta"), dict):
        raise ViewError("this ledger has no lastImport: no import produced it, so no view can be derived")
    run_id, now = info["runId"], info["at"]
    moment = _parse_time(now)
    entries = ledger["jobs"]
    found = sorted((e for e in entries.values() if e.get("lastRunId") == run_id), key=lambda e: e.get("lastRunPos", 0))
    found_ids = {entry["job"]["jobId"] for entry in found}

    def record(entry: dict, closed: bool) -> dict:
        out = job_history._annotate(entry["job"], entry, now=moment, closed=closed)
        if entry.get("llmFacts"):
            out["llmFacts"] = entry["llmFacts"]
        return out

    jobs = [record(e, False) for e in found]
    jobs += [record(e, False) for e in entries.values() if e.get("heldRunId") == run_id and e["job"]["jobId"] not in found_ids]
    for job_id, entry in entries.items():
        closed_at = job_history._parse(entry.get("closedAt"))
        if not closed_at:
            continue
        age = moment - closed_at
        if age > timedelta(days=job_history.PRUNE_AFTER_DAYS):
            continue
        if age <= timedelta(days=job_history.CLOSED_KEEP_DAYS) and job_id not in found_ids:
            jobs.append(record(entry, True))
    meta = copy.deepcopy(info["meta"])
    return copy.deepcopy(_view_from(jobs, meta, now))


# --- the dry run -----------------------------------------------------------------------------------------------------

LEDGER_STAMPS = ("lastRunId", "lastRunPos", "heldRunId")  # what the importer adds to an entry
EXCLUDED = [
    "ledger.updatedAt (the time of the save)", "ledger.lastImport (the importer's own record of the run)",
    "ledger.jobs.*.lastRunId / lastRunPos / heldRunId (the importer's stamps, from which the view is derived)",
    "discovered_jobs.json meta.generatedAt (the time of the save)",
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
    for key in ("updatedAt", "lastImport"):
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
    meta_a = {k: v for k, v in (a.get("meta") or {}).items() if k not in ("generatedAt", "sourceRunId")}
    meta_b = {k: v for k, v in (b.get("meta") or {}).items() if k not in ("generatedAt", "sourceRunId")}
    diff_json(meta_a, meta_b, "discovered.meta", out, label_a, label_b)

    def keyed(jobs):
        seen: dict[str, int] = {}
        keys, by_key = [], {}
        for job in jobs:
            base = str(job.get("jobId"))
            seen[base] = seen.get(base, 0) + 1
            key = base if seen[base] == 1 else f"{base}#{seen[base]}"
            keys.append(key)
            by_key[key] = job
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
    """The `now` the old commit used: every ad found in that run has it as `lastSeen`, and nothing is later."""
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
