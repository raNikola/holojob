"""Spoken languages on the CV: profile -> context -> every CV renderer, never the cover letter."""

import re
from pathlib import Path

import pytest

from cover_letter_generator import build_cover_letter_context
from json_resume_export import build_json_resume
from docx_renderer import render_resume_docx
from profile_languages import (
    JSON_RESUME_FLUENCY,
    PROFICIENCIES,
    format_language,
    languages_text,
    normalize_languages,
)
from resume_parser import parse_resume_from_profile, skill_label
from resume_tailor import build_resume_context
from template_engine import render_cover_letter_md, render_resume_html, render_resume_md

ROOT = Path(__file__).resolve().parents[2]
LANGS = [
    {"language": "Serbian", "proficiency": "native"},
    {"language": "English", "proficiency": "fluent"},
]
JOB = {"title": "PM", "company": "Acme", "description": ""}


def profile_with(languages):
    basic = {"fullName": "Test Person", "email": "t@example.com"}
    if languages is not None:
        basic["languages"] = languages
    return {
        "basicProfile": basic,
        "resume": {"rawText": "", "parsedData": {"skills": [], "education": []}},
    }


def context(languages):
    return build_resume_context(profile_with(languages), {}, JOB)


@pytest.mark.parametrize("raw", [None, "Serbian", 5, {}, [None, "x", 3]])
def test_missing_or_malformed_input_is_an_empty_list(raw):
    assert normalize_languages(raw) == []


def test_normalize_keeps_valid_entries_and_leaves_unknown_levels_unstated():
    raw = [
        {"language": " Serbian ", "proficiency": "Native"},
        {"language": "German", "proficiency": "good-ish"},
        {"language": "", "proficiency": "fluent"},
    ]
    assert normalize_languages(raw) == [
        {"language": "Serbian", "proficiency": "native"},
        {"language": "German", "proficiency": ""},
    ]


def test_text_and_strings_match_what_the_judge_digest_reads():
    assert languages_text(LANGS) == "Serbian (native), English (fluent)"
    assert format_language({"language": "German", "proficiency": ""}) == "German"


def test_context_carries_the_languages():
    ctx = context(LANGS)
    assert ctx["languages"] == LANGS
    assert ctx["languages_text"] == "Serbian (native), English (fluent)"


def test_profiles_saved_before_the_field_existed_have_no_languages():
    ctx = context(None)
    assert ctx["languages"] == [] and ctx["languages_text"] == ""


def test_html_and_markdown_print_a_languages_section():
    ctx = context(LANGS)
    html = render_resume_html({**ctx, "fit": {}})
    md = render_resume_md(ctx)
    assert "<h2>Languages</h2>" in html and "Serbian (native), English (fluent)" in html
    assert "## Languages" in md and "Serbian (native), English (fluent)" in md


def test_no_section_without_languages():
    ctx = context([])
    assert "<h2>Languages</h2>" not in render_resume_html({**ctx, "fit": {}})
    assert "## Languages" not in render_resume_md(ctx)


def test_docx_prints_a_languages_section(tmp_path):
    docx = pytest.importorskip("docx")
    out = tmp_path / "cv.docx"
    assert render_resume_docx(context(LANGS), out)
    paragraphs = [p.text for p in docx.Document(str(out)).paragraphs]
    assert "Languages" in paragraphs
    assert "Serbian (native), English (fluent)" in paragraphs


def test_docx_has_no_languages_heading_without_languages(tmp_path):
    docx = pytest.importorskip("docx")
    out = tmp_path / "cv.docx"
    assert render_resume_docx(context([]), out)
    assert "Languages" not in [p.text for p in docx.Document(str(out)).paragraphs]


def test_json_resume_uses_the_schemas_languages_with_fluency():
    ctx = context(LANGS)
    assert build_json_resume(profile_with(LANGS), {}, ctx)["languages"] == [
        {"language": "Serbian", "fluency": "Native speaker"},
        {"language": "English", "fluency": "Fluent"},
    ]


def test_json_resume_omits_fluency_when_unstated_and_the_list_when_empty():
    ctx = context([{"language": "German", "proficiency": ""}])
    assert build_json_resume(profile_with(None), {}, ctx)["languages"] == [{"language": "German"}]
    assert build_json_resume(profile_with(None), {}, context([]))["languages"] == []


def test_every_proficiency_has_a_json_resume_wording():
    assert set(JSON_RESUME_FLUENCY) == set(PROFICIENCIES)


def test_cover_letter_does_not_carry_the_languages():
    ctx = context(LANGS)
    letter = render_cover_letter_md(build_cover_letter_context(profile_with(LANGS), {}, JOB, ctx))
    assert "Serbian (native)" not in letter
    assert "Languages" not in letter


def labels(ctx):
    return [cat["label"] for cat in ctx["skill_categories"]]


@pytest.mark.parametrize("label", ["Languages", "languages", " Languages: ", "Language"])
def test_bare_languages_row_is_renamed(label):
    assert skill_label(label) == "Programming languages"


@pytest.mark.parametrize("label", ["Backend Frameworks", "Databases", "Programming languages", "Spoken languages"])
def test_other_rows_keep_their_label(label):
    assert skill_label(label) == label


def test_default_skill_rows_do_not_collide_with_the_spoken_languages_section():
    ctx = context(LANGS)
    assert "Programming languages" in labels(ctx)
    assert "Languages" not in labels(ctx)


def test_a_languages_row_in_the_candidates_own_cv_is_renamed():
    profile = profile_with(LANGS)
    profile["resume"]["rawText"] = "SKILLS AND OTHERS Languages: Go, Java Databases: PostgreSQL EDUCATION x"
    rows = parse_resume_from_profile(profile)["skill_categories"]
    assert [r["label"] for r in rows] == ["Programming languages", "Databases"]
    assert rows[0]["skills"] == ["Go", "Java"]


def test_rendered_cv_has_one_spoken_languages_heading_and_a_programming_row():
    ctx = context(LANGS)
    ctx["skill_categories"] = [{"label": "Programming languages", "skills": ["Go", "Java"]}]
    html = render_resume_html({**ctx, "fit": {}})
    assert html.count("<h2>Languages</h2>") == 1
    assert "Programming languages:" in html
    assert ">Languages:<" not in html


def test_llm_drafted_categories_cannot_bring_the_bare_label_back():
    from run_tailor import _apply_llm_content

    ctx = context(LANGS)
    llm = {"subtitle": "S", "summary": "T", "skills": [{"label": "Languages", "skills": ["Go"]}]}
    merged = _apply_llm_content(ctx, llm, {"skillsMap": {"technicalSkills": ["Go"]}})
    assert [c["label"] for c in merged["skill_categories"]] == ["Programming languages"]


def test_proficiency_lists_in_js_and_python_agree():
    source = (ROOT / "src" / "utils" / "languages.js").read_text(encoding="utf-8")
    body = re.search(r"LANGUAGE_PROFICIENCIES\s*=\s*\[([^\]]*)\]", source).group(1)
    assert tuple(re.findall(r"'([^']+)'", body)) == PROFICIENCIES
