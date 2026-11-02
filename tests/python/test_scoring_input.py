"""Scoring reads the discovered file and the manual file, nothing else.

A job the browser keeps with `offList` (absent from current results) and an open ad only the ledger remembers must not
reach the scored output, so an old search or another country's ads cannot enter a new run's scores.
"""

import json
import sys

import pytest

import run_scoring
from match_engine import shadow


def _job(job_id, **extra):
    return {
        "jobId": job_id, "title": "Product Manager", "company": f"Company {job_id}", "location": "Niš, Serbia",
        "description": "Own the roadmap.", "jobUrl": f"https://jobs.example/{job_id}", "provider": "jobspy",
        "status": "new", **extra,
    }


@pytest.fixture
def scored(tmp_path, monkeypatch):
    """run_scoring.main() on temp files only; returns the ids and rows of the output."""
    (tmp_path / "intel.json").write_text(json.dumps({"jobFitPreferences": {}, "roleFamily": "product"}))
    jobs_file = tmp_path / "discovered_jobs.json"
    jobs_file.write_text(json.dumps({"meta": {"sourceRunId": "run"}, "jobs": [_job("found-1"), _job("found-2")]}))
    manual_file = tmp_path / "manual_jobs.json"
    manual_file.write_text(json.dumps({"jobs": [_job("manual-1", provider="manual", manualEntry=True)]}))
    # Everything beside those two files that holds other jobs: the ledger, and an older scored file with a kept row.
    (tmp_path / "job_history.json").write_text(json.dumps({"version": 1, "updatedAt": None, "jobs": {
        "ledger-only": {"firstSeen": "2026-10-01", "lastSeen": "2026-10-01", "closedAt": None, "provider": "jobspy",
                        "seenUnder": "older", "roleKey": "tc:x", "llmFacts": None, "job": _job("ledger-only")},
    }}))
    output = tmp_path / "scored_jobs.json"
    output.write_text(json.dumps({"meta": {}, "jobs": [_job("kept-row", offList=True, status="rejected")]}))
    (tmp_path / "profile.json").write_text(json.dumps({}))
    monkeypatch.setattr(run_scoring, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "llm_fit.json")
    monkeypatch.setattr(shadow, "CACHE_PATH", tmp_path / "engine.json")
    monkeypatch.setattr("confirmed_facts.load", lambda *a, **k: [])
    monkeypatch.setattr(shadow, "load_remap", lambda: {})
    monkeypatch.setattr(sys, "argv", [
        "run_scoring.py", "--intelligence", str(tmp_path / "intel.json"), "--jobs", str(jobs_file),
        "--manual", str(manual_file), "--output", str(output),
    ])
    assert run_scoring.main() == 0
    return json.loads(output.read_text(encoding="utf-8"))["jobs"]


def test_output_holds_exactly_the_discovered_and_manual_jobs(scored):
    assert sorted(j["jobId"] for j in scored) == ["found-1", "found-2", "manual-1"]


def test_no_output_row_carries_the_browser_mark(scored):
    assert not [j for j in scored if "offList" in j]
