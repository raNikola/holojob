"""Cancel a running Re-scrape (slice S6): what a cancelled run may and may not change, offline.

A cancelled run saves the ads it validly collected and nothing else: the list is not rebuilt, no ad becomes held, absent, closed or
Stale, no proven run is recorded, `appliedRuns` is not touched. Process-level cancel is in test_cancel_run.py.
"""

import copy
import json

import pytest

import all_ads
import filtered_ads
import import_run
import importer
import row_state
import staging
import view_guard
from providers.base_provider import dropped_ad
from test_filtered_ads import ad
from test_import import canon
from test_stale import (GOOD, JOB, KEY, OTHER, board_run, classes, counted, day, good_run, imported, ledger_at, staged)


def cancel_run(root, monkeypatch, run_id, at, sources, key=KEY):
    """A staged run the owner cancelled: the marker discovery writes before it imports."""
    staged(root, monkeypatch, run_id, at, sources, key=key)
    staging.mark_cancelled(root, run_id, {"requestedAt": at})
    return imported(root, run_id)


def applied(root):
    return filtered_ads.load(root)["appliedRuns"]


def store_bytes(root):
    path = filtered_ads.file_path(root)
    return path.read_bytes() if path.exists() else b""


def files(root):
    return {p.name: p.read_bytes() for p in (root / "data/jobs").glob("*.json")}


def view_rows(root):
    return json.loads((root / "data/jobs/discovered_jobs.json").read_text())["jobs"]


def corpus(rows):
    """What the IDF corpus is built from: every row that is not a row a run did not find."""
    return [r["jobId"] for r in rows if not row_state.not_found(r)]


NEW = canon(3, provider="jobspy")


def test_a_cancelled_run_saves_what_it_collected_and_changes_nothing_else(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    before, rows_before = ledger_at(tmp_path), view_rows(tmp_path)

    outcome = cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([OTHER, NEW], GOOD, [])})

    ledger = ledger_at(tmp_path)
    assert outcome.committed and outcome.saved == 2 and ledger["generation"] == 2
    assert ledger["lastImport"] == before["lastImport"], "the list is still the last complete run's"
    assert ledger["sourceRuns"] == before["sourceRuns"] and applied(tmp_path) == ["a"]
    assert ledger["partialRuns"] == ["b"]
    assert ledger["jobs"][JOB["jobId"]] == before["jobs"][JOB["jobId"]], "an ad it did not find is exactly as it was"
    assert ledger["jobs"][OTHER["jobId"]]["lastSeen"] == day(10) and ledger["jobs"][OTHER["jobId"]]["firstSeen"] == day(0)
    assert NEW["jobId"] in ledger["jobs"]
    rows = view_rows(tmp_path)
    assert [r["jobId"] for r in rows][:len(rows_before)] == [r["jobId"] for r in rows_before], "the rows that were there keep their order"
    assert [r["jobId"] for r in rows][len(rows_before):] == [NEW["jobId"]]
    assert not any(row_state.not_found(r) for r in rows) and not any(r.get("isStale") or r.get("isAbsent") for r in rows)
    assert corpus(rows) == corpus(rows_before) + [NEW["jobId"]], "the corpus does not shrink"
    assert view_guard.state(tmp_path / "data/jobs/discovered_jobs.json", tmp_path / "data/jobs/job_history.json")["consistent"]
    assert all_ads.build(ledger, None)["meta"]["counts"]["found"] == 3 and classes(tmp_path)[JOB["jobId"]] == "found"
    assert outcome.result.report["cancelled"] is True and outcome.result.report["complete"] is False and outcome.result.report["provenRuns"] == []
    store = filtered_ads.load(tmp_path)
    assert store["ads"] == {} and store["appliedRuns"] == ["a"], "no dropped ads, and the run is remembered only as a partial one"


def test_a_run_that_collected_nothing_writes_nothing_at_all(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    before = files(tmp_path)
    outcome = cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([], GOOD, [])})
    assert outcome.ok and not outcome.committed and outcome.saved == 0
    assert outcome.result.report["nothingSaved"] == "no_valid_ads"
    assert files(tmp_path) == before, "not even a generation"
    info = staging.imported_info(tmp_path, "b")
    assert info["committed"] is False and info["saved"] == 0 and info["cancelled"] is True, "marked so staging is pruned like any run"


