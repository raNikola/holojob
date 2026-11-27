"""The owner's pasted (package 12) or employer-refreshed (package 13) ad text is THE ad text for every step that reads a description.

One rule, one test per step: discovery filters, the facts fingerprint kept in the ledger, the empty-description retry, enrichment,
Fit 3 planning, engine fill and the ledger-ad extraction. The scraped text stays in the ledger and the job list; the overlay is never
written into either. Synthetic data in temp dirs only; the overlay path is derived from the job list's path, never the real data dir.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

import classify_new
import description_overlay as overlay
import employer_refresh as er
import engine_missing
import enrich_jobs
import extract_ledger_ads
import job_history as jh
import pasted_descriptions as pd
from conftest import select_provider
from dedupe_jobs import _crosspost_key
from providers import joberty_provider, role_filter

THIN = "Product role."
PASTED = "You will act as the Product Owner of our platform and own the roadmap and the delivery for our customers every week."
EMPLOYER = PASTED + " The employer's own page adds the team, the stack and the way of working."
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
FACTS = {"workMode": "remote", "roleTrack": "product_management", "seniority": "senior", "yearsRequired": 5}


def ad(job_id="j1", description=THIN, **extra):
    return {"jobId": job_id, "provider": "jobspy", "title": "Implementation Lead", "company": "Acme", "location": "Berlin",
            "description": description, "jobUrl": f"https://x/{job_id}", **extra}


def jobs_file(tmp_path, jobs):
    path = tmp_path / "discovered_jobs.json"
    path.write_text(json.dumps({"jobs": jobs}))
    return path


# --- the one function -------------------------------------------------------------------------------------------------------------------------

def test_effective_never_mutates_and_leaves_a_hand_entered_job_alone():
    ads = {"j1": {"text": PASTED, "source": "employer"}}
    original = ad()
    view = overlay.effective(original, ads)
    assert view["description"] == PASTED and view["descriptionSource"] == "employer" and view["descriptionStatus"] == "complete"
    assert original["description"] == THIN and "descriptionSource" not in original
    assert overlay.effective(ad("j2"), ads)["description"] == THIN
    manual = ad(manualEntry=True)
    assert overlay.effective(manual, ads) is manual


# --- discovery: the filters and text rules ---------------------------------------------------------------------------------------------------

def test_a_filter_reads_the_owner_text_not_the_thin_scrape():
    job = ad()
    try:
        assert role_filter.role_drop_reason(job["title"], "", (), role_filter.description_of(job)) == "title_not_matched"
        role_filter.use_overlay({"j1": {"text": PASTED}})
        assert role_filter.role_drop_reason(job["title"], "", (), role_filter.description_of(job)) is None
        assert role_filter.description_of(ad("j2")) == THIN
    finally:
        role_filter.use_overlay(None)


def test_joberty_asks_no_detail_for_an_ad_with_the_owner_text(tmp_path):
    missing = tmp_path / "none.json"
    try:
        role_filter.use_overlay({"j1": {"text": PASTED}})
        assert "j1" in joberty_provider.known_ids(missing)
    finally:
        role_filter.use_overlay(None)
    assert "j1" not in joberty_provider.known_ids(missing)


# --- the ledger: facts fingerprint and the empty-description retry --------------------------------------------------------------------------

def scan(ledger, jobs, day, pasted=None):
    return jh.apply_run(ledger, jobs, now=(T0 + timedelta(days=day)).isoformat(), providers_returned={"jobspy": len(jobs)},
                        key="k", role_key=_crosspost_key, pasted=pasted)


def test_facts_read_on_the_owner_text_survive_the_next_scan():
    ads = {"j1": {"text": PASTED}}
    ledger = jh.empty_ledger()
    scan(ledger, [ad()], 0, ads)
    ledger["jobs"]["j1"]["llmFacts"] = {**FACTS, "_fingerprint": jh.job_fingerprint(overlay.effective(ad(), ads))}  # what enrichment stores
    _, stats = scan(ledger, [ad()], 1, ads)
    assert stats["carriedFacts"] == 1 and stats["changed"] == 0, "a rescan must not throw the paid read away"
    assert ledger["jobs"]["j1"]["job"]["description"] == THIN, "the scraped text stays in the ledger"
    _, without = scan(ledger, [ad()], 2, None)  # the paste is gone: the ad is the scraped one again, so its facts no longer fit
    assert without["changed"] == 1


def test_an_ad_with_the_owner_text_leaves_the_empty_description_retry():
    ledger = jh.empty_ledger()
    scan(ledger, [ad(description="")], 0)
    scan(ledger, [ad(description="")], 1)
    assert ledger["jobs"]["j1"]["descriptionRetries"] == 1
    _, stats = scan(ledger, [ad(description="")], 2, {"j1": {"text": PASTED}})
    entry = ledger["jobs"]["j1"]
    assert "descriptionRetries" not in entry and "descriptionGaveUp" not in entry
    assert (stats["descriptionRetried"], stats["descriptionGaveUp"], stats["descriptionEmptyNew"]) == (0, 0, 0)
    assert entry["job"]["description"] == ""


# --- enrichment ----------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.usefixtures("open_ai_budget")
def test_enrichment_reads_the_owner_text_and_writes_the_scraped_row_back(tmp_path, monkeypatch):
    path = jobs_file(tmp_path, [ad()])
    pd.put("j1", PASTED, pd.path_for(path))
    seen = []

    def fake(job, model, provider, previous=None, **kw):
        seen.append(job["description"])
        return {**FACTS, "_fingerprint": enrich_jobs.job_fingerprint(job)}

    monkeypatch.setattr(enrich_jobs, "extract", fake)
    monkeypatch.setattr(sys, "argv", ["enrich_jobs.py", "--jobs", str(path), "--intelligence", str(tmp_path / "none.json")])
    select_provider(tmp_path, monkeypatch, "claude-code")
    assert enrich_jobs.main() == 0
    assert seen == [PASTED]
    saved = json.loads(path.read_text())["jobs"][0]
    assert saved["description"] == THIN, "the overlay is never written into the job list"
    assert saved["llmFacts"]["_fingerprint"] == enrich_jobs.job_fingerprint(overlay.effective(ad(), {"j1": {"text": PASTED}}))
    seen.clear()
    assert enrich_jobs.main() == 0 and seen == [], "the facts fit the effective text: nothing is read twice"


# --- Fit 3 planning, engine fill, ledger-ad extraction ---------------------------------------------------------------------------------------------

def test_fit3_planning_sees_the_owner_text(tmp_path):
    path = jobs_file(tmp_path, [ad()])
    pd.put("j1", PASTED, pd.path_for(path))
    rows = classify_new.scoring_rows(path, tmp_path / "manual.json", tmp_path / "kept.json")
    assert [r["description"] for r in rows if r["jobId"] == "j1"] == [PASTED]
    assert json.loads(path.read_text())["jobs"][0]["description"] == THIN


def test_engine_fill_reads_ledger_ads_with_the_owner_text(tmp_path):
    ledger = jh.empty_ledger()
    scan(ledger, [ad()], 0)
    jh.save(jh.ledger_path(tmp_path / "discovered_jobs.json"), ledger)
    scored = tmp_path / "scored_jobs.json"
    assert engine_missing.ledger_rows(scored, set(), {"j1"})[0]["description"] == THIN
    pd.put("j1", EMPLOYER, pd.path_for(scored), source="employer")
    row = engine_missing.ledger_rows(scored, set(), {"j1"})[0]
    assert row["description"] == EMPLOYER and row["descriptionSource"] == "employer"


def test_ledger_ad_extraction_selects_and_reads_the_owner_text():
    stored = ad()
    facts_on_scraped = {"_fingerprint": enrich_jobs.job_fingerprint(stored)}
    ledger = {"jobs": {"j1": {"job": stored, "llmFacts": facts_on_scraped}}}
    rows, counts = extract_ledger_ads.pending_of(ledger, {"j1"})
    assert rows == [] and counts["alreadyRead"] == 1
    rows, counts = extract_ledger_ads.pending_of(ledger, {"j1"}, {"j1": {"text": PASTED}})
    assert [r["description"] for r in rows] == [PASTED] and counts["alreadyRead"] == 0, "facts of the thin text are stale for the owner's text"


# --- history: a later paste never silently overwrites an earlier one -----------------------------------------------------------------------------------

def test_a_second_text_keeps_the_first_as_previous_one_level_and_repeats_do_not_churn(tmp_path):
    path = tmp_path / "pasted.json"
    pd.put("j1", PASTED, path, now="2026-11-27T10:00:00+00:00")
    pd.put("j1", PASTED, path, now="2026-11-27T11:00:00+00:00")  # the same text again
    assert "previous" not in pd.load(path)["j1"]
    pd.put("j1", EMPLOYER, path, now="2026-11-27T12:00:00+00:00", source="employer")
    entry = pd.load(path)["j1"]
    assert entry["text"] == EMPLOYER and entry["previous"] == {"text": PASTED, "pastedAt": "2026-11-27T10:00:00+00:00", "source": "pasted"}
    third = EMPLOYER + " One more paragraph about the interview process."
    pd.put("j1", third, path, now="2026-11-27T13:00:00+00:00")
    entry = pd.load(path)["j1"]
    assert entry["previous"]["text"] == EMPLOYER and "previous" not in entry["previous"], "one level only"


def test_a_failed_rescore_puts_back_the_exact_entry_with_its_history(tmp_path):
    path = tmp_path / "pasted.json"
    pd.put("j1", PASTED, path, now="2026-11-27T10:00:00+00:00")
    pd.put("j1", EMPLOYER, path, now="2026-11-27T11:00:00+00:00", source="employer")
    before = pd.load(path)["j1"]
    pd.put("j1", EMPLOYER + " Changed.", path)
    pd.restore("j1", before, path)
    assert pd.load(path)["j1"] == before
    pd.restore("j1", None, path)
    assert pd.load(path) == {}


def test_the_employer_diff_runs_against_the_text_the_ad_has_now(tmp_path):
    from types import SimpleNamespace

    page = f'<html><script type="application/ld+json">{json.dumps({"@type": "JobPosting", "description": EMPLOYER})}</script></html>'
    ledger = jh.empty_ledger()
    scan(ledger, [ad()], 0)
    jh.save(tmp_path / "job_history.json", ledger)
    jobs = tmp_path / "discovered_jobs.json"
    proposals = tmp_path / "employer_refresh.json"
    fetch = lambda _url: SimpleNamespace(url="https://employer.example/1", html=page)  # noqa: E731
    _, first = er.propose("j1", "https://employer.example/1", jobs=jobs, path=proposals, fetch_page=fetch)
    assert first["against"] == "scraped" and first["replacesText"] is False
    pd.put("j1", PASTED, pd.path_for(jobs))
    _, second = er.propose("j1", "https://employer.example/1", jobs=jobs, path=proposals, fetch_page=fetch)
    assert second["against"] == "pasted" and second["replacesText"] is True and not second["identical"]
    assert second["originalChars"] == len(PASTED)
