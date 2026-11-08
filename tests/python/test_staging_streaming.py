"""Providers stage while they collect (slice 1b): what is staged is what is returned, and it is on disk before the next request.

Offline: every provider runs against fakes for its client. Every path is under tmp_path.
"""

import copy
import json
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]

import staging  # noqa: E402
from providers import (  # noqa: E402
    ashby_provider,
    greenhouse_provider,
    infostud_client,
    infostud_provider,
    jobspy_provider,
    joberty_client,
    joberty_provider,
    lever_provider,
    remoteok_provider,
    workable_client,
    workable_provider,
    wwr_provider,
    yc_provider,
)
from providers.base_provider import ProviderOutcome  # noqa: E402

TERMS = ["Product Manager", "Product Lead"]
LOCATIONS = ["Remote"]
REMOTE = ["remote"]
COUNTRY = "Serbia"
SERBIA = ["Niš, Serbia", "Serbia"]  # the places the Joberty fixtures are in


@pytest.fixture
def run(tmp_path):
    return staging.StagingRun.begin(
        tmp_path, "r1", search_key="k", terms=TERMS, locations=LOCATIONS, country=COUNTRY, remote_filters=REMOTE,
        providers=["x"],
    )


def collect(provider, run, name, tmp_path, locations=None):
    """What run_discovery.fetch_source does: stage while fetching, then close the source. Returns (returned, stage)."""
    import run_discovery

    writer = run.open_source(name)
    jobs, outcome = run_discovery.fetch_source(provider, name, TERMS, locations or LOCATIONS, REMOTE, COUNTRY, stage=writer)
    return jobs, outcome, staging.read_source(tmp_path / "data/jobs/staging/r1" / f"{name}.jsonl")


def staged_file(tmp_path, name):
    return tmp_path / "data/jobs/staging/r1" / f"{name}.jsonl"


# --- the writer: on disk before append returns ---------------------------------------------------------------------


def test_every_append_is_fsynced_before_it_returns(run, monkeypatch, tmp_path):
    synced = []
    real = os.fsync
    monkeypatch.setattr(staging.os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])
    writer = run.open_source("jobspy")
    before = len(synced)
    writer.append([{"jobId": "a", "provider": "p", "title": "t"}], part="one")
    assert len(synced) > before
    assert [b.part for b in staging.read_source(staged_file(tmp_path, "jobspy")).batches] == ["one"], "readable at once"


# --- JobSpy: one search at a time ----------------------------------------------------------------------------------


def frame(*titles):
    return pd.DataFrame([
        {"title": t, "company": "Acme", "location": "Remote", "job_url": f"https://x.example/{t.replace(' ', '-')}",
         "description": "d", "site": "linkedin", "is_remote": True}
        for t in titles
    ])


def test_jobspy_stages_each_search_before_the_next_one_starts(run, monkeypatch, tmp_path):
    seen_at_call = []
    answers = {
        "Product Manager": frame("Senior Product Manager", "SAP Consultant"),
        "Product Lead": frame("Product Lead", "Product Lead EMEA"),
    }

    def fake_fetch(term, location, remote=False, country=""):
        path = staged_file(tmp_path, "jobspy")
        seen_at_call.append([b.part for b in staging.read_source(path).batches])
        return answers[term]

    monkeypatch.setattr(jobspy_provider, "fetch_jobs", fake_fetch)
    provider = jobspy_provider.JobSpyProvider()
    returned, outcome, stage = collect(provider, run, "jobspy", tmp_path)

    assert seen_at_call == [[], ["Product Manager @ Remote"]], "the first search was on disk when the second began"
    assert [b.part for b in stage.batches] == ["Product Manager @ Remote", "Product Lead @ Remote"]
    assert [b.read for b in stage.batches] == [2, 2], "read counts the ads before the title filter"
    assert [len(b.jobs) for b in stage.batches] == [1, 2], "the title filter applies to what is staged, as to what is returned"
    assert stage.jobs == returned and [j["title"] for j in returned] == ["Senior Product Manager", "Product Lead", "Product Lead EMEA"]
    assert stage.complete and stage.footer["written"] == "as it went" and stage.footer["mismatch"] is False
    assert (outcome.read, outcome.kept) == (4, 3) == (stage.footer["read"], stage.footer["kept"])


