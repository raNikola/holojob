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

Next to the folder the run keeps `<runId>.ledger-before.json`, a hard link to the ledger as it was when the run began. The
ledger is replaced by rename, never rewritten in place, so the link keeps the old bytes. Only the last KEEP_RUNS runs stay.
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
KEEP_RUNS = 3
STAGING_DIR = "staging"
MANIFEST = "run.json"
LEDGER_BEFORE_SUFFIX = ".ledger-before.json"
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


class SourceWriter:
    """One source's file. Every append is one whole line, written in one call and fsynced before it returns."""

    def __init__(self, path: Path | None, header: dict | None = None, *, disabled: str | None = None):
        self.path = path
        self.failed: str | None = disabled  # why it writes nothing, or None
        self.batches = 0
        self.staged = 0
        self.invalid: list[dict] = []
        self.invalid_count = 0
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

    def append(self, jobs, *, part: str | None = None, read: int | None = None) -> int:
        """Stage one batch (a search, a board, a page, an ad). Returns how many ads were written; never raises.

        An ad that is not whole is left out of the file and counted in the footer. An empty batch is still a line:
        it records that the part was read and had nothing.
        """
        if not self.active:
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
        try:
            self._write(_line({"t": "batch", "part": part, "read": read, "jobs": whole}))
        except (OSError, ValueError, TypeError) as exc:
            self._fail(exc)
            return 0
        self.batches += 1
        self.staged += len(whole)
        return len(whole)

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
        did stream is checked: what it staged must be what it returned.
        """
        try:
            if self.batches == 0 and jobs:
                self.append(jobs, part="all", read=outcome.read)
                mode = "at the end"
            else:
                mode = "as it went" if self.batches else "nothing to stage"
            accounted = self.staged + self.invalid_count
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
                skipReason=outcome.skip_reason,
                mismatch=(accounted != len(jobs)) if self.failed is None else None,
            )
        except Exception as exc:  # staging never stops a run
            self._fail(exc)


class StagingRun:
    """The folder of one run. When it cannot be made, every source gets a writer that writes nothing."""

    def __init__(self, root: Path, run_id: str):
        self.root = Path(root)
        self.run_id = run_id
        self.dir: Path | None = None
        self.disabled: str | None = None
        self.warnings: list[str] = []
        self._header: dict = {}

    @classmethod
    def begin(
        cls, root: Path, run_id: str, *, search_key: str, terms, locations, country, remote_filters, providers,
        ledger_path: Path | None = None,
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
            try:
                ledger_before = _keep_ledger(base, run_id, ledger_path)
            except OSError as exc:  # the rest of staging does not depend on it
                ledger_before = {"error": f"{type(exc).__name__}: {exc}"}
                run.warnings.append(f"The ledger as it was before this run could not be kept: {exc}")
            run._header = {
                "version": VERSION, "runId": run_id, "searchKey": search_key, "terms": list(terms or []),
                "locations": list(locations or []), "country": country or "", "remoteFilters": list(remote_filters or []),
                "startedAt": started,
            }
            manifest = {**run._header, "providers": list(providers or []), "ledgerBefore": ledger_before}
            _atomic.write_text_atomic(run.dir / MANIFEST, json.dumps(manifest, indent=2), _atomic.PRIVATE_FILE_MODE)
        except Exception as exc:  # staging never stops a run
            run.disabled = f"{type(exc).__name__}: {exc}"
            run.warnings.append(f"Staging is off for this run ({run.disabled}); the scrape carries on without it.")
            logger.warning("%s", run.warnings[-1])
            return run
        try:
            prune(root, keep=KEEP_RUNS, protect=run_id)
        except OSError as exc:
            run.warnings.append(f"Old staging could not be pruned: {exc}")
        return run

    def open_source(self, name: str) -> SourceWriter:
        if self.disabled or self.dir is None:
            return SourceWriter(None, disabled=self.disabled or "no staging folder")
        if not SOURCE_NAME.match(name or ""):
            return SourceWriter(None, disabled=f"bad source name {name!r}")
        writer = SourceWriter(self.dir / f"{name}.jsonl", {**self._header, "source": name, "startedAt": _now()})
        if writer.failed:
            self.warnings.append(f"Staging for {name} is off ({writer.failed}).")
        return writer


def _keep_ledger(base: Path, run_id: str, ledger_path: Path | None) -> dict | None:
    """Hard link the ledger as it is now, so the bytes this run started from survive the run's own commit."""
    if ledger_path is None or not Path(ledger_path).is_file():
        return None
    target = base / f"{run_id}{LEDGER_BEFORE_SUFFIX}"
    digest = hashlib.sha256()
    try:
        os.link(ledger_path, target)
        linked = True
    except OSError:  # another filesystem, or none that links: an ordinary copy, private
        shutil.copyfile(ledger_path, target)
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


def prune(root: Path, *, keep: int = KEEP_RUNS, protect: str | None = None) -> list[str]:
    """Remove all but the newest `keep` runs (and ledger links with no run). Returns the run ids removed."""
    base = staging_dir(root)
    if not base.is_dir():
        return []
    runs = []
    for entry in base.iterdir():
        if entry.is_dir() and not entry.is_symlink() and RUN_ID.match(entry.name):
            runs.append((_started(entry), entry.name))
    runs.sort(reverse=True)
    keepers = {name for _, name in runs[:keep]}
    if protect:
        keepers.add(protect)
    removed = []
    for _, name in runs:
        if name not in keepers:
            shutil.rmtree(base / name, ignore_errors=True)
            (base / f"{name}{LEDGER_BEFORE_SUFFIX}").unlink(missing_ok=True)
            removed.append(name)
    for entry in base.iterdir():
        if entry.name.endswith(LEDGER_BEFORE_SUFFIX) and entry.is_file():
            if entry.name[: -len(LEDGER_BEFORE_SUFFIX)] not in {name for _, name in runs}:
                entry.unlink(missing_ok=True)
    return removed


# --- reading ---------------------------------------------------------------------------------------------------


@dataclass
class Batch:
    part: str | None
    read: int | None
    jobs: list[dict]


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
            stage.batches.append(Batch(record.get("part"), record.get("read"), whole))
        elif kind == "footer" and stage.header is not None:
            stage.footer = record
        else:
            stage.unreadable_lines += 1
    return stage


@dataclass
class RunStage:
    run_id: str
    dir: Path
    manifest: dict | None
    sources: dict[str, SourceStage]

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
    sources = {p.stem: read_source(p) for p in sorted(folder.glob("*.jsonl"))}
    return RunStage(run_id=run_id, dir=folder, manifest=manifest, sources=sources)


def list_runs(root: Path) -> list[str]:
    """Run ids with a staging folder, newest first."""
    base = staging_dir(root)
    if not base.is_dir():
        return []
    runs = [(_started(e), e.name) for e in base.iterdir() if e.is_dir() and not e.is_symlink() and RUN_ID.match(e.name)]
    return [name for _, name in sorted(runs, reverse=True)]
