"""The evidence index, its strength grading, profileVersion and the confirmed-facts store."""

import json
import re
from pathlib import Path

import pytest

import confirmed_facts
from evidence_index import (
    SOURCES,
    build_candidate,
    build_evidence,
    build_gates,
    grade,
    profile_version,
    to_month,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "data" / "examples"
MONTH = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def _profile(**parsed):
    return {"basicProfile": {"fullName": "Ana Example"}, "resume": {"parsedData": parsed}}


DETAIL = [{
    "title": "Product Manager",
    "company": "Acme",
    "start": "Mar 2021",
    "end": "Present",
    "bullets": [
        "Roadmap and discovery for the payments platform",
        "Shipped self-serve onboarding",
        "Led checkout redesign that lifted conversion 18%",
    ],
}]


# --- strength ---------------------------------------------------------------

@pytest.mark.parametrize(
    "text,source,expected",
    [
        ("Python", "fact", 1),
        ("Led a team of 12", "fact", 1),  # a listed entry is a claim, whatever it says
        ("Roadmap and discovery for the payments platform", "role", 2),
        ("Responsible for releases since 2019", "role", 2),
        ("Shipped self-serve onboarding", "role", 3),
        ("- Built the billing service in 2020", "role", 3),  # a year is not an outcome
        ("Led checkout redesign that lifted conversion 18%", "role", 4),
        ("Acme — Billing: Developed 20+ plugins", "project", 4),  # verb after a label
        ("Cost optimization", "example", 2),
        ("Reduced costs", "example", 3),
    ],
)
def test_grade(text, source, expected):
    assert grade(text, source) == expected


# --- dates ------------------------------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [("Apr 2024", "2024-04"), ("September 2019", "2019-09"), ("2024-4", "2024-04"),
     ("04/2024", "2024-04"), ("2014", None), ("Present", None), ("", None), (None, None), ("13/2024", None)],
)
def test_to_month(value, expected):
    assert to_month(value) == expected


# --- building ---------------------------------------------------------------

def test_experience_detail_gives_one_item_per_bullet():
    evidence = build_evidence(_profile(experienceDetail=DETAIL), {})
    assert [e["strength"] for e in evidence] == [2, 3, 4]
    assert {e["role"] for e in evidence} == {"Product Manager — Acme"}
    assert {(e["start"], e["end"]) for e in evidence} == {("2021-03", None)}
    assert {e["source"] for e in evidence} == {"role"}


def test_work_experience_lines_are_read_when_there_is_no_detail():
    line = "Scrum Master — Acme | Jun 2021–Jul 2023 | Led delivery across 2 teams. Backlog prioritization."
    evidence = build_evidence(_profile(workExperience=[line]), {})
    assert [(e["text"], e["strength"]) for e in evidence] == [
        ("Led delivery across 2 teams.", 4),
        ("Backlog prioritization.", 2),
    ]
    assert evidence[0]["role"] == "Scrum Master — Acme"
    assert (evidence[0]["start"], evidence[0]["end"]) == ("2021-06", "2023-07")


def test_detail_wins_over_work_experience():
    evidence = build_evidence(_profile(experienceDetail=DETAIL, workExperience=["X — Y | 2020 | Other text"]), {})
    assert all(e["role"] == "Product Manager — Acme" for e in evidence)


def test_listed_skills_groups_and_intelligence_examples():
    profile = _profile(
        competencyGroups=[{"label": "Product", "items": ["Discovery", "Roadmapping"]}],
        toolGroups=[{"label": "Tools", "items": ["Jira", "Figma"]}],
        skills=["Figma", "SQL"],
        projects=["Acme — Billing: Built invoicing for 3,000 customers"],
    )
    intelligence = {"experienceMap": {
        "projectHighlights": ["Legacy modernization"],
        "ownershipExamples": ["Budget ownership"],
        "leadershipExamples": ["Led a team"],
        "businessImpactExamples": ["Reduced churn by 12%"],
    }}
    evidence = build_evidence(profile, intelligence)
    by_text = {e["text"]: e for e in evidence}
    # Figma is in a tool group and in skills: one item.
    assert [e["text"] for e in evidence if e["source"] == "fact"] == ["Discovery", "Roadmapping", "Jira", "Figma", "SQL"]
    assert all(e["strength"] == 1 for e in evidence if e["source"] == "fact")
    assert by_text["Acme — Billing: Built invoicing for 3,000 customers"]["role"] == "Acme — Billing"
    assert by_text["Acme — Billing: Built invoicing for 3,000 customers"]["strength"] == 4
    assert by_text["Legacy modernization"]["source"] == "project"
    assert (by_text["Budget ownership"]["source"], by_text["Budget ownership"]["strength"]) == ("example", 2)
    assert by_text["Led a team"]["strength"] == 3
    assert by_text["Reduced churn by 12%"]["strength"] == 4


def test_an_empty_profile_is_an_empty_index():
    assert build_evidence({}, {}) == []
    assert build_evidence(None, None) == []


