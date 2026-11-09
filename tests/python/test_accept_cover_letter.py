"""An AI cover letter is a draft until the server re-runs the fact gate on it (Phase 4, confirmation)."""

import json

import pytest

import accept_cover_letter as acl
from verdicts import read_verdict, record_verdicts

CV = """Jane Canary
Senior Product Manager, Acme Platforms | Remote
May 2020 – Present
• Led the billing platform migration and reached 40% faster releases across the group.
SKILLS
Jira, SQL
"""
JOB = {"jobId": "job-1", "title": "Lead Product Manager", "company": "Hiring Co", "location": "Remote"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(acl, "load_project_intelligence", lambda: {})
    paths = {
        "profile_path": tmp_path / "profile.json",
        "intelligence_path": tmp_path / "intel.json",
        "scored_path": tmp_path / "scored.json",
        "resumes_root": tmp_path / "resumes",
    }
    paths["profile_path"].write_text(json.dumps(
        {"basicProfile": {"experienceYears": "12"}, "resume": {"rawText": CV, "parsedData": {"skills": ["Jira", "SQL"]}}}))
    paths["intelligence_path"].write_text("{}")
    paths["scored_path"].write_text(json.dumps({"jobs": [JOB]}))
    return paths


def draft(world, text, job_id="job-1"):
    folder = world["resumes_root"] / job_id / "drafts"
    folder.mkdir(parents=True)
    (folder / "ai_cover_letter.md").write_text(text, encoding="utf-8")
    return world["resumes_root"] / job_id


GOOD = """# AI Cover Letter Variants

## Short
I led the billing platform migration at Acme Platforms and reached 40% faster releases.

## Standard
I am applying for the Lead Product Manager role at Hiring Co. My work on billing platforms reached 40% faster releases.

## Aggressive

Billing platforms are my craft, and I shipped them with 12 years of experience.
"""


def test_a_letter_that_traces_to_the_profile_becomes_a_document_with_a_verdict(world):
    folder = draft(world, GOOD)
    result = acl.accept("job-1", **world)
    assert result == {"ok": True, "passed": True, "issues": [], "file": "ai_cover_letter.md"}
    assert (folder / "ai_cover_letter.md").read_text(encoding="utf-8") == GOOD
    assert read_verdict(folder, "ai_cover_letter.md")["passed"] is True
    assert (folder / ".ai_cover_letter.md.verdict.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("claim", [
    "I managed a team of 47 engineers.",
    "I hold a PhD in economics.",
    "I worked with Google and Netflix on search.",
])
def test_a_letter_with_an_unsupported_claim_is_refused_and_nothing_is_written(world, claim):
    folder = draft(world, GOOD.replace("Billing platforms are my craft", claim))
    result = acl.accept("job-1", **world)
    assert result["ok"] is False and result["error"] == "facts_not_verified" and result["issues"]
    assert not (folder / "ai_cover_letter.md").exists()
    assert not (folder / ".ai_cover_letter.md.verdict.json").exists()


def test_a_refused_letter_does_not_touch_an_earlier_accepted_one(world):
    folder = draft(world, GOOD)
    assert acl.accept("job-1", **world)["ok"]
    (folder / "drafts" / "ai_cover_letter.md").write_text("I managed 47 engineers.", encoding="utf-8")
    assert acl.accept("job-1", **world)["ok"] is False
    assert (folder / "ai_cover_letter.md").read_text(encoding="utf-8") == GOOD
    assert read_verdict(folder, "ai_cover_letter.md")["passed"] is True


def test_the_gate_runs_again_at_accept_time_on_the_current_draft(world):
    folder = draft(world, GOOD)
    (folder / "drafts" / "ai_cover_letter.md").write_text(GOOD + "\nI also led 47 engineers.\n", encoding="utf-8")
    assert acl.accept("job-1", **world)["error"] == "facts_not_verified"


@pytest.mark.parametrize("job_id", ["", "..", ".", "a/b", "../x", "a b", "x" * 300])
def test_an_unusable_job_id_is_refused(world, job_id):
    assert acl.accept(job_id, **world) == {"ok": False, "error": "invalid_job"}


def test_without_a_draft_there_is_nothing_to_accept(world):
    assert acl.accept("job-1", **world) == {"ok": False, "error": "no_draft"}


def test_without_a_readable_profile_nothing_is_accepted(world):
    draft(world, GOOD)
    world["profile_path"].write_text("{ broken")
    assert acl.accept("job-1", **world) == {"ok": False, "error": "no_profile"}


def test_a_verdict_stops_matching_when_the_file_changes(tmp_path):
    (tmp_path / "doc.md").write_text("one", encoding="utf-8")
    record_verdicts(tmp_path, ["doc.md", "missing.md"], True, [])
    assert read_verdict(tmp_path, "doc.md")["passed"] is True
    assert read_verdict(tmp_path, "missing.md") is None
    (tmp_path / "doc.md").write_text("two", encoding="utf-8")
    assert read_verdict(tmp_path, "doc.md") is None


def test_a_corrupt_verdict_counts_as_none(tmp_path):
    (tmp_path / "doc.md").write_text("one", encoding="utf-8")
    (tmp_path / ".doc.md.verdict.json").write_text("{ nope", encoding="utf-8")
    assert read_verdict(tmp_path, "doc.md") is None
