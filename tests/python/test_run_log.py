"""The run log: one record per discovery run, and the per-source outcome behind it."""

import json
import logging
import os
import stat
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
import requests

from conftest import fail_replacing
import run_discovery
import run_log
import run_pipeline as rp
import run_scoring
from match_engine import shadow
from providers import (
    ashby_provider,
    greenhouse_provider,
    infostud_client,
    infostud_provider,
    jobspy_provider,
    joberty_client,
    joberty_provider,
    lever_provider,
    remoteok_provider,
    wellfound_provider,
    workable_client,
    workable_provider,
    wwr_provider,
    yc_provider,
)
from providers.base_provider import JobProvider, ProviderOutcome

TERMS = ["product manager"]
REMOTE = ["Remote"]
RECORD_KEYS = {"version", "runId", "trigger", "startedAt", "finishedAt", "status", "sources", "issues"}
SOURCE_KEYS = {"name", "status", "read", "kept", "new", "error", "boardsFailed"}
# Decided on purpose: discovery does not know these yet, and a later slice fills them.
NOT_KNOWN_YET = {"scored", "closed", "missing", "expired"}


def posting(pid, title="Product Manager"):
    return {"id": pid, "title": title, "absolute_url": f"https://x/{pid}", "location": {"name": "Remote"},
            "content": "Own the roadmap."}


def greenhouse(boards):
    """A real Greenhouse provider; `boards` maps a board to its postings, or to an exception to raise."""
    provider = greenhouse_provider.GreenhouseProvider()
    provider._load_boards = lambda: [{"company": b.title(), "board": b} for b in boards]

    def fetch(board):
        if isinstance(boards[board], Exception):
            raise boards[board]
        return boards[board]

    provider._fetch_board = fetch
    return provider


class Fake(JobProvider):
    """A provider answering with a fixed result; `boom` makes it raise."""

    def __init__(self, jobs=(), outcome=None, boom=None):
        self.jobs, self.outcome, self.boom = list(jobs), outcome, boom

    def fetch_jobs(self, *args):
        if self.boom:
            raise self.boom
        self.last_outcome = self.outcome
        return self.jobs


@pytest.fixture
def discovery(tmp_path, monkeypatch):
    """run_discovery.main() with every path under tmp_path. Call it with {provider name: provider}."""
    monkeypatch.setattr(run_discovery, "ROOT", tmp_path)
    intelligence = tmp_path / "intel.json"
    intelligence.write_text(json.dumps({"searchStrategy": {
        "country": "Serbia", "jobSpySearchTerms": TERMS, "locationFilters": REMOTE, "remoteFilters": ["remote"],
    }}))

    def run(providers, *extra):
        monkeypatch.setattr(run_discovery, "get_provider", lambda name: providers[name])
        monkeypatch.setattr(sys, "argv", ["run_discovery.py", "--providers", ",".join(providers),
                                          "--intelligence", str(intelligence), *extra])
        return run_discovery.main()

    return run


def records():
    folder = run_log.runs_dir()
    found = [json.loads(p.read_text()) for p in folder.iterdir()] if folder.exists() else []
    return sorted(found, key=lambda record: record["startedAt"])


def only_record():
    [record] = records()
    return record


def source_of(record, name):
    return next(s for s in record["sources"] if s["name"] == name)


def messages(record, level):
    return [i["message"] for i in record["issues"] if i["level"] == level]


def discovered(tmp_path):
    return json.loads((tmp_path / "data" / "jobs" / "discovered_jobs.json").read_text())


# --- one record per run --------------------------------------------------------------------------


def test_a_run_writes_exactly_one_record_with_the_documented_fields(discovery, tmp_path):
    assert discovery({"greenhouse": greenhouse({"acme": [posting(1)]})}) == 0
    record = only_record()
    assert set(record) == RECORD_KEYS
    assert record["version"] == 1 and record["status"] == "ok" and record["issues"] == []
    assert record["runId"] == discovered(tmp_path)["meta"]["sourceRunId"]
    assert datetime.fromisoformat(record["startedAt"]) <= datetime.fromisoformat(record["finishedAt"])
    assert record["sources"] == [{"name": "greenhouse", "status": "ok", "read": 1, "kept": 1, "new": 1, "error": None,
                                  "boardsFailed": []}]
    assert set(record["sources"][0]) == SOURCE_KEYS and not NOT_KNOWN_YET & set(record["sources"][0])


