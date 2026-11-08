"""Wave 3: the keyword bank holds keywords, not CV prose (same rule as src/modules/intelligence/keywordShape.js)."""

import json
from pathlib import Path

import pytest

from dimensions.skill_match import bank_prose_count, score_skill_match
from keyword_shape import is_keyword_shaped

CASES = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "keyword-shape.json").read_text(encoding="utf-8"))
PROSE = "Led a team of twelve engineers and shipped the new billing platform across three markets in under a year"


@pytest.mark.parametrize("value", CASES["accept"])
def test_keywords_are_accepted(value):
    assert is_keyword_shaped(value)


@pytest.mark.parametrize("value", CASES["reject"])
def test_prose_is_rejected(value):
    assert not is_keyword_shaped(value)


def test_non_strings_are_not_keywords():
    assert not is_keyword_shaped(None) and not is_keyword_shaped(7) and not is_keyword_shaped(["a"])


JOB = {"title": "Product Manager", "description": "Roadmap ownership and stakeholder management for a payments product."}


def intelligence(medium):
    return {"atsKeywordBank": {"highPriority": ["Product Manager"], "mediumPriority": medium, "supportingKeywords": []}}


def test_prose_in_the_bank_is_ignored_and_reported_and_does_not_lower_the_score():
    clean, polluted = intelligence(["Stakeholder management"]), intelligence(["Stakeholder management", PROSE])
    assert bank_prose_count(clean) == 0 and bank_prose_count(polluted) == 1
    clean_result, polluted_result = score_skill_match(JOB, clean), score_skill_match(JOB, polluted)
    assert clean_result[0] == polluted_result[0], "a paragraph in the bank must not change the score"
    assert any("CV prose" in r for r in polluted_result[1]) and not any("CV prose" in r for r in clean_result[1])
    assert "1/1 high, 1/1 medium" in polluted_result[1][0], "the paragraph is not counted as an achievable keyword"