def test_jobspy_a_failed_search_is_not_a_part_and_an_empty_one_is(run, monkeypatch, tmp_path):
    def fake_fetch(term, location, remote=False, country=""):
        if term == "Product Lead":
            raise RuntimeError("blocked")
        return pd.DataFrame()

    monkeypatch.setattr(jobspy_provider, "fetch_jobs", fake_fetch)
    returned, outcome, stage = collect(jobspy_provider.JobSpyProvider(), run, "jobspy", tmp_path)
    assert returned == [] and outcome.status == "partial"
    assert [(b.part, b.read, len(b.jobs)) for b in stage.batches] == [("Product Manager @ Remote", 0, 0)]
    assert stage.footer["status"] == "partial" and not stage.complete


def test_jobspy_returns_what_it_always_returned(run, monkeypatch, tmp_path):
    """The same list the old end-of-run filter gave: all searches, in order, titles filtered, duplicates left to dedupe."""
    monkeypatch.setattr(jobspy_provider, "fetch_jobs", lambda *a, **k: frame("Product Manager", "Sales Lead"))
    returned, _, stage = collect(jobspy_provider.JobSpyProvider(), run, "jobspy", tmp_path)
    assert [j["title"] for j in returned] == ["Product Manager", "Product Manager"]
    assert stage.jobs == returned
    assert len(jobspy_provider.JobSpyProvider().last_raw_df) == 0


# --- Greenhouse, Lever, Ashby: one board at a time -----------------------------------------------------------------


def board_cases():
    gh = lambda title: {"id": 1, "title": title, "location": {"name": "Remote"}, "absolute_url": f"https://g.example/{title}", "content": "c"}
    lv = lambda title: {"text": title, "categories": {"location": "Remote"}, "hostedUrl": f"https://l.example/{title}", "descriptionPlain": "c"}
    ab = lambda title: {"title": title, "location": "Remote", "jobUrl": f"https://a.example/{title}", "descriptionPlain": "c", "isListed": True}
    return [
        ("greenhouse", greenhouse_provider.GreenhouseProvider, "_load_boards", [{"board": "b1", "company": "One"}, {"board": "b2"}, {"board": "b3"}], "_fetch_board", gh),
        ("lever", lever_provider.LeverProvider, "_load_companies", ["b1", "b2", "b3"], "_fetch_company", lv),
        ("ashby", ashby_provider.AshbyProvider, "_load_companies", ["b1", "b2", "b3"], "_fetch_company", ab),
    ]


@pytest.mark.parametrize("name, cls, loader, boards, fetcher, make", board_cases(), ids=lambda v: v if isinstance(v, str) else "")
def test_a_board_is_staged_as_soon_as_it_is_read(name, cls, loader, boards, fetcher, make, run, monkeypatch, tmp_path):
    provider = cls()
    monkeypatch.setattr(provider, loader, lambda: boards)
    answers = {"b1": [make("Product Manager"), make("Chef")], "b2": RuntimeError("down"), "b3": []}
    seen_at_call = []

    def fake_board(board):
        seen_at_call.append([b.part for b in staging.read_source(staged_file(tmp_path, name)).batches])
        answer = answers[board]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(provider, fetcher, fake_board)
    returned, outcome, stage = collect(provider, run, name, tmp_path)

    assert seen_at_call == [[], ["b1"], ["b1"]], "b1 was on disk before b2 was asked for; the failed b2 is no part"
    assert [(b.part, b.read, len(b.jobs)) for b in stage.batches] == [("b1", 2, 1), ("b3", 0, 0)]
    assert stage.jobs == returned and [j["title"] for j in returned] == ["Product Manager"], "the chef is filtered from both"
    assert outcome.status == "partial" and stage.footer["status"] == "partial" and not stage.complete
    assert stage.footer["boardsFailed"] == ["b2"] and stage.footer["boardsEmpty"] == ["b3"]
    assert stage.footer["written"] == "as it went" and stage.footer["mismatch"] is False


def test_the_whole_board_filter_still_logs_once(run, monkeypatch, caplog):
    provider = greenhouse_provider.GreenhouseProvider()
    monkeypatch.setattr(provider, "_load_boards", lambda: [{"board": f"b{n}"} for n in range(5)])
    monkeypatch.setattr(provider, "_fetch_board", lambda board: [])
    with caplog.at_level("INFO"):
        provider.stage_writer = None
        provider.fetch_jobs(TERMS, LOCATIONS, REMOTE, COUNTRY)
    assert len([r for r in caplog.records if "postings fetched" in r.getMessage()]) == 1


