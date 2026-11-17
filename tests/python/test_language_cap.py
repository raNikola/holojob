"""The language gap (scoringVersion 1.5): a confirmed required-language mismatch is a fact beside the score, not a cap.

Until 1.4 it capped matchScore at 25 (owner decision 2026-11-14); Step 2 moved it out of the score. The detection (the
engine's own gate) is unchanged, so these are the same cases as before, read from `languageGap`.
"""

import json
from pathlib import Path

import pytest

from scorer import score_job

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BODY = ("Own the product roadmap and discovery for our platform. You will work with the team on what customers "
        "need and we will ship it with you. " * 8)


@pytest.fixture
def intelligence():
    data = json.loads((FIXTURES / "candidate-intelligence.json").read_text("utf-8"))
    data["languages"] = ["Serbian (native)", "English (fluent)"]
    return data


def ad(extra, body=BODY, **fields):
    return {"jobId": "j1", "title": "Product Manager", "company": "Acme", "location": "Niš, Serbia", "workMode": "remote",
            "description": f"{body}\n{extra}", "jobUrl": "https://example.com/j", "llmFacts": {"roleTrack": "product_management"}, **fields}


def gap(result):
    return result["languageGap"]


def test_a_required_russian_clause_is_a_gap_that_names_the_language_and_lowers_nothing(intelligence):
    result = score_job(ad("Requirements:\n* Fluent Russian"), intelligence)
    assert gap(result) == ["Russian"]
    assert result["matchScore"] == result["scoreBeforeCaps"]  # no cap: the score is what the dimensions say
    assert not any(r.startswith("Capped:") and "requires" in r for r in result["reasons"])
    assert "Language: the ad requires Russian, which your profile does not list" in result["reasons"]


@pytest.mark.parametrize("extra", [
    "* Russian is a plus",
    "Nice to have\n* Fluent Russian",
    "* Fluent English or Russian",
    "* Fluent English and Serbian",
    "* Our blog is also published in Russian",
])
def test_optional_alternative_covered_or_mentioned_languages_are_no_gap(intelligence, extra):
    assert gap(score_job(ad(extra), intelligence)) == []


def test_a_language_the_profile_lists_or_a_close_relative_is_no_gap(intelligence):
    assert gap(score_job(ad("* Fluent Serbian and Croatian"), intelligence)) == []


def test_text_under_the_thresholds_is_no_gap(intelligence):
    assert gap(score_job(ad("* Fluent Russian", body="Product manager wanted."), intelligence)) == []
    assert gap(score_job(ad("* Fluent Russian", body=""), intelligence)) == []
    assert gap(score_job(ad("* Fluent Russian ...", body=BODY), intelligence)) == []
    german = "Wir suchen einen Produktmanager für unsere Plattform und das Team. " * 20
    assert gap(score_job(ad("* Fluent Russian", body=german), intelligence)) == []


def test_no_profile_languages_means_unknown_and_no_gap(intelligence):
    intelligence["languages"] = []
    assert gap(score_job(ad("* Fluent Russian"), intelligence)) == []


def test_a_gap_does_not_make_a_row_hard_capped(intelligence):
    assert score_job(ad("* Fluent Russian"), intelligence)["hardCapped"] is False


def test_the_extraction_must_have_language_is_a_gap_too(intelligence):
    facts = {"roleTrack": "product_management", "requirements": [
        {"kind": "language", "importance": "must", "text": "Fluent Russian", "postingQuote": "Fluent Russian"}]}
    assert gap(score_job(ad("", llmFacts=facts), intelligence)) == ["Russian"]