def test_two_runs_write_two_records_with_their_own_ids(discovery):
    provider = {"greenhouse": greenhouse({"acme": [posting(1)]})}
    discovery(provider)
    discovery(provider)
    assert len({r["runId"] for r in records()}) == 2


def test_the_trigger_defaults_to_manual_and_takes_the_later_values(discovery):
    provider = {"greenhouse": greenhouse({"acme": [posting(1)]})}
    discovery(provider)
    discovery(provider, "--trigger", "pipeline")
    discovery(provider, "--trigger", "scheduled")
    assert sorted(r["trigger"] for r in records()) == ["manual", "pipeline", "scheduled"]
    with pytest.raises(ValueError):
        run_log.new_record("x", "by hand")


def test_the_pipeline_tells_discovery_it_is_the_pipeline(tmp_path, monkeypatch):
    """The pipeline only starts run_discovery.py once and names itself; it writes no record of its own."""
    monkeypatch.setattr(rp, "INTELLIGENCE", tmp_path / "intel.json")
    commands = []

    def run_step(name, cmd, steps):
        commands.append(cmd)
        raise rp.StepFailed(name, "stop here")

    monkeypatch.setattr(rp, "run_step", run_step)
    with pytest.raises(rp.StepFailed):
        rp.execute(rp.parse_args(["--providers", "ats"]), [])
    [command] = commands
    assert command[0].endswith("run_discovery.py") and command[command.index("--trigger") + 1] == "pipeline"
    assert not run_log.runs_dir().exists()


def test_a_run_that_cannot_start_is_a_failed_record(discovery, tmp_path, monkeypatch):
    (tmp_path / "intel.json").write_text("{}")
    monkeypatch.setattr(run_discovery, "load_intelligence", lambda path: {"searchStrategy": {"country": "Serbia"}})
    assert discovery({"greenhouse": Fake()}) == 1
    record = only_record()
    assert record["status"] == "failed" and record["sources"] == []
    assert messages(record, "error") == ["No jobSpySearchTerms found in intelligence file."]


def test_a_run_that_crashes_still_writes_a_failed_record_and_the_crash_is_not_hidden(discovery, monkeypatch):
    def crash(*args, **kwargs):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(run_discovery, "export_discovered_json", crash)
    with pytest.raises(RuntimeError, match="disk gone"):
        discovery({"greenhouse": greenhouse({"acme": [posting(1)]})})
    record = only_record()
    assert record["status"] == "failed" and messages(record, "error") == ["Discovery stopped: disk gone"]


@pytest.mark.parametrize("statuses, expected", [
    (["ok", "ok"], "ok"),
    (["ok", "partial"], "partial"),
    (["ok", "failed"], "partial"),
    (["failed", "partial"], "partial"),
    (["failed", "failed"], "failed"),
    ([], "failed"),
])
def test_the_run_status_follows_its_sources(statuses, expected):
    record = run_log.new_record("x", "manual")
    for number, status in enumerate(statuses):
        run_log.add_source(record, str(number), ProviderOutcome(status=status, read=1, kept=1))
    assert run_log.finish(record, exit_ok=True)["status"] == expected


def test_warnings_alone_leave_the_run_ok(discovery):
    assert discovery({"greenhouse": greenhouse({"acme": []})}) == 0
    record = only_record()
    assert record["status"] == "ok" and messages(record, "error") == [] and messages(record, "warning")


# --- outcomes through a real run -----------------------------------------------------------------


def test_a_failed_board_among_working_boards_is_partial_and_named_and_its_ad_stays_open(discovery, tmp_path):
    first = {"greenhouse": greenhouse({"good": [posting(1)], "bad": [posting(2, "Senior Product Manager")]})}
    assert discovery(first) == 0
    second = {"greenhouse": greenhouse({"good": [posting(1)], "bad": requests.ConnectionError("boom")})}
    assert discovery(second) == 0

    record = records()[-1]
    source = source_of(record, "greenhouse")
    assert record["status"] == "partial"
    assert (source["status"], source["boardsFailed"], source["read"], source["kept"]) == ("partial", ["bad"], 1, 1)
    assert source["error"] == "bad: boom"
    assert [(i["level"], i["source"], i["message"]) for i in record["issues"]] == [("error", "greenhouse", "bad: boom")]

    payload = discovered(tmp_path)
    assert {j["title"]: j["isClosed"] for j in payload["jobs"]} == {"Product Manager": False, "Senior Product Manager": False}
    assert payload["meta"]["history"]["closed"] == 0 and payload["meta"]["history"]["keptFailedBoard"] == 1


