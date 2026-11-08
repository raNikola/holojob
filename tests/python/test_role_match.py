"""Titles are matched as contiguous substrings, never as token subsets."""

import json
from pathlib import Path

import pytest

from dimensions.role_match import score_role_match

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def intelligence():
    return json.loads((FIXTURES / "candidate-intelligence.json").read_text("utf-8"))


def _score(title, intelligence):
    return score_role_match({"title": title}, intelligence)


def test_product_compliance_manager_is_not_a_product_manager(intelligence):
    score, reasons = _score("Product Compliance Manager", intelligence)
    assert score < 80
    assert not any("Primary role match" in r or "Related role match" in r for r in reasons)


def test_technical_production_manager_is_not_a_technical_product_manager(intelligence):
    score, reasons = _score("Technical Production Manager", intelligence)
    assert score < 80
    assert not any("Primary role match" in r or "Related role match" in r for r in reasons)


@pytest.mark.parametrize(
    "title", ["Senior Technical Product Manager", "Product Manager", "Group Product Manager (Remote)"]
)
def test_real_product_manager_titles_are_primary_matches(title, intelligence):
    assert _score(title, intelligence)[0] == 95


def test_product_owner_is_a_related_match(intelligence):
    assert _score("Principal Product Owner", intelligence)[0] == 80


def test_avoided_role_scores_lowest(intelligence):
    assert _score("Project Manager", intelligence)[0] == 15


def test_shared_generic_word_is_not_enough(intelligence):
    assert _score("Team Lead, Warehouse", intelligence)[0] < 65


FRAGMENTS = {
    "roleFamily": "product",
    "roleStrategy": {
        "primaryTargetRoles": ["Senior Product Manager", "Technical Product Manager", "Head of Product"],
        "secondaryTargetRoles": ["Product Owner"],
        "stretchRoles": ["Director of Product"],
        "searchRoleVariants": ["Senior Product", "Technical Product", "AI Product Manager", "Scrum Lead"],
    },
}


@pytest.mark.parametrize("title", ["Senior Product Designer - Compute, Nebius Console", "Technical Product Writer"])
def test_a_leading_fragment_of_a_target_matches_no_title(title):
    assert _score(title, FRAGMENTS)[0] == 45


def test_a_variant_that_names_a_role_still_matches():
    assert _score("AI Product Manager", FRAGMENTS)[0] == 80
    assert _score("Scrum Lead, Payments", FRAGMENTS)[0] == 80


def test_the_target_itself_is_not_its_own_fragment():
    assert _score("Senior Product Manager, Lab", FRAGMENTS)[0] == 95


def test_product_management_counts_as_a_product_role():
    assert _score("Principal, Product Management", FRAGMENTS)[0] == 65


def test_a_stretch_role_is_read():
    score, reasons = _score("Director of Product, Ecosystem", FRAGMENTS)
    assert score == 65
    assert reasons == ["Stretch role match: director of product"]


@pytest.mark.parametrize("title", ["Head of Product Marketing (Core)", "Head of Product Design"])
def test_a_target_phrase_inside_another_function_is_not_a_target(title):
    assert _score(title, FRAGMENTS)[0] == 65


def test_head_of_product_is_still_the_target():
    assert _score("Head of Product, Payments", FRAGMENTS)[0] == 95


def test_without_a_family_no_phrase_is_set_aside():
    no_family = {k: v for k, v in FRAGMENTS.items() if k != "roleFamily"}
    assert _score("Head of Product Marketing", no_family)[0] == 95


def test_a_near_title_scores_like_a_product_role_in_other_words():
    score, reasons = _score("Senior Technical Program Manager", FRAGMENTS)
    assert score == 65
    assert reasons == ["Near-target role, wording outside target list"]


def test_a_project_title_stays_at_the_bottom_without_product_responsibility():
    assert _score("Technical Project Manager", FRAGMENTS)[0] == 45


def test_a_project_title_with_evidenced_product_responsibility_is_near():
    job = {"title": "Technical Project Manager", "llmFacts": {"roleTrack": "product_management", "roleTrackEvidence": "Owns the roadmap"}}
    assert score_role_match(job, FRAGMENTS)[0] == 65


def test_near_titles_need_a_family():
    no_family = {k: v for k, v in FRAGMENTS.items() if k != "roleFamily"}
    assert _score("Senior Technical Program Manager", no_family)[0] == 45