# --- We Work Remotely: one feed at a time --------------------------------------------------------------------------


def test_wwr_stages_a_feed_at_a_time_and_a_repeat_across_feeds_once(run, monkeypatch, tmp_path):
    feeds = {
        wwr_provider.RSS_FEEDS[0]: [{"title": "Product Manager", "company": "A", "link": "https://w.example/1", "description": "d", "pubDate": ""}],
        wwr_provider.RSS_FEEDS[1]: [
            {"title": "Product Manager", "company": "A", "link": "https://w.example/1", "description": "d", "pubDate": ""},
            {"title": "Product Lead", "company": "B", "link": "https://w.example/2", "description": "d", "pubDate": ""},
        ],
        wwr_provider.RSS_FEEDS[2]: RuntimeError("feed down"),
    }
    provider = wwr_provider.WWRProvider()

    def parse(url):
        if isinstance(feeds[url], Exception):
            raise feeds[url]
        return feeds[url]

    monkeypatch.setattr(provider, "_parse_feed", parse)
    returned, _, stage = collect(provider, run, "wwr", tmp_path)
    assert [(b.part, len(b.jobs)) for b in stage.batches] == [(wwr_provider.RSS_FEEDS[0], 1), (wwr_provider.RSS_FEEDS[1], 1)]
    assert stage.jobs == returned and len(returned) == 2


# --- Infostud: one ad at a time, after its full description is read ------------------------------------------------


def infostud_row(n, title="Product Manager"):
    return {"id": n, "url": f"https://www.infostud.com/oglas/{n}", "title": title, "companyName": "Acme", "location": "Beograd",
            "jobSummary": {"summary": "short"}}


def test_infostud_stages_each_ad_when_its_description_is_complete(run, monkeypatch, tmp_path):
    rows = [infostud_row(1), infostud_row(2), infostud_row(3, "Chef"), infostud_row(4)]
    monkeypatch.setattr(infostud_client, "fetch_raw", lambda categories=None, **_: (rows, 321))
    seen_at_enrich = []

    def enrich(job, delay=1.0):
        seen_at_enrich.append([j["title"] for j in staging.read_source(staged_file(tmp_path, "infostud")).jobs])
        job["description"] = "the full description"
        return job

    monkeypatch.setattr(infostud_client, "enrich", enrich)
    monkeypatch.setattr(
        infostud_provider, "place_drop_reason",
        lambda job, locations, remote, country: "location_not_matched" if "oglas/4" in job["jobUrl"] else None,
    )
    provider = infostud_provider.InfostudProvider()
    returned, outcome, stage = collect(provider, run, "infostud", tmp_path)

    assert len(seen_at_enrich) == 3 and [len(x) for x in seen_at_enrich] == [0, 1, 2], "each ad was on disk before the next request"
    assert len(returned) == 2 and stage.jobs == returned, "an ad outside the place filter is neither staged nor returned"
    assert all(j["description"] == "the full description" for j in stage.jobs)
    assert stage.footer["total"] == 321 and stage.footer["read"] == 4 and stage.footer["kept"] == 2
    assert stage.complete and stage.footer["written"] == "as it went" and stage.footer["mismatch"] is False
    assert [b.part for b in stage.batches if b.jobs] == [j["jobId"] for j in returned]
    assert [b.part for b in stage.batches if not b.jobs][0] == "listing", "what the role filter dropped is recorded first"


def test_infostud_a_listing_that_fails_stages_nothing_and_says_failed(run, monkeypatch, tmp_path):
    def broken(categories=None, **_):
        raise RuntimeError("Infostud unreachable")

    monkeypatch.setattr(infostud_client, "fetch_raw", broken)
    returned, outcome, stage = collect(infostud_provider.InfostudProvider(), run, "infostud", tmp_path)
    assert returned == [] and stage.jobs == [] and stage.footer["status"] == "failed" and not stage.complete


# --- Workable: one search term at a time ---------------------------------------------------------------------------


