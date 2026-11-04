"""The job history ledger: what survives between discovery runs."""

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
import requests

import enrich_jobs
from conftest import fail_replacing, select_provider
import job_history as jh
from dedupe_jobs import _crosspost_key
from job_fingerprint import job_fingerprint
from providers import ashby_provider, greenhouse_provider, lever_provider

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


def run(ledger, jobs, day=0, returned=None, key=KEY, previous_facts=None, evidence=None):
    returned = returned if returned is not None else {p: 1 for p in ("greenhouse", "lever", "ashby", "jobspy")}
    return jh.apply_run(ledger, jobs, now=iso(day), providers_returned=returned, key=key,
                        role_key=_crosspost_key, previous_facts=previous_facts, board_evidence=evidence)


def proven(*boards, provider="greenhouse"):
    """A complete fetch of these boards (None: an ad with no board name) that listed nothing but what the run found."""
    return {provider: {board: {"complete": True, "listed": set()} for board in (boards or (None,))}}


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


def seen_then_missing(provider="greenhouse", returned=None, key2=KEY, other=None, evidence=None):
    ledger = jh.empty_ledger()
    run(ledger, [job(provider=provider)])
    out, stats = run(ledger, other or [], day=1, returned=returned, key=key2, evidence=evidence)
    return ledger, out, stats


def closed_after_two_misses():
    ledger, _, _ = seen_then_missing(evidence=proven())
    out, stats = run(ledger, [], day=2, evidence=proven())
    return ledger, out, stats


def test_a_board_job_that_is_no_longer_listed_is_closed_after_two_complete_fetches_and_still_emitted_as_closed():
    ledger, out, stats = seen_then_missing(evidence=proven())
    assert ledger["jobs"]["g1"]["closedAt"] is None and stats["closed"] == 0 and stats["absent"] == 1
    assert [(o["jobId"], o["isClosed"], o["isAbsent"], o["absentSince"]) for o in out] == [("g1", False, True, iso(1))]
    out, stats = run(ledger, [], day=2, evidence=proven())
    assert ledger["jobs"]["g1"]["closedAt"] == iso(2) and stats["closed"] == 1
    assert [(o["jobId"], o["isClosed"], o["isNew"], o["closedAt"], o["closedAfterChecks"]) for o in out] == [("g1", True, False, iso(2), 2)]


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
    ledger, _, _ = closed_after_two_misses()
    out, stats = run(ledger, [job()], day=3)
    assert out[0]["closedAt"] is None and out[0]["isClosed"] is False and stats["reopened"] == 1
    assert "absentRuns" not in ledger["jobs"]["g1"] and "isAbsent" not in out[0]


def test_closed_jobs_leave_the_output_after_two_weeks_and_the_ledger_after_ninety_days():
    ledger, _, _ = closed_after_two_misses()
    out, _ = run(ledger, [], day=2 + jh.CLOSED_KEEP_DAYS + 1)
    assert out == [] and "g1" in ledger["jobs"]
    run(ledger, [], day=2 + jh.PRUNE_AFTER_DAYS + 1)
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


def test_a_failed_save_keeps_the_previous_ledger_and_leaves_no_temp_file(tmp_path, monkeypatch):
    (tmp_path / "jobs").mkdir()
    path = tmp_path / "jobs" / "job_history.json"
    path.write_text('{"previous": true}', encoding="utf-8")
    temps = fail_replacing(monkeypatch, path)

    with pytest.raises(OSError, match="disk full"):
        jh.save(path, jh.empty_ledger())

    assert temps and temps[0].endswith(".tmp")
    assert path.read_text(encoding="utf-8") == '{"previous": true}'
    assert [p.name for p in path.parent.iterdir()] == ["job_history.json"]


def test_a_failed_enrichment_write_keeps_the_previous_jobs_file_and_leaves_no_temp_file(tmp_path, monkeypatch):
    j = job()
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    jobs_file = jobs_dir / "discovered_jobs.json"
    write_jobs(jobs_file, [j])
    before = jobs_file.read_bytes()
    monkeypatch.setattr(enrich_jobs, "extract", lambda j, model, provider, previous=None: facts_for(j))
    monkeypatch.setattr("sys.argv", ["enrich_jobs.py", "--jobs", str(jobs_file), "--workers", "1",
                                       "--intelligence", str(tmp_path / "none.json")])
    select_provider(tmp_path, monkeypatch, "claude-code")
    temps = fail_replacing(monkeypatch, jobs_file)

    with pytest.raises(OSError, match="disk full"):
        enrich_jobs.main()

    assert temps and temps[0].endswith(".tmp")
    assert jobs_file.read_bytes() == before
    assert [p.name for p in jobs_dir.iterdir()] == ["discovered_jobs.json"]


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