def test_items_match_the_contract_shape():
    with open(EXAMPLES / "candidate-profile.example.json") as f:
        profile = json.load(f)
    with open(EXAMPLES / "candidate-intelligence.example.json") as f:
        intelligence = json.load(f)
    evidence = build_evidence(profile, intelligence) + build_evidence(_profile(experienceDetail=DETAIL), {})
    assert evidence
    for item in evidence:
        assert set(item) == {"id", "text", "source", "role", "start", "end", "strength"}
        assert item["source"] in SOURCES
        assert item["text"]
        assert item["role"] is None or isinstance(item["role"], str)
        assert all(d is None or MONTH.match(d) for d in (item["start"], item["end"]))
        assert 1 <= item["strength"] <= 4
    ids = [e["id"] for e in build_evidence(profile, intelligence)]
    assert len(ids) == len(set(ids))


def test_ids_are_stable_for_the_same_profile():
    profile = _profile(experienceDetail=DETAIL, skills=["SQL"])
    assert build_evidence(profile, {}) == build_evidence(json.loads(json.dumps(profile)), {})


def test_personal_identifiers_are_redacted():
    profile = _profile(
        experienceDetail=[{"title": "PM", "company": "Acme", "bullets": [
            "Ana Example ran the launch; reach me at ana@example.com or +381 64 123 4567, github.com/ana",
        ]}],
        links=["https://ana.example.dev"],
        skills=["See ana.example.dev"],
    )
    text = " ".join(e["text"] for e in build_evidence(profile, {}))
    for leak in ("Ana Example", "ana@example.com", "123 4567", "github.com/ana", "ana.example.dev"):
        assert leak not in text


# --- profileVersion -----------------------------------------------------------

def _candidate(**overrides):
    profile = overrides.pop("profile", _profile(experienceDetail=DETAIL, skills=["SQL"]))
    intelligence = overrides.pop("intelligence", {
        "languages": ["English (fluent)"],
        "jobFitPreferences": {"allowedLocations": ["REMOTE"], "minSalaryEur": 3000,
                              "workAuthorization": {"holds": [], "openToSponsorship": True}},
    })
    return build_candidate(profile, intelligence, overrides.pop("facts", []))


def test_profile_version_is_deterministic():
    assert _candidate()["profileVersion"] == _candidate()["profileVersion"]


@pytest.mark.parametrize(
    "change",
    [
        {"profile": _profile(experienceDetail=DETAIL, skills=["SQL", "Python"])},  # evidence
        {"facts": [{"competencyId": "sql", "has": True, "note": ""}]},  # confirmed fact
        {"intelligence": {"languages": ["English (fluent)", "German (B1)"], "jobFitPreferences": {
            "allowedLocations": ["REMOTE"], "minSalaryEur": 3000,
            "workAuthorization": {"holds": [], "openToSponsorship": True}}}},  # gate
        {"intelligence": {"languages": ["English (fluent)"], "jobFitPreferences": {
            "allowedLocations": ["REMOTE"], "minSalaryEur": 3500,
            "workAuthorization": {"holds": [], "openToSponsorship": True}}}},  # salary floor
        {"intelligence": {"languages": ["English (fluent)"], "jobFitPreferences": {
            "allowedLocations": ["REMOTE"], "minSalaryEur": 3000, "relocation": "abroad",
            "workAuthorization": {"holds": [], "openToSponsorship": True}}}},  # commute preference
    ],
)
def test_any_change_under_candidate_changes_the_version(change):
    assert _candidate(**change)["profileVersion"] != _candidate()["profileVersion"]


def test_role_family_is_part_of_the_version():
    args = ([], [], build_gates({}))
    assert profile_version(*args, "product") != profile_version(*args, "engineering")


def test_gates_take_nothing_by_default():
    assert build_gates({}) == {
        "workAuthorization": {}, "allowedLocations": [], "languages": [], "minSalaryEur": None,
        "preferredLocations": [], "remotePreference": None, "relocation": None, "country": None,
    }


# --- confirmed facts store ------------------------------------------------------

def test_a_missing_store_is_empty(tmp_path):
    assert confirmed_facts.load(tmp_path / "confirmed-facts.json") == []


def test_store_round_trip_and_validation(tmp_path):
    path = tmp_path / "confirmed-facts.json"
    confirmed_facts.save([
        {"competencyId": "sql", "has": True, "note": "daily, 5 years"},
        {"competencyId": "prov:37a02fa46828", "has": False},
        {"competencyId": "", "has": True},  # no id: dropped
        {"competencyId": "go", "has": "yes"},  # not a boolean: dropped
    ], path)
    assert json.loads(path.read_text())["version"] == confirmed_facts.STORE_VERSION
    assert confirmed_facts.load(path) == [
        {"competencyId": "prov:37a02fa46828", "has": False, "note": ""},
        {"competencyId": "sql", "has": True, "note": "daily, 5 years"},
    ]


def test_the_last_answer_for_a_competency_wins(tmp_path):
    path = tmp_path / "confirmed-facts.json"
    path.write_text(json.dumps({"version": 1, "facts": [
        {"competencyId": "sql", "has": True, "note": ""},
        {"competencyId": "sql", "has": False, "note": "never used it"},
    ]}))
    assert confirmed_facts.load(path) == [{"competencyId": "sql", "has": False, "note": "never used it"}]


def test_the_store_lives_with_the_git_ignored_profile():
    assert confirmed_facts.CONFIRMED_FACTS_PATH == ROOT / "data" / "profile" / "confirmed-facts.json"