def test_a_run_that_staged_no_source_at_all_writes_nothing(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    before = files(tmp_path)
    staged(tmp_path, monkeypatch, "b", day(10), {})
    staging.mark_cancelled(tmp_path, "b")
    assert imported(tmp_path, "b").saved == 0 and files(tmp_path) == before


def test_ads_that_were_not_found_are_not_held_absent_closed_or_stale_by_a_cancelled_run(tmp_path, monkeypatch):
    """The held-row consequence the owner turned down: a cancelled run after one source must not turn the rest of the list into held rows."""
    good_run(tmp_path, monkeypatch, "start", day(0), ads=(JOB, OTHER))
    for n, at in enumerate((day(10), day(20))):
        imported(tmp_path, staged(tmp_path, monkeypatch, f"r{n}", at, {"jobspy": ([OTHER], GOOD, [])}))
    before = classes(tmp_path)
    ledger_before = ledger_at(tmp_path)
    cancel_run(tmp_path, monkeypatch, "x", day(30), {"jobspy": ([OTHER, NEW], GOOD, [])})
    after = classes(tmp_path)
    assert after == {**before, NEW["jobId"]: "found"}, "every class is what it was; only the saved ad is new"
    assert ledger_at(tmp_path)["jobs"][JOB["jobId"]] == ledger_before["jobs"][JOB["jobId"]]
    imported(tmp_path, staged(tmp_path, monkeypatch, "r3", day(40), {"jobspy": ([OTHER], GOOD, [])}))
    assert classes(tmp_path)[JOB["jobId"]] == "stale", "the third proven run, not the cancelled one, completes the count"


def test_a_board_a_cancelled_run_read_in_full_still_closes_nothing(tmp_path, monkeypatch):
    job, other = canon(1, source="acme"), canon(2, source="acme")
    board_run(tmp_path, monkeypatch, "a", day(0), "greenhouse", [job, other])
    _board_stage(tmp_path, monkeypatch, "b", day(10), [other])
    staging.mark_cancelled(tmp_path, "b")
    before = ledger_at(tmp_path)["jobs"][job["jobId"]]
    imported(tmp_path, "b")
    assert ledger_at(tmp_path)["jobs"][job["jobId"]] == before
    assert counted(tmp_path, "greenhouse", "board:acme") == ["a"]
    # the same staging without the marker is a proven miss: the marker is what changes the answer
    _board_stage(tmp_path, monkeypatch, "c", day(20), [other])
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


def test_a_cancelled_run_is_never_a_proven_run(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB], GOOD, [])})
    assert counted(tmp_path) == ["a"], "a finished footer does not make a cancelled run count towards Stale"
    good_run(tmp_path, monkeypatch, "c", day(20), ads=(JOB,))
    assert counted(tmp_path) == ["a", "c"] and applied(tmp_path) == ["a", "c"]


def test_an_ad_out_of_the_list_that_a_cancelled_run_collects_comes_back_and_nothing_else_moves(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    imported(tmp_path, staged(tmp_path, monkeypatch, "r1", day(10), {"jobspy": ([OTHER], GOOD, [])}))
    assert JOB["jobId"] not in [r["jobId"] for r in view_rows(tmp_path)], "a search miss is out of the list"
    rows_before = [r["jobId"] for r in view_rows(tmp_path)]
    cancel_run(tmp_path, monkeypatch, "b", day(20), {"jobspy": ([JOB], GOOD, [])})
    assert [r["jobId"] for r in view_rows(tmp_path)] == rows_before + [JOB["jobId"]]


def test_a_different_search_is_not_added_to_this_list(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    before = files(tmp_path)
    outcome = cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([NEW], GOOD, [])}, key="another-search")
    assert outcome.saved == 0 and outcome.result.report["nothingSaved"] == "other_search" and files(tmp_path) == before


def test_with_no_complete_run_to_add_to_nothing_is_saved(tmp_path, monkeypatch):
    outcome = cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([NEW], GOOD, [])})
    assert outcome.saved == 0 and outcome.result.report["nothingSaved"] == "no_complete_run"
    assert not (tmp_path / "data/jobs/job_history.json").exists()


def test_a_cancelled_run_older_than_the_last_import_is_refused_as_any_run_is(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(10), ads=(JOB,))
    staged(tmp_path, monkeypatch, "b", day(5), {"jobspy": ([NEW], GOOD, [])})
    staging.mark_cancelled(tmp_path, "b")
    outcome = importer.import_staged_run(tmp_path, "b")
    assert not outcome.ok and outcome.refused[0].startswith("older_run")


def test_the_dropped_ads_of_a_cancelled_run_are_saved_once_and_never_as_an_applied_run(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    listed = dropped_ad({**ad(1), "jobId": JOB["jobId"], "jobUrl": JOB["jobUrl"]}, "title_not_matched", "e")
    other = dropped_ad({**ad(7), "jobId": "dropped-7", "jobUrl": "https://x.example/7"}, "title_not_matched", "e")
    cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([NEW], GOOD, [listed, other])})

    store = filtered_ads.load(tmp_path)
    assert "dropped-7" in store["ads"] and store["ads"]["dropped-7"]["timesSeen"] == 1
    assert store["appliedRuns"] == ["a"] and store["partialRuns"] == ["b"], "saved, but not presented as one of the complete runs"
    assert "lastListedAt" not in ledger_at(tmp_path)["jobs"][JOB["jobId"]], "a listing seen by a cancelled run proves nothing about Stale"
    assert filtered_ads.unrecorded(tmp_path) == set()

    once = store_bytes(tmp_path)
    assert importer.import_staged_run(tmp_path, "b").ok and store_bytes(tmp_path) == once, "importing it again counts nothing twice"
    assert import_run.main(["--backfill-filtered"], root=tmp_path) == 0
    assert filtered_ads.load(tmp_path)["ads"]["dropped-7"]["timesSeen"] == 1 and filtered_ads.load(tmp_path)["appliedRuns"] == ["a"]


