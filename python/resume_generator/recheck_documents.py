#!/usr/bin/env python3
"""Re-check existing generated documents against the current fact gate, without regenerating them and without any AI call.

Documents made before the verdicts existed have none, so the application store refuses to attach them. This reads each such
file's own bytes on the server, extracts its text, runs the same final check a tailoring run does (`check_document`: numbers, unit
metrics, years of experience, degrees and certifications, against the profile facts and the job's own title / company / location),
and, with --apply, writes a verdict bound to the file's hash: passed, or failed with the reasons. A document that fails stays blocked.

Dry run (default): writes nothing, prints counts and job ids only. --apply: writes verdict files and nothing else. It never modifies
a document, never deletes anything, never reads or writes the application records, and calls no model.
Only documents with no verdict (or one from an older gate) are looked at; a document that already has a current verdict is left alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(ROOT / "python" / "job_scoring") not in sys.path:
    sys.path.append(str(ROOT / "python" / "job_scoring"))

import verdicts  # noqa: E402
from document_text import extract_text  # noqa: E402
from provenance_checker import build_canonical_facts, check_document  # noqa: E402

PROFILE_PATH = ROOT / "data/profile/candidate-profile.json"
INTELLIGENCE_PATH = ROOT / "data/intelligence/candidate-intelligence.json"
SCORED_PATH = ROOT / "data/jobs/scored_jobs.json"
RESUMES_ROOT = ROOT / "data/resumes"

# The cover-letter template prints the day it was made ("November 9, 2026"): code, not a claim, so it is not checked.
DATE_RE = re.compile(r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}")
UNREADABLE = "The text of this file could not be read, so it could not be checked."
RECHECKABLE = ("missing", "old_gate")


def judge(name: str, data: bytes, facts: set[str]) -> tuple[bool, list[str]]:
    text = extract_text(name, data)
    if text is None or not text.strip():
        return False, [UNREADABLE]
    issues = check_document(DATE_RE.sub("", text), facts)
    return not issues, list(dict.fromkeys(issues))


def recheck(resumes_root: Path, profile: dict, intelligence: dict, jobs: dict[str, dict], *, apply: bool = False) -> dict:
    """The report: counts, and the job ids behind them. Writes verdict files only when `apply` is True."""
    base_facts = build_canonical_facts(profile, intelligence)
    report = {"looked": 0, "skipped": Counter(), "passed": 0, "failed": 0, "unreadable": 0, "written": 0,
              "failedJobs": [], "passedJobs": [], "issueKinds": Counter(), "changedWhileChecking": 0, "applied": apply}
    folders = sorted(p for p in resumes_root.iterdir() if p.is_dir()) if resumes_root.is_dir() else []
    for folder in folders:
        job = jobs.get(folder.name, {})
        facts = base_facts | {str(job.get(k) or "").lower() for k in ("title", "company", "location") if job.get(k)}
        failed_here = passed_here = False
        for file in sorted(f for f in folder.iterdir() if f.is_file() and verdicts.is_document(f.name)):
            state = verdicts.status(folder, file.name)
            if state not in RECHECKABLE:
                report["skipped"][state] += 1
                continue
            report["looked"] += 1
            data = file.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            passed, issues = judge(file.name, data, facts)
            if issues == [UNREADABLE]:
                report["unreadable"] += 1
            report["passed" if passed else "failed"] += 1
            failed_here |= not passed
            passed_here |= passed
            for issue in issues:
                report["issueKinds"][issue.split(":")[0]] += 1
            if apply:
                # Bound to the hash of the bytes that were read and judged: a file that changes meanwhile simply does not match.
                verdicts.write_verdict(folder, file.name, sha, passed, issues)
                report["written"] += 1
                if hashlib.sha256(file.read_bytes()).hexdigest() != sha:
                    report["changedWhileChecking"] += 1
        if failed_here:
            report["failedJobs"].append(folder.name)
        if passed_here and not failed_here:
            report["passedJobs"].append(folder.name)
    return report


def load_inputs(profile_path: Path = PROFILE_PATH, intelligence_path: Path = INTELLIGENCE_PATH, scored_path: Path = SCORED_PATH):
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    intelligence = json.loads(intelligence_path.read_text(encoding="utf-8"))
    jobs: dict[str, dict] = {}
    try:
        jobs = {j["jobId"]: j for j in json.loads(scored_path.read_text(encoding="utf-8")).get("jobs") or [] if j.get("jobId")}
    except (OSError, ValueError):
        pass  # without the job list a document is checked without its target's title, company and location
    return profile, intelligence, jobs


def print_report(report: dict) -> None:
    mode = "APPLIED" if report["applied"] else "DRY RUN (nothing written)"
    print(f"re-check of documents without a current verdict: {mode}")
    print(f"  looked at: {report['looked']}")
    print(f"  pass the current checks: {report['passed']}")
    print(f"  fail the current checks: {report['failed']} (of which unreadable: {report['unreadable']})")
    skipped = ", ".join(f"{k}: {v}" for k, v in sorted(report["skipped"].items())) or "none"
    print(f"  left alone (already have a verdict): {skipped}")
    if report["issueKinds"]:
        print("  reasons by kind: " + ", ".join(f"{k}: {v}" for k, v in sorted(report["issueKinds"].items())))
    print(f"jobs with every looked-at document passing ({len(report['passedJobs'])}): {', '.join(report['passedJobs']) or '-'}")
    print(f"jobs with a failing document ({len(report['failedJobs'])}): {', '.join(report['failedJobs']) or '-'}")
    if report["applied"]:
        print(f"  verdict files written: {report['written']}; documents that changed while being checked: {report['changedWhileChecking']}")
    else:
        print("Nothing was written. Run again with --apply to write the verdicts.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Re-check existing documents against the fact gate (no AI, no regeneration).")
    parser.add_argument("--apply", action="store_true", help="write the verdict files (default: dry run, writes nothing)")
    parser.add_argument("--root", type=Path, default=RESUMES_ROOT, help="documents folder (default data/resumes)")
    parser.add_argument("--profile", type=Path, default=PROFILE_PATH)
    parser.add_argument("--intelligence", type=Path, default=INTELLIGENCE_PATH)
    parser.add_argument("--scored", type=Path, default=SCORED_PATH)
    args = parser.parse_args(argv)
    try:
        profile, intelligence, jobs = load_inputs(args.profile, args.intelligence, args.scored)
    except (OSError, ValueError):
        print("The profile or intelligence on the server could not be read, so nothing was checked.", file=sys.stderr)
        return 1
    print_report(recheck(args.root, profile, intelligence, jobs, apply=args.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
