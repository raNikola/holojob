"""Education on the CV: what the profile states, and never anything else.

The generator once carried a hard-coded fallback that printed an education the
candidate never had whenever their entry did not parse. Any fallback would
leave a trace: a section on a CV whose profile gave none. So these tests pin
the absence: nothing given, nothing printed.
"""

import pytest

from json_resume_export import build_json_resume
from docx_renderer import render_resume_docx
from resume_parser import education_problem, parse_education_entry, parse_resume_from_profile
from resume_tailor import build_resume_context
from template_engine import render_resume_html, render_resume_md

ENTRY = "B.Sc. Computer Science — Faculty of Informatics, University of Brno | 2016"
JOB = {"title": "PM", "description": ""}


def profile_with(education):
    return {
        "basicProfile": {"fullName": "Test Person", "email": "t@example.com"},
        "resume": {"rawText": "", "parsedData": {"skills": [], "education": education}},
    }


def context(education):
    return build_resume_context(profile_with(education), {}, JOB)


def test_entry_is_split_into_degree_school_and_year():
    edu = parse_education_entry(ENTRY)
    assert edu["degree"] == "B.Sc. Computer Science"
    assert edu["school"] == "Faculty of Informatics, University of Brno"
    assert edu["graduated"] == "2016"
    assert set(edu) == {"degree", "school", "graduated"}


def test_parts_the_entry_does_not_state_stay_empty():
    assert parse_education_entry("Software Engineering") == {
        "degree": "Software Engineering", "school": "", "graduated": "",
    }
    assert parse_education_entry("") == {}


def test_problem_detection():
    assert education_problem(parse_education_entry(ENTRY)) is None
    assert "no education entry" in education_problem({})
    assert "malformed" in education_problem(parse_education_entry(".Sc. Software Engineering — Uni | 2016"))
    assert "no school" in education_problem(parse_education_entry("Software Engineering"))


@pytest.mark.parametrize("education", [[], None, [""], ["   "]])
def test_missing_education_is_empty_not_invented(education):
    assert parse_resume_from_profile(profile_with(education))["education"] == {}


def test_context_for_a_profile_without_education_warns_and_prints_nothing():
    ctx = context([])
    assert ctx["education"] == {}
    assert any(w.startswith("education:") for w in ctx["warnings"])
    assert "<h2>Education</h2>" not in render_resume_html({**ctx, "fit": {}})
    assert "## Education" not in render_resume_md(ctx)


def test_context_for_a_good_entry_has_no_education_warning():
    ctx = context([ENTRY])
    assert ctx["education"]["school"].startswith("Faculty of Informatics")
    assert not any(w.startswith("education:") for w in ctx["warnings"])


def test_html_and_markdown_print_the_real_entry():
    ctx = context([ENTRY])
    for out in (render_resume_html({**ctx, "fit": {}}), render_resume_md(ctx)):
        assert "University of Brno" in out and "B.Sc. Computer Science" in out
        assert "2016" in out


def test_markdown_has_no_dangling_label_for_a_partial_entry():
    md = render_resume_md(context(["Software Engineering"]))
    assert "Software Engineering" in md
    assert "Graduated" not in md


def test_json_resume_has_no_education_entry_without_education():
    ctx = context([])
    assert build_json_resume(profile_with([]), {}, ctx)["education"] == []


def test_json_resume_carries_the_real_entry():
    profile = profile_with([ENTRY])
    ctx = build_resume_context(profile, {}, JOB)
    assert build_json_resume(profile, {}, ctx)["education"] == [
        {
            "institution": "Faculty of Informatics, University of Brno",
            "studyType": "B.Sc. Computer Science",
            "endDate": "2016",
        }
    ]


def test_docx_prints_degree_school_and_year(tmp_path):
    docx = pytest.importorskip("docx")
    out = tmp_path / "cv.docx"
    assert render_resume_docx(context([ENTRY]), out)
    text = "\n".join(p.text for p in docx.Document(str(out)).paragraphs)
    assert "B.Sc. Computer Science, Faculty of Informatics, University of Brno (2016)" in text


def test_docx_has_no_education_heading_without_education(tmp_path):
    docx = pytest.importorskip("docx")
    out = tmp_path / "cv.docx"
    assert render_resume_docx(context([]), out)
    assert "Education" not in [p.text for p in docx.Document(str(out)).paragraphs]
