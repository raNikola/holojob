"""Insufficient data: an ad that states too little gets a state, not a Fit Score (Wave 2 a1)."""
import json
from pathlib import Path

import pytest

import data_sufficiency
from scorer import score_job, score_jobs

INTEL = json.loads((Path(__file__).resolve().parents[2] / "data/examples/candidate-intelligence.example.json").read_text(encoding="utf-8"))

FULL = ("Own the product roadmap and discovery for a payments platform. You will work with engineering, design and "
        "stakeholders, define strategy, analyse usage data and deliver measurable outcomes. Requirements: five years of "
        "product experience, strong communication skills.")


def job(title="Senior Product Manager", description=FULL, **extra):
    return {"jobId": "j", "title": title, "company": "Acme", "location": "Remote", "isRemote": True,
            "jobUrl": "https://example.com/j", "description": description, **extra}


@pytest.mark.parametrize("text", ["asdf qwerty", "test test test test test test test test test test test test test test", "Great job! Apply now.", "x" * 200])
def test_junk_is_insufficient_whatever_the_title(text):
    for title in ("Senior Product Manager", "Plumber"):
        result = score_job(job(title, text), INTEL)
        assert result["dataStatus"] == "insufficient"
        assert result["matchScore"] <= data_sufficiency.SCORE_CEILING
        assert result["matchLabel"] == "Insufficient data"
        assert result["priority"] == "Unrated" and result["applyRecommendation"] == "Not assessed"
        assert result["insufficientReasons"] and result["hardCapped"] is True
        assert result["reasons"][0].startswith("Insufficient data: ")


def test_a_full_ad_is_sufficient_and_scores_as_before():
    result = score_job(job(), INTEL)
    assert result["dataStatus"] == "sufficient" and result["insufficientReasons"] == []
    assert result["matchScore"] > 40
    assert result["matchLabel"] in ("Excellent", "Strong", "Good", "Weak", "Reject")


def test_a_short_but_informative_ad_is_not_rejected():
    short = "Lead product discovery and own the roadmap; you will define strategy with stakeholders. Five years experience required."
    assert len(short) < 130
    assert score_job(job(description=short), INTEL)["dataStatus"] == "sufficient"


def test_extracted_requirements_make_a_short_ad_sufficient():
    facts = {"requirements": [{"text": "5 years of product management", "importance": "must", "kind": "experience"}]}
    assert score_job(job(description="Product manager wanted.", llmFacts=facts), INTEL)["dataStatus"] == "sufficient"
    assert score_job(job(description="Product manager wanted."), INTEL)["dataStatus"] == "insufficient"


def test_a_padded_ad_is_still_thin():
    assert score_job(job(description="Own the roadmap. " * 30), INTEL)["dataStatus"] == "insufficient"


def test_caps_still_run_first():
    result = score_job(job("Senior Product Designer", FULL), INTEL)
    assert result["dataStatus"] == "sufficient"  # the unrelated-title cap (40) is unchanged by this state


def test_low_confidence_reasons_do_not_change_the_score():
    result = score_job(job(location=""), INTEL)
    assert result["confidence"]["level"] == "low"
    assert any("Requirements not extracted" in r for r in result["confidence"]["reasons"])
    with_facts = score_job(job(location="", llmFacts={"requirements": [{"text": "x", "importance": "must", "kind": "skill"}]}), INTEL)
    assert not any("Requirements not extracted" in r for r in with_facts["confidence"]["reasons"])


def test_insufficient_has_no_confidence_level():
    assert score_job(job(description="hi"), INTEL)["confidence"]["level"] == "none"


def test_the_enhancer_skips_insufficient(monkeypatch):
    from llm_enhancer import LlmFitEnhancer
    enhancer = LlmFitEnhancer.__new__(LlmFitEnhancer)
    enhancer.threshold = 0
    counted = []
    enhancer._count = counted.append
    base = {"matchScore": 5, "dataStatus": "insufficient"}
    assert enhancer.enhance({}, base, {}) is base and counted == ["skipped"]
