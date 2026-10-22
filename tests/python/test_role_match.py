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
