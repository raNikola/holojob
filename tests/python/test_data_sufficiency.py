"""Read status (scoringVersion 1.5): Not read has no Fit Score; Insufficient evidence is a status beside the score.

Replaces the 1.4 "insufficient data" rule (character and term thresholds, score capped at 5).
"""
import json
from pathlib import Path

import pytest

import data_sufficiency
from scorer import score_job

INTEL = json.loads((Path(__file__).resolve().parents[2] / "data/examples/candidate-intelligence.example.json").read_text(encoding="utf-8"))

FULL = ("Own the product roadmap and discovery for a payments platform. You will work with engineering, design and "
        "stakeholders, define strategy, analyse usage data and deliver measurable outcomes. Requirements: five years of "
        "product experience, strong communication skills.")
REQ = {"requirements": [{"text": "5 years of product management", "importance": "must", "kind": "experience"}]}


def job(title="Senior Product Manager", description=FULL, **extra):
    return {"jobId": "j", "title": title, "company": "Acme", "location": "Remote", "isRemote": True,
            "jobUrl": "https://example.com/j", "description": description, **extra}


@pytest.mark.parametrize("description", ["", "   \n ", None, "<br/><p></p>", "!!! --- ???"])
def test_an_empty_or_unreadable_description_is_not_read_and_has_no_score(description):
    for title in ("Senior Product Manager", "Plumber"):
        result = score_job(job(title, description, llmFacts=REQ), INTEL)
        assert result["readStatus"] == "not_read" and result["dataStatus"] == "not_read"
        assert result["matchScore"] is None and result["scoreBeforeCaps"] is None
        assert result["matchLabel"] == "Not read" and result["priority"] == "Unrated" and result["applyRecommendation"] == "Not assessed"
        assert result["insufficientReasons"] and result["hardCapped"] is True
        assert result["reasons"][0].startswith("Not read: ")
        assert result["confidence"]["level"] == "none"


def test_there_is_no_character_threshold():
    """A readable ad of any length is read; whether it is rated depends on what was extracted, not on its size."""
    for text in ("asdf qwerty", "Great job! Apply now.", "x" * 200, "Own the roadmap. " * 30):
        result = score_job(job(description=text), INTEL)
        assert result["readStatus"] == "insufficient_evidence" and result["dataStatus"] == "sufficient"
        assert isinstance(result["matchScore"], int)


def test_a_readable_ad_with_extracted_requirements_is_read():
    result = score_job(job(description="Product manager wanted.", llmFacts=REQ), INTEL)
    assert result["readStatus"] == "read" and result["insufficientReasons"] == []


def test_insufficient_evidence_does_not_change_the_score():
    """The same ad with and without the extracted requirement differs only in status and confidence, not in the number."""
    without = score_job(job(), INTEL)
    assert without["readStatus"] == "insufficient_evidence"
    withreq = score_job(job(llmFacts=REQ), INTEL)
    assert withreq["readStatus"] == "read"
    assert without["matchScore"] > 5  # the old cap of 5 is gone
    assert any("Requirements not extracted" in r for r in without["confidence"]["reasons"])


def test_a_full_ad_scores_and_keeps_its_label():
    result = score_job(job(), INTEL)
    assert result["dataStatus"] == "sufficient" and result["matchScore"] > 40
    assert result["matchLabel"] in ("Excellent", "Strong", "Good", "Weak", "Reject")


def test_caps_still_run_first():
    result = score_job(job("Senior Product Designer", FULL), INTEL)
    assert result["dataStatus"] == "sufficient"  # the caps still apply to a read ad; the read status is not one of them


def test_low_confidence_reasons_do_not_change_the_score():
    result = score_job(job(location=""), INTEL)
    assert result["confidence"]["level"] == "low"
    with_facts = score_job(job(location="", llmFacts={"requirements": [{"text": "x", "importance": "must", "kind": "skill"}]}), INTEL)
    assert not any("Requirements not extracted" in r for r in with_facts["confidence"]["reasons"])


def test_facts_of_an_unknown_shape_are_no_facts():
    bad = {"visaSponsorship": "maybe", "requirements": "all of them"}
    result = score_job(job(llmFacts=bad), INTEL)
    assert "llmFacts" not in result and result["readStatus"] == "insufficient_evidence"
    assert score_job(job(llmFacts="text"), INTEL)["readStatus"] == "insufficient_evidence"


def test_the_enhancer_skips_not_read_rows():
    from llm_enhancer import LlmFitEnhancer
    enhancer = LlmFitEnhancer.__new__(LlmFitEnhancer)
    enhancer.threshold = 0
    counted = []
    enhancer._count = counted.append
    base = {"matchScore": None, "dataStatus": "not_read"}
    assert enhancer.enhance({}, base, {}) is base and counted == ["skipped"]


@pytest.mark.parametrize("status", ["teaser", "failed", "source_truncated"])
def test_cut_off_description_is_low_confidence_and_the_score_is_unchanged(status):
    plain = score_job(job(), INTEL)
    cut = score_job(job(descriptionStatus=status), INTEL)
    assert cut["dataStatus"] == "sufficient" and cut["matchScore"] == plain["matchScore"]
    assert cut["confidence"]["level"] == "low" and data_sufficiency.INCOMPLETE_REASON in cut["confidence"]["reasons"]
    assert data_sufficiency.INCOMPLETE_REASON not in plain["confidence"]["reasons"]
