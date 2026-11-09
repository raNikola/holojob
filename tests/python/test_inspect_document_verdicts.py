"""scripts/inspect-document-verdicts.py: read-only, counts and job ids only."""

import importlib.util
from pathlib import Path

import pytest

from verdicts import record_verdicts

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "inspect-document-verdicts.py"
spec = importlib.util.spec_from_file_location("inspect_document_verdicts", SCRIPT)
inspector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspector)

SECRET = "CANARY-CV-CONTENT"


def snapshot(root):
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def resumes(tmp_path):
    root = tmp_path / "resumes"
    for job in ("ok", "old", "bad", "edited"):
        (root / job).mkdir(parents=True)
        (root / job / "tailored_resume.md").write_text(f"{SECRET} {job}", encoding="utf-8")
        (root / job / "Jane_Acme_PM_Resume.pdf").write_bytes(b"%PDF " + SECRET.encode())
        (root / job / "drafts").mkdir()
        (root / job / "drafts" / "ai_cover_letter.md").write_text(SECRET, encoding="utf-8")
    record_verdicts(root / "ok", ["tailored_resume.md", "Jane_Acme_PM_Resume.pdf"], True, [])
    record_verdicts(root / "bad", ["tailored_resume.md", "Jane_Acme_PM_Resume.pdf"], False, ["Unverified number: 47"])
    record_verdicts(root / "edited", ["tailored_resume.md", "Jane_Acme_PM_Resume.pdf"], True, [])
    (root / "edited" / "tailored_resume.md").write_text("changed", encoding="utf-8")
    return root


def test_counts_each_state_and_lists_job_ids(resumes):
    counts, jobs = inspector.inspect(resumes)
    assert dict(counts) == {"verified": 3, "missing": 2, "failed": 2, "changed": 1}
    assert jobs == {"missing": ["old"], "failed": ["bad"], "changed": ["edited"]}


def test_prints_counts_and_ids_but_no_content_or_issue_text(resumes, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["inspect-document-verdicts.py", "--root", str(resumes)])
    assert inspector.main() == 0
    out = capsys.readouterr().out
    assert "documents: 8" in out and "missing: 2" in out and "old" in out and "bad" in out
    assert SECRET not in out and "Unverified" not in out and "Jane_Acme" not in out


def test_changes_nothing(resumes):
    before = snapshot(resumes)
    inspector.inspect(resumes)
    assert snapshot(resumes) == before


def test_a_missing_folder_is_an_empty_report(tmp_path):
    counts, jobs = inspector.inspect(tmp_path / "nope")
    assert not counts and not jobs
