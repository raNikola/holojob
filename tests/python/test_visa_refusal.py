"""A visa refusal needs the ad's own words refusing sponsorship; a right-to-work requirement is not one (scoringVersion 1.4).

The wordings below are representative phrasings, not stored ads. The five real quotes of the 2026-11 sample
were checked in memory by script (Fingerprint, TrendAI and Siemens Energy refused; Duck Creek and Launchmetrics silent).
"""

import json
from pathlib import Path

import pytest

import work_authorization as wa
from dimensions.experience_match import score_experience_match

FIXTURES = Path(__file__).resolve().parent / "fixtures"

PREFS = {
    "country": "Poland",
    "preferredLocations": ["Kraków"],
    "workAuthorization": {"holds": [{"jurisdiction": "PL", "basis": "citizen"}], "openToSponsorship": True},
    "allowedLocations": [],
    "relocation": "abroad",
}

REFUSALS = [
    "We do not sponsor visas.",
    "We do not offer visa sponsorship for this role.",
    "Unfortunately we are unable to sponsor work permits at this time.",
    "We cannot sponsor employment visas.",
    "We can't provide visa sponsorship.",
    "No visa sponsorship available.",
    "No sponsorship is offered for this position.",
    "Candidates must not require sponsorship now or in the future.",
    "Applicants who will require sponsorship now or in the future will not be considered.",
    "You must be able to work in the US without the need for company-sponsored work authorization.",
    "Must be authorized to work in the UK without sponsorship.",
    "This position is not eligible for visa sponsorship.",
    "We are not able to provide work permit sponsorship.",
    "Visa sponsorship is not available for this role.",
    "Sponsorship is unavailable for this role.",
    "We do not, at this time, offer any kind of visa sponsorship.",
    "We will not be able, for this opening, to sponsor a work permit.",
    "We don't provide visa support or immigration assistance.",
    "We cannot offer work permits to candidates outside the EU.",
    "Sponsorship isn't available.",
    "Visa sponsorship: not provided.",
]

NON_REFUSALS = [
    "Must be legally authorized to work in the United States.",
    "Candidates must be authorized to work in Spain.",
    "Must be based in ES/IT/FR and have a work permit.",
    "Proof of eligibility to work in the UK will be required.",
    "You must have the right to work in Germany.",
    "Applicants need a valid work permit for the Netherlands.",
    "We can sponsor visas for the right candidate.",
    "Visa sponsorship is available for this role.",
    "We offer relocation and visa support.",
    "Employment eligibility verification is required on hire.",
    "You do not need a work permit to apply.",
    "Existing right to work in the EU is required.",
    "",
    None,
]


@pytest.mark.parametrize("quote", REFUSALS)
def test_a_refusing_quote_is_a_refusal(quote):
    assert wa.refuses_sponsorship(quote)


@pytest.mark.parametrize("quote", NON_REFUSALS)
def test_a_quote_that_only_requires_a_right_to_work_is_not_a_refusal(quote):
    assert not wa.refuses_sponsorship(quote)


def berlin(**facts):
    return {"location": "Berlin, Germany", "workMode": "onsite", "llmFacts": {"roleTrack": "product_management", **facts}}


def authorization(**facts):
    return wa.authorization_status(berlin(**facts), PREFS)


@pytest.mark.parametrize("quote", REFUSALS[:6])
def test_not_offered_with_a_refusing_quote_is_refused(quote):
    result = authorization(visaSponsorship="not_offered", visaEvidence=quote)
    assert result["status"] == wa.NEEDS_VISA_REFUSED and result["basis"] == "ad_read"


@pytest.mark.parametrize("quote", NON_REFUSALS[:5])
def test_not_offered_with_a_right_to_work_quote_is_silent(quote):
    result = authorization(visaSponsorship="not_offered", visaEvidence=quote)
    assert result["status"] == wa.NEEDS_VISA_SILENT
    assert "requires an existing right to work; sponsorship not addressed" in result["reason"]


def test_not_offered_without_a_quote_is_silent():
    for evidence in (None, "", "  "):
        assert authorization(visaSponsorship="not_offered", visaEvidence=evidence)["status"] == wa.NEEDS_VISA_SILENT


def test_offered_is_unchanged():
    assert authorization(visaSponsorship="offered", visaEvidence="We do not sponsor")["status"] == wa.SPONSORED


def test_an_unread_ad_says_sponsorship_is_unverified():
    result = wa.authorization_status({"location": "Berlin, Germany", "workMode": "onsite"}, PREFS)
    assert result["status"] == wa.NEEDS_VISA_SILENT and result["basis"] == "not_read"
    assert result["reason"].endswith("ad not read: sponsorship unverified")


def test_a_read_ad_silent_on_sponsorship_keeps_its_reason():
    result = authorization()
    assert result["basis"] == "ad_read" and result["reason"].endswith("the ad does not mention sponsorship")


def test_the_real_quote_shapes():
    refused = [
        "Applicants must be authorized to work in the US now or in the future without sponsorship.",
        "We are unable to sponsor visas.",
        "Candidates must be able to work in Germany without the need for sponsored work authorization.",
    ]
    silent = ["Must be legally authorized to work in the United States.", "Must be based in ES/IT/FR and have a work permit."]
    assert all(wa.refuses_sponsorship(q) for q in refused)
    assert not any(wa.refuses_sponsorship(q) for q in silent)


# --- the years comparison is gone -------------------------------------------------------------


@pytest.fixture
def intelligence():
    return json.loads((FIXTURES / "candidate-intelligence.json").read_text("utf-8"))


@pytest.mark.parametrize("years", [None, 1, 3, 6, 9, 15])
def test_total_years_are_never_compared_with_the_ads_years(intelligence, years):
    base = {"title": "Product Manager", "llmFacts": {"seniority": "senior"}}
    with_years = {"title": "Product Manager", "llmFacts": {"seniority": "senior", "yearsRequired": years}}
    score, reasons = score_experience_match(with_years, intelligence)
    assert (score, reasons) == score_experience_match(base, intelligence)
    assert not any("years" in r.lower() for r in reasons)


def test_a_six_to_nine_years_ad_gets_no_years_delta(intelligence):
    job = {"title": "Product Manager", "llmFacts": {"seniority": "senior", "yearsRequired": 6}}
    score, reasons = score_experience_match(job, intelligence)
    assert score == 92 and reasons == ["Seniority matches (ad)"]
