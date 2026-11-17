"""Blocking facts and the verdict (Step 2b, scoringVersion 1.5): a blocked ad is never Apply or P1, keeps its Fit number,
and every other state leaves the verdict to the score."""

import json
import sys
from pathlib import Path

import pytest

import blocking
import eligibility as el
import labels
import run_scoring
from scorer import score_job
from test_eligibility import BODY, _harness, ad, prefs, refusing

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STACK = {"skillsMap": {"p": ["roadmap", "discovery"]}, "roleFamily": "product", "languages": ["Serbian (native)", "English (fluent)"]}
REFUSAL = "We do not sponsor visas."
PADDING = " ".join(["The team ships the product to customers every week and we value clear writing and calm planning."] * 12)
GERMAN = [{"kind": "language", "text": "Fluent German required", "importance": "must", "postingQuote": "Fluent German required"}]
GERMAN_PLUS = [{"kind": "language", "text": "German is a plus", "importance": "nice", "postingQuote": "German is a plus"}]


def scored(job, **p):
    prefs_ = {**prefs(), **p}
    return score_job(job, {**STACK, "jobFitPreferences": prefs_})


# --- sponsorship ----------------------------------------------------------------------------------------------------

def test_a_refused_ad_is_blocked_with_its_number_and_never_apply_or_p1():
    free = scored(refusing(REFUSAL), workAuthorization={})  # the same ad with the check dormant
    blocked = scored(refusing(REFUSAL))
    assert blocked["eligibility"]["state"] == el.REFUSED
    assert [b["kind"] for b in blocked["blockedBy"]] == ["sponsorship_refused"] and blocked["blockedBy"][0]["text"]
    assert blocked["applyRecommendation"] == labels.BLOCKED_LABEL and blocked["priority"] == labels.BLOCKED_LABEL
    assert isinstance(blocked["matchScore"], int) and blocked["matchScore"] == free["matchScore"]  # the number does not move
    assert blocked["matchLabel"] == labels.match_label(blocked["matchScore"])
    assert any(r.startswith("Blocked:") for r in blocked["reasons"])


def test_right_to_work_required_outside_the_authorized_countries_is_blocked():
    r = scored(refusing("You must have the right to work in Germany."))
    assert r["eligibility"]["kind"] == "right_to_work_required" and r["blockedBy"][0]["kind"] == "sponsorship_refused"


@pytest.mark.parametrize("make, state", [
    (lambda: ad("Warsaw, Poland"), el.AUTHORIZED),
    (lambda: ad(quote="Visa sponsorship is available.", visaSponsorship="offered", visaEvidence="Visa sponsorship is available."), el.OFFERED),
    (lambda: ad(), el.UNKNOWN),  # silent
    (lambda: {**ad(), "llmFacts": {}}, el.UNKNOWN),  # not read: no facts, but a description
    (lambda: refusing(REFUSAL, extra="We hire contractors on a B2B basis."), el.UNKNOWN),  # b2b exception (b2bAvailable below)
])
def test_the_other_states_do_not_block_and_leave_the_verdict_to_the_score(make, state):
    r = scored(make(), **{"workAuthorization": {**prefs()["workAuthorization"], "b2bAvailable": True}})
    assert r["eligibility"]["state"] == state and r["blockedBy"] == []
    assert (r["applyRecommendation"], r["priority"]) == labels.verdict(r["matchScore"], r["redFlags"])
    assert r["applyRecommendation"] != labels.BLOCKED_LABEL


def test_the_b2b_exception_is_not_blocked_but_the_same_ad_without_b2b_is():
    job = refusing(REFUSAL, extra="We hire contractors on a B2B basis.")
    assert scored(job, workAuthorization={**prefs()["workAuthorization"], "b2bAvailable": True})["blockedBy"] == []
    assert scored(job)["blockedBy"][0]["kind"] == "sponsorship_refused"


def test_dormant_authorization_blocks_nothing():
    r = scored(refusing(REFUSAL), workAuthorization={})
    assert r["eligibility"] is None and r["blockedBy"] == []


# --- language -------------------------------------------------------------------------------------------------------

def test_a_required_language_the_profile_does_not_speak_blocks():
    job = ad("Warsaw, Poland", requirements=GERMAN, extra=PADDING + " Fluent German required.")
    r = scored(job)
    assert r["languageGap"] and [b["kind"] for b in r["blockedBy"]] == ["language"]
    assert r["applyRecommendation"] == labels.BLOCKED_LABEL and r["priority"] == labels.BLOCKED_LABEL
    assert r["matchScore"] == scored(ad("Warsaw, Poland", extra=PADDING))["matchScore"]


def test_a_nice_to_have_language_is_no_blocker():
    r = scored(ad("Warsaw, Poland", requirements=GERMAN_PLUS, extra=PADDING + " German is a plus."))
    assert r["languageGap"] == [] and r["blockedBy"] == []


def test_a_required_language_the_profile_speaks_is_no_blocker():
    job = ad("Warsaw, Poland", extra=PADDING + " Fluent English required.", requirements=[{**GERMAN[0], "text": "Fluent English required", "postingQuote": "Fluent English required"}])
    assert scored(job)["blockedBy"] == []


