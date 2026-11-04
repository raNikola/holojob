"""Cancel a running Re-scrape (slice S6): what a cancelled run may and may not change, offline.

Process-level cancel (SIGTERM, the commit claim, the kill grace, the process tree) is in test_cancel_run.py.
"""

import json

import pytest

import all_ads
import filtered_ads
import import_run
import importer
import job_history as jh
import row_state
import staging
import stale_rule
import view_guard
from providers.base_provider import dropped_ad
from test_filtered_ads import ad
from test_import import canon
from test_stale import (GOOD, JOB, KEY, OTHER, board_run, classes, counted, day, good_run, imported, ledger_at, staged)


def cancel_run(root, monkeypatch, run_id, at, sources):
    """A staged run the owner cancelled: the marker discovery writes before it imports."""
    staged(root, monkeypatch, run_id, at, sources)
    staging.mark_cancelled(root, run_id, {"requestedAt": at})
    return imported(root, run_id)


def applied(root):
    return filtered_ads.load(root)["appliedRuns"]


def store_bytes(root):
    path = filtered_ads.file_path(root)
    return path.read_bytes() if path.exists() else b""


def test_a_cancelled_run_imports_what_it_returned_held_and_nothing_else(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    before = store_bytes(tmp_path)
    outcome = cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([OTHER, canon(3, provider="jobspy")], GOOD, [])})

    ledger = ledger_at(tmp_path)
    assert outcome.committed and ledger["generation"] == 2
    assert ledger["lastImport"]["runId"] == "b" and ledger["lastImport"]["cancelled"] is True
    assert canon(3, provider="jobspy")["jobId"] in ledger["jobs"], "an ad it collected is imported"
    assert ledger["jobs"][OTHER["jobId"]]["lastSeen"] == day(10)
    gone = ledger["jobs"][JOB["jobId"]]
    assert not gone.get("closedAt") and not gone.get("absentSince") and not gone.get("absentRuns"), "it said nothing about the ad it did not return"
    assert gone["heldRunId"] == "b" and gone["lastSeen"] == day(0)
    assert outcome.result.report["cancelled"] is True and outcome.result.report["complete"] is False
    assert outcome.result.report["provenRuns"] == []
    view = json.loads((tmp_path / "data/jobs/discovered_jobs.json").read_text())
    held = next(row for row in view["jobs"] if row["jobId"] == JOB["jobId"])
    assert held[row_state.MARK] is True, "shown, and out of the scoring corpus, as a held row is"
    assert view_guard.state(tmp_path / "data/jobs/discovered_jobs.json", tmp_path / "data/jobs/job_history.json")["consistent"]
    assert store_bytes(tmp_path) == before, "filtered_ads.json is not touched"


def test_a_cancelled_run_is_never_a_proven_run(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB], GOOD, [])})
    assert counted(tmp_path) == ["a"], "a finished footer does not make a cancelled run count towards Stale"
    good_run(tmp_path, monkeypatch, "c", day(20), ads=(JOB,))
    assert counted(tmp_path) == ["a", "c"]
    assert "b" not in applied(tmp_path)
    assert applied(tmp_path) == ["a", "c"]


def test_a_board_a_cancelled_run_read_in_full_still_closes_and_marks_nothing(tmp_path, monkeypatch):
    job, other = canon(1, source="acme"), canon(2, source="acme")
    board_run(tmp_path, monkeypatch, "a", day(0), "greenhouse", [job, other])
    staged_board = lambda run_id, at: _board_stage(tmp_path, monkeypatch, run_id, at, [other])  # noqa: E731
    staged_board("b", day(10))
    staging.mark_cancelled(tmp_path, "b")
    imported(tmp_path, "b")
    entry = ledger_at(tmp_path)["jobs"][job["jobId"]]
    assert not entry.get("absentRuns") and not entry.get("absentSince") and not entry.get("closedAt")
    assert counted(tmp_path, "greenhouse", "board:acme") == ["a"]
    # the same staging without the marker is a proven miss: the marker is what changes the answer
    staged_board("c", day(20))
    imported(tmp_path, "c")
    assert ledger_at(tmp_path)["jobs"][job["jobId"]]["absentRuns"] == 1
    assert counted(tmp_path, "greenhouse", "board:acme") == ["a", "c"]


def _board_stage(root, monkeypatch, run_id, at, jobs):
    from providers.base_provider import board_read

    with monkeypatch.context() as patch:
        patch.setattr(staging, "_now", lambda: at)
        run = staging.StagingRun.begin(root, run_id, search_key=KEY, terms=["pm"], locations=["Remote"], country="Serbia", remote_filters=[], providers=["greenhouse"])
        writer = run.open_source("greenhouse")
        writer.append(jobs, part="acme", read=len(jobs))
        writer.finish(status="ok", complete=True, read=len(jobs), kept=len(jobs), boardsFailed=[],
                      boardsRead=[board_read("acme", read=len(jobs), postings=len(jobs), complete=True, reason=None)])
        run.finish()


