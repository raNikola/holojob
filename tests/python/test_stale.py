"""The Stale flag (slice S5f): 30 days and 3 proven runs of the same source and search. A flag only. Offline; every path is under tmp_path."""

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

import all_ads
import importer
import job_history as jh
import row_state
import staging
import stale_rule
import view_guard
from providers.base_provider import board_read, dropped_ad
from test_filtered_ads import ad
from test_import import canon
from test_readers_not_found import VIEW_META

START = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
SEEN = START.isoformat()
KEY = "k"


def day(n, seconds=0):
    return (START + timedelta(days=n, seconds=seconds)).isoformat()


def entry(**fields):
    return {"provider": "jobspy", "seenUnder": KEY, "lastSeen": SEEN, "closedAt": None, "job": {"jobId": "a", "source": "jobspy"}, **fields}


def runs_at(*moments, provider="jobspy", bucket=KEY):
    return {provider: {bucket: [{"runId": f"r{i}", "at": at} for i, at in enumerate(moments)]}}


# --- the rule ------------------------------------------------------------------------------------------------------------------


def test_the_numbers():
    assert stale_rule.STALE_DAYS == 30 and stale_rule.STALE_RUNS == 3


def test_30_days_and_3_runs_is_stale_exactly_at_the_boundary():
    proof = stale_rule.evidence(entry(), runs_at(day(10), day(20), day(30)))
    assert proof == {"days": 30, "runs": 3, "capped": False}


def test_one_second_short_of_30_days_is_not():
    assert stale_rule.evidence(entry(), runs_at(day(10), day(20), day(30, -1))) is None


def test_30_days_with_2_runs_is_not():
    assert stale_rule.evidence(entry(), runs_at(day(20), day(40))) is None


def test_the_date_alone_never_makes_an_ad_stale():
    assert stale_rule.evidence(entry(lastSeen=day(-400)), {}) is None
    assert stale_rule.evidence(entry(lastSeen=day(-400)), None) is None


def test_3_runs_inside_30_days_is_not():
    assert stale_rule.evidence(entry(), runs_at(day(1), day(2), day(3))) is None


def test_runs_before_or_at_the_sighting_do_not_count():
    assert stale_rule.evidence(entry(), runs_at(day(-2), day(-1), SEEN, day(30))) is None
    assert stale_rule.evidence(entry(), runs_at(day(-1), day(1), day(2), day(30)))["runs"] == 3


def test_the_runs_prove_the_gap_not_the_clock():
    """A pause in scraping proves nothing: the newest run is what counts, however long ago it was."""
    assert stale_rule.evidence(entry(), runs_at(day(1), day(2), day(3))) is None
    assert "now" not in stale_rule.__dict__ and "datetime.now" not in open(stale_rule.__file__).read()


def test_a_closed_ad_is_never_stale():
    assert stale_rule.evidence(entry(closedAt=day(5)), runs_at(day(10), day(20), day(30))) is None


@pytest.mark.parametrize("runs", [runs_at(day(10), day(20), day(30), bucket="other"), runs_at(day(10), day(20), day(30), provider="workable")])
def test_runs_of_another_search_or_source_do_not_count(runs):
    assert stale_rule.evidence(entry(), runs) is None


@pytest.mark.parametrize("fields", [{"lastSeen": None}, {"lastSeen": "not a date"}, {"seenUnder": ""}, {"seenUnder": None}])
def test_a_missing_mark_gives_no_stale(fields):
    assert stale_rule.evidence(entry(**fields), runs_at(day(10), day(20), day(30))) is None


def test_a_listing_a_filter_dropped_is_a_sighting():
    runs = runs_at(day(10), day(20), day(30))
    assert stale_rule.evidence(entry(lastListedAt=day(1)), runs) is None
    assert stale_rule.evidence(entry(lastListedAt=day(-5)), runs)["days"] == 30


