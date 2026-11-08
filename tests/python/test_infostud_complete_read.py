"""Infostud's complete-read proof (Wave 4, c): how a listing read ends, what the provider says about it, what the importer records,
and that nothing is closed by it while Infostud is not snapshot-based. Offline."""

import json

import pytest

import importer
import job_history
from providers import infostud_client, infostud_provider
from providers.infostud_provider import completeness
from test_discards import infostud_row
from test_staging import discover


# --- fetch_raw: how the read ends -------------------------------------------------------------------------------------------


def paged(monkeypatch, pages, total):
    """Serve `pages` (lists of rows) for page 1, 2, ..., and `total` as the reported total."""
    def get(url):
        return url

    def results(url):
        number = int(url.split("page=")[1].split("&")[0]) if "page=" in url else 1
        rows = pages[number - 1] if number <= len(pages) else []
        return {"totalPrimaryItems": total, "jobs": {"primary": rows}}

    monkeypatch.setattr(infostud_client, "_get", get)
    monkeypatch.setattr(infostud_client, "_search_results", results)
    monkeypatch.setattr(infostud_client.time, "sleep", lambda s: None)


def rows(*ids):
    return [{"id": n} for n in ids]


def read(monkeypatch, pages, total, **kw):
    paged(monkeypatch, pages, total)
    facts = {}
    got, reported = infostud_client.fetch_raw(facts=facts, **kw)
    return got, reported, facts


def test_a_read_that_reaches_the_reported_total_says_so(monkeypatch):
    got, reported, facts = read(monkeypatch, [rows(1, 2), rows(3)], 3)
    assert (len(got), reported) == (3, 3)
    assert facts == {"pages": 2, "capHit": False, "clampHit": False, "emptyEnd": False, "reachedTotal": True}
    assert completeness(3, 3, facts) == (True, None)


def test_the_page_cap_is_recorded_and_is_not_proof(monkeypatch):
    got, reported, facts = read(monkeypatch, [rows(1, 2), rows(3, 4), rows(5)], 5, max_pages=2)
    assert len(got) == 4 and facts["capHit"] is True and facts["reachedTotal"] is False
    assert completeness(4, 5, facts)[0] is False and completeness(4, 5, facts)[1] == infostud_provider.CAP_HIT


def test_a_page_with_no_new_ad_is_recorded_as_the_clamp(monkeypatch):
    got, _, facts = read(monkeypatch, [rows(1, 2), rows(1, 2)], 5)
    assert len(got) == 2 and facts["clampHit"] is True
    assert completeness(2, 5, facts) == (False, infostud_provider.CLAMP_HIT)


def test_an_empty_page_before_the_total_is_not_proof(monkeypatch):
    got, _, facts = read(monkeypatch, [rows(1, 2)], 5)
    assert len(got) == 2 and facts["emptyEnd"] is True
    assert completeness(2, 5, facts) == (False, infostud_provider.EMPTY_BEFORE_TOTAL)


def test_no_reported_total_and_a_mismatch_are_not_proof(monkeypatch):
    got, reported, facts = read(monkeypatch, [], 0)
    assert got == [] and completeness(0, reported, facts) == (False, infostud_provider.NO_TOTAL)
    assert completeness(4, 3, {"reachedTotal": True}) == (False, infostud_provider.TOTAL_MISMATCH)
    assert completeness(3, 3, None)[0] is False and completeness(3, 3, {})[0] is False, "no facts is never proof"


def test_fetch_raw_without_facts_behaves_as_before(monkeypatch):
    paged(monkeypatch, [rows(1, 2), rows(3)], 3)
    got, reported = infostud_client.fetch_raw()
    assert [r["id"] for r in got] == [1, 2, 3] and reported == 3


# --- the provider and the importer ---------------------------------------------------------------------------------------


