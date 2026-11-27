"""Automatic backup of the four owner files, immediately before any write that changes them (owner decision 2026-11-23).

    data/backups/auto/<file name>/<YYYYMMDD-HHMMSS>.json     (UTC; files 600, folders 700; read back and hash-checked)

Python twin of scripts/auto-backup.js: same files, layout, names and retention (last 10 versions per file, older ones removed here after a
successful backup). scored_jobs.json is the exception (owner decision 2026-11-23): it is backed up ONLY immediately before a re-score
(`event="rescore"`, passed by run_scoring.py), as `<stamp>-pre-rescore.json`, the last 3 of those; no other writer of it (a manual job add or
delete, a restore) makes a backup or uses up the 3, because manual jobs are rebuilt from manual_jobs.json at every re-score. A file that does
not exist yet has nothing to back up; new content equal to the current content makes no backup; a file outside the data folder (a scratch
copy, a test file) is never backed up. When the backup cannot be written `BackupError` is raised and the caller must not write: use
`write_text_with_backup`. Restore is manual (docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data"
AUTO_BACKUP_FILES = ("candidate-intelligence.json", "candidate-profile.json", "profile-enrichment.json", "scored_jobs.json")
KEEP_DEFAULT = 10
KEEP_BY_FILE = {"scored_jobs.json": 3}
# Files backed up only for the named event, and the marker that event puts in the version's name.
EVENT_ONLY = {"scored_jobs.json": "rescore"}
EVENT_MARKER = {"rescore": "-pre-rescore"}
VERSION_NAME = re.compile(r"^\d{8}-\d{6}(-\d+)?(-pre-rescore)?\.json$")


class BackupError(RuntimeError):
    def __init__(self, name: str):
        super().__init__(f"The backup before writing {name} could not be made, so nothing was changed.")
        self.code = "backup_failed"


def _comparable(name: str, data: bytes) -> bytes:
    """What 'the same content' means: the profile without its save stamp, everything else byte for byte."""
    if name != "candidate-profile.json":
        return data
    try:
        doc = json.loads(data.decode("utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("meta"), dict):
            doc["meta"].pop("updatedAt", None)
        return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except ValueError:
        return data


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return path.resolve() != root.resolve()
    except ValueError:
        return False


def _prune(directory: Path, keep: int, marker: str) -> None:
    """Keep the newest `keep` versions of one kind (with or without the event marker). A failure to remove an old one never blocks the write."""
    try:
        names = sorted(n for n in os.listdir(directory) if VERSION_NAME.match(n) and n.endswith("-pre-rescore.json") == bool(marker))
        for old in names[: max(0, len(names) - keep)]:
            try:
                (directory / old).unlink()
            except OSError as exc:
                print(f"[auto-backup] could not remove an old version of {directory.name}: {exc.errno}", file=sys.stderr)
    except OSError as exc:
        print(f"[auto-backup] could not list the versions of {directory.name}: {exc.errno}", file=sys.stderr)


def backup_before_write(path: Path, new_text: str | bytes, data_root: Path | None = None, now: datetime | None = None,
                        event: str | None = None) -> Path | None:
    """Back up `path` as it is now, if `new_text` would change it. The backup's path, or None when none was needed
    (including a file that is backed up only for an event this call does not name). Raises BackupError."""
    path = Path(path)
    root = Path(data_root) if data_root is not None else DATA_ROOT
    name = path.name
    if name not in AUTO_BACKUP_FILES or not _inside(path, root):
        return None
    if name in EVENT_ONLY and EVENT_ONLY[name] != event:
        return None  # scored_jobs.json: only before a re-score
    marker = EVENT_MARKER.get(event, "")
    try:
        current = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        print(f"[auto-backup] {name}: the current file cannot be read: {exc.errno}", file=sys.stderr)
        raise BackupError(name) from exc
    incoming = new_text if isinstance(new_text, bytes) else new_text.encode("utf-8")
    if _comparable(name, current) == _comparable(name, incoming):
        return None
    directory = root / "backups" / "auto" / name
    target: Path | None = None
    try:
        make_private_dirs(directory)
        base = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
        target, n = directory / f"{base}{marker}.json", 2
        while target.exists():
            target, n = directory / f"{base}-{n}{marker}.json", n + 1
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), PRIVATE_FILE_MODE)
            handle.write(current)
            handle.flush()
            os.fsync(handle.fileno())
        if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(current).digest():
            raise OSError("the copy does not match")
    except OSError as exc:
        print(f"[auto-backup] {name}: backup failed: {exc.errno or exc}", file=sys.stderr)
        if target is not None:
            target.unlink(missing_ok=True)
        raise BackupError(name) from exc
    _prune(directory, KEEP_BY_FILE.get(name, KEEP_DEFAULT), marker)
    return target


def write_text_with_backup(path: Path, text: str, new_file_mode: int | None = None, data_root: Path | None = None,
                           event: str | None = None, force_mode: bool = False) -> None:
    """The write of an owner file: its backup first (BackupError: no write), then `write_text_atomic`."""
    backup_before_write(path, text, data_root=data_root, event=event)
    write_text_atomic(Path(path), text, new_file_mode=new_file_mode, force_mode=force_mode)
