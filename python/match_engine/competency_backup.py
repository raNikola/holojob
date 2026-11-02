#!/usr/bin/env python3
"""Back up the files a full re-extraction changes or depends on, and restore them.

    .venv/bin/python python/match_engine/competency_backup.py backup
    .venv/bin/python python/match_engine/competency_backup.py restore data/backups/competency-2c3-<timestamp>

The backup goes to data/backups/competency-2c3-<timestamp>/ (gitignored; the
tool refuses to write where git does not ignore it): the jobs file and its
ledger, the requirement frames, the remap table and learned aliases (if they
exist), the fit and engine verdict caches, the confirmed facts, the profile and
the intelligence. Everything in the backup is private (folders 700, files 600).
manifest.json holds each file's SHA-256 and original mode; old-ids.json holds,
per job, the id of every requirement now (ids and counts, no other content).
Restore verifies the backup against its manifest, then copies every file back
to where it came from, with its original mode. --root points both commands at another tree, which is
how the tests exercise a restore without touching live files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))

from match_engine import competency_report  # noqa: E402 (puts job_scoring on the path)
from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic  # noqa: E402
from requirement_frames import frame_key  # noqa: E402
from requirement_ids import PROVISIONAL_PREFIX  # noqa: E402

BACKUP_FILES = (
    "data/jobs/discovered_jobs.json",
    "data/jobs/job_history.json",
    "data/cache/requirement-frames.json",
    "data/requirement-remap.json",
    "data/competency-aliases.json",
    "data/cache/llm_fit.json",
    "data/cache/engine.json",
    "data/profile/confirmed-facts.json",
    "data/profile/candidate-profile.json",
    "data/intelligence/candidate-intelligence.json",
)
JOBS_FILE = "data/jobs/discovered_jobs.json"
BACKUPS_DIR = "data/backups"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def old_ids(jobs: list[dict]) -> dict:
    """{"jobs": {frame key: {"jobId", "requirements": {text: id}}}, "counts": {...}}; ids only."""
    out, total, provisional = {}, 0, 0
    for job in jobs:
        reqs = ((job.get("llmFacts") or {}).get("requirements")) or []
        if not reqs:
            continue
        out[frame_key(job)] = {"jobId": job.get("jobId"), "requirements": {r["text"]: r["id"] for r in reqs if r.get("id")}}
        total += len(reqs)
        provisional += sum(1 for r in reqs if str(r.get("id", "")).startswith(PROVISIONAL_PREFIX))
    return {"jobs": out, "counts": {"ads": len(out), "requirements": total, "provisional": provisional}}


def ignored_by_git(path: Path, root: Path) -> bool:
    return subprocess.run(["git", "-C", str(root), "check-ignore", "-q", str(path)], capture_output=True).returncode == 0


def backup(root: Path = ROOT, stamp: str | None = None) -> Path:
    stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    target = root / BACKUPS_DIR / f"competency-2c3-{stamp}"
    if (root / BACKUPS_DIR).resolve() not in target.resolve().parents:
        raise SystemExit(f"refusing to write outside {BACKUPS_DIR}: {target}")
    if target.exists():
        raise SystemExit(f"backup already exists: {target}")
    if (root / ".git").exists() and not ignored_by_git(target / "manifest.json", root):
        raise SystemExit(f"git does not ignore {target}; add {BACKUPS_DIR}/ to .gitignore first")
    make_private_dirs(target)
    files = {}
    for rel in BACKUP_FILES:
        src = root / rel
        if not src.exists():
            continue
        dest = target / rel
        make_private_dirs(dest.parent)
        shutil.copy2(src, dest)
        os.chmod(dest, PRIVATE_FILE_MODE)
        files[rel] = {"sha256": sha256(src), "bytes": src.stat().st_size, "mode": stat.S_IMODE(src.stat().st_mode)}
        if sha256(dest) != files[rel]["sha256"]:
            raise SystemExit(f"copy of {rel} does not match its source")
    jobs_path = root / JOBS_FILE
    payload = json.loads(jobs_path.read_text(encoding="utf-8")) if jobs_path.exists() else []
    ids = old_ids(payload.get("jobs") if isinstance(payload, dict) else payload)
    write_text_atomic(target / "old-ids.json", json.dumps(ids, indent=1, ensure_ascii=False), new_file_mode=PRIVATE_FILE_MODE)
    manifest = {"created": stamp, "files": files, "absent": [r for r in BACKUP_FILES if r not in files],
                "oldIds": ids["counts"]}
    write_text_atomic(target / "manifest.json", json.dumps(manifest, indent=1), new_file_mode=PRIVATE_FILE_MODE)
    return target


def verify(source: Path) -> dict:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    bad = [rel for rel, meta in manifest["files"].items() if sha256(source / rel) != meta["sha256"]]
    if bad:
        raise SystemExit(f"backup is damaged, checksum differs: {', '.join(bad)}")
    return manifest


def _copy_atomic(src: Path, dest: Path, mode: int | None = None) -> None:
    """copy2 to a temp file next to `dest`, then rename: `dest` is the old file or the whole copy, with the copy's exact
    bytes and time, and `mode` (a backup older than the recorded mode: the copy's). Not write_text_atomic: these files are
    restored as bytes, and it would keep the live file's mode."""
    tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(src, tmp)
        if mode is not None:
            os.chmod(tmp, mode)
        with tmp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def restore(source: Path, root: Path = ROOT) -> list[str]:
    """Copy every backed-up file back under `root`; a file the backup lacked (it did not exist) is removed."""
    manifest = verify(source)
    for rel, meta in manifest["files"].items():
        dest = root / rel
        make_private_dirs(dest.parent)
        _copy_atomic(source / rel, dest, meta.get("mode"))
    for rel in manifest["absent"]:
        (root / rel).unlink(missing_ok=True)
    return sorted(manifest["files"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--root", type=Path, default=ROOT)
    r = sub.add_parser("restore")
    r.add_argument("backup", type=Path)
    r.add_argument("--root", type=Path, default=ROOT)
    args = p.parse_args(argv)

    if args.command == "backup":
        target = backup(args.root)
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        print(f"backup: {target}")
        for rel, meta in manifest["files"].items():
            print(f"  {meta['sha256']}  {meta['bytes']:>10}  {rel}")
        print(f"  not present, so not backed up: {', '.join(manifest['absent']) or 'none'}")
        c = manifest["oldIds"]
        print(f"old-ids.json: {c['requirements']} requirements in {c['ads']} ads, {c['provisional']} provisional")
        print(f"restore with: .venv/bin/python python/match_engine/competency_backup.py restore {target.relative_to(args.root)}")
        return 0
    restored = restore(args.backup, args.root)
    print(f"restored {len(restored)} files from {args.backup} to {args.root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