def test_workable_stages_the_ads_each_term_added_and_none_twice(run, monkeypatch, tmp_path):
    def row(n, title="Product Manager"):
        return {"title": title, "company": "Acme", "url": f"https://jobs.workable.com/view/{n}", "description": "<p>d</p>",
                "workplace": "remote", "location": {"city": "Niš", "countryName": "Serbia"}}

    answers = {"Product Manager": [row(1), row(2), row(3, "Chef")], "Product Lead": [row(2), row(4, "Product Lead")]}
    seen_at_search = []

    def search(term, location="", limit=100):
        seen_at_search.append([b.part for b in staging.read_source(staged_file(tmp_path, "workable")).batches])
        return answers[term]

    monkeypatch.setattr(workable_client, "search", search)
    monkeypatch.setattr(workable_client.time, "sleep", lambda s: None)
    provider = workable_provider.WorkableProvider()
    returned, outcome, stage = collect(provider, run, "workable", tmp_path)

    assert seen_at_search == [[], ["Product Manager"]]
    assert [(b.part, [j["jobUrl"][-1] for j in b.jobs]) for b in stage.batches] == [("Product Manager", ["1", "2"]), ("Product Lead", ["4"])]
    assert stage.jobs == returned and len(returned) == 3
    assert stage.footer["written"] == "as it went" and stage.footer["mismatch"] is False


# --- Joberty: one ad at a time, as each detail is read -------------------------------------------------------------


def test_joberty_stages_each_ad_as_its_detail_arrives(run, monkeypatch, tmp_path):
    from test_joberty import CITIES, DETAIL, LISTING, product_ad

    items = [product_ad(1), product_ad(2), product_ad(3)]
    seen_at_detail = []

    def detail(job_id):
        seen_at_detail.append([j["externalId"] for j in staging.read_source(staged_file(tmp_path, "joberty")).jobs])
        return copy.deepcopy(DETAIL) if job_id != 2 else {}

    monkeypatch.setattr(joberty_client, "fetch_cities", lambda: CITIES)
    monkeypatch.setattr(joberty_client, "fetch_listing", lambda *a, **k: copy.deepcopy(items))
    monkeypatch.setattr(joberty_client, "fetch_detail", detail)
    provider = joberty_provider.JobertyProvider(ledger_path=tmp_path / "none.json")
    returned, outcome, stage = collect(provider, run, "joberty", tmp_path, SERBIA)

    assert len(seen_at_detail) == 3 and [len(x) for x in seen_at_detail] == [0, 1, 1], "ad 2 had no text: not returned, not staged"
    assert stage.jobs == returned and [b.part for b in stage.batches if b.jobs] == ["ad 1", "ad 3"]
    assert stage.footer["read"] == 3 and stage.footer["kept"] == 2 and stage.complete


def test_joberty_an_ad_the_ledger_holds_is_staged_as_returned_without_a_request(run, monkeypatch, tmp_path):
    from test_joberty import CITIES, product_ad
    import job_history

    item = product_ad(7)
    ledger = tmp_path / "job_history.json"
    first = joberty_provider.to_canonical(copy.deepcopy(item))
    job_history.save(ledger, {"version": 1, "updatedAt": None, "jobs": {first["jobId"]: {"job": {"description": "x" * 300}}}})
    monkeypatch.setattr(joberty_client, "fetch_cities", lambda: CITIES)
    monkeypatch.setattr(joberty_client, "fetch_listing", lambda *a, **k: [copy.deepcopy(item)])
    monkeypatch.setattr(joberty_client, "fetch_detail", lambda job_id: pytest.fail("no request for a known ad"))
    returned, _, stage = collect(joberty_provider.JobertyProvider(ledger_path=ledger), run, "joberty", tmp_path, SERBIA)
    assert len(returned) == 1 and stage.jobs == returned and returned[0]["description"] == "", "the ledger restores it at commit, not here"


# --- the ones that cannot stream: a single response ----------------------------------------------------------------


def test_remoteok_and_yc_are_one_response_so_they_are_staged_whole_when_it_returns(run, monkeypatch, tmp_path):
    ok = remoteok_provider.RemoteOKProvider()
    monkeypatch.setattr(ok, "_fetch_all", lambda: [{"position": "Product Manager", "company": "A", "url": "https://r.example/1", "description": "d"}])
    returned, _, stage = collect(ok, run, "remoteok", tmp_path)
    assert [b.part for b in stage.batches] == ["all"] and stage.jobs == returned

    yc = yc_provider.YCProvider()
    monkeypatch.setattr(yc, "_fetch_all", lambda: [{"title": "Product Manager", "company": {"name": "Y"}, "location": "Remote", "url": "https://y.example/1"}])
    returned, _, stage = collect(yc, run, "yc", tmp_path)
    assert [b.part for b in stage.batches] == ["all"] and stage.jobs == returned


