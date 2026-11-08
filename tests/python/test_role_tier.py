"""Three title tiers for a role family, and the cap only the unrelated one gets."""

import pytest

from role_tier import NEAR, TARGET, UNRELATED, title_tier
from scorer import UNRELATED_TITLE_CAP, score_job

EVIDENCE = "Owns the product roadmap"


@pytest.mark.parametrize(
    "title",
    [
        "Senior Technical Program Manager (IDE Department)",
        "Technical Program Manager - New Data Center Launches",
        "Senior Manager, Technical Product Management, Compliance",
        "Vice President of Platform Product Management",
        "Platform Product Domain Lead",
        "Director of Product, Ecosystem",
        "Product Operations Manager",
        "VP Product",
    ],
)
def test_near_titles(title):
    assert title_tier(title, 45, "product") == NEAR


@pytest.mark.parametrize(
    "title",
    [
        "Senior Product Designer - Compute, Nebius Console",
        "Technical Product Marketing Manager (.NET Developer Tools)",
        "Senior Product Analyst",
        "Senior Software Engineer",
        "Senior Power Platform Product Specialist",
        "Director of Product Design",
        "HR Program Manager",
    ],
)
def test_unrelated_titles(title):
    assert title_tier(title, 45, "product") == UNRELATED


def test_a_product_role_in_other_words_is_near_unless_it_is_another_function():
    assert title_tier("Manager, Product Platform", 65, "product") == NEAR
    assert title_tier("Senior Product Design Manager", 65, "product") == UNRELATED


def test_a_target_title_is_target_whatever_it_mentions():
    assert title_tier("Senior Product Manager, Marketing", 95, "product") == TARGET


@pytest.mark.parametrize("title", ["Technical Project Manager (Hardware)", "Senior Delivery Manager"])
def test_a_project_title_is_unrelated_without_product_responsibility(title):
    assert title_tier(title, 45, "product") == UNRELATED
    assert title_tier(title, 45, "product", {"roleTrack": "project_delivery", "roleTrackEvidence": "Runs delivery"}) == UNRELATED
    assert title_tier(title, 45, "product", {"roleTrack": "program_management", "roleTrackEvidence": "Runs programs"}) == UNRELATED


def test_a_project_title_with_evidenced_product_responsibility_is_near():
    assert title_tier("Technical Project Manager", 45, "product", {"roleTrack": "product_management", "roleTrackEvidence": EVIDENCE}) == NEAR


def test_a_track_without_its_quote_is_no_evidence():
    assert title_tier("Technical Project Manager", 45, "product", {"roleTrack": "product_management", "roleTrackEvidence": " "}) == UNRELATED


@pytest.mark.parametrize("family", [None, "", "engineering"])
def test_no_vocabulary_says_nothing(family):
    assert title_tier("Senior Product Designer", 45, family) is None


def test_an_empty_title_says_nothing():
    assert title_tier("  ", 30, "product") is None


INTELLIGENCE = {
    "roleFamily": "product",
    "roleStrategy": {"primaryTargetRoles": ["Senior Product Manager"], "searchRoleVariants": ["Senior Product"]},
    "atsKeywordBank": {"highPriority": ["Senior Product Manager", "Roadmap"]},
}


def _job(title):
    return {"jobId": "t", "title": title, "company": "Acme", "description": "Senior product roadmap work", "location": "Remote", "isRemote": True}


def test_an_unrelated_title_is_capped_held_and_explained():
    result = score_job(_job("Senior Product Designer"), INTELLIGENCE)
    assert result["matchScore"] <= UNRELATED_TITLE_CAP
    assert result["hardCapped"] is True
    assert "Capped: the title matches no product target role" in result["reasons"]


def test_a_near_title_is_not_capped_by_its_title():
    result = score_job(_job("Senior Technical Program Manager"), INTELLIGENCE)
    assert not any("the title matches no" in reason for reason in result["reasons"])


def test_a_target_title_is_not_capped():
    result = score_job(_job("Senior Product Manager, Lab"), INTELLIGENCE)
    assert result["matchScore"] > UNRELATED_TITLE_CAP
    assert not any("the title matches no" in reason for reason in result["reasons"])


def test_without_a_family_no_title_is_capped():
    intelligence = {k: v for k, v in INTELLIGENCE.items() if k != "roleFamily"}
    result = score_job(_job("Senior Product Designer"), intelligence)
    assert not any("the title matches no" in reason for reason in result["reasons"])


def test_a_program_track_is_no_longer_off_track_for_product():
    job = {**_job("Senior Product Manager"), "llmFacts": {"roleTrack": "program_management", "roleTrackEvidence": "Runs programs"}}
    assert not any(r.startswith("Capped: the ad describes") for r in score_job(job, INTELLIGENCE)["reasons"])


def test_a_delivery_track_stays_off_track_for_product():
    job = {**_job("Senior Product Manager"), "llmFacts": {"roleTrack": "project_delivery", "roleTrackEvidence": "Runs delivery"}}
    assert any(r.startswith("Capped: the ad describes") for r in score_job(job, INTELLIGENCE)["reasons"])
