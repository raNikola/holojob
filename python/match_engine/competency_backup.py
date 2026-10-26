#!/usr/bin/env python3
"""Back up the files a full re-extraction changes or depends on, and restore them.

    .venv/bin/python python/match_engine/competency_backup.py backup
    .venv/bin/python python/match_engine/competency_backup.py restore data/backups/competency-2c3-<timestamp>

The backup goes to data/backups/competency-2c3-<timestamp>/ (gitignored; the
tool refuses to write where git does not ignore it): the jobs file and its
ledger, the requirement frames, the remap table and learned aliases (if they
exist), the fit and engine verdict caches, the confirmed facts, the profile and
the intelligence. manifest.json holds each file's SHA-256; old-ids.json holds,
per job, the id of every requirement now (ids and counts, no other content).
Restore verifies the backup against its manifest, then copies every file back
to where it came from. --root points both commands at another tree, which is
how the tests exercise a restore without touching live files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))

from match_engine import competency_report  # noqa: E402 (puts job_scoring on the path)
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
    files = {}
    for rel in BACKUP_FILES:
        src = root / rel
        if not src.exists():
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        files[rel] = {"sha256": sha256(src), "bytes": src.stat().st_size}
        if sha256(dest) != files[rel]["sha256"]:
            raise SystemExit(f"copy of {rel} does not match its source")
    jobs_path = root / JOBS_FILE
    payload = json.loads(jobs_path.read_text(encoding="utf-8")) if jobs_path.exists() else []
    ids = old_ids(payload.get("jobs") if isinstance(payload, dict) else payload)
    (target / "old-ids.json").write_text(json.dumps(ids, indent=1, ensure_ascii=False), encoding="utf-8")
    manifest = {"created": stamp, "files": files, "absent": [r for r in BACKUP_FILES if r not in files],
                "oldIds": ids["counts"]}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return target


def verify(source: Path) -> dict:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    bad = [rel for rel, meta in manifest["files"].items() if sha256(source / rel) != meta["sha256"]]
    if bad:
        raise SystemExit(f"backup is damaged, checksum differs: {', '.join(bad)}")
    return manifest


def restore(source: Path, root: Path = ROOT) -> list[str]:
    """Copy every backed-up file back under `root`; a file the backup lacked (it did not exist) is removed."""
    manifest = verify(source)
    for rel in manifest["files"]:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, dest)
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