def test_every_board_failing_is_a_failed_source_and_closes_nothing(discovery, tmp_path):
    discovery({"greenhouse": greenhouse({"acme": [posting(1)]})})
    assert discovery({"greenhouse": greenhouse({"acme": requests.Timeout("slow")})}) == 0
    record = records()[-1]
    assert record["status"] == "failed" and source_of(record, "greenhouse")["boardsFailed"] == ["acme"]
    assert messages(record, "warning") == []  # the error says it already
    assert [j["isClosed"] for j in discovered(tmp_path)["jobs"]] == [False]


def test_a_provider_that_raises_is_one_failed_source_the_others_still_run_and_its_ads_stay(discovery, tmp_path):
    discovery({"greenhouse": greenhouse({"acme": [posting(1)]}), "lever": Fake(outcome=ProviderOutcome())})
    assert discovery({"greenhouse": Fake(boom=ValueError("bad config")), "lever": Fake(outcome=ProviderOutcome())}) == 0
    record = records()[-1]
    assert source_of(record, "greenhouse")["status"] == "failed" and source_of(record, "greenhouse")["error"] == "bad config"
    assert source_of(record, "lever")["status"] == "ok" and record["status"] == "partial"
    assert [j["isClosed"] for j in discovered(tmp_path)["jobs"]] == [False]


def test_a_provider_that_reports_no_outcome_is_a_failed_source_not_a_guess(discovery):
    assert discovery({"greenhouse": Fake(outcome=None)}) == 0
    assert "no outcome" in source_of(only_record(), "greenhouse")["error"]


def test_a_source_with_no_ads_gets_a_warning_and_closes_nothing(discovery, tmp_path):
    discovery({"greenhouse": greenhouse({"acme": [posting(1)]})})
    empty = Fake(outcome=ProviderOutcome(read=0, kept=0))
    assert discovery({"greenhouse": empty}) == 0
    record = records()[-1]
    assert record["status"] == "ok"
    assert [(i["level"], i["source"]) for i in record["issues"]] == [("warning", "greenhouse")]
    assert "0 ads kept (read 0)" in record["issues"][0]["message"]
    assert discovered(tmp_path)["meta"]["history"]["closed"] == 0


def test_the_warning_says_when_ads_were_read_and_all_filtered_out(discovery):
    assert discovery({"greenhouse": greenhouse({"acme": [posting(1, "Software Engineer")]})}) == 0
    source, [message] = source_of(only_record(), "greenhouse"), messages(only_record(), "warning")
    assert (source["read"], source["kept"]) == (1, 0) and "read 1, all filtered out" in message


def test_an_empty_board_is_warned_about_by_name_and_its_ad_stays_open(discovery, tmp_path):
    first = {"greenhouse": greenhouse({"good": [posting(1)], "empty": [posting(2, "Senior Product Manager")]})}
    assert discovery(first) == 0
    assert discovery({"greenhouse": greenhouse({"good": [posting(1)], "empty": []})}) == 0

    record = records()[-1]
    assert source_of(record, "greenhouse")["status"] == "ok" and record["status"] == "ok"
    [message] = messages(record, "warning")
    assert "board empty answered with 0 ads" in message

    payload = discovered(tmp_path)
    assert {j["title"]: j["isClosed"] for j in payload["jobs"]} == {"Product Manager": False, "Senior Product Manager": False}
    assert payload["meta"]["history"]["closed"] == 0 and payload["meta"]["history"]["keptEmptyBoard"] == 1