def test_a_snapshot_ad_counts_its_board_and_ignores_the_search_key():
    snapshot = entry(provider="greenhouse", seenUnder="any", job={"jobId": "a", "source": "acme"})
    assert stale_rule.evidence(snapshot, runs_at(day(10), day(20), day(30), provider="greenhouse", bucket="board:acme"))["runs"] == 3
    assert stale_rule.evidence(snapshot, runs_at(day(10), day(20), day(30), provider="greenhouse", bucket="board:other")) is None
    assert stale_rule.evidence(snapshot, runs_at(day(10), day(20), day(30), provider="greenhouse", bucket="any")) is None
    assert stale_rule.entry_bucket(entry(provider="lever", job={})) is None


def test_the_snapshot_list_is_the_ledgers():
    assert stale_rule.SNAPSHOT_PROVIDERS == jh.CLOSURE_PROVIDERS


def test_odd_rows_in_the_record_are_ignored():
    runs = {"jobspy": {KEY: ["text", {"at": "not a date"}, {"at": day(10)}, {"at": day(20)}, {"at": day(30)}]}}
    assert stale_rule.evidence(entry(), runs)["runs"] == 3


def test_record_run_counts_a_run_once_in_time_order_and_stays_bounded():
    ledger = {}
    stale_rule.record_run(ledger, "jobspy", KEY, "b", day(2))
    stale_rule.record_run(ledger, "jobspy", KEY, "a", day(1))
    stale_rule.record_run(ledger, "jobspy", KEY, "b", day(2))
    assert [r["runId"] for r in ledger["sourceRuns"]["jobspy"][KEY]] == ["a", "b"]
    for n in range(150):
        stale_rule.record_run(ledger, "jobspy", KEY, f"n{n}", day(10 + n))
    kept = ledger["sourceRuns"]["jobspy"][KEY]
    assert len(kept) == stale_rule.MAX_RUNS_KEPT and kept[-1]["runId"] == "n149"


def test_past_the_bound_it_says_at_least():
    runs = [{"runId": f"n{i}", "at": day(1 + i)} for i in range(stale_rule.MAX_RUNS_KEPT)]
    assert stale_rule.evidence(entry(), {"jobspy": {KEY: runs}})["capped"] is True
    answer = all_ads.ledger_reason("stale", entry(), source_runs={"jobspy": {KEY: runs}})
    assert "100 or more successful runs of this search" in answer


# --- which runs count, through the real importer ------------------------------------------------------------------------------


def staged(root, monkeypatch, run_id, at, sources, key=KEY):
    with monkeypatch.context() as patch:
        patch.setattr(staging, "_now", lambda: at)
        run = staging.StagingRun.begin(root, run_id, search_key=key, terms=["pm"], locations=["Remote"], country="Serbia", remote_filters=[], providers=list(sources))
        for name, (ads, footer, dropped) in sources.items():
            writer = run.open_source(name)
            writer.append(ads, part="p", read=len(ads) + len(dropped))
            writer.drops(dropped)
            if footer is not None:
                writer.finish(**{"status": "ok", "complete": True, "read": len(ads) + len(dropped), "kept": len(ads), **footer})
        run.finish()
    return run_id


def imported(root, run_id):
    outcome = importer.import_staged_run(root, run_id)
    assert outcome.ok, outcome.refused
    return outcome


def ledger_at(root):
    return json.loads((root / "data/jobs/job_history.json").read_text())


def counted(root, provider="jobspy", bucket=KEY):
    return [r["runId"] for r in ledger_at(root).get("sourceRuns", {}).get(provider, {}).get(bucket, [])]


JOB = canon(1, provider="jobspy")
OTHER = canon(2, provider="jobspy")
GOOD = {}


def good_run(root, monkeypatch, run_id, at, ads=(JOB,), **kw):
    return imported(root, staged(root, monkeypatch, run_id, at, {"jobspy": (list(ads), GOOD, [])}, **kw))


def test_a_finished_run_of_a_source_counts(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0))
    assert counted(tmp_path) == ["a"]
    assert ledger_at(tmp_path)["sourceRuns"]["jobspy"][KEY][0]["at"] == day(0)


@pytest.mark.parametrize("footer", [{"status": "failed", "complete": False}, {"status": "partial", "complete": False}, {"status": "skipped", "complete": False}, None],
                         ids=["failed", "partial", "skipped", "unfinished"])
