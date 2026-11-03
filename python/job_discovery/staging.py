"""Staging: the ads a scrape has collected, written while it collects.

A scrape writes data/jobs/staging/<runId>/<source>.jsonl as it goes and touches no other data file. A later import (not built
yet) reads these files, so a run that was cancelled or killed still leaves every ad it had written. One line is one record:

    {"t":"header", "version", "runId", "source", "searchKey", "terms", "locations", "country", "remoteFilters", "startedAt"}
    {"t":"batch",  "part", "read", "jobs":[canonical ad, ...]}     one search, board, feed, page or ad, fsynced as a whole
    {"t":"footer", "status", "complete", "read", "kept", "total", "staged", "invalid", ...}

A source with a header and no footer is unfinished: it was stopped, and the ads it holds say nothing about what else the
source lists. A footer with `complete` false (a partial or failed source) says the same. Only a footer with
`complete: true` means the source ran to its end.

A line is the unit of "written": the reader ignores a last line with no newline (a torn write) and any line that does not
parse, and drops an ad that fails `problems()`, so what it returns is always whole. Nothing here ever raises into a run:
a writer that cannot write disables itself, logs once and lets the scrape carry on.

Next to the folder the run keeps `<runId>.ledger-before.json` and `<runId>.discovered-before.json`, hard links to the two
files as they were when the run began. Both are replaced by rename, never rewritten in place, so the links keep the old bytes
and an import can be replayed on exactly what the run started from.

`status.json` in a run's folder says whether staging itself worked. `imported.json` says the run was imported (written only by a
real import). Staging is removed by status (`prune`): only runs that were imported, and only beyond the newest KEEP_IMPORTED of
them. A run that waits for an import or for recovery, and a run whose staging failed (evidence, never importable), stay.
`usage()` says how much room staging takes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Loaded by path, as export_jobs does: job_scoring on sys.path would let its modules shadow this package's.
_atomic_spec = importlib.util.spec_from_file_location(
    "_staging_atomic_write", Path(__file__).resolve().parents[1] / "job_scoring" / "atomic_write.py"
)
_atomic = importlib.util.module_from_spec(_atomic_spec)
_atomic_spec.loader.exec_module(_atomic)

logger = logging.getLogger(__name__)

VERSION = 1
STAGING_DIR = "staging"
MANIFEST = "run.json"
DISCARDS = "discards.jsonl"
LEDGER_BEFORE_SUFFIX = ".ledger-before.json"
DISCOVERED_BEFORE_SUFFIX = ".discovered-before.json"
STATUS = "status.json"
IMPORTED = "imported.json"
KEEP_IMPORTED = 3
RUN_ID = re.compile(r"^[0-9A-Za-z]{1,32}$")
SOURCE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
EXAMPLES_KEPT = 5  # invalid ads named in a footer; the count is always complete

# The canonical job (providers/base_provider.build_canonical_job). Providers add fields of their own; they pass.
REQUIRED_TEXT = ("jobId", "provider", "title")
OPTIONAL_TEXT = (
    "source", "company", "location", "site", "jobUrl", "description", "datePosted", "salary",
    "employmentType", "searchTerm", "searchLocation", "scrapedAt", "status",
)


def jobs_dir(root: Path) -> Path:
    return Path(root) / "data" / "jobs"


def staging_dir(root: Path) -> Path:
    return jobs_dir(root) / STAGING_DIR


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def problems(job) -> list[str]:
    """Why this is not a whole canonical ad; empty when it is. The same check runs when writing and when reading."""
    if not isinstance(job, dict):
        return ["not an object"]
    found = []
    for key in REQUIRED_TEXT:
        value = job.get(key)
        if not isinstance(value, str) or not value.strip():
            found.append(f"{key} is missing or not text")
    for key in OPTIONAL_TEXT:
        if key in job and not isinstance(job[key], str):
            found.append(f"{key} is not text")
    if "isRemote" in job and not isinstance(job["isRemote"], bool):
        found.append("isRemote is not true or false")
    if not found:
        try:
            json.dumps(job, allow_nan=False)
        except (TypeError, ValueError) as exc:
            found.append(f"not storable as JSON: {exc}")
    return found


def _line(record: dict) -> bytes:
    return (json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


class _AppendFile:
    """A file that only grows by whole lines: created exclusively, 600, a header first, every write fsynced."""

    def __init__(self, path: Path | None, header: dict | None = None, *, disabled: str | None = None):
        self.path = path
        self.failed: str | None = disabled  # why it writes nothing, or None
        self.finished = False
        self._fd: int | None = None
        if self.failed or path is None:
            return
        try:
            _atomic.make_private_dirs(path.parent)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, _atomic.PRIVATE_FILE_MODE)
            self._fd = fd
            os.fchmod(fd, _atomic.PRIVATE_FILE_MODE)  # exactly 600, whatever the umask
            self._write(_line({"t": "header", **(header or {})}))
            self._sync_dir()
        except Exception as exc:  # staging never stops a run
            self._fail(exc)

    def _fail(self, exc: Exception) -> None:
        if self.failed is None:
            self.failed = f"{type(exc).__name__}: {exc}"
            logger.warning("Staging for %s stopped, the scrape carries on: %s", self.path and self.path.name, exc)
        self._close()

    def _close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def _write(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            written = os.write(self._fd, view)
            view = view[written:]
        os.fsync(self._fd)

    def _sync_dir(self) -> None:
        try:
            directory = os.open(self.path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory)
        except OSError:
            pass
        finally:
            os.close(directory)

    @property
    def active(self) -> bool:
        return self._fd is not None and not self.finished


def _text(value, limit: int = 300) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _identify(job) -> dict:
    """What names a dropped ad: never its description. `job` may be a canonical ad or a provider's own row."""
    job = job if isinstance(job, dict) else {}
    return {
        "jobId": _text(job.get("jobId")) or None,
        "title": _text(job.get("title")),
        "company": _text(job.get("company")),
        "location": _text(job.get("location")),
        "url": _text(job.get("jobUrl") or job.get("url") or job.get("job_url") or job.get("link"), 500),
    }


