"""Ads outside the candidate's places are capped by scoring either way, so they are not read."""

import json
import sys

import pytest

import enrich_jobs
import work_authorization as wa
from scorer import score_job

ALLOWED = {"allowedLocations": ["REMOTE", "EU", "US", "RS"]}
FACTS = {"_fingerprint": "x", "workMode": "onsite", "roleTrack": "product_management", "seniority": "senior", "yearsRequired": 5}


def job(location, **extra):
    return {"jobId": location, "title": "Product Manager", "company": "Acme", "location": location,
            "description": "Own the roadmap.", **extra}


@pytest.mark.parametrize("location, expected", [
    ("London, England, UK", True),
    ("Manchester Area, UK", True),
    ("Berlin, Germany", False),          # EU is allowed
    ("Austin, TX, USA", False),          # US is allowed
    ("Nowhereville", False),             # an unknown place is not known to be outside
    ("", False),
])
def test_rule_follows_the_boards_own_location(location, expected):
    assert wa.outside_allowed_before_enrichment(job(location), ALLOWED) is expected


def test_remote_by_the_board_is_not_decided_before_reading():
    assert wa.outside_allowed_before_enrichment(job("London, UK", isRemote=True), ALLOWED) is False


def test_an_empty_allowed_list_gates_nothing():
    assert wa.outside_allowed_before_enrichment(job("London, UK"), {"allowedLocations": []}) is False
    assert wa.outside_allowed_before_enrichment(job("London, UK"), {}) is False


def test_the_rule_agrees_with_the_status_scoring_reaches_without_facts():
    j = job("London, England, UK")
    assert wa.authorization_status(j, ALLOWED)["status"] == wa.OUTSIDE_ALLOWED
    assert wa.outside_allowed_before_enrichment(j, ALLOWED)


def test_a_skipped_ad_is_still_capped_by_scoring(intelligence_with_allowed):
    scored = score_job(job("London, England, UK"), intelligence_with_allowed)
    assert scored["workAuthorization"]["status"] == wa.OUTSIDE_ALLOWED
    assert scored["matchScore"] <= 40 and scored["hardCapped"]


@pytest.fixture
def intelligence_with_allowed():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    intel = json.loads((root / "data" / "examples" / "candidate-intelligence.example.json").read_text())
    return {**intel, "jobFitPreferences": {**(intel.get("jobFitPreferences") or {}), **ALLOWED}}


def _run_enrich(tmp_path, monkeypatch, jobs, intelligence, extra=()):
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text(json.dumps({"jobs": jobs}))
    intel_file = tmp_path / "intel.json"
    intel_file.write_text(json.dumps(intelligence))
    read = []
    monkeypatch.setattr(enrich_jobs, "extract", lambda j, model, provider, previous=None: read.append(j["jobId"]) or FACTS)
    monkeypatch.setattr(sys, "argv", ["enrich_jobs.py", "--jobs", str(jobs_file), "--intelligence", str(intel_file), *extra])
    assert enrich_jobs.main() == 0
    return read


def test_enrichment_does_not_read_ads_outside_allowed_places(tmp_path, monkeypatch, capsys):
    jobs = [job("London, England, UK"), job("Berlin, Germany"), job("Manchester Area, UK")]
    read = _run_enrich(tmp_path, monkeypatch, jobs, {"jobFitPreferences": ALLOWED})
    assert read == ["Berlin, Germany"]
    assert "not read 2 (outside your allowed locations)" in capsys.readouterr().out


def test_an_ad_that_already_has_facts_is_left_as_it_is(tmp_path, monkeypatch):
    fp = enrich_jobs.job_fingerprint(job("London, England, UK"))
    jobs = [job("London, England, UK", llmFacts={"_fingerprint": fp, "workMode": "hybrid"})]
    _run_enrich(tmp_path, monkeypatch, jobs, {"jobFitPreferences": ALLOWED})
    saved = json.loads((tmp_path / "jobs.json").read_text())["jobs"][0]
    assert saved["llmFacts"]["workMode"] == "hybrid"


def test_the_flag_turns_the_skip_off(tmp_path, monkeypatch):
    jobs = [job("London, England, UK")]
    read = _run_enrich(tmp_path, monkeypatch, jobs, {"jobFitPreferences": ALLOWED}, extra=["--read-outside-allowed"])
    assert read == ["London, England, UK"]


def test_no_intelligence_file_means_nothing_is_skipped(tmp_path, monkeypatch):
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text(json.dumps({"jobs": [job("London, England, UK")]}))
    read = []
    monkeypatch.setattr(enrich_jobs, "extract", lambda j, m, p, previous=None: read.append(1) or FACTS)
    monkeypatch.setattr(sys, "argv", ["enrich_jobs.py", "--jobs", str(jobs_file), "--intelligence", str(tmp_path / "missing.json")])
    assert enrich_jobs.main() == 0
    assert read == [1]