def test_a_run_that_did_not_finish_well_does_not_count(tmp_path, monkeypatch, footer):
    imported(tmp_path, staged(tmp_path, monkeypatch, "a", day(0), {"jobspy": ([JOB], footer, []), "workable": ([canon(3, provider="workable")], GOOD, [])}))
    assert counted(tmp_path) == []
    assert counted(tmp_path, "workable") == ["a"], "the other source of that run counts for itself"


def test_a_run_that_read_nothing_does_not_count(tmp_path, monkeypatch):
    imported(tmp_path, staged(tmp_path, monkeypatch, "a", day(0), {"jobspy": ([], GOOD, [])}))
    assert counted(tmp_path) == []


@pytest.mark.parametrize("extra", [{"boardsFailed": ["x"]}, {"discardMismatch": True}, {"mismatch": True}, {"invalid": 1}], ids=["part failed", "discards off", "staged differ", "ad lost"])
def test_a_run_whose_books_do_not_balance_does_not_count(tmp_path, monkeypatch, extra):
    imported(tmp_path, staged(tmp_path, monkeypatch, "a", day(0), {"jobspy": ([JOB], extra, [])}))
    assert counted(tmp_path) == []


def test_a_run_with_damaged_discards_does_not_count(tmp_path, monkeypatch):
    staged(tmp_path, monkeypatch, "a", day(0), {"jobspy": ([JOB], GOOD, [])})
    with open(tmp_path / "data/jobs/staging/a/discards.jsonl", "ab") as handle:
        handle.write(b"not json\n")
    imported(tmp_path, "a")
    assert counted(tmp_path) == []


def test_a_disabled_source_gets_no_run(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0))
    imported(tmp_path, staged(tmp_path, monkeypatch, "b", day(1), {"workable": ([canon(3, provider="workable")], GOOD, [])}))
    assert counted(tmp_path) == ["a"]


def test_a_run_with_no_search_key_does_not_count(tmp_path, monkeypatch):
    imported(tmp_path, staged(tmp_path, monkeypatch, "a", day(0), {"jobspy": ([JOB], GOOD, [])}, key=""))
    assert ledger_at(tmp_path).get("sourceRuns") in (None, {})


def test_runs_are_counted_under_their_own_key(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), key="old")
    good_run(tmp_path, monkeypatch, "b", day(1), key="new")
    assert counted(tmp_path, bucket="old") == ["a"] and counted(tmp_path, bucket="new") == ["b"]


def test_the_same_run_imported_again_counts_once(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0))
    before = (tmp_path / "data/jobs/job_history.json").read_bytes()
    assert imported(tmp_path, "a").committed is False
    assert (tmp_path / "data/jobs/job_history.json").read_bytes() == before


def test_a_dry_run_of_a_run_imported_before_this_slice_still_compares_clean(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0))
    now = ledger_at(tmp_path)
    now["jobs"][JOB["jobId"]]["lastListedAt"] = day(0)
    older = copy.deepcopy(now)
    del older["sourceRuns"]
    del older["jobs"][JOB["jobId"]]["lastListedAt"]
    assert importer.compare_ledgers(now, older, "new", "old").items == []
    view = {"meta": {}, "jobs": [{"jobId": "a", "isStale": True}]}
    assert importer.compare_views(view, {"meta": {}, "jobs": [{"jobId": "a"}]}, "new", "old").items == []


def test_a_dry_run_writes_no_record(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0))
    staged(tmp_path, monkeypatch, "b", day(1), {"jobspy": ([JOB], GOOD, [])})
    before = (tmp_path / "data/jobs/job_history.json").read_bytes()
    importer.dry_run(tmp_path, "b")
    assert (tmp_path / "data/jobs/job_history.json").read_bytes() == before


def test_the_report_says_what_was_counted(tmp_path, monkeypatch):
    assert good_run(tmp_path, monkeypatch, "a", day(0)).result.report["provenRuns"] == ["jobspy"]


