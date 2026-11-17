"""Eligibility: work authorization as a state beside the score (Step 2, scoringVersion 1.5).

States: authorized, sponsorship_offered, sponsorship_refused, unknown ("Unconfirmed"). The refusal and non-refusal
phrasings are Package A's (test_visa_refusal.py), run through the new module.
"""

import json
import sys

import pytest

import eligibility as el
import run_scoring
from match_engine import shadow
from scorer import score_job
from test_visa_refusal import NON_REFUSALS, REFUSALS

AUTH = {"holds": [{"jurisdiction": "PL", "basis": "citizen"}], "openToSponsorship": True}
BODY = "Own the product roadmap and discovery for our platform. You will work with the team. "


def prefs(**auth):
    return {"country": "Poland", "relocation": "abroad", "allowedLocations": [], "workAuthorization": {**AUTH, **auth}}


def ad(location="Berlin, Germany", quote=None, extra="", **facts):
    """An onsite ad whose description holds `quote` (and `extra`), with extraction facts built from `facts`."""
    description = f"{BODY}{quote or ''} {extra}".strip()
    return {"jobId": "j", "title": "Product Manager", "company": "Acme", "location": location, "workMode": "onsite",
            "description": description, "jobUrl": "https://example.com/j", "llmFacts": {"roleTrack": "product_management", **facts}}


def refusing(quote, **kw):
    return ad(quote=quote, visaSponsorship="not_offered", visaEvidence=quote, **kw)


# --- the four states ---------------------------------------------------------------------------------------------

def test_a_country_the_candidate_may_work_in_is_authorized():
    r = el.assess(ad("Warsaw, Poland"), prefs())
    assert r["state"] == el.AUTHORIZED and r["label"] == "Authorized" and r["country"] == "PL"


def test_offered_with_a_quote_is_sponsorship_offered():
    r = el.assess(ad(quote="Visa sponsorship is available for this role.", visaSponsorship="offered",
                     visaEvidence="Visa sponsorship is available for this role."), prefs())
    assert r["state"] == el.OFFERED and r["quote"]


def test_offered_to_a_candidate_not_open_to_sponsorship_is_blocked():
    job = ad(quote="We sponsor visas.", visaSponsorship="offered", visaEvidence="We sponsor visas.")
    assert el.assess(job, prefs(openToSponsorship=False))["state"] == el.REFUSED


@pytest.mark.parametrize("quote", REFUSALS)
def test_a_refusing_quote_is_sponsorship_refused(quote):
    r = el.assess(refusing(quote), prefs())
    assert r["state"] == el.REFUSED and r["kind"] == "refused" and r["quote"] == quote


@pytest.mark.parametrize("quote", NON_REFUSALS[:5])
def test_a_right_to_work_requirement_is_blocked_only_outside_the_authorized_countries(quote):
    outside = el.assess(refusing(quote), prefs())
    assert outside["state"] == el.REFUSED and outside["kind"] == "right_to_work_required"
    inside = el.assess(refusing(quote, location="Warsaw, Poland"), prefs())
    assert inside["state"] == el.AUTHORIZED  # the same quote in an authorized country blocks nothing
    unknown_country = el.assess(refusing(quote, location=""), prefs())
    assert unknown_country["state"] == el.UNKNOWN and unknown_country["kind"] == "no_country"


def test_silence_on_visa_is_never_a_refusal():
    assert el.assess(ad(), prefs())["state"] == el.UNKNOWN
    assert el.assess(ad(visaSponsorship="not_mentioned"), prefs())["kind"] == "silent"
    assert el.assess(ad(visaSponsorship="not_offered"), prefs())["state"] == el.UNKNOWN  # no quote at all


def test_an_ad_never_read_is_unconfirmed():
    job = ad()
    job["llmFacts"] = None
    r = el.assess(job, prefs())
    assert r["state"] == el.UNKNOWN and r["kind"] == "not_read" and r["basis"] == "not_read"


# --- the quote must be in the ad ---------------------------------------------------------------------------------

