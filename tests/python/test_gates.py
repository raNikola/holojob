"""The five gates, decided in code (contract 5.4)."""

import json
from pathlib import Path

import pytest

from match_engine.gates import (
    bucket_for,
    gate_results,
    language_result,
    location_result,
    required_languages,
    role_family_result,
    salary_floor_result,
    work_authorization_result,
)
from match_engine.matcher import GATES

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "postings"


def cand_gates(**overrides):
    base = {
        "workAuthorization": {"holds": [{"jurisdiction": "RS"}], "openToSponsorship": False},
        "allowedLocations": [],
        "languages": ["Serbian (native)", "English (fluent)"],
        "minSalaryEur": 2000,
        "preferredLocations": ["Niš"],
        "remotePreference": "flexible",
        "relocation": "none",
        "country": "Serbia",
    }
    return {**base, **overrides}


def tr(track):
    """A role track with the evidence quote the cap requires."""
    return {"roleTrack": track, "roleTrackEvidence": "Own the roadmap and discovery."}


def job(location="Niš, Serbia", facts=None, **fields):
    return {"title": "Product Manager", "location": location, "description": "", "llmFacts": facts or {}, **fields}


# --- work_authorization ---------------------------------------------------------------

def test_work_authorization_pass_where_the_candidate_holds_rights():
    assert work_authorization_result(job("Belgrade, Serbia"), cand_gates()) == "pass"


def test_work_authorization_pass_when_sponsored_and_open_to_it():
    j = job("Berlin, Germany", {"visaSponsorship": "offered"})
    gates = cand_gates(workAuthorization={"holds": [{"jurisdiction": "RS"}], "openToSponsorship": True})
    assert work_authorization_result(j, gates) == "pass"


@pytest.mark.parametrize("sponsorship", ["not_offered", "offered"])
def test_work_authorization_fail_when_a_visa_is_needed_and_not_available(sponsorship):
    # "offered" fails too: the candidate is not open to sponsored roles.
    j = job("Berlin, Germany", {"visaSponsorship": sponsorship})
    assert work_authorization_result(j, cand_gates()) == "fail"


def test_work_authorization_unknown_when_the_ad_is_silent_on_sponsorship():
    assert work_authorization_result(job("Berlin, Germany"), cand_gates()) == "unknown"


def test_work_authorization_unknown_without_rights_in_the_profile():
    assert work_authorization_result(job("Berlin, Germany"), cand_gates(workAuthorization={})) == "unknown"


def test_work_authorization_ignores_the_location_set():
    # Outside allowedLocations is the location gate's fail, not this one's.
    gates = cand_gates(allowedLocations=["REMOTE"])
    assert work_authorization_result(job("Belgrade, Serbia"), gates) == "pass"


# --- location -------------------------------------------------------------------------

def test_location_pass_remote():
    assert location_result(job("Germany", isRemote=True), cand_gates()) == "pass"


def test_location_pass_in_a_city_the_candidate_named():
    assert location_result(job("Nis, Serbia", workMode="onsite"), cand_gates()) == "pass"


def test_location_pass_where_the_candidate_would_relocate():
    j = job("Berlin, Germany", workMode="onsite")
    assert location_result(j, cand_gates(relocation="abroad")) == "pass"


def test_location_fail_onsite_elsewhere():
    assert location_result(job("Belgrade, Serbia", workMode="onsite"), cand_gates()) == "fail"


def test_location_fail_outside_allowed_locations():
    gates = cand_gates(allowedLocations=["RS", "REMOTE"])
    assert location_result(job("Berlin, Germany", workMode="hybrid"), gates) == "fail"


@pytest.mark.parametrize("j", [
    job("Belgrade, Serbia", workMode="hybrid"),
    job("Belgrade, Serbia"),          # work mode unknown
    job("Serbia"),                    # country only, mode unknown
    job(""),                          # no location
])
def test_location_unknown_when_the_ad_leaves_it_open(j):
    assert location_result(j, cand_gates()) == "unknown"