def board_run(root, monkeypatch, run_id, at, provider, jobs, *, complete=True, failed=()):
    with monkeypatch.context() as patch:
        patch.setattr(staging, "_now", lambda: at)
        run = staging.StagingRun.begin(root, run_id, search_key=KEY, terms=["pm"], locations=["Remote"], country="Serbia", remote_filters=[], providers=[provider])
        writer = run.open_source(provider)
        writer.append(jobs, part="acme", read=len(jobs))
        writer.finish(status="ok", complete=True, read=len(jobs), kept=len(jobs), boardsFailed=list(failed),
                      boardsRead=[board_read("acme", read=len(jobs), postings=len(jobs), complete=complete, reason=None)])
        run.finish()
    return imported(root, run_id)


def test_a_board_counts_only_when_proven_complete(tmp_path, monkeypatch):
    board_run(tmp_path, monkeypatch, "a", day(0), "greenhouse", [canon(1, source="acme")])
    assert counted(tmp_path, "greenhouse", "board:acme") == ["a"]
    assert ledger_at(tmp_path)["sourceRuns"]["greenhouse"].keys() == {"board:acme"}, "no search key for a board"
    board_run(tmp_path, monkeypatch, "b", day(1), "greenhouse", [canon(1, source="acme")], complete=False)
    assert counted(tmp_path, "greenhouse", "board:acme") == ["a"]
    board_run(tmp_path, monkeypatch, "c", day(2), "greenhouse", [canon(1, source="acme")], failed=["acme"])
    assert counted(tmp_path, "greenhouse", "board:acme") == ["a"]


def test_a_board_that_can_never_prove_itself_gets_no_runs(tmp_path, monkeypatch):
    """Ashby's boards are never complete (S5b), so its ads never go Stale, as they never close."""
    board_run(tmp_path, monkeypatch, "a", day(0), "ashby", [canon(1, provider="ashby", source="acme")], complete=False)
    assert "ashby" not in (ledger_at(tmp_path).get("sourceRuns") or {})


def test_a_snapshot_ad_a_proven_board_stops_listing_closes_first(tmp_path, monkeypatch):
    job, other = canon(1, source="acme"), canon(2, source="acme")
    board_run(tmp_path, monkeypatch, "a", day(0), "greenhouse", [job, other])
    for n, run_id in enumerate(("b", "c", "d")):
        board_run(tmp_path, monkeypatch, run_id, day(20 + n * 10), "greenhouse", [other])
    answer = all_ads.build(ledger_at(tmp_path), None)
    assert {row["jobId"]: row["class"] for row in answer["rows"]}[job["jobId"]] == "closed"
    assert answer["meta"]["counts"]["stale"] == 0


# --- the whole way -------------------------------------------------------------------------------------------------------------


def classes(root):
    return {row["jobId"]: row["class"] for row in all_ads.build(ledger_at(root), None)["rows"]}


def scenario(root, monkeypatch, moments, footers=None):
    """JOB found at day 0, then runs that return only OTHER."""
    good_run(root, monkeypatch, "start", day(0), ads=(JOB, OTHER))
    for n, at in enumerate(moments):
        footer = (footers or {}).get(n, GOOD)
        imported(root, staged(root, monkeypatch, f"r{n}", at, {"jobspy": ([OTHER], footer, [])}))


def test_an_ad_goes_stale_through_real_imports(tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch, [day(10), day(20), day(30)])
    found = classes(tmp_path)
    assert found[JOB["jobId"]] == "stale" and found[OTHER["jobId"]] == "found"
    row = next(r for r in all_ads.build(ledger_at(tmp_path), None)["rows"] if r["jobId"] == JOB["jobId"])
    assert row["reason"] == "No sighting for 30 days and 3 successful runs of this search. Last seen 2026-10-01"


def test_one_run_short_or_one_second_short_it_is_absent(tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch, [day(20), day(30)])
    assert classes(tmp_path)[JOB["jobId"]] == "absent"
    (other := tmp_path / "b").mkdir()
    scenario(other, monkeypatch, [day(10), day(20), day(30, -1)])
    assert classes(other)[JOB["jobId"]] == "absent"


def test_a_failed_run_does_not_count_towards_it(tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch, [day(10), day(20), day(30)], footers={1: {"status": "failed", "complete": False}})
    assert classes(tmp_path)[JOB["jobId"]] != "stale"