def test_a_cancelled_run_whose_dropped_ads_could_not_be_saved_waits_and_a_backfill_saves_it_once(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    other = dropped_ad({**ad(7), "jobId": "dropped-7", "jobUrl": "https://x.example/7"}, "title_not_matched", "e")
    monkeypatch.setattr(filtered_ads, "record_run", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([NEW], GOOD, [other])})
    staging.mark_cancelled(tmp_path, "b")
    assert any("not recorded" in w for w in importer.import_staged_run(tmp_path, "b").warnings)
    assert filtered_ads.unrecorded(tmp_path) == {"b"}, "it is kept out of pruning until its dropped ads are saved"
    monkeypatch.undo()
    for _ in range(2):
        assert import_run.main(["--backfill-filtered"], root=tmp_path) == 0
    store = filtered_ads.load(tmp_path)
    assert store["ads"]["dropped-7"]["timesSeen"] == 1 and store["partialRuns"] == ["b"] and store["appliedRuns"] == ["a"]
    assert filtered_ads.unrecorded(tmp_path) == set()


def test_a_backfill_skips_a_cancelled_run_that_saved_nothing(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    other = dropped_ad({**ad(7), "jobId": "dropped-7", "jobUrl": "https://x.example/7"}, "title_not_matched", "e")
    cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([], GOOD, [other])})
    report = filtered_ads.backfill(tmp_path, lambda run: day(10))
    line = next(item for item in report["runs"] if item["runId"] == "b")
    assert line["state"].startswith("cancelled run that saved nothing") and report["cancelled"] == 1
    assert "dropped-7" not in filtered_ads.load(tmp_path)["ads"] and "b" not in filtered_ads.unrecorded(tmp_path)


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
    cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB, NEW], GOOD, [])})
    first = files(tmp_path)
    again = importer.import_staged_run(tmp_path, "b")
    assert again.ok and not again.committed and files(tmp_path) == first


def test_the_marker_is_what_the_import_command_obeys_too(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([OTHER, NEW], GOOD, [])})
    staging.mark_cancelled(tmp_path, "b")
    assert import_run.main(["--run", "b", "--import"], root=tmp_path) == 0
    ledger = ledger_at(tmp_path)
    assert ledger["lastImport"]["runId"] == "a" and ledger["partialRuns"] == ["b"] and counted(tmp_path) == ["a"] and "b" not in applied(tmp_path)
    assert NEW["jobId"] in ledger["jobs"]


def test_an_unreadable_marker_still_means_cancelled(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    staged(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB], GOOD, [])})
    (tmp_path / "data/jobs/staging/b" / staging.CANCELLED).write_text("{not json")
    imported(tmp_path, "b")
    assert counted(tmp_path) == ["a"] and ledger_at(tmp_path)["lastImport"]["runId"] == "a"


def test_the_staging_of_a_cancelled_run_follows_the_one_rule_for_imported_runs(tmp_path, monkeypatch):
    """Kept for inspection like any imported run, then pruned by the same count, hard links included. No special case."""
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB,))
    cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([JOB], GOOD, [])})
    base = tmp_path / "data/jobs/staging"
    assert (base / "b" / staging.CANCELLED).is_file() and (base / "b" / staging.IMPORTED).is_file()
    assert staging.imported_info(tmp_path, "b")["cancelled"] is True
    for n in range(4):
        good_run(tmp_path, monkeypatch, f"n{n}", day(20 + n), ads=(JOB,))
    assert not (base / "b").exists() and not list(base.glob("b.*")), "pruned with its two links once three newer runs are imported"


def test_the_next_complete_run_rebuilds_the_list_as_ever(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([OTHER, NEW], GOOD, [])})
    good_run(tmp_path, monkeypatch, "c", day(20), ads=(OTHER, NEW))
    ledger = ledger_at(tmp_path)
    assert ledger["lastImport"]["runId"] == "c" and ledger["generation"] == 3
    assert [r["jobId"] for r in view_rows(tmp_path)] == [OTHER["jobId"], NEW["jobId"]]
    assert counted(tmp_path) == ["a", "c"]


@pytest.mark.parametrize("name", ["../x", "a b", ""])
def test_the_marker_refuses_a_bad_run_id(tmp_path, name):
    (tmp_path / "data/jobs/staging").mkdir(parents=True)
    with pytest.raises(ValueError):
        staging.mark_cancelled(tmp_path, name)
