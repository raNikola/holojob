"""CV analysis: what is removed before sending, and what survives the guard."""

import json

from analysis import build_prompt, fingerprint, verify
from redact import redact_cv_text

CV = (
    "Jane Doe Senior Product Manager Lisbon, Portugal +351 912 345 678 jane.doe@example.com "
    "linkedin.com/in/janedoe https://janedoe.dev PROFESSIONAL SUMMARY Product leader with 9 years "
    "of experience in B2B SaaS. PROFESSIONAL EXPERIENCE Senior Product Manager — Acme Corp | Mar 2021–Present "
    "• Launched a billing platform used by 40 customers. • Led a team of 12 engineers. "
    "Project Manager — Globex | 2016–2021 • Delivered 30 projects on schedule. "
    "CORE COMPETENCIES Product Leadership Roadmapping, Prioritization, Discovery. "
    "People Leadership Hiring, Coaching. TOOLS Product & Delivery : Jira, Monday.com, Figma "
    "AI Tooling: ChatGPT, Cursor EDUCATION & CERTIFICATIONS University of Porto B. Sc. Informatics | 2012 "
    "Professional Scrum Master I Scrum.org | 2020"
)

RAW = {
    "summary": "Product leader with 9 years of experience in B2B SaaS.",
    "draft_career_summary": "I am a product leader with 9 years of experience in B2B SaaS who launched a billing platform at Acme Corp.",
    "skills": ["Roadmapping", "Jira", "Kubernetes", "Jira"],
    "key_projects": [
        {"name": "Acme Corp — billing platform", "summary": "Launched a billing platform used by 40 customers."},
        {"name": "Acme Corp — billing platform", "summary": "Launched a billing platform used by 40 customers."},
        {"name": "Moon base", "summary": "Built a moon base."},
    ],
    "experience": [
        {"title": "Senior Product Manager", "company": "Acme Corp", "start": "Mar 2021", "end": "Present",
         "bullets": ["Launched a billing platform used by 40 customers.", "Won a Nobel prize."]},
        {"title": "Astronaut", "company": "NASA", "start": None, "end": None, "bullets": []},
    ],
    "competency_groups": [
        {"label": "Product Leadership", "items": ["Roadmapping", "Prioritization", "Telepathy"]},
        {"label": "Invented Group", "items": ["Roadmapping"]},
    ],
    "tool_groups": [
        {"label": "Product & Delivery", "items": ["Jira", "Monday.com", "Figma"]},
        {"label": "AI Tooling", "items": ["ChatGPT", "Cursor"]},
    ],
    "education": [
        {"degree": "B. Sc. Informatics", "school": "University of Porto", "year": "2012"},
        {"degree": "PhD Physics", "school": "MIT", "year": "2030"},
    ],
    "certifications": [{"name": "Professional Scrum Master I", "issuer": "Scrum.org", "year": "2020"}],
}


def test_redaction_removes_identity_and_keeps_tool_names():
    text, removed = redact_cv_text(CV, "Jane Doe", ["https://janedoe.dev"])
    for gone in ("Jane", "Doe", "jane.doe@example.com", "+351 912 345 678", "linkedin.com/in/janedoe", "janedoe.dev"):
        assert gone not in text
    assert "Monday.com" in text and "Scrum.org" in text
    assert "Mar 2021–Present" in text and "2016–2021" in text
    assert removed == {"names": 2, "emails": 1, "phones": 1, "links": 2}


def test_redaction_matches_a_name_without_its_accents():
    text, _ = redact_cv_text("Nikola Ranđelović is a PM. RANDJELOVIC again.", "Nikola Randjelovic")
    assert "Ran" not in text.replace("[NAME]", "") and text.count("[NAME]") == 3


def test_a_date_range_is_not_a_phone_number():
    text, removed = redact_cv_text("Worked 2019 - 2024 and 2016–2021.")
    assert removed["phones"] == 0 and "2019 - 2024" in text


def test_guard_keeps_what_the_cv_says_and_drops_the_rest():
    facts, rejected = verify(RAW, CV)
    assert facts["skills"] == ["Roadmapping", "Jira"]
    assert [p["name"] for p in facts["keyProjects"]] == ["Acme Corp — billing platform"]
    assert [r["title"] for r in facts["experience"]] == ["Senior Product Manager"]
    assert facts["experience"][0]["bullets"] == ["Launched a billing platform used by 40 customers."]
    assert facts["competencyGroups"] == [{"label": "Product Leadership", "items": ["Roadmapping", "Prioritization"]}]
    assert facts["toolGroups"][0] == {"label": "Product & Delivery", "items": ["Jira", "Monday.com", "Figma"]}
    assert facts["education"] == [{"degree": "B. Sc. Informatics", "school": "University of Porto", "year": "2012"}]
    assert facts["certifications"][0]["issuer"] == "Scrum.org"
    dropped = {r["value"] for r in rejected}
    assert {"Kubernetes", "Won a Nobel prize.", "Telepathy", "Invented Group", "Astronaut — NASA"} <= dropped
    assert "PhD Physics — MIT" in dropped


def test_draft_summary_is_kept_only_when_its_numbers_and_names_are_in_the_cv():
    assert verify(RAW, CV)[0]["draftCareerSummary"].startswith("I am a product leader")
    invented = dict(RAW, draft_career_summary="I run Initech and doubled revenue by 300%.")
    facts, rejected = verify(invented, CV)
    assert facts["draftCareerSummary"] == ""
    assert any(r["field"] == "draftCareerSummary" and "Initech" in r["reason"] for r in rejected)


def test_guard_accepts_accent_and_case_differences():
    facts, _ = verify({"skills": ["ROADMAPPING"]}, "Rođmapping and Roadmapping")
    assert facts["skills"] == ["ROADMAPPING"]


def test_guard_survives_a_malformed_reply():
    facts, _ = verify({"experience": [None, "x"], "skills": [3, None], "education": "nope"}, CV)
    assert facts["skills"] == [] and facts["experience"] == []


def test_fingerprint_changes_with_text_provider_and_model():
    base = fingerprint("cv", "openai", "m1")
    assert base == fingerprint("cv", "openai", "m1")
    assert len({base, fingerprint("cv2", "openai", "m1"), fingerprint("cv", "deepseek", "m1"), fingerprint("cv", "openai", "m2")}) == 4


def test_prompt_carries_only_the_redacted_text():
    text, _ = redact_cv_text(CV, "Jane Doe", ["https://janedoe.dev"])
    prompt = build_prompt(text)
    assert "[NAME]" in prompt and "jane.doe@example.com" not in prompt and json.dumps(prompt)


def test_a_figure_with_a_plus_matches_the_cv_either_way():
    facts, _ = verify({"draft_career_summary": "I ran 250 sites and 10+ projects."}, "Ran 250+ websites on 10 projects")
    assert facts["draftCareerSummary"]
    assert verify({"skills": ["C++", "C#"]}, "Wrote C++ and C# code")[0]["skills"] == ["C++", "C#"]
