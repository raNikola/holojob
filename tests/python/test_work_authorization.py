"""Work authorization: one status per job, a cap per status, nothing hidden."""

import copy
import json
from pathlib import Path

import pytest

import work_authorization as wa
from dimensions.location_match import score_location_match
from enrich_jobs import _coerce
from geography import country_of_name, covers, resolve_countries, resolve_country
from scorer import WORK_AUTHORIZATION_CAPS, score_job, score_jobs

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# A candidate who may work only in their own country (Kraków, Poland is the
# home in these tests) and would take a sponsored role elsewhere.
PREFS = {
    "country": "Poland",
    "preferredLocations": ["Kraków"],
    "workAuthorization": {"holds": [{"jurisdiction": "PL", "basis": "citizen"}], "openToSponsorship": True},
    "allowedLocations": [],
    "relocation": "abroad",
}


def job(location, mode="onsite", **facts):
    return {"location": location, "workMode": mode, "llmFacts": facts}


def status(j, **overrides):
    return wa.authorization_status(j, {**PREFS, **overrides})["status"]


# --- geography ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "location,code",
    [("Belgrade, Serbia", "RS"), ("Niš, Centralna Srbija, Serbia", "RS"), ("Berlin, Deutschland", "DE"),
     ("Remote, US", "US"), ("Austin, United States", "US"), ("Somewhere, Atlantis", None), ("", None)],
)
def test_locations_resolve_to_countries(location, code):
    assert resolve_country(location) == code


def test_a_right_for_the_eu_covers_its_members_and_eu_remote_roles_only():
    assert covers("EU", "DE") and covers("EU", "EU") and covers("PL", "PL")
    assert not covers("EU", "RS") and not covers("RS", "EU") and not covers("PL", "DE")
    assert country_of_name("Srbija") == "RS" and country_of_name("Belgrade") is None


# --- statuses ----------------------------------------------------------------------------------


def test_work_in_a_country_the_candidate_holds_is_authorized():
    assert status(job("Warsaw, Poland")) == wa.AUTHORIZED


def test_a_sponsored_role_abroad_is_sponsored():
    assert status(job("Berlin, Germany", visaSponsorship="offered")) == wa.SPONSORED


def test_an_ad_silent_on_sponsorship_needs_a_visa():
    assert status(job("Berlin, Germany")) == wa.NEEDS_VISA_SILENT


def test_an_ad_refusing_sponsorship_is_refused():
    assert status(job("Berlin, Germany", visaSponsorship="not_offered")) == wa.NEEDS_VISA_REFUSED


def test_sponsorship_offered_to_a_candidate_not_open_to_it_is_refused():
    no = {"holds": PREFS["workAuthorization"]["holds"], "openToSponsorship": False}
    assert status(job("Berlin, Germany", visaSponsorship="offered"), workAuthorization=no) == wa.NEEDS_VISA_REFUSED


def test_remote_with_no_restriction_is_authorized():
    assert status(job("Remote", "remote")) == wa.AUTHORIZED
    assert status(job("Remote", "remote", remoteEligibility=["WORLDWIDE"])) == wa.AUTHORIZED


def test_remote_restricted_to_a_region_the_candidate_cannot_work_in_needs_a_visa():
    assert status(job("Remote", "remote", remoteEligibility=["US"])) == wa.NEEDS_VISA_SILENT
    eu_citizen = {"holds": [{"jurisdiction": "EU", "basis": "citizen"}], "openToSponsorship": False}
    assert status(job("Remote", "remote", remoteEligibility=["EU"]), workAuthorization=eu_citizen) == wa.AUTHORIZED


def test_the_country_the_model_read_is_used_when_the_location_names_none():
    assert status(job("Head office", jobCountry="DE")) == wa.NEEDS_VISA_SILENT


def test_unknown_country_or_unset_rights_never_guess():
    assert status(job("Head office")) == wa.UNKNOWN
    assert status(job("Berlin, Germany"), workAuthorization={}) == wa.UNKNOWN


def test_an_allowed_location_set_gates_only_when_the_candidate_sets_one():
    us = job("Austin, United States", visaSponsorship="offered")
    assert status(us) == wa.SPONSORED
    assert status(us, allowedLocations=["EUROPE", "REMOTE"]) == wa.OUTSIDE_ALLOWED
    assert status(job("Remote", "remote"), allowedLocations=["EUROPE"]) == wa.OUTSIDE_ALLOWED
    assert status(job("Berlin, Germany"), allowedLocations=["EUROPE"]) == wa.NEEDS_VISA_SILENT
    # An unknown place is not known to be outside the set.
    assert status(job("Head office"), allowedLocations=["EUROPE"]) == wa.UNKNOWN