class DiscardLog(_AppendFile):
    """discards.jsonl of one run: a line for every ad a provider dropped, with the reason. Shared by all sources."""

    def add_many(self, records: list[dict]) -> bool:
        """One write for the lot (one search, one ad): True when they are on disk. Never raises."""
        if not self.active:
            return False
        if not records:
            return True
        try:
            self._write(b"".join(_line(record) for record in records))
        except (OSError, ValueError, TypeError) as exc:
            self._fail(exc)
            return False
        return True


class SourceWriter(_AppendFile):
    """One source's file. Every append is one whole line, written in one call and fsynced before it returns."""

    def __init__(
        self, path: Path | None, header: dict | None = None, *, disabled: str | None = None,
        discard_log: DiscardLog | None = None,
    ):
        self.source = (header or {}).get("source") or (path.stem if path else "")
        self.discard_log = discard_log
        self.batches = 0
        self.staged = 0
        self.invalid: list[dict] = []
        self.invalid_count = 0
        self.discarded = 0  # dropped ads that were part of the source's `read` count: read == kept + discarded
        self.discarded_uncounted = 0  # rows dropped before they were counted (no title, no id, ...)
        self.discard_reasons: dict[str, int] = {}
        self.mismatch = False  # set when the source is closed: staged ads differ from the ones returned
        super().__init__(path, header, disabled=disabled)

    def append(
        self, jobs, *, part: str | None = None, read: int | None = None, external_ids: dict | None = None,
        dropped: list[dict] | None = None,
    ) -> int:
        """Stage one batch (a search, a board, a page, an ad). Returns how many ads were written; never raises.

        An ad that is not whole is left out of the file and counted in the footer. An empty batch is still a line:
        it records that the part was read and had nothing. `external_ids` (jobId -> the source's own id) is kept in
        the line beside the ads, not inside them. `dropped` goes to discards.jsonl after the batch.
        """
        if not self.active:
            self.drops(dropped)
            return 0
        whole = []
        for job in jobs or []:
            found = problems(job)
            if found:
                self.invalid_count += 1
                if len(self.invalid) < EXAMPLES_KEPT:
                    self.invalid.append({
                        "jobId": job.get("jobId") if isinstance(job, dict) else None, "problems": found[:3],
                    })
            else:
                whole.append(job)
        record = {"t": "batch", "part": part, "read": read, "jobs": whole}
        ids = {
            job["jobId"]: str(external_ids[job["jobId"]])
            for job in whole if external_ids and external_ids.get(job["jobId"]) not in (None, "")
        }
        if ids:
            record["externalIds"] = ids
        try:
            self._write(_line(record))
        except (OSError, ValueError, TypeError) as exc:
            self._fail(exc)
            self.drops(dropped)
            return 0
        self.batches += 1
        self.staged += len(whole)
        self.drops(dropped, part=part)
        return len(whole)

    def drops(self, dropped: list[dict] | None, *, part: str | None = None) -> None:
        """Record dropped ads with their reasons (see base_provider.dropped_ad). Never raises."""
        if not dropped or self.discard_log is None:
            return
        try:
            records = []
            for item in dropped:
                records.append({
                    "t": "discard", "source": self.source, "externalId": _external(item.get("externalId")),
                    "reason": str(item.get("reason") or "unknown")[:120], **_identify(item.get("job")),
                    "counted": item.get("counted", True) is not False, "part": part,
                })
            if self.discard_log.add_many(records):
                for record in records:
                    key = "discarded" if record["counted"] else "discarded_uncounted"
                    setattr(self, key, getattr(self, key) + 1)
                    self.discard_reasons[record["reason"]] = self.discard_reasons.get(record["reason"], 0) + 1
        except Exception as exc:  # staging never stops a run
            logger.warning("Discards for %s not recorded: %s", self.source, exc)

    def finish(self, *, status: str, complete: bool, read: int, kept: int, total: int | None = None, **extra) -> None:
        """The footer: the source ran to its end (or failed or was skipped) and this is how it went. Never raises."""
        if not self.active:
            self._close()
            return
        footer = {
            "t": "footer", "status": status, "complete": bool(complete), "read": read, "kept": kept, "total": total,
            "staged": self.staged, "batches": self.batches, "invalid": self.invalid_count,
            "invalidExamples": self.invalid, "finishedAt": _now(), **extra,
        }
        try:
            self._write(_line(footer))
        except (OSError, ValueError, TypeError) as exc:
            self._fail(exc)
            return
        self.finished = True
        self._close()

    def close_source(self, jobs: list[dict], outcome) -> None:
        """Called once, by the runner, when a source's fetch has returned (or raised, and `outcome` says failed).

        A provider that did not stream gets its whole list written here, so every source has staging. A provider that
        did stream is checked: what it staged must be what it returned, and what it read must be what it kept plus what
        it dropped (`discardMismatch`; not judged for a failed source, whose reading stopped half way).
        """
        try:
            if self.batches == 0 and jobs:
                self.append(jobs, part="all", read=outcome.read)
                mode = "at the end"
            else:
                mode = "as it went" if self.batches else "nothing to stage"
            accounted = self.staged + self.invalid_count
            judged = self.failed is None and outcome.status != "failed"
            self.mismatch = bool(self.failed is None and accounted != len(jobs))
            self.finish(
                status=outcome.status,
                complete=outcome.status == "ok",
                read=outcome.read,
                kept=outcome.kept,
                total=getattr(outcome, "total_reported", None),
                returned=len(jobs),
                written=mode,
                error=(str(outcome.error)[:300] if outcome.error else None),
                boardsFailed=list(outcome.boards_failed),
                boardsEmpty=list(outcome.boards_empty),
                boardsRead=[dict(row) for row in getattr(outcome, "boards_read", None) or []],
                skipReason=outcome.skip_reason,
                mismatch=(accounted != len(jobs)) if self.failed is None else None,
                discarded=self.discarded,
                discardedUncounted=self.discarded_uncounted,
                discardReasons=dict(sorted(self.discard_reasons.items())),
                discardMismatch=(outcome.read != len(jobs) + self.discarded) if judged else None,
            )
        except Exception as exc:  # staging never stops a run
            self._fail(exc)