def test_a_cancelled_run_marks_no_ad_stale_and_ends_no_stale_ad(tmp_path, monkeypatch):
    """The lifecycle rules are untouched: a cancelled run is not one of the three runs, and an ad it returns was seen."""
    good_run(tmp_path, monkeypatch, "start", day(0), ads=(JOB, OTHER))
    for n, at in enumerate((day(10), day(20))):
        imported(tmp_path, staged(tmp_path, monkeypatch, f"r{n}", at, {"jobspy": ([OTHER], GOOD, [])}))
    cancel_run(tmp_path, monkeypatch, "x", day(30), {"jobspy": ([OTHER], GOOD, [])})
    assert classes(tmp_path)[JOB["jobId"]] == "held", "two proven runs and a cancelled one: not stale"
    imported(tmp_path, staged(tmp_path, monkeypatch, "r3", day(40), {"jobspy": ([OTHER], GOOD, [])}))
    assert classes(tmp_path)[JOB["jobId"]] == "stale", "the third proven run, not the cancelled one, completes the count"


def test_the_dropped_ads_of_a_cancelled_run_are_not_counted_by_any_path(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    listed = dropped_ad({**ad(1), "jobId": JOB["jobId"], "jobUrl": JOB["jobUrl"]}, "title_not_matched", "e")
    other = dropped_ad({**ad(7), "jobId": "dropped-7", "jobUrl": "https://x.example/7"}, "title_not_matched", "e")
    cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([OTHER], GOOD, [listed, other])})

    assert "dropped-7" not in filtered_ads.load(tmp_path)["ads"] and "b" not in applied(tmp_path)
    assert "lastListedAt" not in ledger_at(tmp_path)["jobs"][JOB["jobId"]], "a listing seen by a cancelled run proves nothing"
    assert "b" not in filtered_ads.unrecorded(tmp_path), "it is not waiting to be counted, so nothing is held back for it"
    assert import_run.main(["--backfill-filtered"], root=tmp_path) == 0
    assert "b" not in applied(tmp_path) and "dropped-7" not in filtered_ads.load(tmp_path)["ads"]


def test_a_backfill_names_the_cancelled_run_and_skips_it(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    other = dropped_ad({**ad(7), "jobId": "dropped-7", "jobUrl": "https://x.example/7"}, "title_not_matched", "e")
    cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([OTHER], GOOD, [other])})
    report = filtered_ads.backfill(tmp_path, lambda run: day(10))
    line = next(item for item in report["runs"] if item["runId"] == "b")
    assert line["state"] == "cancelled run: not counted" and report["cancelled"] == 1
    assert "b" not in filtered_ads.load(tmp_path)["appliedRuns"]


def test_the_lifecycle_report_does_not_read_a_cancelled_run_as_evidence(tmp_path, monkeypatch):
    import lifecycle_report

    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB], GOOD, [])})
    good_run(tmp_path, monkeypatch, "c", day(20), ads=(JOB,))
    seen = []
    real = lifecycle_report.build_report
    monkeypatch.setattr(lifecycle_report, "build_report", lambda start, ledger, runs, **kw: seen.append([r.run_id for r in runs]) or real(start, ledger, runs, **kw))
    lifecycle_report.gather(tmp_path, None, as_of=day(30), measure=False)
    assert seen == [["a", "c"]]


def test_importing_a_cancelled_run_twice_changes_nothing_the_second_time(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB], GOOD, [])})
    first = (tmp_path / "data/jobs/job_history.json").read_bytes()
    again = importer.import_staged_run(tmp_path, "b")
    assert again.ok and not again.committed and (tmp_path / "data/jobs/job_history.json").read_bytes() == first


def test_the_marker_is_what_the_import_command_obeys_too(tmp_path, monkeypatch):
    """Not only the live path: `import_run.py --import` of a staged cancelled run is held as well."""
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([OTHER], GOOD, [])})
    staging.mark_cancelled(tmp_path, "b")
    assert import_run.main(["--run", "b", "--import"], root=tmp_path) == 0
    ledger = ledger_at(tmp_path)
    assert ledger["lastImport"]["cancelled"] is True and counted(tmp_path) == ["a"] and "b" not in applied(tmp_path)
    assert not ledger["jobs"][JOB["jobId"]].get("absentSince")


def test_an_unreadable_marker_still_means_cancelled(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB], GOOD, [])})
    (tmp_path / "data/jobs/staging/b" / staging.CANCELLED).write_text("{not json")
    imported(tmp_path, "b")
    assert counted(tmp_path) == ["a"] and ledger_at(tmp_path)["lastImport"]["cancelled"] is True


def test_the_staging_of_a_cancelled_run_follows_the_one_rule_for_imported_runs(tmp_path, monkeypatch):
    """Kept for inspection like any imported run, then pruned by the same count, hard links included. No special case."""
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB], GOOD, [])})
    base = tmp_path / "data/jobs/staging"
    assert (base / "b" / staging.CANCELLED).is_file() and (base / "b" / staging.IMPORTED).is_file()
    assert json.loads((base / "b" / staging.IMPORTED).read_text())["cancelled"] is True
    for n in range(4):
        good_run(tmp_path, monkeypatch, f"n{n}", day(20 + n), ads=(JOB,))
    assert not (base / "b").exists() and not list(base.glob("b.*")), "pruned with its two links once three newer runs are imported"


@pytest.mark.parametrize("name", ["a", "../x", "a b", ""])
def test_the_marker_refuses_a_bad_run_id(tmp_path, name):
    (tmp_path / "data/jobs/staging").mkdir(parents=True)
    with pytest.raises(ValueError):
        staging.mark_cancelled(tmp_path, name)
