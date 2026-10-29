"""The job history ledger: what survives between discovery runs."""

import json
from datetime import datetime, timedelta, timezone

import pytest

import enrich_jobs
from conftest import select_provider
import job_history as jh
from dedupe_jobs import _crosspost_key
from job_fingerprint import job_fingerprint

# These tests cover the work around a model call, not the AI budget gate (test_ai_gate.py).
pytestmark = pytest.mark.usefixtures("open_ai_budget")

KEY = "search-a"
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def iso(days=0):
    return (T0 + timedelta(days=days)).isoformat()


def job(job_id="g1", provider="greenhouse", title="Product Manager", company="Acme", description="Own the roadmap."):
    return {"jobId": job_id, "provider": provider, "title": title, "company": company,
            "location": "Berlin", "description": description, "jobUrl": f"https://x/{job_id}"}


def facts_for(j):
    return {"workMode": "remote", "roleTrack": "product_management", "seniority": "senior",
            "yearsRequired": 5, "_fingerprint": job_fingerprint(j)}


def run(ledger, jobs, day=0, returned=None, key=KEY, previous_facts=None):
    returned = returned if returned is not None else {p: 1 for p in ("greenhouse", "lever", "ashby", "jobspy")}
    return jh.apply_run(ledger, jobs, now=iso(day), providers_returned=returned, key=key,
                        role_key=_crosspost_key, previous_facts=previous_facts)


# --- first sight and known jobs -----------------------------------------------------------------


def test_a_new_job_is_first_and_last_seen_now_with_no_facts():
    ledger = jh.empty_ledger()
    out, stats = run(ledger, [job()])
    assert (out[0]["firstSeen"], out[0]["lastSeen"], out[0]["closedAt"]) == (iso(), iso(), None)
    assert out[0]["isNew"] is True and out[0]["isClosed"] is False and "llmFacts" not in out[0]
    assert stats["new"] == 1 and stats["carriedFacts"] == 0


def test_a_known_job_keeps_firstSeen_updates_lastSeen_and_reuses_its_facts():
    ledger = jh.empty_ledger()
    j = job()
    run(ledger, [j], day=0)
    ledger["jobs"]["g1"]["llmFacts"] = facts_for(j)
    out, stats = run(ledger, [job()], day=5)
    assert (out[0]["firstSeen"], out[0]["lastSeen"]) == (iso(0), iso(5))
    assert out[0]["llmFacts"] == facts_for(j) and stats["carriedFacts"] == 1 and stats["known"] == 1
    assert out[0]["isNew"] is False  # first seen more than NEW_WINDOW_DAYS ago


def test_facts_are_dropped_when_the_ad_changed():
    ledger = jh.empty_ledger()
    j = job()
    run(ledger, [j])
    ledger["jobs"]["g1"]["llmFacts"] = facts_for(j)
    out, stats = run(ledger, [job(description="A completely different ad now.")], day=1)
    assert "llmFacts" not in out[0] and stats["changed"] == 1 and ledger["jobs"]["g1"]["llmFacts"] is None


def test_facts_from_the_file_being_replaced_seed_a_new_ledger():
    j = job()
    out, stats = run(jh.empty_ledger(), [j], previous_facts={"g1": facts_for(j)})
    assert out[0]["llmFacts"] == facts_for(j) and stats["carriedFacts"] == 1


# --- closing ------------------------------------------------------------------------------------


def seen_then_missing(provider="greenhouse", returned=None, key2=KEY, other=None):
    ledger = jh.empty_ledger()
    run(ledger, [job(provider=provider)])
    out, stats = run(ledger, other or [], day=1, returned=returned, key=key2)
    return ledger, out, stats


def test_a_board_job_that_is_no_longer_listed_is_closed_and_still_emitted_as_closed():
    ledger, out, stats = seen_then_missing()
    assert ledger["jobs"]["g1"]["closedAt"] == iso(1) and stats["closed"] == 1
    assert [(o["jobId"], o["isClosed"], o["isNew"], o["closedAt"]) for o in out] == [("g1", True, False, iso(1))]


def test_a_linkedin_job_missing_from_a_run_is_not_closed():
    ledger, out, stats = seen_then_missing(provider="jobspy")
    assert ledger["jobs"]["g1"]["closedAt"] is None and stats["closed"] == 0 and out == []


def test_a_provider_that_returned_nothing_closes_nothing():
    ledger, _, stats = seen_then_missing(returned={"greenhouse": 0})
    assert ledger["jobs"]["g1"]["closedAt"] is None and stats["closed"] == 0


def test_a_changed_search_closes_nothing():
    ledger, _, stats = seen_then_missing(key2="search-b")
    assert ledger["jobs"]["g1"]["closedAt"] is None and stats["closed"] == 0


