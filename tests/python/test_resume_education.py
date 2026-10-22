"""Education on the CV: what the profile states, and never anything else.

The generator once carried a hard-coded fallback (a university in Hyderabad,
a 2022 graduation, CGPA 7.0/10) that was printed whenever the education
entry did not parse. These tests pin that it cannot come back.
"""

import json

import pytest

from json_resume_export import build_json_resume
from docx_renderer import render_resume_docx
from resume_parser import education_problem, parse_education_entry, parse_resume_from_profile
from resume_tailor import build_resume_context
from template_engine import render_resume_html, render_resume_md

ENTRY = "B.Sc. Software Engineering — Faculty of Electronic Engineering, University of Niš | 2016"
FAKE = ("Jawaharlal", "Hyderabad", "7.0/10", "Bachelor of Technology")


def profile_with(education):
    return {
        "basicProfile": {"fullName": "Test Person", "email": "t@example.com"},
        "resume": {"rawText": "", "parsedData": {"skills": [], "education": education}},
    }


def test_entry_is_split_into_degree_school_and_year():
    edu = parse_education_entry(ENTRY)
    assert edu["degree"] == "B.Sc. Software Engineering"
    assert edu["school"] == "Faculty of Electronic Engineering, University of Niš"
    assert edu["graduated"] == "2016"
    assert edu["cgpa"] == ""


def test_parts_the_entry_does_not_state_stay_empty():
    edu = parse_education_entry("Software Engineering")
    assert edu == {"degree": "Software Engineering", "school": "", "graduated": "", "cgpa": ""}
    assert parse_education_entry("") == {}


def test_cgpa_is_read_only_when_the_entry_gives_one():
    edu = parse_education_entry("B.Sc. X — Some University | 2016, CGPA: 8.1/10")
    assert edu["cgpa"] == "8.1/10"
    assert edu["graduated"] == "2016"


def test_problem_detection():
    assert education_problem(parse_education_entry(ENTRY)) is None
    assert "no education entry" in education_problem({})
    assert "malformed" in education_problem(parse_education_entry(".Sc. Software Engineering — Uni | 2016"))
    assert "no school" in education_problem(parse_education_entry("Software Engineering"))


@pytest.mark.parametrize("education", [[], None, [""], ["   "]])
def test_missing_education_is_empty_not_invented(education):
    parsed = parse_resume_from_profile(profile_with(education))
    assert parsed["education"] == {}


def test_context_for_a_profile_without_education_warns_and_invents_nothing():
    ctx = build_resume_context(profile_with([]), {}, {"title": "PM", "description": ""})
    assert ctx["education"] == {}
    assert any(w.startswith("education:") for w in ctx["warnings"])
    assert not any(f in json.dumps(ctx, ensure_ascii=False) for f in FAKE)


def test_context_for_a_good_entry_has_no_warning():
    ctx = build_resume_context(profile_with([ENTRY]), {}, {"title": "PM", "description": ""})
    assert ctx["education"]["school"].startswith("Faculty of Electronic Engineering")
    assert ctx["warnings"] == []


def test_html_and_markdown_print_the_real_entry():
    ctx = build_resume_context(profile_with([ENTRY]), {}, {"title": "PM", "description": ""})
    for out in (render_resume_html({**ctx, "fit": {}}), render_resume_md(ctx)):
        assert "University of Niš" in out and "B.Sc. Software Engineering" in out
        assert "2016" in out
        assert not any(f in out for f in FAKE)


def test_templates_leave_the_section_out_without_education():
    ctx = build_resume_context(profile_with([]), {}, {"title": "PM", "description": ""})
    html = render_resume_html({**ctx, "fit": {}})
    md = render_resume_md(ctx)
    assert "<h2>Education</h2>" not in html
    assert "## Education" not in md
    assert not any(f in html + md for f in FAKE)


def test_markdown_has_no_dangling_labels_for_a_partial_entry():
    ctx = build_resume_context(profile_with(["Software Engineering"]), {}, {"title": "PM", "description": ""})
    md = render_resume_md(ctx)
    assert "Software Engineering" in md
    assert "Graduated" not in md and "CGPA" not in md


def test_json_resume_has_no_education_entry_without_education():
    ctx = build_resume_context(profile_with([]), {}, {"title": "PM", "description": ""})
    assert build_json_resume(profile_with([]), {}, ctx)["education"] == []


def test_json_resume_carries_the_real_entry():
    profile = profile_with([ENTRY])
    ctx = build_resume_context(profile, {}, {"title": "PM", "description": ""})
    edu = build_json_resume(profile, {}, ctx)["education"]
    assert edu == [
        {
            "institution": "Faculty of Electronic Engineering, University of Niš",
            "studyType": "B.Sc. Software Engineering",
            "endDate": "2016",
        }
    ]


def test_docx_prints_degree_school_and_year(tmp_path):
    docx = pytest.importorskip("docx")
    out = tmp_path / "cv.docx"
    ctx = build_resume_context(profile_with([ENTRY]), {}, {"title": "PM", "description": ""})
    assert render_resume_docx(ctx, out)
    text = "\n".join(p.text for p in docx.Document(str(out)).paragraphs)
    assert "B.Sc. Software Engineering, Faculty of Electronic Engineering, University of Niš (2016)" in text
    assert not any(f in text for f in FAKE)
