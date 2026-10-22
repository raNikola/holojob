"""Rule-based tailoring states only what the candidate stated."""

from resume_tailor import build_resume_context
from template_engine import render_resume_html, render_resume_md

CV = (
    "JO DOE PRODUCT LEADER FOR PLATFORMS CONTACT Leeds, UK | jo@example.com "
    "PROFESSIONAL SUMMARY Product leader with a decade of platform work and a record of shipping. "
    "PROFESSIONAL EXPERIENCE Product Lead, Acme | Remote May 2020 – Present | (Platform vendor) "
    "Owned the roadmap for the billing platform and launched it to the first fifty customers. "
    "TOOLS Delivery: Jira, Figma. Analysis: SQL, Looker EDUCATION Some University"
)
JOB = {"title": "Staff Backend Engineer (Payments)", "description": "Kubernetes, Go, AWS microservices."}


def profile(raw=CV, skills=("Product Strategy", "Jira", "Go")):
    return {
        "basicProfile": {"fullName": "Jo Doe", "currentRole": "Product Lead"},
        "resume": {
            "rawText": raw,
            "parsedData": {
                "skills": list(skills),
                "workExperience": ["Product Lead — Acme | May 2020–Present | Platform"],
                "education": ["B.A. History — Some University | 2012"],
                "links": [],
            },
        },
    }


def test_the_summary_is_the_candidates_own_text_whatever_the_job_is():
    ctx = build_resume_context(profile(), {}, JOB)
    assert ctx["summary"] == "Product leader with a decade of platform work and a record of shipping."
    # The job's vocabulary does not leak into claims about the candidate.
    for word in ("Backend", "Payments", "Kubernetes", "cloud-native", "distributed"):
        assert word not in ctx["summary"]


def test_the_tagline_is_the_candidates_headline_not_the_jobs_title():
    ctx = build_resume_context(profile(), {}, JOB)
    assert ctx["subtitle"] == "Product Leader for Platforms"
    assert "Backend" not in ctx["subtitle"]


def test_without_a_headline_the_tagline_is_the_profiles_current_role():
    ctx = build_resume_context(profile(raw="no header here"), {}, JOB)
    assert ctx["subtitle"] == "Product Lead"


def test_with_no_summary_anywhere_the_summary_is_empty_and_warned_about():
    ctx = build_resume_context(profile(raw="JO DOE EXPERIENCE nothing"), {}, JOB)
    assert ctx["summary"] == ""
    assert any(w.startswith("summary:") for w in ctx["warnings"])
    assert "<h2>Professional Summary</h2>" not in render_resume_html({**ctx, "fit": {}})
    assert "## Professional Summary" not in render_resume_md(ctx)


def test_the_questionnaire_answer_fills_in_a_missing_summary():
    p = profile(raw="JO DOE EXPERIENCE nothing")
    p["questionnaire"] = {"answers": [{"id": 17, "question": "career summary", "answer": "I lead product teams."}]}
    assert build_resume_context(p, {}, JOB)["summary"] == "I lead product teams."


def test_the_engines_narrative_is_never_used_for_the_summary():
    # Without the questionnaire answer the engine fills careerNarrative from a
    # template or a placeholder; neither is the candidate's own text.
    intelligence = {"candidateSummary": {"careerNarrative": "Career narrative pending — complete questionnaire Q17."}}
    ctx = build_resume_context(profile(raw="JO DOE EXPERIENCE nothing"), intelligence, JOB)
    assert ctx["summary"] == ""


def test_a_summary_sentence_with_a_banned_phrase_is_left_out_not_edited():
    raw = CV.replace("a record of shipping.", "a record of shipping. I am a passionate team player.")
    assert build_resume_context(profile(raw=raw), {}, JOB)["summary"] == (
        "Product leader with a decade of platform work and a record of shipping."
    )


def test_contact_line_comes_from_the_parsed_header_and_profile():
    ctx = build_resume_context(profile(), {}, JOB)
    assert ctx["contact_items"] == ["Leeds, UK", "jo@example.com"]


def test_skill_rows_are_the_cvs_own_rows_plus_one_row_for_the_rest_of_the_profile():
    ctx = build_resume_context(profile(), {}, JOB)
    rows = {r["label"]: r["skills"] for r in ctx["skill_categories"]}
    assert rows["Delivery"] == ["Jira", "Figma"] and rows["Analysis"] == ["SQL", "Looker"]
    # Jira is already shown; the rest of the profile's list follows in one row.
    assert rows["Skills"] == ["Product Strategy", "Go"]


def test_no_work_experience_anywhere_is_warned_about_and_left_empty():
    p = profile(raw="JO DOE SUMMARY text here")
    p["resume"]["parsedData"]["workExperience"] = []
    ctx = build_resume_context(p, {}, JOB)
    assert ctx["experience"] == []
    assert any(w.startswith("experience:") for w in ctx["warnings"])


def test_the_experience_on_the_cv_is_the_candidates_not_the_jobs():
    ctx = build_resume_context(profile(), {}, JOB)
    assert [(e["title"], e["company"]) for e in ctx["experience"]] == [("Product Lead", "Acme")]
    assert ctx["experience"][0]["bullets"][0].startswith("Owned the roadmap")