def _external(value) -> str | None:
    """A source's own id as text, or None when it gives none."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text[:200] or None


class StagingRun:
    """The folder of one run. When it cannot be made, every source gets a writer that writes nothing."""

    def __init__(self, root: Path, run_id: str):
        self.root = Path(root)
        self.run_id = run_id
        self.dir: Path | None = None
        self.disabled: str | None = None
        self.warnings: list[str] = []
        self.discards: DiscardLog | None = None
        self.writers: list["SourceWriter"] = []
        self._header: dict = {}

    @classmethod
    def begin(
        cls, root: Path, run_id: str, *, search_key: str, terms, locations, country, remote_filters, providers,
        ledger_path: Path | None = None, discovered_path: Path | None = None,
    ) -> "StagingRun":
        run = cls(root, run_id)
        try:
            if not RUN_ID.match(str(run_id)):
                raise ValueError("bad run id")
            base = staging_dir(root)
            _atomic.make_private_dirs(base)
            run.dir = base / run_id
            run.dir.mkdir(mode=_atomic.PRIVATE_DIR_MODE)
            started = _now()
            kept_before = {}
            for label, source, suffix in (
                ("ledger", ledger_path, LEDGER_BEFORE_SUFFIX), ("discovered file", discovered_path, DISCOVERED_BEFORE_SUFFIX),
            ):
                try:
                    kept_before[label] = _keep_file(base, run_id, source, suffix)
                except OSError as exc:  # the rest of staging does not depend on it
                    kept_before[label] = {"error": f"{type(exc).__name__}: {exc}"}
                    run.warnings.append(f"The {label} as it was before this run could not be kept: {exc}")
            ledger_before, discovered_before = kept_before["ledger"], kept_before["discovered file"]
            run._header = {
                "version": VERSION, "runId": run_id, "searchKey": search_key, "terms": list(terms or []),
                "locations": list(locations or []), "country": country or "", "remoteFilters": list(remote_filters or []),
                "startedAt": started,
            }
            manifest = {
                **run._header, "providers": list(providers or []), "ledgerBefore": ledger_before,
                "discoveredBefore": discovered_before,
            }
            _atomic.write_text_atomic(run.dir / MANIFEST, json.dumps(manifest, indent=2), _atomic.PRIVATE_FILE_MODE)
            run.discards = DiscardLog(
                run.dir / DISCARDS, {"version": VERSION, "runId": run_id, "kind": "discards", "startedAt": started}
            )
            if run.discards.failed:
                run.warnings.append(f"Discard reasons are not recorded for this run ({run.discards.failed}).")
        except Exception as exc:  # staging never stops a run
            run.disabled = f"{type(exc).__name__}: {exc}"
            run.warnings.append(f"Staging is off for this run ({run.disabled}); the scrape carries on without it.")
            logger.warning("%s", run.warnings[-1])
            return run
        return run

    def open_source(self, name: str) -> SourceWriter:
        if self.disabled or self.dir is None:
            return SourceWriter(None, disabled=self.disabled or "no staging folder")
        if not SOURCE_NAME.match(name or ""):
            return SourceWriter(None, disabled=f"bad source name {name!r}")
        writer = SourceWriter(
            self.dir / f"{name}.jsonl", {**self._header, "source": name, "startedAt": _now()}, discard_log=self.discards
        )
        if writer.failed:
            self.warnings.append(f"Staging for {name} is off ({writer.failed}).")
        self.writers.append(writer)
        return writer

    def finish(self) -> tuple[bool, list[str]]:
        """When the sources are done: did staging itself work? Writes status.json (best effort) and returns (ok, problems).

        Not ok when the run folder could not be made, a source or the discards log stopped writing, a source's staged ads are
        not what it returned, or ads were left out of staging for not being whole. A staged run that is not ok must not be imported
        as if it were a complete scrape. This marks the run record and the folder; it changes no discovery output.
        """
        problems = []
        if self.disabled:
            problems.append(f"staging is off for this run: {self.disabled}")
        for writer in self.writers:
            if writer.failed:
                problems.append(f"{writer.source}: staging stopped writing ({writer.failed})")
            elif writer.mismatch:
                problems.append(f"{writer.source}: what was staged is not what the provider returned")
            if writer.invalid_count:
                problems.append(f"{writer.source}: {writer.invalid_count} ads were not whole and are not staged")
        if self.discards is not None and self.discards.failed:
            problems.append(f"discard reasons stopped being recorded ({self.discards.failed})")
        ok = not problems
        if self.dir is not None and not self.disabled:
            try:
                _atomic.write_text_atomic(
                    self.dir / STATUS,
                    json.dumps({"version": VERSION, "ok": ok, "problems": problems, "finishedAt": _now()}, indent=2),
                    _atomic.PRIVATE_FILE_MODE,
                )
            except Exception as exc:  # the record still carries it
                logger.warning("Staging status not written: %s", exc)
        return ok, problems


def _keep_file(base: Path, run_id: str, source: Path | None, suffix: str) -> dict | None:
    """Hard link a data file as it is now, so the bytes this run started from survive the run's own commit."""
    if source is None or not Path(source).is_file():
        return None
    target = base / f"{run_id}{suffix}"
    digest = hashlib.sha256()
    try:
        os.link(source, target)
        linked = True
    except OSError:  # another filesystem, or none that links: an ordinary copy, private
        shutil.copyfile(source, target)
        os.chmod(target, _atomic.PRIVATE_FILE_MODE)
        linked = False
    with open(target, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return {"file": target.name, "linked": linked, "bytes": target.stat().st_size, "sha256": digest.hexdigest()}


def _started(folder: Path) -> str:
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        if isinstance(manifest, dict) and isinstance(manifest.get("startedAt"), str):
            return manifest["startedAt"]
    except (OSError, ValueError):
        pass
    return datetime.fromtimestamp(folder.stat().st_mtime, tz=timezone.utc).isoformat()


def mark_imported(root: Path, run_id: str, info: dict | None = None) -> Path:
    """The run was imported for real (never by a dry run): staging/<runId>/imported.json, 600, atomic."""
    folder = staging_dir(Path(root)) / run_id
    if not RUN_ID.match(str(run_id)) or not folder.is_dir():
        raise ValueError("no staging folder for this run")
    path = folder / IMPORTED
    _atomic.write_text_atomic(path, json.dumps({"runId": run_id, "importedAt": _now(), **(info or {})}, indent=2), _atomic.PRIVATE_FILE_MODE)
    return path


def is_imported(root: Path, run_id: str) -> bool:
    return (staging_dir(Path(root)) / run_id / IMPORTED).is_file()


def prune(root: Path, keep: int = KEEP_IMPORTED, protect=frozenset()) -> list[str]:
    """Remove imported runs beyond the newest `keep` of them, with their two hard links. Never a run that is not imported:
    one awaiting an import or recovery, one with no marker (every run before S4a), one whose staging failed. Never one in `protect`:
    its dropped ads are not recorded yet (filtered_ads.unrecorded). Returns the ids removed."""
    base = staging_dir(Path(root))
    imported = [(started, name) for started, name in
                sorted(((_started(base / r), r) for r in list_runs(root)), reverse=True) if (base / name / IMPORTED).is_file()]
    removed = []
    for _, name in imported[max(0, keep):]:
        if name in protect:
            continue
        shutil.rmtree(base / name, ignore_errors=True)
        for suffix in (LEDGER_BEFORE_SUFFIX, DISCOVERED_BEFORE_SUFFIX):
            (base / f"{name}{suffix}").unlink(missing_ok=True)
        removed.append(name)
    return removed


def usage(root: Path) -> dict:
    """What staging takes on disk: runs, files and bytes, each inode once (a hard link to a data file is not a second copy)."""
    base = staging_dir(root)
    runs = 0
    files = 0
    total = 0
    seen: set[tuple[int, int]] = set()
    if base.is_dir():
        runs = sum(1 for e in base.iterdir() if e.is_dir() and not e.is_symlink() and RUN_ID.match(e.name))
        for current, _dirs, names in os.walk(base):
            for name in names:
                try:
                    info = os.stat(os.path.join(current, name))
                except OSError:
                    continue
                files += 1
                if (info.st_dev, info.st_ino) not in seen:
                    seen.add((info.st_dev, info.st_ino))
                    total += info.st_size
    return {"runs": runs, "files": files, "bytes": total}


# --- reading ---------------------------------------------------------------------------------------------------


@dataclass
class Batch:
    part: str | None
    read: int | None
    jobs: list[dict]
    external_ids: dict[str, str] = field(default_factory=dict)  # jobId -> the source's own id, for the ads of this batch


@dataclass
class SourceStage:
    """What one source's file holds. Whole lines only: see the module docstring."""

    source: str
    path: Path
    header: dict | None = None
    batches: list[Batch] = field(default_factory=list)
    footer: dict | None = None
    torn: bool = False  # the file ends in a line with no newline, which was ignored
    unreadable_lines: int = 0
    rejected_ads: int = 0  # ads on whole lines that fail problems()

    @property
    def jobs(self) -> list[dict]:
        return [job for batch in self.batches for job in batch.jobs]

    @property
    def external_ids(self) -> dict[str, str]:
        """jobId -> the source's own id for every staged ad that has one."""
        return {job_id: ext for batch in self.batches for job_id, ext in batch.external_ids.items()}

    @property
    def finished(self) -> bool:
        """A footer was written. Without one the source was stopped."""
        return self.footer is not None

    @property
    def complete(self) -> bool:
        """The source ran to its end without a failed part: the only state that may say what is no longer listed."""
        return bool(self.footer and self.footer.get("complete") is True)

    @property
    def usable(self) -> bool:
        return self.header is not None


def read_source(path: Path) -> SourceStage:
    path = Path(path)
    stage = SourceStage(source=path.stem, path=path)
    try:
        data = path.read_bytes()
    except OSError:
        stage.unreadable_lines += 1
        return stage
    *lines, tail = data.split(b"\n")
    stage.torn = bool(tail)
    for raw in lines:
        if not raw:
            continue
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            stage.unreadable_lines += 1
            continue
        kind = record.get("t") if isinstance(record, dict) else None
        if stage.footer is not None:
            continue  # nothing counts after the footer
        if kind == "header":
            if stage.header is None:
                stage.header = record
        elif kind == "batch" and stage.header is not None and isinstance(record.get("jobs"), list):
            whole = []
            for job in record["jobs"]:
                if problems(job):
                    stage.rejected_ads += 1
                else:
                    whole.append(job)
            kept_ids = {job["jobId"] for job in whole}
            ids = record.get("externalIds")
            ids = {k: v for k, v in ids.items() if k in kept_ids and isinstance(v, str)} if isinstance(ids, dict) else {}
            stage.batches.append(Batch(record.get("part"), record.get("read"), whole, ids))
        elif kind == "footer" and stage.header is not None:
            stage.footer = record
        else:
            stage.unreadable_lines += 1
    return stage


REASON = re.compile(r"^[a-z][a-z_]*(:[^\n]{1,100})?$")


def discard_problems(record) -> list[str]:
    """Why a discard line is not usable; empty when it is."""
    if not isinstance(record, dict) or record.get("t") != "discard":
        return ["not a discard"]
    found = []
    if not isinstance(record.get("source"), str) or not record["source"]:
        found.append("source is missing")
    if not isinstance(record.get("reason"), str) or not REASON.match(record["reason"]):
        found.append("reason is not a stable code")
    if record.get("externalId") is not None and not isinstance(record["externalId"], str):
        found.append("externalId is not text")
    if not isinstance(record.get("counted"), bool):
        found.append("counted is missing")
    if "description" in record:
        found.append("a discard never carries a description")
    return found


@dataclass
class DiscardStage:
    path: Path
    header: dict | None = None
    records: list[dict] = field(default_factory=list)
    torn: bool = False
    unreadable_lines: int = 0
    rejected: int = 0

    def by_source(self, source: str) -> list[dict]:
        return [r for r in self.records if r["source"] == source]

    def reasons(self, source: str | None = None, *, counted_only: bool = False) -> dict[str, int]:
        found: dict[str, int] = {}
        for record in self.records:
            if (source is None or record["source"] == source) and (record["counted"] or not counted_only):
                found[record["reason"]] = found.get(record["reason"], 0) + 1
        return found


def read_discards(path: Path) -> DiscardStage:
    """Whole, valid discard lines only: a torn last line, an unparsable line or a line that fails discard_problems is left out."""
    path = Path(path)
    stage = DiscardStage(path=path)
    try:
        data = path.read_bytes()
    except OSError:
        return stage
    *lines, tail = data.split(b"\n")
    stage.torn = bool(tail)
    for raw in lines:
        if not raw:
            continue
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            stage.unreadable_lines += 1
            continue
        if isinstance(record, dict) and record.get("t") == "header":
            stage.header = stage.header or record
        elif discard_problems(record):
            stage.rejected += 1
        else:
            stage.records.append(record)
    return stage


@dataclass
class RunStage:
    run_id: str
    dir: Path
    manifest: dict | None
    sources: dict[str, SourceStage]
    discards: DiscardStage | None = None
    status: dict | None = None  # status.json: did staging itself work (absent: the run never reached its end)

    @property
    def discovered_before(self) -> Path | None:
        info = (self.manifest or {}).get("discoveredBefore")
        if isinstance(info, dict) and isinstance(info.get("file"), str):
            candidate = self.dir.parent / info["file"]
            return candidate if candidate.is_file() else None
        return None

    @property
    def ledger_before(self) -> Path | None:
        info = (self.manifest or {}).get("ledgerBefore")
        if isinstance(info, dict) and isinstance(info.get("file"), str):
            candidate = self.dir.parent / info["file"]
            return candidate if candidate.is_file() else None
        return None


def read_run(root: Path, run_id: str) -> RunStage | None:
    if not RUN_ID.match(str(run_id)):
        return None
    folder = staging_dir(root) / run_id
    if not folder.is_dir():
        return None
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        manifest = manifest if isinstance(manifest, dict) else None
    except (OSError, ValueError):
        manifest = None
    sources = {p.stem: read_source(p) for p in sorted(folder.glob("*.jsonl")) if p.name != DISCARDS}
    try:
        status = json.loads((folder / STATUS).read_text(encoding="utf-8"))
        status = status if isinstance(status, dict) else None
    except (OSError, ValueError):
        status = None
    return RunStage(
        run_id=run_id, dir=folder, manifest=manifest, sources=sources, discards=read_discards(folder / DISCARDS),
        status=status,
    )


def list_runs(root: Path) -> list[str]:
    """Run ids with a staging folder, newest first."""
    base = staging_dir(root)
    if not base.is_dir():
        return []
    runs = [(_started(e), e.name) for e in base.iterdir() if e.is_dir() and not e.is_symlink() and RUN_ID.match(e.name)]
    return [name for _, name in sorted(runs, reverse=True)]