def test_a_later_sighting_ends_it_and_the_count_starts_over(tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch, [day(10), day(20), day(30)])
    good_run(tmp_path, monkeypatch, "back", day(40), ads=(JOB, OTHER))
    assert classes(tmp_path)[JOB["jobId"]] == "found"
    imported(tmp_path, staged(tmp_path, monkeypatch, "after", day(80), {"jobspy": ([OTHER], GOOD, [])}))
    assert classes(tmp_path)[JOB["jobId"]] == "absent", "one run since, however long ago it was seen"


def test_a_stale_ad_seen_again_loses_the_flag_and_returns_to_the_actionable_buckets(tmp_path, monkeypatch):
    """The whole way back, through real imports: Stale -> found again. The ad is a view row again, with no `isStale` and no not-found mark, so it is in the
    scoring corpus and the model calls again; the class and the counts say found; the ledger's history is not rewritten."""
    scenario(tmp_path, monkeypatch, [day(10), day(20), day(30)])
    assert JOB["jobId"] not in {r["jobId"] for r in view_guard.derive_view(ledger_at(tmp_path))["jobs"]}, "a search-based miss is out of the view"
    assert all_ads.build(ledger_at(tmp_path), None)["meta"]["counts"]["stale"] == 1

    good_run(tmp_path, monkeypatch, "back", day(40), ads=(JOB, OTHER))
    view = json.loads((tmp_path / "data/jobs/discovered_jobs.json").read_text())
    after = next(r for r in view["jobs"] if r["jobId"] == JOB["jobId"])
    assert "isStale" not in after and not row_state.not_found(after)
    assert after["lastSeen"] == day(40)
    counts = all_ads.build(ledger_at(tmp_path), None)["meta"]["counts"]
    assert counts["stale"] == 0 and counts["found"] == 2 and counts["absent"] == 0 and counts["held"] == 0
    assert classes(tmp_path)[JOB["jobId"]] == "found"
    assert ledger_at(tmp_path)["jobs"][JOB["jobId"]]["firstSeen"] == day(0), "seen again is not a new ad"


def test_a_filter_dropped_listing_keeps_it_from_going_stale_and_changes_no_history(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "start", day(0), ads=(JOB, OTHER))
    for n, at in enumerate((day(10), day(20))):
        imported(tmp_path, staged(tmp_path, monkeypatch, f"r{n}", at, {"jobspy": ([OTHER], GOOD, [])}))
    listed = dropped_ad({**ad(1), "jobId": JOB["jobId"], "jobUrl": JOB["jobUrl"]}, "title_not_matched", "e")
    imported(tmp_path, staged(tmp_path, monkeypatch, "r2", day(30), {"jobspy": ([OTHER], GOOD, [listed])}))
    one = ledger_at(tmp_path)["jobs"][JOB["jobId"]]
    assert one["lastListedAt"] == day(30) and one["lastSeen"] == day(0)
    assert classes(tmp_path)[JOB["jobId"]] == "absent"


def test_an_older_key_row_is_not_stale_by_the_runs_of_another_search(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "start", day(0), ads=(JOB, OTHER), key="old")
    for n, at in enumerate((day(10), day(20), day(30))):
        good_run(tmp_path, monkeypatch, f"r{n}", at, ads=(OTHER,), key="new")
    assert classes(tmp_path)[JOB["jobId"]] == "older_key"


def test_stale_comes_before_held_and_absent_and_after_found_and_closed():
    ledger = {"lastImport": {"runId": "now", "meta": {"providers": ["jobspy"]}}, "sourceRuns": runs_at(day(10), day(20), day(30)), "jobs": {
        "found": entry(lastRunId="now"), "closed": entry(closedAt=day(5)), "held": entry(heldRunId="now"), "proven": entry(absentSince=day(5)), "plain": entry(),
    }}
    for job_id, one in ledger["jobs"].items():
        one["job"] = {"jobId": job_id}
    assert {r["jobId"]: r["class"] for r in all_ads.build(ledger, None)["rows"]} == {"found": "found", "closed": "closed", "held": "stale", "proven": "stale", "plain": "stale"}