# --- a failed board closes nothing --------------------------------------------------------------


def board_job(job_id, board, provider="greenhouse", key_title=None):
    return {**job(job_id, provider=provider, title=key_title or f"Product Manager {job_id}"), "source": board}


def two_boards(provider="greenhouse"):
    """A ledger holding one open ad on board "good" and one on board "bad", both with stored facts."""
    ledger = jh.empty_ledger()
    jobs = [board_job("g1", "good", provider), board_job("b1", "bad", provider)]
    run(ledger, jobs, day=0)
    ledger["jobs"]["b1"]["llmFacts"] = facts_for(jobs[1])
    return ledger, jobs


def run_failed(ledger, jobs, failed, day=1, returned=None, key=KEY, evidence=None):
    return jh.apply_run(ledger, jobs, now=iso(day), providers_returned=returned or {"greenhouse": 1}, key=key,
                        role_key=_crosspost_key, failed_boards=failed, board_evidence=evidence)


def test_a_failed_board_changes_nothing_while_another_board_succeeds():
    ledger, jobs = two_boards()
    before = copy.deepcopy(ledger["jobs"]["b1"])
    out, stats = run_failed(ledger, [jobs[0]], {"greenhouse": {"bad"}})
    assert ledger["jobs"]["b1"] == before, "the failed board's ledger entry must not change at all"
    assert stats["closed"] == 0 and stats["keptFailedBoard"] == 1
    # Still in the file the scorer reads, still open, with what enrichment already learned.
    held = next(j for j in out if j["jobId"] == "b1")
    assert held["isClosed"] is False and held["closedAt"] is None and held["lastSeen"] == iso(0)
    assert held["llmFacts"] == facts_for(jobs[1])


def test_without_the_fix_signal_the_same_run_would_close_the_ad():
    """The bug this guards against: other boards succeed, so the provider count is above zero."""
    ledger, jobs = two_boards()
    run_failed(ledger, [jobs[0]], None, evidence=proven("good", "bad"))
    out, stats = run_failed(ledger, [jobs[0]], None, day=2, evidence=proven("good", "bad"))
    assert stats["closed"] == 1 and ledger["jobs"]["b1"]["closedAt"] == iso(2)
    assert next(j for j in out if j["jobId"] == "b1")["isClosed"] is True


def test_a_successful_board_still_closes_its_absent_ads_while_another_board_failed():
    ledger, jobs = two_boards()
    gone = board_job("g2", "good")
    run(ledger, [*jobs, gone], day=0)
    run_failed(ledger, [jobs[0]], {"greenhouse": {"bad"}}, evidence=proven("good"))
    out, stats = run_failed(ledger, [jobs[0]], {"greenhouse": {"bad"}}, day=2, evidence=proven("good"))
    assert stats["closed"] == 1 and ledger["jobs"]["g2"]["closedAt"] == iso(2)
    assert ledger["jobs"]["b1"]["closedAt"] is None


def test_a_provider_returning_no_ads_never_mass_closes():
    ledger, jobs = two_boards()
    for failed in (None, {}, {"greenhouse": {"bad"}}, {"greenhouse": {"good", "bad"}}):
        _, stats = run_failed(ledger, [], failed, returned={"greenhouse": 0})
        assert stats["closed"] == 0
    assert all(entry["closedAt"] is None for entry in ledger["jobs"].values())


def test_a_provider_that_failed_before_naming_a_board_holds_all_its_ads():
    ledger, jobs = two_boards()
    out, stats = run_failed(ledger, [], {"greenhouse": None}, returned={"greenhouse": 0})
    assert stats["closed"] == 0 and {j["jobId"] for j in out} == {"g1", "b1"}


def test_an_entry_with_no_board_name_is_held_when_its_provider_has_a_failed_board():
    ledger, jobs = two_boards()
    del ledger["jobs"]["b1"]["job"]["source"]
    _, stats = run_failed(ledger, [jobs[0]], {"greenhouse": {"other"}})
    assert stats["closed"] == 0 and ledger["jobs"]["b1"]["closedAt"] is None


