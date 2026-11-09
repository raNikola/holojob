"""Wave 7 S4: DOCX resumes. Files are built here with python-docx (no real documents, no personal data)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from docx import Document
from docx.oxml import parse_xml
from docx.opc.constants import RELATIONSHIP_TYPE as RT

from profile_import.docx_reader import MAX_DOCX_BYTES, check_package, docx_to_text
from profile_import.text_parser import TextImportError, parse_text

ROOT = Path(__file__).resolve().parents[2]
RUNNER = str(ROOT / "python/profile_import/run_file_import.py")
CANARY = "Zorbel-Canary-5521"


def _bytes(document) -> bytes:
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _resume() -> Document:
    d = Document()
    d.sections[0].header.paragraphs[0].text = "jane@example.invalid | +1 555 010 0100"
    d.add_paragraph("Jane Sample")
    d.add_paragraph("Summary")
    d.add_paragraph("Product leader with 10+ years shipping software.")
    d.add_paragraph("Experience")
    d.add_paragraph("Head of Product — Northwind")
    d.add_paragraph("April 2024 – Present")
    d.add_paragraph("Grew ARR by 40%.", style="List Bullet")
    d.add_paragraph("Cut churn.", style="List Bullet")
    d.add_paragraph("Skills")
    table = d.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Roadmapping"
    table.rows[0].cells[1].text = "SQL"
    d.add_paragraph("Education")
    d.add_paragraph("BSc Economics, University of Springfield, 2012")
    return d


def test_reads_headers_paragraphs_lists_and_tables_in_document_order():
    text, notes = docx_to_text(_bytes(_resume()))
    assert notes == []
    lines = text.split("\n")
    assert lines[0] == "jane@example.invalid | +1 555 010 0100"  # the header holds the contact line
    assert "- Grew ARR by 40%." in lines and "- Cut churn." in lines
    assert "Roadmapping | SQL" in lines
    assert lines.index("Experience") < lines.index("Skills") < lines.index("Education")


def test_the_text_goes_through_the_same_parser_as_pasted_text():
    text, _ = docx_to_text(_bytes(_resume()))
    draft = parse_text(text, "resume_docx")
    assert draft["source"] == "resume_docx" and draft["parserVersion"] == "text-1"
    assert draft["basicProfile"]["email"] == "jane@example.invalid"
    entry = draft["parsedData"]["experienceDetail"][0]
    assert entry["company"] == "Northwind" and entry["bullets"] == ["Grew ARR by 40%.", "Cut churn."]
    assert "SQL" in draft["parsedData"]["skills"] and "Roadmapping" in draft["parsedData"]["skills"]
    assert draft["parsedData"]["education"] and "Springfield" in draft["parsedData"]["education"][0]


def test_a_hyperlink_keeps_its_address_and_a_merged_cell_is_read_once():
    d = Document()
    p = d.add_paragraph("My profile: ")
    rid = d.part.relate_to("https://linkedin.com/in/jane-sample", RT.HYPERLINK, is_external=True)
    p._p.append(parse_xml(
        f'<w:hyperlink xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="{rid}"><w:r><w:t>LinkedIn</w:t></w:r></w:hyperlink>'))
    table = d.add_table(rows=1, cols=3)
    table.rows[0].cells[0].merge(table.rows[0].cells[1]).text = "Merged"
    table.rows[0].cells[2].text = "Last"
    text, _ = docx_to_text(_bytes(d))
    assert "LinkedIn https://linkedin.com/in/jane-sample" in text
    assert "Merged | Last" in text.split("\n")


def test_text_boxes_are_reported_not_silently_dropped():
    d = _resume()
    d.element.body.append(parse_xml(
        '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:r><w:pict><w:txbxContent><w:p><w:r><w:t>boxed</w:t></w:r></w:p></w:txbxContent></w:pict></w:r></w:p>'))
    _, notes = docx_to_text(_bytes(d))
    assert notes and "Text boxes" in notes[0]


def test_a_document_without_text_is_no_text_not_an_empty_draft():
    d = Document()
    d.add_paragraph("   ")
    with pytest.raises(TextImportError) as err:
        docx_to_text(_bytes(d))
    assert err.value.code == "no_text"


def _zip(members: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return out.getvalue()


@pytest.mark.parametrize("name,data,code", [
    ("empty", b"", "empty"),
    ("not a zip", b"MZ" + b"x" * 300, "corrupt_file"),
    ("old .doc or password protected", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100, "encrypted"),
    ("macro enabled", _zip({"word/document.xml": b"<x/>", "word/vbaProject.bin": b"vba"}), "unsupported_type"),
    ("a zip that is not a Word file", _zip({"readme.txt": b"hello"}), "unsupported_type"),
    ("an unpacked-size bomb", _zip({"word/document.xml": b"\0" * (60 * 1024 * 1024)}), "corrupt_file"),
    ("too many members", _zip({"word/document.xml": b"<x/>", **{f"m{i}.txt": b"a" for i in range(2100)}}), "corrupt_file"),
    ("over the size limit", b"PK" + b"x" * (MAX_DOCX_BYTES + 1), "too_large"),
])
def test_refusals_use_fixed_codes(name, data, code):
    with pytest.raises(TextImportError) as err:
        docx_to_text(data)
    assert err.value.code == code, name


def test_a_truncated_docx_is_corrupt_and_the_error_carries_no_content():
    good = _bytes(_resume())
    d = Document()
    d.add_paragraph(CANARY)
    cut = _bytes(d)[:-40]
    with pytest.raises(TextImportError) as err:
        docx_to_text(cut)
    assert err.value.code == "corrupt_file" and CANARY not in str(err.value) and err.value.__cause__ is None
    assert docx_to_text(good)[0]


def test_a_forged_docx_with_broken_xml_is_corrupt_not_a_crash():
    with pytest.raises(TextImportError) as err:
        docx_to_text(_zip({"word/document.xml": f"<w:document>{CANARY}".encode(), "[Content_Types].xml": b"<x/>"}))
    assert err.value.code == "corrupt_file" and CANARY not in str(err.value)


def test_external_entities_are_not_resolved():
    xxe = (b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY e SYSTEM "file:///etc/hostname">]>'
           b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&e;</w:t></w:r></w:p></w:body></w:document>')
    base = _bytes(Document())
    with zipfile.ZipFile(io.BytesIO(base)) as z:
        members = {n: z.read(n) for n in z.namelist()}
    members["word/document.xml"] = xxe
    try:
        text, _ = docx_to_text(_zip(members))
    except TextImportError:
        return
    assert Path("/etc/hostname").read_text().strip() not in text


def _run(data: bytes, source="resume_docx"):
    return subprocess.run([sys.executable, "-I", RUNNER, source], input=data, capture_output=True)


def test_the_runner_answers_a_draft_or_a_fixed_code_and_prints_nothing_to_stderr():
    ok = _run(_bytes(_resume()))
    out = json.loads(ok.stdout)
    assert out["ok"] is True and out["draft"]["source"] == "resume_docx" and ok.stderr == b""
    for data, code in ((b"", "empty"), (b"garbage " + CANARY.encode(), "corrupt_file")):
        bad = _run(data)
        assert json.loads(bad.stdout) == {"ok": False, "code": code}
        assert CANARY.encode() not in bad.stdout + bad.stderr and bad.stderr == b""
    assert json.loads(_run(b"x", "paste").stdout) == {"ok": False, "code": "invalid_request"}


def test_the_file_is_not_written_anywhere(tmp_path):
    before = sorted(p.name for p in Path("/tmp").glob("*docx*"))
    _run(_bytes(_resume()))
    assert sorted(p.name for p in Path("/tmp").glob("*docx*")) == before


def test_check_package_accepts_a_real_document():
    check_package(_bytes(_resume()))