def test_the_flag_changes_no_entry_history(tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch, [day(10), day(20)])
    before = copy.deepcopy(ledger_at(tmp_path)["jobs"][JOB["jobId"]])
    imported(tmp_path, staged(tmp_path, monkeypatch, "r2", day(30), {"jobspy": ([OTHER], GOOD, [])}))
    after = ledger_at(tmp_path)["jobs"][JOB["jobId"]]
    assert classes(tmp_path)[JOB["jobId"]] == "stale"
    assert after == before, "the class is worked out on reading; nothing is written on the entry"


# --- the view ---------------------------------------------------------------------------------------------------------------


def held_ledger():
    ledger = {"generation": 3, "lastImport": {"runId": "now", "at": day(30), "startedAt": day(30), "meta": {**VIEW_META, "providers": ["jobspy"]}, "marksNotFound": True},
              "sourceRuns": runs_at(day(10), day(20), day(30)), "jobs": {
                  "held": {**entry(heldRunId="now", firstSeen=SEEN), "job": {"jobId": "held", "title": "H", "provider": "jobspy"}},
                  "recent": {**entry(heldRunId="now", lastSeen=day(25), firstSeen=SEEN), "job": {"jobId": "recent", "title": "R", "provider": "jobspy"}},
                  "found": {**entry(lastRunId="now", lastRunPos=0, firstSeen=SEEN), "job": {"jobId": "found", "title": "F", "provider": "jobspy"}},
              }}
    return ledger


def test_the_view_marks_a_held_row_that_is_stale_and_only_that(tmp_path):
    rows = {row["jobId"]: row for row in view_guard.derive_view(held_ledger())["jobs"]}
    assert rows["held"]["isStale"] is True and "isStale" not in rows["recent"] and "isStale" not in rows["found"]
    assert row_state.not_found(rows["held"]), "out of the corpus and of model calls, as it already was as a held row"
    assert jh.STALE_MARK in jh.HISTORY_FIELDS


def test_a_held_stale_row_found_by_the_next_import_loses_the_flag_in_the_view():
    ledger = held_ledger()
    rows = {row["jobId"]: row for row in view_guard.derive_view(ledger)["jobs"]}
    assert rows["held"]["isStale"] is True and row_state.not_found(rows["held"])
    entry_ = ledger["jobs"]["held"]
    entry_.update(lastRunId="next", lastRunPos=0, lastSeen=day(40))
    entry_.pop("heldRunId")
    ledger["lastImport"] = {**ledger["lastImport"], "runId": "next"}
    again = {row["jobId"]: row for row in view_guard.derive_view(ledger)["jobs"]}
    assert "isStale" not in again["held"] and not row_state.not_found(again["held"])
    assert all_ads.build(ledger, None)["rows"] and next(r for r in all_ads.build(ledger, None)["rows"] if r["jobId"] == "held")["class"] == "found"


def test_a_ledger_from_before_derives_the_same_bytes():
    ledger = held_ledger()
    del ledger["sourceRuns"]
    view = view_guard.derive_view(ledger)
    assert "isStale" not in json.dumps(view)
    ledger["sourceRuns"] = {}
    assert view_guard.derive_view(ledger) == view


def test_a_ledger_from_before_has_no_stale_row():
    ledger = held_ledger()
    del ledger["sourceRuns"]
    assert all_ads.build(ledger, None)["meta"]["counts"]["stale"] == 0


def test_classes_do_not_depend_on_the_view_or_the_clock(tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch, [day(10), day(20), day(30)])
    before = classes(tmp_path)
    jobs, ledger_file = tmp_path / "data/jobs/discovered_jobs.json", tmp_path / "data/jobs/job_history.json"
    jobs.unlink()
    assert view_guard.ensure(jobs, ledger_file)["regenerated"] is True
    assert classes(tmp_path) == before
    moved = ledger_at(tmp_path)
    moved["lastImport"]["at"] = "2099-01-01T00:00:00+00:00"
    moved["updatedAt"] = "2099-01-01T00:00:00+00:00"
    assert {r["jobId"]: r["class"] for r in all_ads.build(moved, None)["rows"]} == before


def test_the_route_needs_only_the_standard_library_still():
    source = open(stale_rule.__file__, encoding="utf-8").read()
    assert not [line for line in source.splitlines() if line.startswith(("import ", "from ")) and not line.startswith(("from __future__", "from datetime"))]