def test_a_failed_boards_ad_is_not_held_after_the_search_changed_or_when_listed_under_another_copy():
    ledger, jobs = two_boards()
    out, _ = run_failed(ledger, [jobs[0]], {"greenhouse": {"bad"}}, key="search-b")
    assert "b1" not in {j["jobId"] for j in out}  # as for any ad of another search

    ledger, jobs = two_boards()
    copy_elsewhere = {**board_job("l9", "acme", "lever"), "title": jobs[1]["title"]}
    out, stats = run_failed(ledger, [jobs[0], copy_elsewhere], {"greenhouse": {"bad"}})
    assert "b1" not in {j["jobId"] for j in out} and stats["keptFailedBoard"] == 0
    assert ledger["jobs"]["b1"]["closedAt"] is None


@pytest.mark.parametrize("provider", ["jobspy", "infostud", "workable", "joberty"])
def test_search_based_providers_are_untouched_by_a_failed_board(provider):
    ledger, jobs = two_boards(provider)
    for failed in (None, {provider: {"bad"}}, {provider: None}):
        out, stats = run_failed(ledger, [jobs[0]], failed, returned={provider: 1})
        assert stats["closed"] == 0 and stats["keptFailedBoard"] == 0
        assert {j["jobId"] for j in out} == {"g1"}  # missing from a search: neither closed nor carried


def greenhouse_posting(pid):
    return {"id": pid, "title": "Product Manager", "absolute_url": f"https://x/{pid}", "location": {"name": "Remote"},
            "content": "Own the roadmap."}


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code, self.body = status, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self.body


def provider_with(monkeypatch, name, answers):
    """A real board provider with two boards, "good" and "bad", against a fake HTTP layer."""
    module = {"greenhouse": greenhouse_provider, "lever": lever_provider, "ashby": ashby_provider}[name]
    monkeypatch.setattr(module.requests, "get", lambda url, **kw: answers("bad" if "bad" in url else "good", url))
    if name == "greenhouse":
        provider = greenhouse_provider.GreenhouseProvider()
        provider._load_boards = lambda: [{"company": "Good", "board": "good"}, {"company": "Bad", "board": "bad"}]
    else:
        provider = {"lever": lever_provider.LeverProvider, "ashby": ashby_provider.AshbyProvider}[name]()
        provider._load_companies = lambda: ["good", "bad"]
    return provider


GOOD_BODY = {
    "greenhouse": {"jobs": [greenhouse_posting(1)]},
    "ashby": {"jobs": [{"title": "Product Manager", "jobUrl": "https://x/1", "location": "Remote",
                        "descriptionPlain": "Own the roadmap."}]},
    "lever": [{"text": "Product Manager", "hostedUrl": "https://x/1", "descriptionPlain": "Own the roadmap.",
               "categories": {"location": "Remote"}}],
}


def fetch(provider):
    return provider.fetch_jobs(["product manager"], ["Remote"], ["remote"], "Serbia")


@pytest.mark.parametrize("name", ["greenhouse", "lever", "ashby"])
def test_a_board_that_raises_is_named_and_the_others_still_return_their_jobs(monkeypatch, name):
    def answers(board, url):
        if board == "bad":
            raise requests.ConnectionError("boom")
        return FakeResponse(body=GOOD_BODY[name])

    provider = provider_with(monkeypatch, name, answers)
    assert [j["source"] for j in fetch(provider)] == ["good"]
    assert provider.last_outcome.boards_failed == ["bad"]


@pytest.mark.parametrize("name", ["greenhouse", "lever", "ashby"])
@pytest.mark.parametrize("bad", [FakeResponse(500), FakeResponse(200, {"unexpected": True}), FakeResponse(200, "text")],
                         ids=["http-500", "no-jobs-list", "not-json-shape"])
def test_a_board_with_an_error_status_or_an_unreadable_answer_is_failed_not_empty(monkeypatch, name, bad):
    provider = provider_with(monkeypatch, name, lambda board, url: bad if board == "bad" else FakeResponse(body=GOOD_BODY[name]))
    fetch(provider)
    assert provider.last_outcome.boards_failed == ["bad"]


def test_lever_counts_a_404_on_both_hosts_as_failed_and_still_tries_the_eu_host(monkeypatch):
    def answers(board, url):
        if board == "bad":
            return FakeResponse(404)
        return FakeResponse(body=GOOD_BODY["lever"]) if "api.eu." in url else FakeResponse(404)

    provider = provider_with(monkeypatch, "lever", answers)
    assert [j["source"] for j in fetch(provider)] == ["good"]
    assert provider.last_outcome.boards_failed == ["bad"]


@pytest.mark.parametrize("name", ["greenhouse", "ashby", "lever"])
def test_a_board_that_really_is_empty_is_not_failed(monkeypatch, name):
    empty = [] if name == "lever" else {"jobs": []}
    provider = provider_with(monkeypatch, name, lambda board, url: FakeResponse(body=empty))
    assert fetch(provider) == [] and provider.last_outcome.boards_failed == []