def test_an_ad_gone_from_a_non_empty_board_still_closes_when_another_board_is_empty(discovery, tmp_path):
    first = {"greenhouse": greenhouse({"good": [posting(1), posting(3, "Lead Product Manager")], "empty": [posting(2, "Senior Product Manager")]})}
    discovery(first)
    discovery({"greenhouse": greenhouse({"good": [posting(1)], "empty": []})})
    states = {j["title"]: j["isClosed"] for j in discovered(tmp_path)["jobs"]}
    assert states == {"Product Manager": False, "Senior Product Manager": False, "Lead Product Manager": True}


def test_all_boards_empty_in_a_real_run_closes_nothing_and_keeps_the_ads(discovery, tmp_path):
    discovery({"greenhouse": greenhouse({"a": [posting(1)], "b": [posting(2, "Senior Product Manager")]})})
    assert discovery({"greenhouse": greenhouse({"a": [], "b": []})}) == 0
    payload = discovered(tmp_path)
    assert len(payload["jobs"]) == 2 and not any(j["isClosed"] for j in payload["jobs"])
    assert payload["meta"]["history"]["closed"] == 0 and payload["meta"]["history"]["keptEmptyBoard"] == 2


def test_read_counts_what_the_filter_saw_and_kept_what_passed(discovery):
    discovery({"greenhouse": greenhouse({"acme": [posting(1), posting(2, "Software Engineer")]})})
    source = source_of(only_record(), "greenhouse")
    assert (source["read"], source["kept"]) == (2, 1)


def test_new_is_counted_per_source_after_dedupe_and_adds_up_to_the_history_figure(discovery, tmp_path):
    def lever_job(job_id, title):
        return {"jobId": job_id, "provider": "lever", "source": "acme", "title": title, "company": "Acme",
                "location": "Remote", "description": "Own the roadmap.", "jobUrl": f"https://y/{job_id}"}

    providers = {
        "greenhouse": greenhouse({"acme": [posting(1)]}),
        "lever": Fake([lever_job("l1", "Head of Product"), lever_job("l2", "Product Lead")],
                      ProviderOutcome(read=2, kept=2)),
    }
    discovery(providers)
    first = only_record()
    assert (source_of(first, "greenhouse")["new"], source_of(first, "lever")["new"]) == (1, 2)
    assert sum(s["new"] for s in first["sources"]) == discovered(tmp_path)["meta"]["history"]["new"]

    discovery(providers)
    assert [s["new"] for s in records()[-1]["sources"]] == [0, 0]


def test_a_failing_run_log_does_not_fail_the_run(discovery, tmp_path, monkeypatch, caplog):
    (tmp_path / "blocked").write_text("a file, not a folder")
    monkeypatch.setenv("CAREER_OS_ANALYTICS_DIR", str(tmp_path / "blocked"))
    with caplog.at_level(logging.WARNING):
        assert discovery({"greenhouse": greenhouse({"acme": [posting(1)]})}) == 0
    assert "Run log not written" in caplog.text


# --- each provider reports -----------------------------------------------------------------------


def fetch(provider, country="Serbia"):
    return provider.fetch_jobs(TERMS, REMOTE, ["remote"], country)


class Answer:
    def __init__(self, body=None, content=b""):
        self.body, self.content, self.status_code = body, content, 200

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def boom(*args, **kwargs):
    raise requests.ConnectionError("no route")


REMOTEOK_BODY = [{"legal": "notice"}, {"position": "Product Manager", "company": "A", "url": "https://r/1"},
                 {"position": "Welder", "company": "B", "url": "https://r/2"}]
YC_BODY = {"jobs": [{"title": "Product Manager", "company": "A", "location": "Remote", "url": "https://y/1"},
                    {"title": "Welder", "company": "B", "location": "Remote", "url": "https://y/2"}]}
WWR_FEED = (b"<rss><channel><item><title>A: Product Manager</title><link>https://w/1</link></item>"
            b"<item><title>B: Welder</title><link>https://w/2</link></item></channel></rss>")