def test_a_role_still_listed_under_another_copy_is_not_closed():
    other = job(job_id="g2", provider="lever")  # same title and company, different posting
    ledger, _, stats = seen_then_missing(other=[other])
    assert ledger["jobs"]["g1"]["closedAt"] is None and stats["closed"] == 0


def test_a_closed_job_that_returns_is_reopened():
    ledger, _, _ = seen_then_missing()
    out, stats = run(ledger, [job()], day=2)
    assert out[0]["closedAt"] is None and out[0]["isClosed"] is False and stats["reopened"] == 1


def test_closed_jobs_leave_the_output_after_two_weeks_and_the_ledger_after_ninety_days():
    ledger, _, _ = seen_then_missing()
    out, _ = run(ledger, [], day=1 + jh.CLOSED_KEEP_DAYS + 1)
    assert out == [] and "g1" in ledger["jobs"]
    run(ledger, [], day=1 + jh.PRUNE_AFTER_DAYS + 1)
    assert "g1" not in ledger["jobs"]


def test_isNew_covers_the_first_days_only():
    ledger = jh.empty_ledger()
    run(ledger, [job()], day=0)
    assert run(ledger, [job()], day=jh.NEW_WINDOW_DAYS)[0][0]["isNew"] is True
    assert run(ledger, [job()], day=jh.NEW_WINDOW_DAYS + 1)[0][0]["isNew"] is False


# --- the file ------------------------------------------------------------------------------------


def test_a_corrupt_ledger_is_set_aside_not_overwritten(tmp_path):
    path = tmp_path / "job_history.json"
    path.write_text("{not json", encoding="utf-8")
    assert jh.load(path) == jh.empty_ledger()
    assert [p.name for p in tmp_path.glob("job_history.json.corrupt-*")] and not path.exists()


def test_save_then_load_round_trips(tmp_path):
    ledger = jh.empty_ledger()
    run(ledger, [job()])
    path = tmp_path / "job_history.json"
    jh.save(path, ledger)
    assert jh.load(path)["jobs"]["g1"]["firstSeen"] == iso()


# --- enrichment checks the ledger first ----------------------------------------------------------


def write_jobs(path, jobs):
    path.write_text(json.dumps({"meta": {}, "jobs": jobs}), encoding="utf-8")


def test_the_fingerprint_is_defined_once():
    assert enrich_jobs._fingerprint is job_fingerprint


def test_enrichment_reuses_ledger_facts_and_calls_the_model_only_for_new_ads(tmp_path, monkeypatch):
    known, fresh = job("g1"), job("g2", title="Group Product Manager")
    ledger = jh.empty_ledger()
    run(ledger, [known, fresh])
    ledger["jobs"]["g1"]["llmFacts"] = facts_for(known)
    jobs_file = tmp_path / "discovered_jobs.json"
    jh.save(jh.ledger_path(jobs_file), ledger)
    write_jobs(jobs_file, [known, fresh])  # as discovery writes it: no facts on the records

    asked = []
    monkeypatch.setattr(enrich_jobs, "extract", lambda j, model, provider, previous=None: (asked.append(j["jobId"]), facts_for(j))[1])
    monkeypatch.setattr("sys.argv", ["enrich_jobs.py", "--jobs", str(jobs_file), "--workers", "1",
                                       "--intelligence", str(tmp_path / "none.json")])
    select_provider(tmp_path, monkeypatch, "claude-code")
    assert enrich_jobs.main() == 0

    assert asked == ["g2"]  # the known ad was not sent to the model
    written = {j["jobId"]: j for j in json.loads(jobs_file.read_text())["jobs"]}
    assert written["g1"]["llmFacts"] == facts_for(known) and "llmFacts" in written["g2"]
    stored = jh.load(jh.ledger_path(jobs_file))["jobs"]
    assert stored["g2"]["llmFacts"]["_fingerprint"] == job_fingerprint(fresh)  # new facts reach the ledger


def test_a_second_enrichment_run_makes_no_calls(tmp_path, monkeypatch, capsys):
    j = job()
    ledger = jh.empty_ledger()
    run(ledger, [j])
    jobs_file = tmp_path / "discovered_jobs.json"
    jh.save(jh.ledger_path(jobs_file), ledger)
    write_jobs(jobs_file, [j])
    calls = []
    monkeypatch.setattr(enrich_jobs, "extract", lambda x, m, p, previous=None: (calls.append(1), facts_for(x))[1])
    monkeypatch.setattr("sys.argv", ["enrich_jobs.py", "--jobs", str(jobs_file), "--workers", "1",
                                       "--intelligence", str(tmp_path / "none.json")])
    select_provider(tmp_path, monkeypatch, "claude-code")
    enrich_jobs.main()
    write_jobs(jobs_file, [j])  # the next discovery run rewrites the file without facts
    select_provider(tmp_path, monkeypatch, "claude-code")
    enrich_jobs.main()
    assert len(calls) == 1
    assert "cached 1 (1 from the ledger)" in capsys.readouterr().out


