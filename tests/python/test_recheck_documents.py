"""Re-checking existing documents: no regeneration, no AI, verdicts bound to the file hash, documents and applications untouched."""

import hashlib
import io
import json
import re
from pathlib import Path

import pytest

import recheck_documents as rc
import verdicts
from document_text import extract_text

CV = """Jane Canary
Senior Product Manager, Acme Platforms | Remote
May 2020 – Present
• Led the billing platform migration and reached 40% faster releases across the group.
SKILLS
Jira, SQL
"""
GOOD = "Led the billing platform migration at Acme Platforms and reached 40% faster releases."
BAD = "Managed a team of 47 engineers."
SECRET = "CANARY-DOCUMENT-CONTENT"
JOB = {"jobId": "job-1", "title": "Lead Product Manager 2", "company": "Hiring Co", "location": "Remote"}


def make_pdf(text: str) -> bytes:
    """A one-page PDF whose text pypdf can read (hand-written, so the test needs no PDF library to write one)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    return out + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def make_docx(text: str) -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def write_set(folder: Path, text: str, *, date="November 9, 2026"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tailored_resume.md").write_text(f"# Jane\n{text}\nMay 2020 – Present\n", encoding="utf-8")
    (folder / "tailored_resume.html").write_text(f"<html><body><p>{text}</p></body></html>", encoding="utf-8")
    (folder / "cover_letter.md").write_text(f"{date}\n\n{text}\n", encoding="utf-8")
    (folder / "Jane_Acme_PM_Resume.json").write_text(json.dumps(
        {"basics": {"summary": text}, "work": [{"startDate": "2020-05", "endDate": "2024-01-15", "summary": text}]}), encoding="utf-8")
    (folder / "Jane_Acme_PM_Resume.docx").write_bytes(make_docx(text))
    (folder / "Jane_Acme_PM_Resume.pdf").write_bytes(make_pdf(text))
    (folder / "Jane_Acme_PM_CoverLetter.pdf").write_bytes(make_pdf(f"{date} {text}"))


@pytest.fixture
def world(tmp_path):
    profile = {"basicProfile": {"experienceYears": "12"}, "resume": {"rawText": CV, "parsedData": {"skills": ["Jira", "SQL"]}}}
    root = tmp_path / "resumes"
    write_set(root / "good", GOOD)
    write_set(root / "bad", BAD)
    return profile, {}, {"job-1": JOB}, root


def snapshot(root: Path):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file()}


def sidecars(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob(".*.verdict.json"))


def test_text_is_read_from_every_kind_of_file(tmp_path):
    write_set(tmp_path / "x", "Shipped billing tools")
    for file in sorted((tmp_path / "x").iterdir()):
        assert "Shipped billing tools" in extract_text(file.name, file.read_bytes()), file.name


def test_iso_dates_of_a_json_resume_are_not_claims(tmp_path):
    data = json.dumps({"work": [{"startDate": "2020-05", "endDate": "2024-01-15", "summary": "Built it", "year": "2021"}]}).encode()
    text = extract_text("x_Resume.json", data)
    assert "Built it" in text and "2020-05" not in text and "2024-01-15" not in text


def test_a_corrupt_or_empty_file_cannot_be_read_and_is_never_a_pass(tmp_path):
    assert extract_text("a_Resume.pdf", b"not a pdf") is None
    assert extract_text("a_Resume.docx", b"not a docx") is None
    assert extract_text("a_Resume.json", b"{ broken") is None
    assert rc.judge("a_Resume.pdf", b"not a pdf", set()) == (False, [rc.UNREADABLE])
    assert rc.judge("cover_letter.md", b"   ", set()) == (False, [rc.UNREADABLE])


def test_dry_run_reports_counts_and_job_ids_and_writes_nothing(world, capsys):
    profile, intel, jobs, root = world
    before = snapshot(root)
    report = rc.recheck(root, profile, intel, jobs)
    assert snapshot(root) == before and sidecars(root) == []
    assert report["looked"] == 14 and report["passed"] == 7 and report["failed"] == 7 and report["written"] == 0
    assert report["failedJobs"] == ["bad"] and report["passedJobs"] == ["good"]
    rc.print_report(report)
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "bad" in out and "good" in out and "Nothing was written" in out
    assert SECRET not in out and BAD not in out and "47" not in out and "Jane_Acme" not in out


def test_apply_writes_a_verdict_per_file_bound_to_its_hash_and_changes_no_document(world):
    profile, intel, jobs, root = world
    documents = snapshot(root)
    report = rc.recheck(root, profile, intel, jobs, apply=True)
    assert report["written"] == 14 and report["changedWhileChecking"] == 0
    assert snapshot(root) == {k: v for k, v in snapshot(root).items() if k in documents} | {k: v for k, v in snapshot(root).items() if k not in documents}
    after = snapshot(root)
    assert {k: v for k, v in after.items() if k in documents} == documents          # every document byte- and mtime-identical
    assert len(sidecars(root)) == 14 and len(after) == len(documents) + 14           # nothing else was created
    for folder, expected in (("good", "verified"), ("bad", "failed")):
        for file in (root / folder).iterdir():
            if verdicts.is_document(file.name):
                assert verdicts.status(root / folder, file.name) == expected, (folder, file.name)
                body = json.loads(verdicts.verdict_path(root / folder, file.name).read_text(encoding="utf-8"))
                assert body["sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()
                assert body["passed"] is (expected == "verified") and body["gateVersion"] == verdicts.GATE_VERSION
                assert (body["issues"] == []) is (expected == "verified")
    assert "Unverified number: 47" in json.loads((root / "bad" / ".cover_letter.md.verdict.json").read_text(encoding="utf-8"))["issues"]


def test_a_failed_document_keeps_its_reasons_and_stays_blocked(world):
    profile, intel, jobs, root = world
    rc.recheck(root, profile, intel, jobs, apply=True)
    body = json.loads((root / "bad" / ".tailored_resume.md.verdict.json").read_text(encoding="utf-8"))
    assert body["passed"] is False and body["issues"]
    assert (root / "bad" / "tailored_resume.md").exists()           # nothing deleted


def test_a_second_apply_looks_at_nothing_and_a_current_verdict_is_left_alone(world):
    profile, intel, jobs, root = world
    rc.recheck(root, profile, intel, jobs, apply=True)
    sidecar_bytes = {p: p.read_bytes() for p in root.rglob(".*.verdict.json")}
    again = rc.recheck(root, profile, intel, jobs, apply=True)
    assert again["looked"] == 0 and again["written"] == 0 and again["skipped"]["verified"] == 7 and again["skipped"]["failed"] == 7
    assert {p: p.read_bytes() for p in root.rglob(".*.verdict.json")} == sidecar_bytes


def test_a_changed_document_and_an_older_gate_are_treated_as_they_are(world):
    profile, intel, jobs, root = world
    rc.recheck(root, profile, intel, jobs, apply=True)
    (root / "good" / "cover_letter.md").write_text("edited by hand", encoding="utf-8")       # now 'changed': left alone
    old = verdicts.verdict_path(root / "good", "tailored_resume.md")
    body = json.loads(old.read_text(encoding="utf-8"))
    old.write_text(json.dumps({**body, "gateVersion": 0}), encoding="utf-8")                  # 'old_gate': checked again
    report = rc.recheck(root, profile, intel, jobs, apply=True)
    assert report["looked"] == 1 and report["skipped"]["changed"] == 1
    assert verdicts.status(root / "good", "tailored_resume.md") == "verified"
    assert verdicts.status(root / "good", "cover_letter.md") == "changed"


def test_the_job_s_own_title_may_be_named_and_a_missing_job_is_checked_without_it(world):
    profile, intel, jobs, root = world
    write_set(root / "job-1", "I apply for the Lead Product Manager 2 role at Hiring Co.")
    assert rc.recheck(root, profile, intel, jobs)["passedJobs"].count("job-1") == 1
    assert "job-1" in rc.recheck(root, profile, intel, {})["failedJobs"]


def test_the_date_the_letter_was_made_is_not_a_claim(world):
    profile, intel, jobs, root = world
    write_set(root / "dated", GOOD, date="March 3, 2025")
    assert "dated" in rc.recheck(root, profile, intel, jobs)["passedJobs"]


def test_a_document_that_changes_while_it_is_checked_gets_a_verdict_for_what_was_read(world, monkeypatch):
    profile, intel, jobs, root = world
    target = root / "good" / "cover_letter.md"
    real = rc.judge

    def judge_then_edit(name, data, facts):
        result = real(name, data, facts)
        if name == "cover_letter.md" and data == target.read_bytes():       # only the file under test, not another job's letter
            target.write_text("replaced while checking", encoding="utf-8")
        return result

    monkeypatch.setattr(rc, "judge", judge_then_edit)
    report = rc.recheck(root, profile, intel, jobs, apply=True)
    assert report["changedWhileChecking"] == 1
    assert verdicts.status(root / "good", "cover_letter.md") == "changed"      # blocked: the verdict is for the bytes that were read


def test_no_model_is_called_and_nothing_is_regenerated(world, monkeypatch):
    profile, intel, jobs, root = world
    import claude_code

    def refuse(*a, **k):
        raise AssertionError("a model was called")

    monkeypatch.setattr(claude_code, "_run", refuse)
    monkeypatch.setattr(claude_code.subprocess, "run", refuse)
    rc.recheck(root, profile, intel, jobs, apply=True)
    source = Path(rc.__file__).read_text(encoding="utf-8")
    assert not re.search(r"claude_code|ai_gate|run_tailor|generate_llm|render_", source.replace("no AI call", ""))


def test_the_application_records_are_never_touched(world, tmp_path):
    profile, intel, jobs, root = world
    base = tmp_path / "data" / "applications"
    (base / "files" / "app-1").mkdir(parents=True)
    (base / "applications.json").write_text(json.dumps({"applications": {"app-1": {"events": [{"type": "application_voided"}]}}}))
    (base / "files" / "app-1" / "Resume.pdf").write_bytes(b"%PDF frozen copy")
    before = snapshot(base)
    rc.recheck(root, profile, intel, jobs)
    rc.recheck(root, profile, intel, jobs, apply=True)
    assert snapshot(base) == before
    import ast

    tree = ast.parse(Path(rc.__file__).read_text(encoding="utf-8"))
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    docstring = tree.body[0].value.value          # the module docstring, as written
    code_strings = [t for t in strings if t != docstring]
    assert not any("applications" in t for t in code_strings), code_strings


def test_the_cli_defaults_to_a_dry_run(world, tmp_path, monkeypatch, capsys):
    profile, intel, jobs, root = world
    (tmp_path / "p.json").write_text(json.dumps(profile))
    (tmp_path / "i.json").write_text("{}")
    (tmp_path / "s.json").write_text(json.dumps({"jobs": [JOB]}))
    common = ["--root", str(root), "--profile", str(tmp_path / "p.json"), "--intelligence", str(tmp_path / "i.json"), "--scored", str(tmp_path / "s.json")]
    assert rc.main(common) == 0
    assert sidecars(root) == [] and "DRY RUN" in capsys.readouterr().out
    assert rc.main([*common, "--apply"]) == 0
    assert len(sidecars(root)) == 14 and "APPLIED" in capsys.readouterr().out


def test_unreadable_inputs_stop_with_an_error_and_write_nothing(world, tmp_path, capsys):
    _, _, _, root = world
    assert rc.main(["--root", str(root), "--profile", str(tmp_path / "missing.json"), "--apply"]) == 1
    assert sidecars(root) == []