@pytest.mark.parametrize("make, module, body, content", [
    (remoteok_provider.RemoteOKProvider, remoteok_provider, REMOTEOK_BODY, b""),
    (yc_provider.YCProvider, yc_provider, YC_BODY, b""),
], ids=["remoteok", "yc"])
def test_a_single_feed_provider_reports_read_kept_and_failure(monkeypatch, make, module, body, content):
    monkeypatch.setattr(module.requests, "get", lambda *a, **k: Answer(body, content))
    provider = make()
    assert len(fetch(provider)) == 1
    assert (provider.last_outcome.status, provider.last_outcome.read, provider.last_outcome.kept) == ("ok", 2, 1)

    monkeypatch.setattr(module.requests, "get", boom)
    assert fetch(provider) == []
    assert (provider.last_outcome.status, provider.last_outcome.error) == ("failed", "no route")

    monkeypatch.setattr(module.requests, "get", lambda *a, **k: Answer({"unexpected": True}))
    fetch(provider)
    assert provider.last_outcome.status == "failed"


def test_wwr_reports_each_feed_and_is_partial_when_one_fails(monkeypatch):
    feeds = wwr_provider.RSS_FEEDS

    def get(url, **kwargs):
        if url == feeds[0]:
            raise requests.Timeout("slow")
        return Answer(content=WWR_FEED)

    monkeypatch.setattr(wwr_provider.requests, "get", get)
    provider = wwr_provider.WWRProvider()
    assert len(fetch(provider)) == 1
    outcome = provider.last_outcome
    assert (outcome.status, outcome.boards_failed, outcome.read, outcome.kept) == ("partial", [feeds[0]], 2, 1)

    monkeypatch.setattr(wwr_provider.requests, "get", boom)
    fetch(provider)
    assert provider.last_outcome.status == "failed" and provider.last_outcome.boards_failed == feeds


def test_wellfound_says_it_is_not_built():
    provider = wellfound_provider.WellfoundProvider()
    assert fetch(provider) == []
    assert provider.last_outcome.status == "ok" and "not built" in provider.last_outcome.warnings[0]


def test_jobspy_reports_read_before_its_title_filter_and_failed_searches(monkeypatch):
    frame = pd.DataFrame([{"title": "Product Manager", "company": "A", "location": "Remote", "job_url": "https://j/1"},
                          {"title": "Welder", "company": "B", "location": "Remote", "job_url": "https://j/2"}])
    monkeypatch.setattr(jobspy_provider, "fetch_jobs", lambda *a, **k: frame)
    provider = jobspy_provider.JobSpyProvider()
    assert len(provider.fetch_jobs(TERMS, ["Remote", "Serbia"], ["remote"], "Serbia")) == 2
    outcome = provider.last_outcome
    assert (outcome.status, outcome.read, outcome.kept) == ("ok", 4, 2)

    answers = iter([frame])

    def one_fails(*args, **kwargs):
        try:
            return next(answers)
        except StopIteration:
            raise RuntimeError("blocked") from None

    monkeypatch.setattr(jobspy_provider, "fetch_jobs", one_fails)
    provider.fetch_jobs(TERMS, ["Remote", "Serbia"], ["remote"], "Serbia")
    outcome = provider.last_outcome
    assert (outcome.status, outcome.read, outcome.boards_failed) == ("partial", 2, [])
    assert outcome.error == "product manager @ Serbia: blocked"

    monkeypatch.setattr(jobspy_provider, "fetch_jobs", boom)
    provider.fetch_jobs(TERMS, ["Remote"], ["remote"], "Serbia")
    assert provider.last_outcome.status == "failed"


def test_infostud_reports_ads_read_before_the_clients_role_filter(monkeypatch):
    rows = [{"id": 1, "title": "Product Manager", "url": "https://i/1", "location": "Rad od kuće", "workFromHome": True},
            {"id": 2, "title": "Welder", "url": "https://i/2", "location": "Beograd"}]
    monkeypatch.setattr(infostud_client, "fetch_raw", lambda categories: (rows, 2))
    provider = infostud_provider.InfostudProvider()
    monkeypatch.setattr(infostud_client, "enrich", lambda job: job)
    assert len(fetch(provider)) == 1
    outcome = provider.last_outcome
    assert (outcome.status, outcome.read, outcome.kept) == ("ok", 2, 1)

    assert fetch(provider, "Germany") == []
    assert provider.last_outcome.status == "ok" and "not searched" in provider.last_outcome.warnings[0]

    monkeypatch.setattr(infostud_client, "fetch_raw", boom)
    assert fetch(provider) == []
    assert (provider.last_outcome.status, provider.last_outcome.error) == ("failed", "no route")