def test_from_a_failing_board_to_the_ledger_nothing_of_that_board_closes(monkeypatch):
    def answers(board, url):
        if board == "bad":
            raise requests.Timeout("slow")
        return FakeResponse(body=GOOD_BODY["greenhouse"])

    ledger = jh.empty_ledger()
    run(ledger, [board_job("b1", "bad")], day=0)
    provider = provider_with(monkeypatch, "greenhouse", answers)
    jobs = fetch(provider)
    _, stats = run_failed(ledger, jobs, {"greenhouse": set(provider.last_outcome.boards_failed)}, returned={"greenhouse": len(jobs)})
    assert stats["closed"] == 0 and ledger["jobs"]["b1"]["closedAt"] is None


# --- a board that answers with no jobs holds its ads ---------------------------------------------


def run_empty(ledger, jobs, empty, day=1, returned=None, failed=None, key=KEY, evidence=None):
    return jh.apply_run(ledger, jobs, now=iso(day), providers_returned=returned or {"greenhouse": 1}, key=key,
                        role_key=_crosspost_key, failed_boards=failed, empty_boards=empty, board_evidence=evidence)


def test_an_empty_board_holds_its_ads_while_another_board_returns_jobs():
    ledger, jobs = two_boards()
    before = copy.deepcopy(ledger["jobs"]["b1"])
    out, stats = run_empty(ledger, [jobs[0]], {"greenhouse": {"bad"}})
    assert ledger["jobs"]["b1"] == before, "an empty board's ledger entry must not change"
    assert stats["closed"] == 0 and stats["keptEmptyBoard"] == 1 and stats["keptFailedBoard"] == 0
    held = next(j for j in out if j["jobId"] == "b1")
    assert held["isClosed"] is False and held["closedAt"] is None and held["lastSeen"] == iso(0)
    assert held["llmFacts"] == facts_for(jobs[1])


def test_a_non_empty_board_still_closes_its_absent_ads_while_another_board_is_empty():
    ledger, jobs = two_boards()
    gone = board_job("g2", "good")
    run(ledger, [*jobs, gone], day=0)
    run_empty(ledger, [jobs[0]], {"greenhouse": {"bad"}}, evidence=proven("good"))
    out, stats = run_empty(ledger, [jobs[0]], {"greenhouse": {"bad"}}, day=2, evidence=proven("good"))
    assert stats["closed"] == 1 and ledger["jobs"]["g2"]["closedAt"] == iso(2)
    assert next(j for j in out if j["jobId"] == "g2")["isClosed"] is True
    assert ledger["jobs"]["b1"]["closedAt"] is None


def test_all_boards_empty_never_mass_closes_and_keeps_every_ad():
    ledger, _ = two_boards()
    out, stats = run_empty(ledger, [], {"greenhouse": {"good", "bad"}}, returned={"greenhouse": 0})
    assert stats["closed"] == 0 and stats["keptEmptyBoard"] == 2
    assert {j["jobId"] for j in out} == {"g1", "b1"} and not any(j["isClosed"] for j in out)


def test_a_failed_board_and_an_empty_board_in_one_run_are_counted_apart():
    ledger, jobs = two_boards()
    third = board_job("e1", "empty")
    run(ledger, [*jobs, third], day=0)
    _, stats = run_empty(ledger, [jobs[0]], {"greenhouse": {"empty"}}, failed={"greenhouse": {"bad"}})
    assert (stats["closed"], stats["keptFailedBoard"], stats["keptEmptyBoard"]) == (0, 1, 1)


def test_an_empty_boards_ad_is_not_held_after_the_search_changed():
    ledger, jobs = two_boards()
    out, stats = run_empty(ledger, [jobs[0]], {"greenhouse": {"bad"}}, key="search-b")
    assert "b1" not in {j["jobId"] for j in out} and stats["keptEmptyBoard"] == 0


@pytest.mark.parametrize("provider", ["jobspy", "infostud", "workable", "joberty"])
def test_search_based_providers_are_untouched_by_an_empty_board(provider):
    ledger, jobs = two_boards(provider)
    out, stats = run_empty(ledger, [jobs[0]], {provider: {"bad"}}, returned={provider: 1})
    assert stats["closed"] == 0 and stats["keptEmptyBoard"] == 0 and {j["jobId"] for j in out} == {"g1"}