def test_a_multi_office_ad_is_authorized_if_any_office_is_where_the_candidate_may_work():
    offices = (
        "Amsterdam, Netherlands; Belgrade, Serbia; Berlin, Germany; Limassol, Cyprus; "
        "London, United Kingdom; Madrid, Spain; Munich, Germany; Prague, Czech Republic; "
        "Warsaw, Poland; Yerevan, Armenia, Netherlands"
    )
    serbian = {"holds": [{"jurisdiction": "RS", "basis": "citizen"}], "openToSponsorship": True}
    assert resolve_countries(offices)[:3] == ["NL", "RS", "DE"]
    result = wa.authorization_status(job(offices), {**PREFS, "workAuthorization": serbian})
    assert result["status"] == wa.AUTHORIZED and result["reason"] == "you can work in RS"
    # No office is one the candidate holds: still a visa job, named by its first offices.
    american = {"holds": [{"jurisdiction": "US", "basis": "citizen"}], "openToSponsorship": True}
    result = wa.authorization_status(job(offices), {**PREFS, "workAuthorization": american})
    assert result["status"] == wa.NEEDS_VISA_SILENT and result["place"] == "NL/RS/DE +5 more"


# --- scorer ------------------------------------------------------------------------------------


@pytest.fixture
def intelligence():
    data = json.loads((FIXTURES / "candidate-intelligence.json").read_text("utf-8"))
    data["jobFitPreferences"] = {**data["jobFitPreferences"], **PREFS}
    return data


AD = "Own the product roadmap and discovery for our platform. " * 8


def full_job(location, **facts):
    return {
        "jobId": location, "title": "Product Manager", "company": "Acme", "location": location,
        "workMode": "onsite", "description": AD, "jobUrl": "https://example.com/j",
        "llmFacts": {"roleTrack": "product_management", **facts},
    }


@pytest.mark.parametrize(
    "facts,status_,cap",
    [({"visaSponsorship": "not_offered"}, wa.NEEDS_VISA_REFUSED, 25),
     ({}, wa.NEEDS_VISA_SILENT, 45)],
)
def test_visa_statuses_cap_the_score_and_say_why(intelligence, facts, status_, cap):
    result = score_job(full_job("Berlin, Germany", **facts), intelligence)
    assert result["workAuthorization"]["status"] == status_
    assert result["matchScore"] <= cap == WORK_AUTHORIZATION_CAPS[status_]
    assert result["hardCapped"] is True
    assert any(r.startswith("Capped: needs a work permit for DE") for r in result["reasons"])


def test_an_excluded_location_is_capped_at_40(intelligence):
    intel = copy.deepcopy(intelligence)
    intel["jobFitPreferences"]["allowedLocations"] = ["EUROPE"]
    result = score_job(full_job("Austin, United States", visaSponsorship="offered"), intel)
    assert result["workAuthorization"]["status"] == wa.OUTSIDE_ALLOWED and result["matchScore"] <= 40


def test_sponsored_and_authorized_jobs_are_not_capped(intelligence):
    for location, facts in (("Berlin, Germany", {"visaSponsorship": "offered"}), ("Warsaw, Poland", {})):
        result = score_job(full_job(location, **facts), intelligence)
        assert result["workAuthorization"]["status"] in (wa.SPONSORED, wa.AUTHORIZED)
        assert not any(r.startswith("Capped:") for r in result["reasons"])


def test_capped_jobs_are_scored_not_removed(intelligence):
    jobs = [full_job("Berlin, Germany", visaSponsorship="not_offered"), full_job("Warsaw, Poland")]
    assert len(score_jobs(jobs, intelligence)) == 2


# --- location_match ----------------------------------------------------------------------------


def loc(j, **prefs):
    return score_location_match(j, {"jobFitPreferences": {**PREFS, **prefs}})[0]


def test_relocation_abroad_makes_an_onsite_role_abroad_usable_but_not_one_at_home():
    assert loc(job("Berlin, Germany")) == 60
    assert loc(job("Warsaw, Poland")) == 15
    assert loc(job("Kraków, Poland")) == 90


def test_relocation_policies():
    assert loc(job("Berlin, Germany"), relocation="none") == 15
    assert loc(job("Warsaw, Poland"), relocation="anywhere") == 60
    assert loc(job("Berlin, Germany"), relocation=None) == 15


def test_hybrid_at_home_keeps_its_tier():
    assert loc(job("Warsaw, Poland", "hybrid")) == 55


def test_a_country_in_preferred_locations_is_never_a_commute_place():
    assert loc(job("Warsaw, Poland"), preferredLocations=["Poland"], relocation="none") == 15


def test_a_bare_country_is_recognised_for_any_country():
    assert loc(job("Germany", "unclear"), relocation="none") == 45


# --- extraction --------------------------------------------------------------------------------


def test_extracted_facts_are_coerced_to_known_codes():
    facts = _coerce({
        "job_country": "de", "remote_eligibility": ["eu", "Narnia", "worldwide"],
        "visa_sponsorship": "Offered", "visa_evidence": "We sponsor work permits.",
    })
    assert facts["jobCountry"] == "DE"
    assert facts["remoteEligibility"] == ["EU", "WORLDWIDE"]
    assert facts["visaSponsorship"] == "offered"
    assert _coerce({"job_country": "Narnia", "visa_sponsorship": "maybe"})["jobCountry"] is None
    assert _coerce({"visa_sponsorship": "maybe"})["visaSponsorship"] == "not_mentioned"


def test_board_spellings_of_onsite_get_the_onsite_tier():
    for spelling in ("on_site", "on-site", "onsite"):
        assert loc(job("Warsaw, Poland", spelling)) == 15