# --- location -------------------------------------------------------------------------------------------------------

def loc(job, allowed):
    return blocking.location_state(job, {**prefs(), "allowedLocations": allowed})


def test_location_is_dormant_without_allowed_locations():
    assert loc(ad("Berlin, Germany"), []) is None


def test_a_named_place_outside_the_allowed_ones_is_outside():
    assert loc(ad("Berlin, Germany"), ["RS"])["state"] == blocking.OUTSIDE


def test_a_named_place_inside_the_allowed_ones_is_in():
    assert loc(ad("Belgrade, Serbia"), ["RS"])["state"] == blocking.IN


def test_a_bare_remote_is_neither_in_nor_outside():
    job = {**ad("Remote"), "workMode": "remote"}
    assert loc(job, ["RS"])["state"] == blocking.UNKNOWN
    assert loc(job, ["RS", "REMOTE"])["state"] == blocking.UNKNOWN


def test_an_unknown_country_is_unknown_never_outside():
    assert loc(ad(""), ["RS"])["state"] == blocking.UNKNOWN


def test_only_an_outside_location_blocks():
    outside = scored(ad("Berlin, Germany"), allowedLocations=["RS"])
    assert [b["kind"] for b in outside["blockedBy"]] == ["location"] and outside["priority"] == labels.BLOCKED_LABEL
    assert outside["locationState"]["state"] == blocking.OUTSIDE
    inside = scored(ad("Belgrade, Serbia"), allowedLocations=["RS"])
    assert inside["blockedBy"] == [] and inside["locationState"]["state"] == blocking.IN
    remote = scored({**ad("Remote"), "workMode": "remote"}, allowedLocations=["RS"])
    assert remote["blockedBy"] == []


# --- verdict, judge path, unread -------------------------------------------------------------------------------------

@pytest.mark.parametrize("score", [0, 39, 40, 54, 55, 69, 70, 75, 76, 100])
def test_verdict_without_blockers_is_the_old_rule_and_with_blockers_never_apply_or_p1(score):
    apply_rec = labels.apply_recommendation(score, [])
    assert labels.verdict(score, []) == (apply_rec, labels.priority(score, apply_rec, []))
    assert labels.verdict(score, [], [{"kind": "language", "text": "x"}]) == ("Blocked", "Blocked")


def test_the_fit_judge_adjustment_keeps_a_blocked_ad_blocked():
    import llm_enhancer
    intelligence = json.loads((FIXTURES / "candidate-intelligence.json").read_text(encoding="utf-8"))
    row = scored(refusing(REFUSAL))
    row = {**row, "matchScore": 70, "scoreBeforeCaps": 70, "hardCapped": False}
    answer = {"fit": "strong", "fit_reason": "x", "requirements": [{"requirement": "a", "status": "met", "evidence": "b"}],
              "missing": [], "dealbreakers": []}
    judge = llm_enhancer.LlmFitEnhancer("openai", "gpt-4o", threshold=0, complete=lambda *a, **k: answer)
    out = judge.enhance(refusing(REFUSAL), row, intelligence)
    assert out["matchScore"] == 75 and out["llmFit"]["adjustment"] == 5  # the judge moved the number...
    assert (out["applyRecommendation"], out["priority"]) == ("Blocked", "Blocked")  # ...and the ad stays blocked


def test_remote_limited_to_a_country_is_unknown_when_remote_is_allowed_and_outside_when_it_is_not():
    job = {**ad("Remote"), "workMode": "remote", "llmFacts": {"roleTrack": "product_management", "remoteEligibility": ["DE"]}}
    assert loc(job, ["RS", "REMOTE"])["state"] == blocking.UNKNOWN  # remote is welcome, but a German-only hire is not evidence for Serbia
    assert loc(job, ["RS"])["state"] == blocking.OUTSIDE


def test_an_unread_ad_with_no_blocker_keeps_not_assessed():
    r = scored({**ad(), "description": ""})
    assert r["readStatus"] == "not_read" and r["blockedBy"] == []
    assert r["applyRecommendation"] == labels.INSUFFICIENT_APPLY and r["matchScore"] is None


def test_rescore_blocks_without_a_model_call(tmp_path, monkeypatch):
    jobs_file = _harness(tmp_path, monkeypatch)
    jobs_file.write_text(json.dumps({"meta": {"sourceRunId": "run"}, "jobs": [refusing(REFUSAL)]}))
    import llm_enhancer

    def forbidden(*a, **k):
        raise AssertionError("a Re-score must never call a model")

    monkeypatch.setattr(llm_enhancer, "complete_json", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    output = tmp_path / "scored.json"
    monkeypatch.setattr(sys, "argv", ["run_scoring.py", "--intelligence", str(tmp_path / "intel.json"), "--jobs", str(jobs_file),
                                      "--manual", str(tmp_path / "manual_jobs.json"), "--output", str(output)])
    assert run_scoring.main() == 0
    row = json.loads(output.read_text())["jobs"][0]
    assert row["priority"] == "Blocked" and row["applyRecommendation"] == "Blocked" and row["blockedBy"][0]["kind"] == "sponsorship_refused"
    assert row["scoringVersion"] == "1.5"