@pytest.mark.parametrize("name", ["greenhouse", "ashby", "lever"])
def test_a_provider_names_the_board_that_answered_empty(monkeypatch, name):
    empty = [] if name == "lever" else {"jobs": []}
    provider = provider_with(
        monkeypatch, name, lambda board, url: FakeResponse(body=empty if board == "bad" else GOOD_BODY[name])
    )
    assert [j["source"] for j in fetch(provider)] == ["good"]
    assert provider.last_outcome.boards_empty == ["bad"] and provider.last_outcome.boards_failed == []
    assert provider.last_outcome.status == "ok"
    assert any("bad" in warning for warning in provider.last_outcome.warnings)


# --- a source that did not run keeps its ads ------------------------------------------------------


def run_not_run(ledger, jobs, not_run, day=1, returned=None, key=KEY, evidence=None):
    return jh.apply_run(ledger, jobs, now=iso(day), providers_returned=returned or {}, key=key,
                        role_key=_crosspost_key, sources_not_run=not_run, board_evidence=evidence)


@pytest.mark.parametrize("provider", ["infostud", "joberty", "workable", "jobspy", "wellfound", "greenhouse"])
def test_a_source_that_did_not_run_keeps_its_ads_exactly_as_they_were(provider):
    ledger, jobs = two_boards(provider)
    before = copy.deepcopy(ledger["jobs"])
    out, stats = run_not_run(ledger, [], {provider})
    assert ledger["jobs"] == before, "no field of the entry may change: no closedAt, no new lastSeen"
    assert stats["closed"] == 0 and stats["keptSourceNotRun"] == 2
    assert {j["jobId"] for j in out} == {"g1", "b1"}
    for record in out:
        assert record["isClosed"] is False and record["closedAt"] is None and record["lastSeen"] == iso(0)
    assert next(j for j in out if j["jobId"] == "b1")["llmFacts"] == facts_for(jobs[1])


def test_a_source_skipped_for_another_country_keeps_its_ads_though_the_search_changed():
    """An unsupported country is by definition a different search from the one that found the ad."""
    ledger, _ = two_boards("infostud")
    out, stats = run_not_run(ledger, [], {"infostud"}, key="search-germany")
    assert {j["jobId"] for j in out} == {"g1", "b1"} and stats["keptSourceNotRun"] == 2


def test_a_board_provider_that_did_not_run_never_closes_even_with_a_count_above_zero():
    ledger, _ = two_boards()
    _, stats = run_not_run(ledger, [], {"greenhouse"}, returned={"greenhouse": 5})
    assert stats["closed"] == 0 and all(e["closedAt"] is None for e in ledger["jobs"].values())


def test_an_ad_of_a_source_that_did_not_run_is_not_kept_when_listed_under_another_copy():
    ledger, jobs = two_boards("infostud")
    copy_elsewhere = {**board_job("l9", "acme", "lever"), "title": jobs[1]["title"]}
    out, stats = run_not_run(ledger, [copy_elsewhere], {"infostud"})
    assert "b1" not in {j["jobId"] for j in out} and stats["keptSourceNotRun"] == 1


def test_a_closed_ad_of_a_source_that_did_not_run_stays_closed():
    ledger, _ = two_boards()
    ledger["jobs"]["b1"]["closedAt"] = iso(0)
    out, stats = run_not_run(ledger, [], {"greenhouse"})
    assert ledger["jobs"]["b1"]["closedAt"] == iso(0) and stats["keptSourceNotRun"] == 1
    assert next(j for j in out if j["jobId"] == "b1")["isClosed"] is True


@pytest.mark.parametrize("provider", ["infostud", "workable", "joberty", "jobspy"])
def test_a_search_source_that_ran_and_did_not_return_an_ad_behaves_as_before(provider):
    ledger, jobs = two_boards(provider)
    out, stats = run_not_run(ledger, [jobs[0]], {"another-source"}, returned={provider: 1})
    assert {j["jobId"] for j in out} == {"g1"}  # gone from the file
    assert ledger["jobs"]["b1"]["closedAt"] is None and stats["closed"] == 0 and stats["keptSourceNotRun"] == 0


def test_a_board_source_that_ran_and_lost_an_ad_still_closes_it():
    ledger, jobs = two_boards()
    run_not_run(ledger, [jobs[0]], {"another-source"}, returned={"greenhouse": 1}, evidence=proven("good", "bad"))
    out, stats = run_not_run(ledger, [jobs[0]], {"another-source"}, day=2, returned={"greenhouse": 1}, evidence=proven("good", "bad"))
    assert stats["closed"] == 1 and ledger["jobs"]["b1"]["closedAt"] == iso(2)
    assert next(j for j in out if j["jobId"] == "b1")["isClosed"] is True