# --- closed jobs are not candidates for bulk actions ---------------------------------------------


def tailor_args(**kw):
    import argparse

    base = dict(job_id=None, job_ids=None, apply_only=False, priority=None, apply_recommendation=None, limit=10)
    return argparse.Namespace(**{**base, **kw})


def scored(job_id, closed=False, priority="P1", apply="Apply"):
    return {"jobId": job_id, "priority": priority, "applyRecommendation": apply, "isClosed": closed}


def test_a_bulk_tailor_run_skips_closed_jobs_but_a_job_picked_by_id_is_still_tailored():
    import run_tailor

    jobs = [scored("open1"), scored("gone", closed=True), scored("open2")]
    for args in (tailor_args(priority="P1"), tailor_args(apply_only=True), tailor_args()):
        assert [j["jobId"] for j in run_tailor._select_jobs(jobs, args)] == ["open1", "open2"]
    # Closed jobs do not use up the limit either.
    assert [j["jobId"] for j in run_tailor._select_jobs([scored("gone", closed=True), scored("open1")], tailor_args(limit=1))] == ["open1"]
    assert [j["jobId"] for j in run_tailor._select_jobs(jobs, tailor_args(job_id="gone"))] == ["gone"]
    assert [j["jobId"] for j in run_tailor._select_jobs(jobs, tailor_args(job_ids="gone,open1"))] == ["open1", "gone"]


def test_the_quality_audit_sample_skips_closed_jobs():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "python" / "quality_audit" / "audit_utils.py"
    spec = importlib.util.spec_from_file_location("_audit_utils", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    picked = module.pick_sample_jobs([{**scored("gone", closed=True), "matchScore": 99}, {**scored("open1"), "matchScore": 70}])
    assert [j["jobId"] for j in picked] == ["open1"]


# --- a throttled fetch must not degrade what is known --------------------------------------------

FULL = "Own the product roadmap and discovery for our platform. " * 8


def test_a_thin_description_does_not_replace_a_fuller_one_so_the_facts_survive():
    ledger = jh.empty_ledger()
    full = job(description=FULL)
    run(ledger, [full])
    ledger["jobs"]["g1"]["llmFacts"] = facts_for(full)
    out, stats = run(ledger, [job(description="")], day=1)  # LinkedIn throttled the detail fetch
    assert out[0]["description"] == FULL and out[0]["llmFacts"] == facts_for(full)
    assert stats["keptFullerDescription"] == 1 and stats["changed"] == 0


def test_a_fuller_description_replaces_a_thin_one_and_the_ad_is_read_again():
    ledger = jh.empty_ledger()
    thin = job(description="")
    run(ledger, [thin])
    ledger["jobs"]["g1"]["llmFacts"] = facts_for(thin)
    out, stats = run(ledger, [job(description=FULL)], day=1)
    assert out[0]["description"] == FULL and "llmFacts" not in out[0] and stats["changed"] == 1


def test_a_really_changed_full_description_is_still_read_again():
    ledger = jh.empty_ledger()
    first = job(description=FULL)
    run(ledger, [first])
    ledger["jobs"]["g1"]["llmFacts"] = facts_for(first)
    out, stats = run(ledger, [job(description=FULL + "New responsibility: own pricing.")], day=1)
    assert "llmFacts" not in out[0] and stats["changed"] == 1 and stats["keptFullerDescription"] == 0


# --- an install that already had jobs: the first ledger run ---------------------------------------


def test_jobs_inherited_from_the_replaced_file_are_not_new_but_truly_new_ones_are():
    ledger = jh.empty_ledger()
    earlier = iso(-1)
    out, stats = run_seeded(ledger, [job("old"), job("fresh", title="Lead Product Manager")], {"old": earlier})
    by_id = {o["jobId"]: o for o in out}
    assert by_id["old"]["firstSeen"] == earlier and by_id["old"]["isNew"] is False
    assert by_id["fresh"]["firstSeen"] == iso() and by_id["fresh"]["isNew"] is True
    # On the next run it is still not new: it stays seeded.
    assert run_seeded(ledger, [job("old")], {}, day=1)[0][0]["isNew"] is False


def run_seeded(ledger, jobs, seen_before, day=0):
    return jh.apply_run(ledger, jobs, now=iso(day), providers_returned={"greenhouse": 1}, key=KEY,
                        role_key=_crosspost_key, seen_before=seen_before)