def test_location_onsite_is_unknown_without_a_city_to_commute_to():
    # A country is never a commute place, so "elsewhere" cannot be known.
    gates = cand_gates(preferredLocations=["Serbia"])
    assert location_result(job("Belgrade, Serbia", workMode="onsite"), gates) == "unknown"


# --- language -------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Fluency in spoken and written English.", {"English"}),
    ("Upper-intermediate or higher level of English (spoken and written).", {"English"}),
    ("Communicate clearly and confidently in English, both in writing", {"English"}),
    ("Odlično poznavanje engleskog jezika.", {"English"}),
    ("Fluent German and English required.", {"English", "German"}),
    ("Pick up the local language or sharpen your English skills.", set()),
    ("Fluent German is a plus.", set()),
    ("We build products for German retailers.", set()),
    ("", set()),
])
def test_required_languages_from_the_ad(text, expected):
    assert required_languages(job(description=text)) == expected


def test_required_languages_from_must_have_language_requirements():
    reqs = [
        {"kind": "language", "importance": "must", "text": "German", "postingQuote": "German"},
        {"kind": "language", "importance": "nice", "text": "French", "postingQuote": "French"},
    ]
    assert required_languages(job(), reqs) == {"German"}


def test_language_pass_when_every_required_language_is_spoken():
    assert language_result(job(description="Fluent English required."), cand_gates()) == "pass"


def test_language_unknown_on_a_language_the_candidate_does_not_list():
    # A short list is not a statement that the rest is not spoken.
    assert language_result(job(description="Fluent German and English required."), cand_gates()) == "unknown"


def test_language_fail_only_on_a_language_confirmed_as_not_spoken():
    gates = cand_gates(languagesNotSpoken=["German"])
    assert language_result(job(description="Fluent German and English required."), gates) == "fail"
    assert language_result(job(description="Fluent French and English required."), gates) == "unknown"


def test_role_family_unknown_for_other_or_a_track_without_evidence():
    assert role_family_result(job(facts={"roleTrack": "other", "roleTrackEvidence": "Sells devices."}), "product") == "unknown"
    assert role_family_result(job(facts={"roleTrack": "engineering"}), "product") == "unknown"
    assert role_family_result(job(facts={"roleTrack": "engineering", "roleTrackEvidence": " "}), "product") == "unknown"
    assert role_family_result(job(facts=tr("engineering")), "product") == "fail"


def test_language_unknown_when_the_ad_states_none():
    assert language_result(job(description="Own the roadmap."), cand_gates()) == "unknown"


def test_language_unknown_when_the_candidate_lists_none():
    # Empty means unstated, not "none" (contract 1.1).
    assert language_result(job(description="Fluent German required."), cand_gates(languages=[])) == "unknown"


# --- salary_floor ---------------------------------------------------------------------

def test_salary_pass_when_the_range_reaches_the_floor():
    assert salary_floor_result(job(salary="EUR 1500 - 2500 per month"), cand_gates()) == "pass"


def test_salary_pass_when_the_pay_cannot_be_read():
    assert salary_floor_result(job(salary="competitive"), cand_gates()) == "pass"
    assert salary_floor_result(job(), cand_gates()) == "pass"


def test_salary_fail_when_the_top_is_below_the_floor():
    assert salary_floor_result(job(salary="EUR 1200 - 1800 per month"), cand_gates()) == "fail"


def test_salary_unknown_without_a_floor():
    assert salary_floor_result(job(salary="EUR 1200 per month"), cand_gates(minSalaryEur=None)) == "unknown"


# --- role_family ----------------------------------------------------------------------

@pytest.mark.parametrize("track", ["product_management", "product_ownership"])
def test_role_family_pass_on_an_accepted_track(track):
    assert role_family_result(job(facts=tr(track)), "product") == "pass"