def serve(monkeypatch, ids, *, total=None, complete=True, titles=None):
    """Make fetch_raw return Infostud rows for `ids` (a Chef for id 99, a Product Manager for the rest)."""
    data = [infostud_row(n, "Chef" if n == 99 else f"Product Manager {n}", "Beograd") for n in ids]

    def fake(categories=None, facts=None, **_):
        if facts is not None:
            facts.update({"pages": 1, "capHit": not complete, "clampHit": False, "emptyEnd": False, "reachedTotal": complete})
        return data, len(data) if total is None else total

    monkeypatch.setattr(infostud_client, "fetch_raw", fake)
    monkeypatch.setattr(infostud_provider, "place_drop_reason", lambda *a: None)  # the place filter is not what these tests are about
    monkeypatch.setattr(infostud_client, "enrich", lambda job, delay=1.0: job)


def last_meta(root):
    return json.loads((root / "data/jobs/job_history.json").read_text())["lastImport"]["meta"]


def test_a_whole_read_is_recorded_as_a_complete_read_in_the_meta(tmp_path, monkeypatch):
    serve(monkeypatch, [1, 2, 99])
    assert discover(tmp_path, monkeypatch, {"infostud": infostud_provider.InfostudProvider()}) == 0
    (row,) = last_meta(tmp_path)["sources"]
    assert row["name"] == "infostud" and row["reportedTotal"] == 3 and row["read"] == 3
    assert row["completeRead"] == {"complete": True, "why": ["board_complete"]}
    assert row["readClass"] == "ok"


def test_a_capped_read_is_recorded_as_not_complete_and_incomplete(tmp_path, monkeypatch):
    serve(monkeypatch, [1, 2, 99], total=10, complete=False)
    discover(tmp_path, monkeypatch, {"infostud": infostud_provider.InfostudProvider()})
    (row,) = last_meta(tmp_path)["sources"]
    assert row["completeRead"]["complete"] is False and row["readClass"] == "incomplete"
    assert "board_not_complete" in row["completeRead"]["why"] or row["completeRead"]["why"], row


def test_the_switch_is_off_and_infostud_closes_nothing(tmp_path, monkeypatch):
    assert job_history.SNAPSHOT_AFTER_PROOF is False and "infostud" not in job_history.CLOSURE_PROVIDERS
    serve(monkeypatch, [1, 2, 99])
    discover(tmp_path, monkeypatch, {"infostud": infostud_provider.InfostudProvider()})
    for _ in range(3):  # three complete reads that no longer list ads 1 and 2
        serve(monkeypatch, [3, 99])
        discover(tmp_path, monkeypatch, {"infostud": infostud_provider.InfostudProvider()})
    jobs = json.loads((tmp_path / "data/jobs/job_history.json").read_text())["jobs"]
    assert jobs and all(entry.get("closedAt") is None for entry in jobs.values())


def test_with_the_switch_on_two_complete_misses_close_and_an_incomplete_read_closes_nothing(tmp_path, monkeypatch):
    # The importer and discovery load their own copies of job_history from the file; the importer's is the one that closes.
    closing = importer.job_history
    monkeypatch.setattr(closing, "CLOSURE_PROVIDERS", set(closing.CLOSURE_PROVIDERS) | {"infostud"})
    serve(monkeypatch, [1, 2, 99])
    discover(tmp_path, monkeypatch, {"infostud": infostud_provider.InfostudProvider()})
    serve(monkeypatch, [2, 99], total=9, complete=False)  # a capped read that misses ad 1: proves nothing
    discover(tmp_path, monkeypatch, {"infostud": infostud_provider.InfostudProvider()})
    serve(monkeypatch, [2, 99])
    discover(tmp_path, monkeypatch, {"infostud": infostud_provider.InfostudProvider()})
    jobs = json.loads((tmp_path / "data/jobs/job_history.json").read_text())["jobs"]
    absent = [e for e in jobs.values() if e.get("absentRuns")]
    assert len(absent) == 1 and absent[0]["absentRuns"] == 1 and absent[0].get("closedAt") is None, "one complete miss, the capped read did not count"
    serve(monkeypatch, [2, 99])
    discover(tmp_path, monkeypatch, {"infostud": infostud_provider.InfostudProvider()})
    jobs = json.loads((tmp_path / "data/jobs/job_history.json").read_text())["jobs"]
    assert sum(1 for e in jobs.values() if e.get("closedAt")) == 1, "the second complete miss closes it"