def test_workable_reports_different_ads_read_before_the_clients_role_filter(monkeypatch):
    rows = [{"title": "Product Manager", "company": "A", "url": "https://k/1", "workplace": "remote"},
            {"title": "Welder", "company": "B", "url": "https://k/2", "workplace": "remote"}]
    monkeypatch.setattr(workable_client, "search", lambda term, location: rows)
    monkeypatch.setattr(workable_client.time, "sleep", lambda s: None)
    provider = workable_provider.WorkableProvider()
    provider_terms = ["product manager", "product lead"]  # both searches answer the same two ads
    assert len(provider.fetch_jobs(provider_terms, REMOTE, ["remote"], "Serbia")) == 1
    outcome = provider.last_outcome
    assert (outcome.status, outcome.read, outcome.kept) == ("ok", 2, 1)

    monkeypatch.setattr(workable_client, "search", boom)
    assert fetch(provider) == []
    assert (provider.last_outcome.status, provider.last_outcome.error) == ("failed", "no route")


def test_joberty_reports_the_listing_as_read_and_failure(monkeypatch, tmp_path):
    item = {"companyName": "A", "companyUrlName": "a", "cities": ["Remote (Serbia)"]}
    listing = [{**item, "id": 1, "jobTitle": "Product Manager"}, {**item, "id": 2, "jobTitle": "Welder"}]
    monkeypatch.setattr(joberty_client, "fetch_cities", lambda: ["Remote (Serbia)", "Belgrade (Serbia)"])
    monkeypatch.setattr(joberty_client, "fetch_listing", lambda: listing)
    monkeypatch.setattr(joberty_client, "fetch_detail", lambda job_id: {"text": "<p>Own the roadmap.</p>"})
    provider = joberty_provider.JobertyProvider(ledger_path=tmp_path / "job_history.json")
    assert len(fetch(provider)) == 1
    outcome = provider.last_outcome
    assert (outcome.status, outcome.read, outcome.kept) == ("ok", 2, 1)

    monkeypatch.setattr(joberty_client, "fetch_cities", lambda: [])
    assert fetch(provider) == []
    assert provider.last_outcome.status == "ok" and "not searched" in provider.last_outcome.warnings[0]

    monkeypatch.setattr(joberty_client, "fetch_cities", boom)
    assert fetch(provider) == []
    assert (provider.last_outcome.status, provider.last_outcome.error) == ("failed", "no route")


@pytest.mark.parametrize("name, module, make", [
    ("lever", lever_provider, lever_provider.LeverProvider),
    ("ashby", ashby_provider, ashby_provider.AshbyProvider),
], ids=["lever", "ashby"])
def test_lever_and_ashby_report_a_failed_board_with_its_error(monkeypatch, name, module, make):
    monkeypatch.setattr(module.requests, "get", boom)
    provider = make()
    provider._load_companies = lambda: ["acme", "beta"]
    assert fetch(provider) == []
    assert provider.last_outcome.status == "failed" and provider.last_outcome.boards_failed == ["acme", "beta"]
    assert provider.last_outcome.error == "acme: no route; beta: no route"


def test_every_registered_provider_is_covered_here():
    from providers.provider_registry import PROVIDER_CLASSES

    assert set(PROVIDER_CLASSES) == {"jobspy", "greenhouse", "lever", "ashby", "wellfound", "remoteok", "yc", "wwr",
                                     "infostud", "workable", "joberty"}


# --- the file ------------------------------------------------------------------------------------


def saved_record(run_id="abc", started=None):
    record = run_log.new_record(run_id, "manual")
    if started:
        record["startedAt"] = started.isoformat()
    return run_log.finish(record, exit_ok=True)


def test_new_files_are_600_and_new_folders_700():
    path = run_log.save(saved_record())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.parent.parent.stat().st_mode) == 0o700


def test_an_existing_analytics_folder_keeps_its_mode(tmp_path):
    analytics = tmp_path / "analytics"
    analytics.mkdir(mode=0o750)
    os.chmod(analytics, 0o750)
    run_log.save(saved_record())
    assert stat.S_IMODE(analytics.stat().st_mode) == 0o750