def test_a_quote_the_ad_does_not_hold_is_not_used():
    job = ad(visaSponsorship="not_offered", visaEvidence="We do not sponsor visas.")  # the ad text says nothing of the kind
    r = el.assess(job, prefs())
    assert r["state"] == el.UNKNOWN and r["kind"] == "quote_not_in_ad"
    offered = ad(visaSponsorship="offered", visaEvidence="Visa sponsorship is available.")
    assert el.assess(offered, prefs())["state"] == el.UNKNOWN


@pytest.mark.parametrize("quote,text,found", [
    ("We do not sponsor visas.", "<p>We  do NOT\nsponsor visas.</p>", True),
    ("Kandidat mora imati radnu dozvolu", "Kandidat mora imati radnu dozvolu u Nemačkoj", True),
    ("Sponsorship ... not available", "Visa Sponsorship is currently not available here", True),
    ("We don’t sponsor", "We don't sponsor", True),
    ("We do not sponsor visas.", "", False),
    ("We do not sponsor visas.", "We sponsor visas.", False),
    ("", "anything", False),
    ("no", "no way", False),  # too short to prove anything
])
def test_quote_in_text(quote, text, found):
    assert el.quote_in_text(quote, text) is found


# --- dormant ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("auth", [{"holds": []}, {"holds": [{"jurisdiction": ""}]}, {}])
def test_an_empty_authorized_field_is_dormant_no_state_and_no_effect(auth):
    p = {**prefs(), "workAuthorization": auth}
    assert el.assess(refusing("We do not sponsor visas."), p) is None


def test_the_scorer_stores_no_state_when_dormant_and_never_changes_the_score_either_way():
    intel = {"skillsMap": {"p": ["roadmap"]}, "roleFamily": "product"}
    job = refusing("We do not sponsor visas.")
    dormant = score_job(job, {**intel, "jobFitPreferences": {**prefs(), "workAuthorization": {}}})
    active = score_job(job, {**intel, "jobFitPreferences": prefs()})
    assert dormant["eligibility"] is None and active["eligibility"]["state"] == el.REFUSED
    assert dormant["matchScore"] == active["matchScore"] == active["scoreBeforeCaps"]
    assert active["scoringVersion"] == "1.5" and active["hardCapped"] is False


# --- B2B / employer of record / contractor ------------------------------------------------------------------------

REFUSAL = "We do not sponsor visas."


@pytest.mark.parametrize("wording", [
    "We hire contractors on a B2B basis.", "Employer of Record available in your country.", "Independent contractors welcome.",
    "We are open to contractors in this role.",
])
def test_b2b_wording_prevents_blocked_when_the_candidate_is_available_for_it(wording):
    job = refusing(REFUSAL, extra=wording)
    r = el.assess(job, prefs(b2bAvailable=True))
    assert r["state"] == el.UNKNOWN and r["kind"] == "b2b_exception" and r["b2b"] and r["quote"]
    assert el.assess(job, prefs(b2bAvailable=False))["state"] == el.REFUSED  # not available: no exception
    assert el.assess(job, prefs())["state"] == el.REFUSED


@pytest.mark.parametrize("wording", ["No B2B or contractors on a B2B basis.", "We do not work with EOR providers, no b2b."])
def test_negated_b2b_wording_is_no_exception(wording):
    assert el.assess(refusing(REFUSAL, extra=wording), prefs(b2bAvailable=True))["state"] == el.REFUSED


def test_the_b2b_exception_applies_to_a_right_to_work_requirement_too():
    job = refusing("You must have the right to work in Germany.", extra="B2B contracts are fine.")
    assert el.assess(job, prefs(b2bAvailable=True))["state"] == el.UNKNOWN


# --- facts of an unknown shape are no facts ------------------------------------------------------------------------

def test_facts_of_an_unknown_shape_never_produce_a_refusal():
    job = ad(quote=REFUSAL)
    job["llmFacts"] = {"visaSponsorship": "no", "visaEvidence": REFUSAL}  # not one of the three values
    scored = score_job(job, {"skillsMap": {"p": ["roadmap"]}, "jobFitPreferences": prefs()})
    assert scored["eligibility"]["state"] == el.UNKNOWN and "llmFacts" not in scored


