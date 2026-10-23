"""The ATS boards must not drop a job in a place the candidate is searching.

The search locations name Europe or the United States only when the profile
says the candidate would relocate there. Such a job has to reach scoring, where
the visa cap flags it, instead of being dropped at discovery for being outside
the run's home country.
"""

import json
from pathlib import Path

import pytest

from providers.ashby_provider import AshbyProvider
from providers.base_provider import filter_jobs, in_searched_place
from providers.greenhouse_provider import GreenhouseProvider
from providers.lever_provider import LeverProvider
from scorer import score_job

FIXTURES = Path(__file__).resolve().parent / "fixtures"

HOME = ["Niš, Serbia", "Serbia"]
RELOCATING = HOME + ["Europe", "United States"]
TERMS = ["Product Manager"]
REMOTE = ["remote", "hybrid", "flexible"]
AD = "Own the product roadmap and discovery for our platform. " * 8

ONSITE_BERLIN = "Berlin, Germany"
ONSITE_AUSTIN = "Austin, United States"
ONSITE_MUMBAI = "Mumbai, India"


def ad(location, **extra):
    return {"title": "Product Manager", "description": AD, "location": location, "isRemote": False, **extra}


def kept(locations, *places):
    return [j["location"] for j in filter_jobs([ad(p) for p in places], TERMS, locations, REMOTE, "Serbia")]


def test_onsite_jobs_in_searched_regions_pass_when_the_candidate_would_relocate():
    assert kept(RELOCATING, ONSITE_BERLIN, ONSITE_AUSTIN) == [ONSITE_BERLIN, ONSITE_AUSTIN]


def test_nothing_changes_for_a_candidate_who_would_not_relocate():
    assert kept(HOME, ONSITE_BERLIN, ONSITE_AUSTIN, "Belgrade, Serbia") == ["Belgrade, Serbia"]


def test_a_place_outside_every_searched_place_is_still_dropped():
    assert kept(RELOCATING, ONSITE_MUMBAI) == []


def test_a_region_covers_its_countries_and_a_country_only_itself():
    assert in_searched_place(ad("Warsaw, Poland"), ["Europe"])
    assert not in_searched_place(ad("Warsaw, Poland"), ["United States"])
    assert not in_searched_place(ad("Berlin, Germany"), ["Remote"])
    assert not in_searched_place(ad("Berlin, Germany"), ["Atlantis"])


# --- through the real providers into scoring ---------------------------------------------------


def _greenhouse(location):
    p = GreenhouseProvider()
    p._load_boards = lambda: [{"company": "Acme", "board": "acme"}]
    p._fetch_board = lambda board: [
        {"id": 1, "title": "Product Manager", "content": AD, "absolute_url": "https://x/1", "location": {"name": location}}
    ]
    return p


def _lever(location):
    p = LeverProvider()
    p._load_companies = lambda: ["acme"]
    p._fetch_company = lambda company: [
        {"text": "Product Manager", "descriptionPlain": AD, "hostedUrl": "https://x/2",
         "categories": {"location": location}}
    ]
    return p


def _ashby(location):
    p = AshbyProvider()
    p._load_companies = lambda: ["acme"]
    p._fetch_company = lambda slug: [
        {"title": "Product Manager", "descriptionPlain": AD, "jobUrl": "https://x/3", "location": location}
    ]
    return p


@pytest.fixture
def serbian_intelligence():
    data = json.loads((FIXTURES / "candidate-intelligence.json").read_text("utf-8"))
    data["jobFitPreferences"] = {
        **data["jobFitPreferences"],
        "country": "Serbia",
        "relocation": "abroad",
        "allowedLocations": [],
        "workAuthorization": {"holds": [{"jurisdiction": "RS", "basis": "citizen"}], "openToSponsorship": True},
    }
    return data


@pytest.mark.parametrize("make", [_greenhouse, _lever, _ashby], ids=["greenhouse", "lever", "ashby"])
@pytest.mark.parametrize("location", [ONSITE_BERLIN, ONSITE_AUSTIN])
def test_an_onsite_job_abroad_reaches_scoring_and_is_capped_there(make, location, serbian_intelligence):
    relocating = make(location).fetch_jobs(TERMS, RELOCATING, REMOTE, "Serbia")
    assert len(relocating) == 1, "dropped at discovery instead of reaching scoring"

    job = {**relocating[0], "workMode": "onsite", "llmFacts": {"roleTrack": "product_management"}}
    scored = score_job(job, serbian_intelligence)
    assert scored["workAuthorization"]["status"] == "needs_visa_silent"
    assert scored["matchScore"] <= 45 and scored["hardCapped"] is True
    assert any(r.startswith("Capped: needs a work permit") for r in scored["reasons"])

    assert make(location).fetch_jobs(TERMS, HOME, REMOTE, "Serbia") == []


def test_filter_jobs_logs_fetched_against_kept(caplog):
    """"0 jobs" must say whether nothing was fetched or everything was filtered out."""
    import logging
    from providers.base_provider import filter_jobs

    jobs = [{"title": "Software Engineer", "description": "", "location": "Berlin, Germany"}]
    with caplog.at_level(logging.INFO):
        assert filter_jobs(jobs, ["Product Manager"], ["Berlin"], [], "Germany") == []
    assert "1 postings fetched, 0 kept" in caplog.text
