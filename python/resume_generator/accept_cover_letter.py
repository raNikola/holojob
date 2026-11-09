#!/usr/bin/env python3
"""Accept an AI cover-letter draft: re-run the fact gate on the draft file now, and only then make it a document.

`scripts/run-ai.js` writes the AI cover letter to data/resumes/<jobId>/drafts/ai_cover_letter.md, where nothing can attach it.
This step reads that draft from the server's own disk (never from the request), checks it against the profile facts, and on a
pass writes data/resumes/<jobId>/ai_cover_letter.md with its verdict. A failure writes nothing. Prints one JSON line.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(ROOT / "python" / "job_scoring") not in sys.path:
    sys.path.append(str(ROOT / "python" / "job_scoring"))

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic  # noqa: E402
from llm_tailor import load_project_intelligence, project_names  # noqa: E402
from provenance_checker import build_canonical_facts, check_draft  # noqa: E402
from verdicts import record_verdicts  # noqa: E402

PROFILE_PATH = ROOT / "data/profile/candidate-profile.json"
INTELLIGENCE_PATH = ROOT / "data/intelligence/candidate-intelligence.json"
SCORED_PATH = ROOT / "data/jobs/scored_jobs.json"
RESUMES_ROOT = ROOT / "data/resumes"
DRAFT_NAME = "ai_cover_letter.md"
JOB_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


def letter_paragraphs(text: str) -> list[str]:
    """The prose of the draft: the headings are ours, the variants are the model's."""
    blocks = (b.strip() for b in re.split(r"\n\s*\n", text))
    return [re.sub(r"\s+", " ", b) for b in blocks if b and not b.lstrip().startswith("#")]


def accept(job_id: str, *, resumes_root: Path = RESUMES_ROOT, profile_path: Path = PROFILE_PATH,
           intelligence_path: Path = INTELLIGENCE_PATH, scored_path: Path = SCORED_PATH) -> dict:
    if not JOB_ID_RE.match(job_id or "") or job_id in (".", ".."):
        return {"ok": False, "error": "invalid_job"}
    folder = resumes_root / job_id
    draft = folder / "drafts" / DRAFT_NAME
    if not draft.is_file():
        return {"ok": False, "error": "no_draft"}
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        intelligence = json.loads(intelligence_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "no_profile"}
    job: dict = {}
    try:
        for row in json.loads(scored_path.read_text(encoding="utf-8")).get("jobs") or []:
            if row.get("jobId") == job_id:
                job = row
                break
    except (OSError, ValueError):
        pass

    text = draft.read_text(encoding="utf-8")
    facts = build_canonical_facts(profile, intelligence)
    issues = check_draft({"cover_letter_paragraphs": letter_paragraphs(text)}, facts, job=job,
                         extra=project_names(load_project_intelligence()))
    if issues:
        return {"ok": False, "error": "facts_not_verified", "passed": False, "issues": issues}

    make_private_dirs(folder)
    write_text_atomic(folder / DRAFT_NAME, text, new_file_mode=PRIVATE_FILE_MODE)
    record_verdicts(folder, [DRAFT_NAME], True, [])
    return {"ok": True, "passed": True, "issues": [], "file": DRAFT_NAME}


def main() -> int:
    parser = argparse.ArgumentParser(description="Accept an AI cover-letter draft after the fact gate.")
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    print(json.dumps(accept(args.job_id), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
