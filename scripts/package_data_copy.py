#!/usr/bin/env python3
"""Reduced data copy for a package session (docs/redesign/PACKAGES_PLAN.md, "Data copy"; owner decision 2026-11-26).

    .venv/bin/python scripts/package_data_copy.py --dest WORKTREE --application-job-ids FILE [--source /srv/holojob]

Copies ad data and settings from SOURCE/data into WORKTREE/data by allowlist; private files are not copied at all.
Writes WORKTREE/data/derived/must-keep.json: the owner's Applied, Saved and Rejected ads as ids and statuses only.
Saved/Rejected come from data/jobs/job-state.json; Applied from the node export of application job ids
(scripts/export-application-job-ids.js; TRACKER_PLAN 6a: Python does not read the application store).
Read-only on SOURCE. Files 600, directories 700. Prints counts only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

MUST_KEEP_EXPECTED = 19
MUST_KEEP_REL = "derived/must-keep.json"
STATUS_RANK = {"applied": 3, "saved": 2, "rejected": 1}

# A path ending in "/" copies the whole directory. Everything not listed is private by default.
AD_DATA_ALLOW = (
    "jobs/discovered_jobs.json", "jobs/job_history.json", "jobs/filtered_ads.json", "jobs/normalized_jobs.json",
    "jobs/raw_jobs.csv", "jobs/scored_jobs.json", "jobs/rescored_kept.json", "jobs/pipeline_last_run.json",
    "jobs/job-state.json", "jobs/staging/",
    "ai/settings.json", "ai/usage-ledger.jsonl",
    "config/sources.json", "config/ai-settings.json",
    "analytics/runs/",
    "cache/engine.json", "cache/requirement-frames.json",
)

_SECRET_DIRS = ("data/secrets", "claude-config")
_SECRET_NAME = re.compile(
    r"(^|[-_.])(api[-_]?keys?|secrets?|tokens?|cookies?|sessions?|credentials?|passw(or)?d|li[-_]?at|id[-_]rsa)([-_.]|$)", re.I)
_SECRET_EXT = re.compile(r"\.(pem|key|p12|pfx)$", re.I)


def is_secret_path(rel: str) -> bool:
    """Port of scripts/secret-paths.js isSecretPath (node is not on the host). Paths relative to the repo root."""
    raw = str(rel or "")
    if not raw or "\0" in raw:
        return True
    s = raw.replace("\\", "/")
    if s.startswith("/") or re.match(r"^[A-Za-z]:", s):
        return True
    parts = [p for p in s.split("/") if p not in ("", ".")]
    if ".." in parts:
        return True
    lower = "/".join(parts).lower()
    if any(lower == d or lower.startswith(d + "/") for d in _SECRET_DIRS):
        return True
    lp = lower.split("/")
    name = lp[-1]
    if name == ".env" or name.startswith(".env.") or _SECRET_EXT.search(name):
        return True
    return any((i > 0 or len(lp) == 1) and _SECRET_NAME.search(p) for i, p in enumerate(lp))


def _allowed(rel: str) -> bool:
    return any(rel == a or (a.endswith("/") and rel.startswith(a)) for a in AD_DATA_ALLOW)


@dataclass
class Split:
    copy: list[str] = field(default_factory=list)      # files (relative to data/) copied
    private: list[str] = field(default_factory=list)   # files never copied
    tracked: list[str] = field(default_factory=list)   # tracked in git (examples, .gitkeep): come with every checkout


def classify(data_root: Path, tracked: set[str] | frozenset[str] = frozenset()) -> Split:
    """Split data/ into the ad-data copy and the private rest. Never reads file contents."""
    split = Split()
    for path in sorted(data_root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(data_root).as_posix()
        if rel in tracked:
            split.tracked.append(rel)
        elif _allowed(rel) and not path.is_symlink() and not is_secret_path(f"data/{rel}"):
            split.copy.append(rel)
        else:
            split.private.append(rel)
    return split


def copy_data(src: Path, dst: Path, split: Split) -> None:
    dst.mkdir(mode=0o700, parents=True, exist_ok=True)
    for rel in split.copy:
        target = dst / rel
        for parent in reversed(target.relative_to(dst).parents[:-1]):
            (dst / parent).mkdir(mode=0o700, exist_ok=True)
        subprocess.run(["cp", "--reflink=auto", "--preserve=timestamps", str(src / rel), str(target)], check=True)
        target.chmod(0o600)


def read_id_lines(path: Path) -> set[str]:
    """Job ids from an export file: one per line, `#` lines are header comments."""
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            ids.add(line)
    return ids


def build_must_keep(job_state: Path, application_ids: set[str], out: Path) -> dict:
    """The owner's Applied/Saved/Rejected ads, ids and statuses only (applied wins over saved over rejected)."""
    status: dict[str, str] = {}

    def put(job_id: str, st: str) -> None:
        if STATUS_RANK[st] > STATUS_RANK.get(status.get(job_id, ""), 0):
            status[job_id] = st

    doc = json.loads(job_state.read_text(encoding="utf-8")) if job_state.exists() else {}
    for entry in (doc.get("jobs") or {}).values():
        st = entry.get("status") if isinstance(entry, dict) else None
        if st in STATUS_RANK and isinstance(entry.get("jobId"), str):
            put(entry["jobId"], st)
    for job_id in application_ids:
        put(job_id, "applied")
    ads = [{"id": i, "status": status[i]} for i in sorted(status)]
    result = {
        "version": 1,
        "source": "job-state.json (saved, rejected) + application job id export (applied); ids and statuses only",
        "builtAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "expected": MUST_KEEP_EXPECTED,
        "count": len(ads),
        "ads": ads,
    }
    out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    out.chmod(0o600)
    return result


