"""Stable requirement ids across readings of the same ad (DECISIONS.md principle 9, contract section 6)."""

import json
import sys

import pytest

import enrich_jobs
from conftest import select_provider
import job_fingerprint
import requirement_frames as rf
from enrich_jobs import _previous_block, _reuse_previous, extract
from requirement_ids import assign_id, provisional_id

# These tests cover the work around a model call, not the AI budget gate (test_ai_gate.py).
pytestmark = pytest.mark.usefixtures("open_ai_budget")

AD = {"jobId": "j1", "title": "Product Manager", "company": "Acme", "location": "Remote",
      "description": "Own the roadmap. Five years of B2B SaaS product experience. SQL."}


def req(text, previous_id=None, kind="experience", importance="must", quote=None):
    return {"text": text, "kind": kind, "importance": importance, "postingQuote": quote or text,
            "previousId": previous_id}


PREVIOUS = [
    {"id": provisional_id("5+ years of B2B SaaS product management"), "text": "5+ years of B2B SaaS product management",
     "kind": "experience", "importance": "must"},
    {"id": "sql", "text": "SQL", "kind": "skill", "importance": "must"},
]


# --- code reuses the id the model points at -----------------------------------------

def test_a_named_previous_id_keeps_its_id_and_its_text():
    out = _reuse_previous([req("Five years of B2B SaaS product experience", PREVIOUS[0]["id"])], PREVIOUS)
    assert out[0]["id"] == PREVIOUS[0]["id"] and out[0]["provisional"] is True
    assert out[0]["text"] == "5+ years of B2B SaaS product management"
    assert out[0]["postingQuote"] == "Five years of B2B SaaS product experience"  # this reading's quote
    assert "previousId" not in out[0]


def test_a_reused_canonical_id_stays_canonical():
    out = _reuse_previous([req("SQL querying", "sql", kind="skill")], PREVIOUS)
    assert (out[0]["id"], out[0]["provisional"], out[0]["text"]) == ("sql", False, "SQL")


def test_an_id_not_in_the_previous_frame_is_ignored():
    out = _reuse_previous([req("Stakeholder management", "made-up-id")], PREVIOUS)
    assert out[0] == assign_id({k: v for k, v in req("Stakeholder management").items() if k != "previousId"})


def test_a_previous_id_is_used_once():
    out = _reuse_previous([req("SQL", "sql", kind="skill"), req("Advanced SQL", "sql", kind="skill")], PREVIOUS)
    assert out[0]["id"] == "sql" and out[1]["text"] == "Advanced SQL"
    assert out[1] == assign_id({k: v for k, v in req("Advanced SQL", kind="skill").items() if k != "previousId"})


def test_without_a_previous_frame_every_id_is_assigned():
    out = _reuse_previous([req("SQL", "sql", kind="skill")], None)
    assert out[0] == assign_id({k: v for k, v in req("SQL", kind="skill").items() if k != "previousId"})


# --- the prompt carries the previous frame ------------------------------------------

def test_the_prompt_lists_the_previous_frame_only_when_there_is_one(monkeypatch):
    prompts = []
    monkeypatch.setattr(enrich_jobs, "complete_json", lambda prompt, **kw: prompts.append(prompt) or {})
    extract(AD, None, "openai")
    extract(AD, None, "openai", PREVIOUS)
    assert "PREVIOUS REQUIREMENTS (an earlier" not in prompts[0]
    assert "PREVIOUS REQUIREMENTS (an earlier" in prompts[1]
    assert json.dumps(PREVIOUS[1], ensure_ascii=False) in prompts[1]
    assert "BEGIN JOB AD" in prompts[1].split("END PREVIOUS REQUIREMENTS")[1]  # before the ad: the variable tail


def test_the_previous_block_holds_ids_and_texts_only():
    block = _previous_block([{**PREVIOUS[1], "postingQuote": "SQL", "provisional": False}])
    assert "postingQuote" not in block and "provisional" not in block


# --- the store ----------------------------------------------------------------------

def test_the_frame_key_survives_a_prompt_bump(monkeypatch):
    before, fp_before = rf.frame_key(AD), job_fingerprint.job_fingerprint(AD)
    monkeypatch.setattr(job_fingerprint, "PROMPT_VERSION", job_fingerprint.PROMPT_VERSION + 1)
    assert rf.frame_key(AD) == before
    assert job_fingerprint.job_fingerprint(AD) != fp_before


def test_the_frame_key_changes_with_the_ad_text():
    assert rf.frame_key(AD) != rf.frame_key({**AD, "description": AD["description"] + " Jira."})


def test_previous_for_prefers_the_store_then_the_jobs_own_facts():
    on_job = {**AD, "llmFacts": {"requirements": [{**PREVIOUS[1], "postingQuote": "SQL", "provisional": False}]}}
    assert rf.previous_for({}, AD) == []
    assert rf.previous_for({}, on_job) == [PREVIOUS[1]]
    assert rf.previous_for({rf.frame_key(AD): PREVIOUS}, on_job) == PREVIOUS


def test_remember_keeps_the_old_frame_when_a_reading_has_no_requirements():
    frames = {rf.frame_key(AD): PREVIOUS}
    rf.remember(frames, AD, {"requirements": []})
    assert frames[rf.frame_key(AD)] == PREVIOUS
    rf.remember(frames, AD, {"requirements": [{**PREVIOUS[1], "postingQuote": "SQL"}]})
    assert frames[rf.frame_key(AD)] == [PREVIOUS[1]]


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "frames.json"
    rf.save({"k": PREVIOUS}, path)
    assert rf.load(path) == {"k": PREVIOUS}
    assert rf.load(tmp_path / "absent.json") == {}


def test_tests_never_touch_the_servers_frames_file():
    assert rf.FRAMES_PATH.name == "requirement-frames.json" and "data" not in rf.FRAMES_PATH.parts[-3:-1]


# --- enrichment feeds the frame back and stores the new one -------------------------

def test_enrichment_passes_the_stored_frame_and_stores_the_new_one(tmp_path, monkeypatch):
    jobs_file = tmp_path / "discovered_jobs.json"
    jobs_file.write_text(json.dumps({"meta": {}, "jobs": [AD]}), encoding="utf-8")
    rf.save({rf.frame_key(AD): PREVIOUS})
    seen = []
    new = [{**PREVIOUS[1], "postingQuote": "SQL", "provisional": False}]

    def fake(job, model, provider, previous=None):
        seen.append(previous)
        return {"requirements": new, "workMode": "remote", "roleTrack": "product_management",
                "seniority": "senior", "yearsRequired": 5, "_fingerprint": job_fingerprint.job_fingerprint(job)}

    monkeypatch.setattr(enrich_jobs, "extract", fake)
    monkeypatch.setattr(sys, "argv", ["enrich_jobs.py", "--jobs", str(jobs_file), "--workers", "1",
                                      "--intelligence", str(tmp_path / "none.json")])
    select_provider(tmp_path, monkeypatch, "claude-code")
    assert enrich_jobs.main() == 0
    assert seen == [PREVIOUS]
    assert rf.load() == {rf.frame_key(AD): [PREVIOUS[1]]}