@pytest.mark.parametrize("track", ["project_delivery", "engineering"])
def test_role_family_fail_off_the_family(track):
    assert role_family_result(job(facts=tr(track)), "product") == "fail"


def test_role_family_follows_the_candidate_family():
    assert role_family_result(job(facts=tr("engineering")), "engineering") == "pass"


def test_role_family_unknown_without_a_track():
    assert role_family_result(job(), "product") == "unknown"


@pytest.mark.parametrize("family", [None, ""])
def test_role_family_unknown_without_a_family(family):
    # No family is assumed: not product, not anything else.
    for track in ("product_management", "engineering", "other"):
        assert role_family_result(job(facts=tr(track)), family) == "unknown"


def test_an_unset_family_never_blocks_or_caps():
    from match_engine.fit import score

    gates = gate_results(job(facts=tr("engineering")), {"gates": cand_gates(), "roleFamily": None})
    role = next(g for g in gates if g["gate"] == "role_family")
    assert role["result"] == "unknown"
    out = score([], gates)
    assert "role_family_mismatch" not in out["caps"]
    assert {"competencyId": "role_family", "question": "Is this the kind of role you are looking for?"} in out["questions"]


@pytest.mark.parametrize("family,track,result", [
    ("product", "product_management", "pass"),
    ("product", "product_ownership", "pass"),
    ("product", "engineering", "fail"),
    ("engineering", "engineering", "pass"),
    ("engineering", "product_management", "fail"),
    ("delivery", "project_delivery", "pass"),
])
def test_role_family_follows_the_chosen_family(family, track, result):
    assert role_family_result(job(facts=tr(track)), family) == result


# --- all five and the bucket ----------------------------------------------------------

def test_gate_results_returns_all_five_in_order_with_quotes():
    quotes = [{"gate": "language", "quote": "in English"}]
    results = gate_results(job(), {"gates": cand_gates(), "roleFamily": "product"}, quotes)
    assert [g["gate"] for g in results] == list(GATES)
    assert {g["gate"]: g["quote"] for g in results} == {**{g: None for g in GATES}, "language": "in English"}


def test_the_quote_decides_nothing():
    candidate = {"gates": cand_gates(), "roleFamily": "product"}
    j = job("Belgrade, Serbia", workMode="onsite")
    plain = gate_results(j, candidate)
    quoted = gate_results(j, candidate, {g: "Fully remote, any language, any salary." for g in GATES})
    assert [g["result"] for g in plain] == [g["result"] for g in quoted]


def test_bucket_for():
    def g(*results):
        return [{"gate": n, "result": r, "quote": None} for n, r in zip(GATES, results)]
    assert bucket_for(g("pass", "pass", "pass", "pass", "pass")) == "apply"
    assert bucket_for(g("pass", "unknown", "pass", "pass", "pass")) == "check_first"
    assert bucket_for(g("pass", "unknown", "fail", "pass", "pass")) == "blocked"


def test_linkedin_fixture_gates():
    posting = json.loads((FIXTURES / "linkedin-1.json").read_text(encoding="utf-8"))
    results = {g["gate"]: g["result"] for g in gate_results(posting, {"gates": cand_gates(), "roleFamily": "product"})}
    # Niš is the candidate's city; the ad asks for English; no salary; not enriched, so no role track.
    assert results == {"work_authorization": "pass", "location": "pass", "language": "pass",
                       "salary_floor": "pass", "role_family": "unknown"}


def test_a_preferred_bullet_does_not_hide_a_required_language():
    text = "Requirements:\n- Fintech experience preferred\n- Exceptional English, both written and spoken\n"
    assert required_languages(job(description=text)) == {"English"}


def test_clauses_split_on_html_tags():
    text = "&lt;li&gt;Jira preferred&lt;/li&gt;&lt;li&gt;Fluency in English&lt;/li&gt;"
    assert required_languages(job(description=text)) == {"English"}