# --- Re-score makes no model call and is one path -----------------------------------------------------------------

def _harness(tmp_path, monkeypatch):
    (tmp_path / "intel.json").write_text(json.dumps({"jobFitPreferences": prefs(), "roleFamily": "product", "skillsMap": {"p": ["roadmap"]}}))
    jobs_file = tmp_path / "discovered_jobs.json"
    jobs_file.write_text(json.dumps({"meta": {"sourceRunId": "run"}, "jobs": [ad()]}))
    (tmp_path / "job_history.json").write_text(json.dumps({"version": 1, "updatedAt": None, "jobs": {}}))
    (tmp_path / "manual_jobs.json").write_text(json.dumps({"jobs": []}))
    (tmp_path / "profile.json").write_text(json.dumps({}))
    monkeypatch.setattr(run_scoring, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "llm_fit.json")
    monkeypatch.setattr(shadow, "CACHE_PATH", tmp_path / "engine.json")
    monkeypatch.setattr("confirmed_facts.load", lambda *a, **k: [])
    monkeypatch.setattr(shadow, "load_remap", lambda: {})
    return jobs_file


def test_rescore_makes_no_model_call_and_stamps_each_row(tmp_path, monkeypatch):
    jobs_file = _harness(tmp_path, monkeypatch)
    import llm_enhancer

    def forbidden(*a, **k):
        raise AssertionError("a Re-score must never call a model")

    monkeypatch.setattr(llm_enhancer, "complete_json", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    seen = []
    real = run_scoring.local_enhancer
    monkeypatch.setattr(run_scoring, "local_enhancer", lambda *a, **k: seen.append(1) or real(*a, **k))
    output = tmp_path / "scored.json"
    monkeypatch.setattr(sys, "argv", ["run_scoring.py", "--intelligence", str(tmp_path / "intel.json"), "--jobs", str(jobs_file),
                                      "--manual", str(tmp_path / "manual_jobs.json"), "--output", str(output)])
    assert run_scoring.main() == 0 and seen
    doc = json.loads(output.read_text())
    assert doc["meta"]["scoringVersion"] == "1.5" and all(r["scoringVersion"] == "1.5" for r in doc["jobs"])
    with pytest.raises(RuntimeError):
        real()._complete("prompt", schema=None, model=None, provider=None)


def test_the_kept_ad_rescore_goes_through_the_same_local_path(tmp_path, monkeypatch):
    import job_history
    import rescore_kept
    jobs_file = _harness(tmp_path, monkeypatch)
    ledger = job_history.empty_ledger()
    kept = {**ad(), "jobId": "kept1"}
    facts = {"roleTrack": "product_management", "visaSponsorship": "not_offered", "visaEvidence": REFUSAL}
    kept["description"] += " " + REFUSAL
    ledger["jobs"] = {"kept1": {"job": {k: v for k, v in kept.items() if k != "llmFacts"}, "llmFacts": facts}}
    job_history.ledger_path(jobs_file).write_text(json.dumps(ledger))
    (tmp_path / "scored_jobs.json").write_text(json.dumps({"meta": {}, "jobs": []}))
    seen = []
    real = run_scoring.local_enhancer
    monkeypatch.setattr(run_scoring, "local_enhancer", lambda *a, **k: seen.append(1) or real(*a, **k))
    monkeypatch.setattr("socket.socket.connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network in a Re-score")))
    code, body = rescore_kept.run("kept1", intelligence=tmp_path / "intel.json", jobs=jobs_file, manual=tmp_path / "manual_jobs.json",
                                  scored=tmp_path / "scored_jobs.json", kept=tmp_path / "kept.json")
    assert code == 0 and seen
    # the ledger fix: the kept ad is scored from its stored facts, so it is read and its refusal is found
    assert body["job"]["eligibility"]["state"] == el.REFUSED and body["job"]["scoringVersion"] == "1.5"
