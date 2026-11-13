"""The language cap: a confirmed required-language mismatch caps matchScore at 25 (owner decision 2026-11-14)."""

import copy
import json
from pathlib import Path

import pytest

from scorer import LANGUAGE_CAP, score_job

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


def capped(result):
    return [r for r in result["reasons"] if r.startswith("Capped:") and "the ad requires" in r]


def test_a_required_russian_clause_caps_at_25_and_names_the_language(intelligence):
    result = score_job(ad("Requirements:\n* Fluent Russian"), intelligence)
    assert LANGUAGE_CAP == 25 and result["matchScore"] <= 25 and result["hardCapped"] is True
    assert capped(result) == ["Capped: the ad requires Russian, which your profile does not list"]


@pytest.mark.parametrize("extra", [
    "* Russian is a plus",
    "Nice to have\n* Fluent Russian",
    "* Fluent English or Russian",
    "* Fluent English and Serbian",
    "* Our blog is also published in Russian",
])
def test_optional_alternative_covered_or_mentioned_languages_do_not_cap(intelligence, extra):
    assert not capped(score_job(ad(extra), intelligence))


def test_a_language_the_profile_lists_or_a_close_relative_does_not_cap(intelligence):
    assert not capped(score_job(ad("* Fluent Serbian and Croatian"), intelligence))


def test_text_under_the_thresholds_does_not_cap(intelligence):
    short = score_job(ad("* Fluent Russian", body="Product manager wanted."), intelligence)
    assert not capped(short)
    assert not capped(score_job(ad("* Fluent Russian", body=""), intelligence))
    teaser = score_job(ad("* Fluent Russian ...", body=BODY), intelligence)
    assert not capped(teaser)
    german = "Wir suchen einen Produktmanager für unsere Plattform und das Team. " * 20
    assert not capped(score_job(ad("* Fluent Russian", body=german), intelligence))


def test_no_profile_languages_means_unknown_and_no_cap(intelligence):
    intelligence["languages"] = []
    assert not capped(score_job(ad("* Fluent Russian"), intelligence))


def test_a_capped_row_keeps_its_other_caps_and_reasons(intelligence):
    intel = copy.deepcopy(intelligence)
    intel["jobFitPreferences"] = {**intel["jobFitPreferences"], "allowedLocations": ["EUROPE"]}
    job = ad("* Fluent Russian", location="Austin, United States", workMode="onsite")
    job["llmFacts"] = {"roleTrack": "product_management", "visaSponsorship": "offered"}
    result = score_job(job, intel)
    others = [r for r in result["reasons"] if r.startswith("Capped:") and "the ad requires" not in r]
    assert result["workAuthorization"]["status"] == "outside_allowed" and others  # cap 40 keeps its reason
    assert result["matchScore"] == 25 and len(capped(result)) == 1  # the minimum wins


def test_the_extraction_must_have_language_caps_too(intelligence):
    facts = {"roleTrack": "product_management", "requirements": [
        {"kind": "language", "importance": "must", "text": "Fluent Russian", "postingQuote": "Fluent Russian"}]}
    result = score_job(ad("", llmFacts=facts), intelligence)
    assert capped(result) == ["Capped: the ad requires Russian, which your profile does not list"]