def test_the_write_is_atomic_a_failed_rename_leaves_no_file_and_no_temp_file(monkeypatch):
    record = saved_record()
    run_log._atomic.make_private_dirs(run_log.runs_dir())
    started = datetime.fromisoformat(record["startedAt"]).astimezone(timezone.utc)
    target = run_log.runs_dir() / f"{started.strftime('%Y%m%dT%H%M%SZ')}-abc.json"
    temps = fail_replacing(monkeypatch, target)
    assert run_log.save(record) is None  # the failure is logged, it does not raise
    assert temps and temps[0].startswith(".") and list(run_log.runs_dir().iterdir()) == []


def planted(run_id, started):
    """A record already on disk: save() would prune one this old straight away."""
    folder = run_log.runs_dir()
    run_log._atomic.make_private_dirs(folder)
    path = folder / f"{started.strftime('%Y%m%dT%H%M%SZ')}-{run_id}.json"
    path.write_text(json.dumps(saved_record(run_id, started)))
    return path


def test_records_older_than_ninety_days_are_pruned_at_write_time_and_nothing_else():
    now = datetime.now(timezone.utc)
    old = planted("old", now - timedelta(days=91))
    edge = planted("edge", now - timedelta(days=89, hours=23))
    foreign = run_log.runs_dir() / "notes.txt"
    foreign.write_text("not a record")
    bad_date = run_log.runs_dir() / "20269999T000000Z-x.json"
    bad_date.write_text("{}")

    fresh = run_log.save(saved_record("fresh"))
    assert not old.exists(), "a record past 90 days goes when the next one is written"
    assert edge.exists() and fresh.exists() and foreign.exists() and bad_date.exists()


def test_pruning_reads_the_start_time_not_the_file_time():
    now = datetime.now(timezone.utc)
    old = planted("old", now - timedelta(days=200))
    os.utime(old)  # a copy or a restore makes the file look fresh
    assert run_log.prune(run_log.runs_dir(), now) == 1 and not old.exists()


def test_no_credential_or_endless_message_reaches_a_record():
    record = run_log.new_record("x", "manual")
    run_log.add_source(record, "s", ProviderOutcome(
        status="failed", error="GET https://a/b?api_key=hunter2&q=pm token=abc123 sk-abcdefghijkl " + "x" * 2000))
    error = record["sources"][0]["error"]
    assert "hunter2" not in error and "abc123" not in error and "sk-abcdefghijkl" not in error
    assert "q=pm" in error and len(error) == run_log.MAX_MESSAGE_CHARS
    assert record["issues"][0]["message"] == error


# --- scoring is told which run it scored ---------------------------------------------------------


@pytest.mark.parametrize("meta, expected", [
    ({"sourceRunId": "disc123"}, "disc123"),
    ({}, None),
    (None, None),
], ids=["discovery-id", "older-file", "no-meta"])
def test_scoring_records_the_discovery_run_id_and_keeps_its_own(tmp_path, monkeypatch, meta, expected):
    (tmp_path / "intel.json").write_text(json.dumps({"jobFitPreferences": {}, "roleFamily": "product"}))
    (tmp_path / "jobs.json").write_text(json.dumps({**({"meta": meta} if meta is not None else {}), "jobs": [{
        "jobId": "a", "title": "Product Manager", "company": "Acme", "location": "Niš, Serbia",
        "description": "Own the roadmap.", "jobUrl": "https://jobs.example/a", "provider": "jobspy", "status": "new",
    }]}))
    monkeypatch.setattr(run_scoring, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "llm_fit.json")
    monkeypatch.setattr(shadow, "CACHE_PATH", tmp_path / "engine.json")
    monkeypatch.setattr(sys, "argv", [
        "run_scoring.py", "--intelligence", str(tmp_path / "intel.json"), "--jobs", str(tmp_path / "jobs.json"),
        "--manual", str(tmp_path / "manual.json"), "--output", str(tmp_path / "scored.json"),
    ])
    assert run_scoring.main() == 0
    scored_meta = json.loads((tmp_path / "scored.json").read_text())["meta"]
    assert scored_meta["discoveryRunId"] == expected
    assert scored_meta["sourceRunId"] and scored_meta["sourceRunId"] != expected
