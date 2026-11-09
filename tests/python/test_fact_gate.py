"""The fact gate (DECISIONS.md principle 8): which claim types are checked against the candidate's facts, and which are not.

Synthetic data only. `check_draft` judges what a model drafted; `check_document` judges finished text.
"""

import json

import pytest

from provenance_checker import (
    build_canonical_facts,
    check_document,
    check_draft,
    check_named_things,
)

COMPANY = "Acme Platforms"
JOB = {"title": "Lead Product Manager", "company": "Hiring Co", "location": "Remote"}
CV = """Jane Canary
Senior Product Manager, Acme Platforms | Remote
May 2020 – Present
• Led the billing platform migration and reached 40% faster releases across the group.
• Served 1,200 users with a team of 6 people.
Product Manager, Borealis Systems
SKILLS
Jira, Roadmapping, SQL
EDUCATION
B.A. Economics, University of Nis, 2012
CERTIFICATIONS
Certified Scrum Product Owner
"""


def facts(**basic):
    profile = {"basicProfile": {"experienceYears": "12", **basic},
               "resume": {"rawText": CV, "parsedData": {"skills": ["Jira", "SQL"], "certifications": ["Certified Scrum Product Owner"]}}}
    return build_canonical_facts(profile, {})


def draft(**parts):
    base = {
        "subtitle": "Lead Product Manager | Billing Platforms",
        "summary": "Product leader with a long record of shipping billing platforms at Acme Platforms.",
        "experience": [{"company": COMPANY, "bullets": ["Led the billing platform migration and reached 40% faster releases."]}],
        "projects": [],
        "cover_letter_paragraphs": ["Opening paragraph about the role."],
    }
    base.update(parts)
    return base


def issues(**parts):
    return check_draft(draft(**parts), facts(), job=JOB)


def test_a_draft_that_only_rewords_the_cv_passes():
    assert issues() == []


# --- covered claim types: each is rejected -------------------------------------------------------


@pytest.mark.parametrize("bullet", [
    "Managed a team of 47 engineers.",          # number with a noun
    "Grew revenue to $8 billion in one year.",  # amount
    "Reached 73% growth.",                      # metric with a unit
    "Shipped it in 2031.",                      # a year the CV does not state
])
def test_an_invented_number_is_rejected(bullet):
    found = issues(experience=[{"company": COMPANY, "bullets": [bullet]}])
    assert found and any("Unverified" in f for f in found)


def test_a_number_the_cv_states_passes():
    assert issues(experience=[{"company": COMPANY, "bullets": ["Served 1,200 users with a team of 6 people since 2020."]}]) == []


@pytest.mark.parametrize(("claim", "ok"), [
    ("Over 12 years of experience in product.", True),    # experienceYears is 12
    ("12+ years of product work.", True),
    ("Over 15 years of experience in product.", False),   # not stated anywhere
    ("A career of 6 years at the top.", False),           # 6 occurs in the CV, but as a team size, not as years
])
def test_years_of_experience_must_be_stated(claim, ok):
    found = issues(summary=claim + " " + "Shipping billing platforms at Acme Platforms and partner tools.")
    assert (found == []) is ok, found


@pytest.mark.parametrize("claim", [
    "Worked with the leadership of Google and Netflix.",   # employers
    "Built the platform on Kubernetes and Terraform.",     # technologies
    "Holds a degree from Stanford University.",            # school
    "Promoted to Chief Product Officer at Borealis Systems.",  # title
])
def test_an_invented_named_thing_is_rejected(claim):
    found = issues(experience=[{"company": COMPANY, "bullets": [claim]}])
    assert any("Unverified name or term" in f for f in found), found


def test_names_from_the_cv_and_the_job_pass():
    claim = "Partnered with Borealis Systems on the billing platform for Hiring Co in Remote teams."
    assert issues(cover_letter_paragraphs=[claim]) == []


def test_a_capitalised_word_that_opens_a_sentence_is_not_a_name():
    assert check_named_things("Delivered the roadmap. Owned the backlog.", {"roadmap", "backlog"}) == []


@pytest.mark.parametrize("claim", ["Holds a PhD in economics.", "Earned an MBA.", "Holds a master's degree."])
def test_an_invented_degree_or_certification_is_rejected(claim):
    found = issues(summary=claim + " Shipping billing platforms at Acme Platforms for many years.")
    assert any("degree or certification" in f for f in found), found


def test_a_certification_the_cv_lists_passes():
    assert issues(summary="Certified product owner shipping billing platforms at Acme Platforms and partner tools.") == []


def test_the_subtitle_is_checked_word_by_word():
    assert issues(subtitle="Strategic Visionary | Billing Platforms")
    assert issues(subtitle="Lead Product Manager | Billing Platforms") == []


def test_a_certification_name_is_checked_as_a_named_thing_not_as_a_credential_word():
    # The CV lists one certification, so the word "certified" is vouched for; the name AWS is not in the facts.
    found = issues(summary="Shipping billing platforms at Acme Platforms and now AWS certified for many years.")
    assert any("Unverified name or term: AWS" in f for f in found), found


def test_numbers_in_the_job_title_may_be_named():
    found = check_draft(draft(subtitle="Product Manager | Billing Platforms",
                              cover_letter_paragraphs=["I apply for the Product Manager 2 role."]), facts(),
                        job={**JOB, "title": "Product Manager 2"})
    assert found == []


# --- project intelligence is not a fact source for numbers -----------------------------------------


def test_a_project_metric_the_profile_does_not_state_is_rejected():
    project = {"projects": [{"name": "Atlas", "techStack": ["Python"], "quantifiables": ["cut cost by 31%"]}]}
    line = {"name": "Atlas", "line": "Atlas cut cost by 31%."}
    found = check_draft(draft(projects=[line]), facts(), job=JOB, extra=["Atlas", "Python"])
    assert any("31%" in f for f in found), (found, project)


def test_a_project_metric_the_profile_states_passes_and_the_project_name_may_be_used():
    line = {"name": "Atlas", "line": "Atlas brought releases 40% faster."}
    assert check_draft(draft(projects=[line]), facts(), job=JOB, extra=["Atlas"]) == []


def test_a_project_name_the_candidate_does_not_keep_is_a_name_to_verify():
    line = {"name": "Atlas", "line": "Delivered Atlas for customers."}
    assert check_draft(draft(projects=[line]), facts(), job=JOB, extra=[]) != []


# --- finished documents: numbers, years and degrees, not names -------------------------------------


def test_a_finished_document_with_only_cv_numbers_passes():
    text = "# Jane\nSenior Product Manager, Acme Platforms\nMay 2020 – Present\n- 40% faster releases\n12+ years"
    assert check_document(text, facts()) == []


def test_a_finished_document_with_an_invented_number_fails():
    assert check_document("- Managed 47 engineers", facts())


# --- not covered, stated so the limit stays visible ------------------------------------------------


def test_documented_limit_a_lowercase_invented_technology_is_not_caught():
    assert issues(summary="Built the whole stack on kubernetes and terraform at Acme Platforms for the billing platforms.") == []


def test_documented_limit_a_number_the_cv_states_elsewhere_is_not_caught():
    # 6 is a team size in the CV; "6 engineers" cannot be told from it.
    assert issues(experience=[{"company": COMPANY, "bullets": ["Managed 6 engineers."]}]) == []


def test_the_draft_checker_ignores_a_malformed_part_instead_of_raising():
    assert check_draft({"summary": 5, "experience": ["x", {"bullets": "no"}], "projects": [None]}, facts(), job=JOB) == []
    json.dumps(draft())
