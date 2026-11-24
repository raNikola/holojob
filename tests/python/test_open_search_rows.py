"""Open ads of a search source that the list no longer holds are scored (owner decision 2026-11-24): free, marked not found, no paid step.

The list file (discovered_jobs.json) is not changed by this; only the scoring input is. Closing rules of proven boards and the skipped-source
carry-over have their own tests (test_job_history.py, test_stale.py); here they are checked only as far as this change could touch them.
"""
import json
import sys
from pathlib import Path

import pytest

import all_ads
import job_history
import row_state
import run_scoring
from job_history import open_search_rows

ROOT = Path(__file__).resolve().parents[2]
INTEL = json.loads((ROOT / "data/examples/candidate-intelligence.example.json").read_text(encoding="utf-8"))
AD = ("Own the product roadmap and discovery for a payments platform. You will work with engineering, design and "
      "stakeholders, define strategy and deliver measurable outcomes. Requirements: five years of product experience.")


def job(job_id, provider, url=None, **extra):
    return {"jobId": job_id, "title": "Senior Product Manager", "company": f"Co {job_id}", "location": "Remote", "isRemote": True,
            "description": AD, "jobUrl": url or f"https://x.example/{job_id}", "provider": provider, **extra}


def entry(row, **extra):
    return {"job": row, "provider": row["provider"], "firstSeen": "2026-11-01T10:00:00+00:00", "lastSeen": "2026-11-10T10:00:00+00:00", **extra}


def ledger_of(**entries):
    ledger = job_history.empty_ledger()
    ledger["jobs"] = entries
    return ledger


RUN, KEY = "run2", "key-now"


def after_import(**entries):
    """A ledger whose last import (RUN, search KEY, sources greenhouse and jobspy) found the entries marked `lastRunId`."""
    ledger = ledger_of(**entries)
    ledger["lastImport"] = {"runId": RUN, "at": "2026-11-12T10:00:00+00:00", "meta": {"providers": ["greenhouse", "jobspy"]}}
    return ledger


def seen(row, found=False, key=KEY, **extra):
    return entry(row, seenUnder=key, **({"lastRunId": RUN} if found else {"lastRunId": "run1"}), **extra)


def test_an_open_search_ad_the_list_lacks_gets_a_marked_row_with_its_ledger_dates():
    [row] = open_search_rows(ledger_of(spy1=entry(job("spy1", "jobspy"), llmFacts={"_fingerprint": "f"})), set())
    assert row["jobId"] == "spy1" and row[row_state.MARK] is True and row["isClosed"] is False
    assert row["lastSeen"] == "2026-11-10T10:00:00+00:00" and row["firstSeen"] == "2026-11-01T10:00:00+00:00"
    assert row["llmFacts"] == {"_fingerprint": "f"}
    assert row_state.not_found(row) and not row_state.in_idf_corpus(row)


def test_closed_ads_snapshot_sources_listed_ads_and_ads_without_dates_give_no_row():
    ledger = ledger_of(
        closed=entry(job("closed", "jobspy"), closedAt="2026-11-12T10:00:00+00:00"),
        board=entry(job("board", "greenhouse")),  # a proven board: its closing rules are untouched, and it stays out as ever
        listed=entry(job("listed", "jobspy")),
        undated={"job": job("undated", "jobspy"), "provider": "jobspy"},
    )
    assert open_search_rows(ledger, {"listed"}) == []


def test_infostud_workable_and_joberty_count_as_search_sources():
    ledger = ledger_of(**{p: entry(job(p, p)) for p in ("infostud", "workable", "joberty", "lever")})
    assert {r["jobId"] for r in open_search_rows(ledger, set())} == {"infostud", "workable", "joberty"}


def test_only_an_ad_the_latest_search_did_not_return_is_chosen_when_the_scoring_run_asks_for_it():
    ledger = after_import(
        found=seen(job("found", "jobspy"), found=True),
        absent=seen(job("absent", "jobspy")),                       # the search ran and did not return it
        older=seen(job("older", "jobspy"), key="key-before"),       # from an earlier search: stays out of Active, so no score is needed
        skipped=seen(job("skipped", "workable")),                   # its source was not part of the last import
    )
    chosen = open_search_rows(ledger, {"found"}, wanted=all_ads.absent_test(ledger))
    assert [r["jobId"] for r in chosen] == ["absent"]
    # The list of all ads says the same: the scoring input and the route cannot drift apart.
    built = {r["jobId"]: r["class"] for r in all_ads.build(ledger, None)["rows"]}
    assert built == {"found": "found", "absent": "absent", "older": "older_key", "skipped": "unclassified"}


@pytest.fixture
def scoring(tmp_path, monkeypatch):
    (tmp_path / "intel.json").write_text(json.dumps(INTEL))
    (tmp_path / "profile.json").write_text("{}")
    monkeypatch.setattr(run_scoring, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "llm_fit.json")
    monkeypatch.setattr("confirmed_facts.load", lambda *a, **k: [])
    d = tmp_path / "jobs"
    d.mkdir()

    def go(listed, entries, manual=(), ledger=None):
        jobs, out = d / "discovered_jobs.json", tmp_path / "out.json"
        jobs.write_text(json.dumps({"meta": {}, "jobs": listed}))
        job_history.ledger_path(jobs).write_text(json.dumps(ledger if ledger is not None else ledger_of(**entries)))
        (tmp_path / "manual.json").write_text(json.dumps({"version": 1, "jobs": list(manual)}))
        before = jobs.read_bytes()
        monkeypatch.setattr(sys, "argv", ["run_scoring.py", "--intelligence", str(tmp_path / "intel.json"), "--jobs", str(jobs),
                                          "--manual", str(tmp_path / "manual.json"), "--kept", str(d / "kept.json"), "--output", str(out)])
        assert run_scoring.main() == 0
        assert jobs.read_bytes() == before  # the list is not touched
        return {r["jobId"]: r for r in json.loads(out.read_text())["jobs"]}

    return go


def test_a_real_run_scores_the_unreturned_ad_and_moves_no_other_score(scoring):
    listed = [job("a1", "greenhouse"), job("a2", "greenhouse", title="Product Owner")]
    found = {r["jobId"]: seen(r, found=True) for r in listed}
    alone = scoring(listed, {}, ledger=after_import(**found))
    both = scoring(listed, {}, ledger=after_import(**found, spy1=seen(job("spy1", "jobspy")), older=seen(job("older", "jobspy"), key="key-before")))
    assert isinstance(both["spy1"]["matchScore"], int) and both["spy1"][row_state.MARK] is True
    assert both["spy1"]["lastSeen"] == "2026-11-10T10:00:00+00:00"
    pick = lambda rows: {i: json.dumps(rows[i], sort_keys=True) for i in ("a1", "a2")}  # noqa: E731
    assert pick(alone) == pick(both)
    assert "spy1" not in alone
    assert "older" not in both  # not an ad the Active list can show: no score, no 27 KB row


def test_a_hand_entered_job_wins_over_an_unreturned_ad_with_the_same_url(scoring):
    gone = job("spy1", "jobspy", url="https://same.example/1")
    manual = {**job("man1", "manual", url="https://same.example/1"), "manualEntry": True, "status": "new"}
    rows = scoring([], {}, manual=[manual], ledger=after_import(spy1=seen(gone)))
    assert "spy1" not in rows and "man1" in rows