# --- killed mid-source: every finished search is readable, the live files are untouched ------------------------------


def test_sigkill_during_a_jobspy_run_keeps_every_finished_search_and_touches_no_live_file(tmp_path):
    jobs_dir = tmp_path / "data/jobs"
    jobs_dir.mkdir(parents=True)
    live = {name: f"live {name}".encode() for name in ("job_history.json", "discovered_jobs.json", "normalized_jobs.json", "raw_jobs.csv")}
    for name, data in live.items():
        (jobs_dir / name).write_bytes(data)
    intelligence = tmp_path / "intel.json"
    intelligence.write_text(json.dumps({"searchStrategy": {
        "country": "Serbia", "jobSpySearchTerms": ["Product Manager", "Product Lead", "Product Owner"],
        "locationFilters": ["Remote", "Serbia"], "remoteFilters": ["remote"],
    }}))
    driver = tmp_path / "driver.py"
    driver.write_text(textwrap.dedent(f"""
        import os, signal, sys
        from pathlib import Path
        for sub in ("job_discovery", "job_scoring"):
            sys.path.append(str(Path({str(ROOT)!r}) / "python" / sub))
        sys.path.insert(0, str(Path({str(ROOT)!r}) / "python" / "job_discovery"))
        import pandas as pd
        import run_discovery
        from providers import jobspy_provider

        calls = []
        def fake_fetch(term, location, remote=False, country=""):
            calls.append((term, location))
            if len(calls) == 5:
                os.kill(os.getpid(), signal.SIGKILL)   # the fifth search is under way
            return pd.DataFrame([
                {{"title": "Product Manager", "company": "A", "location": "Remote", "id": f"li-{{len(calls)}}",
                  "job_url": f"https://x.example/{{len(calls)}}", "description": "d", "site": "linkedin"}},
                {{"title": "Sales Lead", "company": "A", "location": "Remote", "id": f"sl-{{len(calls)}}",
                  "job_url": f"https://x.example/sales{{len(calls)}}", "description": "d", "site": "linkedin"}},
            ])

        jobspy_provider.fetch_jobs = fake_fetch
        run_discovery.ROOT = Path({str(tmp_path)!r})
        run_discovery.effective_provider_names = lambda spec: ["jobspy"]
        sys.argv = ["run_discovery.py", "--providers", "jobspy", "--intelligence", {str(intelligence)!r}]
        run_discovery.main()
    """))
    env = dict(os.environ, HOLOJOB_ANALYTICS_DIR=str(tmp_path / "analytics"), HOLOJOB_PIPELINE_LOCK=str(tmp_path / "lock"))
    done = subprocess.run([sys.executable, str(driver)], env=env, capture_output=True)
    assert done.returncode == -signal.SIGKILL, done.stderr.decode()[-800:]

    [run_id] = staging.list_runs(tmp_path)
    stage = staging.read_run(tmp_path, run_id).sources["jobspy"]
    assert len(stage.batches) == 4, "four searches had finished"
    assert [j["jobUrl"][-1] for j in stage.jobs] == ["1", "2", "3", "4"] and not stage.torn
    assert not stage.finished and not stage.complete, "no footer: this source was stopped"
    found = staging.read_run(tmp_path, run_id)
    assert [d["externalId"] for d in found.discards.records] == ["sl-1", "sl-2", "sl-3", "sl-4"], "the drops of finished searches too"
    assert {d["reason"] for d in found.discards.records} == {"title_not_matched"}
    assert list(stage.external_ids.values()) == ["li-1", "li-2", "li-3", "li-4"]
    for name, data in live.items():
        assert (jobs_dir / name).read_bytes() == data, name
    assert sorted(p.name for p in jobs_dir.iterdir()) == sorted([*live, "staging"])
    assert staging.read_run(tmp_path, run_id).ledger_before.read_bytes() == live["job_history.json"]