def check_dest(source: Path, dest: Path, tracked: set[str]) -> Path:
    src, dst = source.resolve(), dest.resolve()
    if dst == src or src / "data" in (dst, *dst.parents) or dst in src.parents:
        raise SystemExit(f"package_data_copy: refused: {dest} is the production checkout or contains it")
    if not (dst / ".git").exists():
        raise SystemExit(f"package_data_copy: refused: {dest} is not a git checkout (worktree)")
    data = dst / "data"
    extra = [p for p in data.rglob("*") if p.is_file() and p.relative_to(data).as_posix() not in tracked] if data.exists() else []
    if extra:
        raise SystemExit(f"package_data_copy: refused: {data} already holds {len(extra)} untracked files")
    return dst


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dest", required=True, type=Path, help="the package worktree")
    ap.add_argument("--application-job-ids", required=True, type=Path, help="output of export-application-job-ids.js")
    ap.add_argument("--source", default=Path("/srv/holojob"), type=Path)
    a = ap.parse_args(argv)
    ls = subprocess.run(["git", "-C", str(a.dest), "ls-files", "data"], capture_output=True, text=True, check=True)
    tracked = {f.removeprefix("data/") for f in ls.stdout.splitlines()}
    dest = check_dest(a.source, a.dest, tracked)
    split = classify(a.source / "data", tracked)
    copy_data(a.source / "data", dest / "data", split)
    keep = build_must_keep(a.source / "data/jobs/job-state.json", read_id_lines(a.application_job_ids),
                           dest / "data" / MUST_KEEP_REL)
    by = {s: sum(1 for x in keep["ads"] if x["status"] == s) for s in STATUS_RANK}
    print(f"package_data_copy: {len(split.copy)} files copied, {len(split.private)} private files not copied, "
          f"{len(split.tracked)} tracked files left as they are")
    print(f"package_data_copy: must-keep {keep['count']} ads ({by['applied']} applied, {by['saved']} saved, "
          f"{by['rejected']} rejected); expected {MUST_KEEP_EXPECTED}")
    if keep["count"] != MUST_KEEP_EXPECTED:
        print(f"package_data_copy: WARNING: must-keep has {keep['count']}, the plan says {MUST_KEEP_EXPECTED}: "
              "statuses held only in the browser reach the server through Settings > import browser state", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
