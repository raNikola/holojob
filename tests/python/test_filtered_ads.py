"""data/jobs/filtered_ads.json (slice S5e1): every dropped ad stays findable after its staging run is pruned. Offline; every path is
under tmp_path. The process-kill tests run the real importer in a child process and stop it with os._exit at the named point."""

import copy
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import filtered_ads
import import_run
import importer
import staging
from normalize_jobs import _make_job_id
from providers import (
    ashby_provider,
    greenhouse_provider,
    infostud_client,
    infostud_provider,
    joberty_client,
    joberty_provider,
    jobspy_provider,
    lever_provider,
    remoteok_provider,
    workable_client,
    workable_provider,
    wwr_provider,
    yc_provider,
)
from providers.base_provider import dropped_ad
from test_discards import COUNTRY, PLACE, TERMS, board_postings, frame, gather, infostud_row, jobspy_row, workable_row
from test_import import canon, snapshot
from test_staging_streaming import SERBIA

DISCOVERY = Path(__file__).resolve().parents[2] / "python" / "job_discovery"
T = [f"2026-11-0{day}T10:00:00+00:00" for day in range(1, 9)]


def ad(n, title="Chef", **extra):
    return canon(n, title=title, **extra)


def stage_run(root, monkeypatch, run_id, at, *, kept=(), dropped=(), reason="title_not_matched", finish=True, key=None, source="greenhouse"):
    """A staged run at time `at`: `kept` ads of source greenhouse, and `dropped` ads with the reason."""
    with monkeypatch.context() as patch:
        patch.setattr(staging, "_now", lambda: at)
        run = staging.StagingRun.begin(root, run_id, search_key=key or f"key-{run_id}", terms=["pm"], locations=["Remote"], country="Serbia",
                                       remote_filters=["remote"], providers=[source])
        writer = run.open_source(source)
        writer.append(list(kept), part="p", read=len(kept) + len(dropped))
        writer.drops([dropped_ad(job, reason, f"ext-{job['jobId']}") for job in dropped])
        writer.finish(status="ok", complete=True, read=len(kept) + len(dropped), kept=len(kept))
        if finish:
            run.finish()
    return run_id


def record_of(root, job):
    return filtered_ads.load(root)["ads"][job["jobId"]]


def imported(root, run_id):
    outcome = importer.import_staged_run(root, run_id)
    assert outcome.ok, outcome.refused
    return outcome


def backfill(root, *extra):
    return import_run.main(["--backfill-filtered", *extra], root=root)


def discard_line(job, reason="title_not_matched", **extra):
    return {"t": "discard", "source": "greenhouse", "externalId": "e", "reason": reason, "jobId": job["jobId"], "title": job["title"],
            "company": job["company"], "location": job["location"], "url": job["jobUrl"], "counted": True, "part": "p", **extra}


# --- one record per ad -----------------------------------------------------------------------------------------------------


def test_the_file_has_the_agreed_shape_and_never_a_description(tmp_path, monkeypatch):
    job = ad(1)
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[job])
    imported(tmp_path, "a")
    store = json.loads((tmp_path / "data/jobs/filtered_ads.json").read_text())
    assert list(store) == ["version", "appliedRuns", "ads"] and store["version"] == 1 and store["appliedRuns"] == ["a"]
    assert store["ads"] == {job["jobId"]: {
        "source": "greenhouse", "title": "Chef", "company": "Acme", "location": "Remote", "url": job["jobUrl"],
        "externalId": f"ext-{job['jobId']}", "reason": "title_not_matched", "firstSeen": T[0], "lastSeen": T[0], "lastRunId": "a",
        "timesSeen": 1, "searchKey": "key-a", "inLedger": False,
    }}
    assert "Own the roadmap" not in json.dumps(store) and "description" not in json.dumps(store)


def test_only_the_named_fields_are_copied_from_a_discard_line():
    store = filtered_ads.empty()
    filtered_ads.apply_run(store, "a", T[0], "k", [discard_line(ad(1), salary="9000 EUR", description="should never get here")])
    assert set(next(iter(store["ads"].values()))) == set(filtered_ads._SHOWN) | {"firstSeen", "lastSeen", "lastRunId", "timesSeen", "searchKey", "inLedger"}


def test_one_ad_under_several_searches_is_one_sighting_with_the_first_reason():
    store = filtered_ads.empty()
    job = ad(1)
    stats = filtered_ads.apply_run(store, "a", T[0], "k", [discard_line(job, "title_not_matched"), discard_line(job, "location_not_matched")])
    assert store["ads"][job["jobId"]]["timesSeen"] == 1 and store["ads"][job["jobId"]]["reason"] == "title_not_matched"
    assert (stats["lines"], stats["ads"], stats["new"]) == (2, 1, 1)


def test_a_line_with_no_id_is_counted_as_such_and_makes_no_record():
    store = filtered_ads.empty()
    stats = filtered_ads.apply_run(store, "a", T[0], "k", [{**discard_line(ad(1)), "jobId": None}, {**discard_line(ad(2)), "jobId": ""}])
    assert store["ads"] == {} and stats["noId"] == 2 and store["appliedRuns"] == ["a"]


def test_a_later_run_moves_the_record_forward():
    store = filtered_ads.empty()
    job = ad(1)
    filtered_ads.apply_run(store, "a", T[0], "k1", [discard_line(job, "title_not_matched")])
    filtered_ads.apply_run(store, "b", T[1], "k2", [{**discard_line(job, "location_not_matched"), "title": "Chef de cuisine"}])
    record = store["ads"][job["jobId"]]
    assert (record["firstSeen"], record["lastSeen"], record["lastRunId"], record["timesSeen"]) == (T[0], T[1], "b", 2)
    assert (record["reason"], record["title"], record["searchKey"]) == ("location_not_matched", "Chef de cuisine", "k2")


# --- idempotence and order -------------------------------------------------------------------------------------------------


def test_a_run_applied_twice_counts_once():
    store = filtered_ads.empty()
    job = ad(1)
    filtered_ads.apply_run(store, "a", T[0], "k", [discard_line(job)])
    once = copy.deepcopy(store)
    stats = filtered_ads.apply_run(store, "a", T[0], "k", [discard_line(job)])
    assert stats["alreadyApplied"] and store == once


def test_a_then_b_then_a_counts_a_once_which_last_run_id_alone_could_not_say():
    store = filtered_ads.empty()
    job = ad(1)
    filtered_ads.apply_run(store, "a", T[0], "k", [discard_line(job)])
    filtered_ads.apply_run(store, "b", T[1], "k", [discard_line(job)])
    assert store["ads"][job["jobId"]]["lastRunId"] == "b"
    filtered_ads.apply_run(store, "a", T[0], "k", [discard_line(job)])
    assert store["ads"][job["jobId"]]["timesSeen"] == 2 and store["appliedRuns"] == ["a", "b"]


def test_an_older_run_never_moves_last_seen_back():
    store = filtered_ads.empty()
    job = ad(1)
    filtered_ads.apply_run(store, "new", T[3], "new-key", [discard_line(job, "location_not_matched")])
    stats = filtered_ads.apply_run(store, "old", T[1], "old-key", [{**discard_line(job, "title_not_matched"), "title": "Old title"}])
    record = store["ads"][job["jobId"]]
    assert stats["older"] == 1 and (record["lastSeen"], record["lastRunId"], record["reason"]) == (T[3], "new", "location_not_matched")
    assert (record["title"], record["searchKey"], record["firstSeen"], record["timesSeen"]) == ("Chef", "new-key", T[1], 2), "only firstSeen and the count move"


def test_a_time_in_another_offset_compares_as_a_time_not_as_text():
    store = filtered_ads.empty()
    job = ad(1)
    filtered_ads.apply_run(store, "a", "2026-11-01T10:00:00+00:00", "k", [discard_line(job)])
    filtered_ads.apply_run(store, "b", "2026-11-01T11:00:00+05:00", "k", [discard_line(job)])  # 06:00 UTC: earlier, though the text sorts later
    assert store["ads"][job["jobId"]]["lastRunId"] == "a"


def test_a_run_with_no_usable_time_is_refused_and_not_marked_applied():
    store = filtered_ads.empty()
    with pytest.raises(ValueError):
        filtered_ads.apply_run(store, "a", "", "k", [discard_line(ad(1))])
    assert store == filtered_ads.empty()


def test_the_list_of_applied_runs_only_grows_and_holds_ids_only(tmp_path, monkeypatch):
    jobs = staging.jobs_dir(tmp_path)
    jobs.mkdir(parents=True)
    store = filtered_ads.empty()
    ids = [f"r{n}" for n in range(1200)]
    for run_id in ids:
        filtered_ads.apply_run(store, run_id, T[0], "k", [])
    filtered_ads.save(tmp_path, store)
    assert filtered_ads.load(tmp_path)["appliedRuns"] == ids, "no bound, and none of them is a run on this disk"


# --- the real import -------------------------------------------------------------------------------------------------------


def test_a_real_import_writes_it_before_the_marker_and_pruning(tmp_path, monkeypatch):
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[ad(1)])
    order = []
    real_record, real_mark, real_prune = filtered_ads.record_run, staging.mark_imported, staging.prune
    monkeypatch.setattr(filtered_ads, "record_run", lambda *a, **k: (order.append("store"), real_record(*a, **k))[1])
    monkeypatch.setattr(staging, "mark_imported", lambda *a, **k: (order.append("marker"), real_mark(*a, **k))[1])
    monkeypatch.setattr(staging, "prune", lambda *a, **k: (order.append("prune"), real_prune(*a, **k))[1])
    outcome = imported(tmp_path, "a")
    assert order == ["store", "marker", "prune"] and outcome.warnings == []
    assert record_of(tmp_path, ad(1))["lastRunId"] == "a"


def test_the_record_outlives_the_pruned_run(tmp_path, monkeypatch):
    job = ad(1)
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[job])
    imported(tmp_path, "a")
    for n, run_id in enumerate(("b", "c", "d"), start=1):
        stage_run(tmp_path, monkeypatch, run_id, T[n], kept=[canon(9)])
        outcome = imported(tmp_path, run_id)
    assert outcome.pruned == ["a"] and outcome.warnings == []
    assert record_of(tmp_path, job)["lastRunId"] == "a"


def test_importing_the_same_run_again_counts_it_once(tmp_path, monkeypatch):
    job = ad(1)
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[job])
    imported(tmp_path, "a")
    first = (tmp_path / "data/jobs/filtered_ads.json").read_bytes()
    again = imported(tmp_path, "a")
    assert again.committed is False and (tmp_path / "data/jobs/filtered_ads.json").read_bytes() == first


def test_a_dry_run_of_the_import_writes_no_store(tmp_path, monkeypatch):
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[ad(1)])
    importer.dry_run(tmp_path, "a")
    import_run.main(["--run", "a", "--dry-run"], root=tmp_path)
    assert not (tmp_path / "data/jobs/filtered_ads.json").exists()


def test_a_refused_import_writes_no_store(tmp_path, monkeypatch):
    stage_run(tmp_path, monkeypatch, "new", T[3], kept=[canon(9)])
    imported(tmp_path, "new")
    before = (tmp_path / "data/jobs/filtered_ads.json").read_bytes()
    stage_run(tmp_path, monkeypatch, "old", T[0], kept=[canon(9)], dropped=[ad(1)])
    assert not importer.import_staged_run(tmp_path, "old").ok, "the order guard refuses an older run"
    assert (tmp_path / "data/jobs/filtered_ads.json").read_bytes() == before


def test_an_older_run_forced_through_the_import_does_not_move_last_seen_back(tmp_path, monkeypatch):
    job = ad(1)
    stage_run(tmp_path, monkeypatch, "new", T[3], kept=[canon(9)], dropped=[job])
    imported(tmp_path, "new")
    stage_run(tmp_path, monkeypatch, "old", T[0], kept=[canon(9)], dropped=[job])
    assert importer.import_staged_run(tmp_path, "old", allow_older=True).ok
    record = record_of(tmp_path, job)
    assert (record["firstSeen"], record["lastSeen"], record["lastRunId"], record["timesSeen"]) == (T[0], T[3], "new", 2)


def test_a_torn_last_line_and_a_bad_line_are_skipped_and_the_rest_counted(tmp_path, monkeypatch):
    whole, other = ad(1), ad(2)
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[whole])
    discards = tmp_path / "data/jobs/staging/a/discards.jsonl"
    with open(discards, "ab") as handle:
        handle.write(b"not json at all\n")
        handle.write(json.dumps({**discard_line(ad(3)), "description": "refused"}).encode() + b"\n")
        handle.write(json.dumps(discard_line(other)).encode()[:40])
    imported(tmp_path, "a")
    ads = filtered_ads.load(tmp_path)["ads"]
    assert set(ads) == {whole["jobId"]} and filtered_ads.load(tmp_path)["appliedRuns"] == ["a"]


def test_a_discards_file_that_cannot_be_read_is_not_a_run_that_dropped_nothing(tmp_path, monkeypatch):
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[ad(1)])
    run = staging.read_run(tmp_path, "a")
    (tmp_path / "data/jobs/staging/a/discards.jsonl").chmod(0)
    try:
        with pytest.raises(OSError):
            filtered_ads.record_run(tmp_path, run, T[0], {})
    finally:
        (tmp_path / "data/jobs/staging/a/discards.jsonl").chmod(0o600)
    assert "a" in filtered_ads.unrecorded(tmp_path)


def test_a_run_with_no_discards_file_has_nothing_to_lose(tmp_path, monkeypatch):
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)])
    (tmp_path / "data/jobs/staging/a/discards.jsonl").unlink()
    assert filtered_ads.unrecorded(tmp_path) == set()


# --- a failed write ----------------------------------------------------------------------------------------------------------


def four_imports(tmp_path, monkeypatch, *, fail=False):
    job = ad(1)
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[job])
    if fail:
        with monkeypatch.context() as patch:
            def broken(*a, **k):
                raise OSError("disk full")

            patch.setattr(filtered_ads, "save", broken)
            first = imported(tmp_path, "a")
    else:
        first = imported(tmp_path, "a")
    outcomes = [first]
    for n, run_id in enumerate(("b", "c", "d"), start=1):
        stage_run(tmp_path, monkeypatch, run_id, T[n], kept=[canon(9)])
        outcomes.append(imported(tmp_path, run_id))
    return job, outcomes


def test_a_failed_write_does_not_stop_the_import_and_blocks_pruning_of_that_run(tmp_path, monkeypatch):
    job, outcomes = four_imports(tmp_path, monkeypatch, fail=True)
    assert outcomes[0].ok and outcomes[0].committed and staging.is_imported(tmp_path, "a"), "the import itself stands"
    assert any("not recorded" in w for w in outcomes[0].warnings)
    assert outcomes[3].pruned == [] and "a" in staging.list_runs(tmp_path), "past the three kept, and still there"
    assert any("--backfill-filtered" in w for w in outcomes[3].warnings)
    assert job["jobId"] not in filtered_ads.load(tmp_path)["ads"]


def test_the_control_without_the_failure_prunes_that_run(tmp_path, monkeypatch):
    _, outcomes = four_imports(tmp_path, monkeypatch)
    assert outcomes[3].pruned == ["a"]


def test_a_backfill_recovers_the_failed_run_and_pruning_then_goes_on(tmp_path, monkeypatch):
    job, _ = four_imports(tmp_path, monkeypatch, fail=True)
    assert backfill(tmp_path) == 0
    assert record_of(tmp_path, job)["timesSeen"] == 1
    stage_run(tmp_path, monkeypatch, "e", T[4], kept=[canon(9)])
    assert set(imported(tmp_path, "e").pruned) == {"a", "b"}


def test_a_store_that_cannot_be_read_is_left_alone_and_blocks_all_pruning(tmp_path, monkeypatch):
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[ad(1)])
    imported(tmp_path, "a")
    path = tmp_path / "data/jobs/filtered_ads.json"
    path.write_text("{ broken")
    outcomes = []
    for n, run_id in enumerate(("b", "c", "d"), start=1):
        stage_run(tmp_path, monkeypatch, run_id, T[n], kept=[canon(9)])
        outcomes.append(imported(tmp_path, run_id))
    assert path.read_text() == "{ broken" and outcomes[-1].pruned == [] and outcomes[-1].warnings
    assert backfill(tmp_path) == 2 and path.read_text() == "{ broken"


@pytest.mark.parametrize("body", [[], {"version": 2, "appliedRuns": [], "ads": {}}, {"version": 1, "appliedRuns": {}, "ads": {}}, {"version": 1, "appliedRuns": []}])
def test_a_store_of_another_shape_is_refused(tmp_path, body):
    staging.jobs_dir(tmp_path).mkdir(parents=True)
    filtered_ads.file_path(tmp_path).write_text(json.dumps(body))
    with pytest.raises(filtered_ads.FilteredAdsError):
        filtered_ads.load(tmp_path)


# --- kept later ------------------------------------------------------------------------------------------------------------


def test_an_ad_kept_later_keeps_its_record_marked_so_readers_show_it_once(tmp_path, monkeypatch):
    job, other = ad(1), ad(2)
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[job, other])
    imported(tmp_path, "a")
    assert record_of(tmp_path, job)["inLedger"] is False
    stage_run(tmp_path, monkeypatch, "b", T[1], kept=[canon(1, title="Product Manager"), canon(9)])
    imported(tmp_path, "b")
    ledger = json.loads((tmp_path / "data/jobs/job_history.json").read_text())
    assert job["jobId"] in ledger["jobs"], "the same address: the same id"
    record = record_of(tmp_path, job)
    assert record["inLedger"] is True and (record["lastRunId"], record["timesSeen"]) == ("a", 1), "not deleted, and being kept is no sighting"
    assert record_of(tmp_path, other)["inLedger"] is False


def test_a_backfill_refreshes_the_mark_when_every_run_is_already_counted(tmp_path, monkeypatch):
    job = ad(1)
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[job])
    imported(tmp_path, "a")
    store = filtered_ads.load(tmp_path)
    store["ads"][job["jobId"]]["inLedger"] = True
    filtered_ads.save(tmp_path, store)
    assert backfill(tmp_path) == 0
    assert record_of(tmp_path, job)["inLedger"] is False, "the mark says what the ledger says"


# --- the backfill ----------------------------------------------------------------------------------------------------------


def five_runs(tmp_path, monkeypatch):
    """Imported, never imported, a failed status: all of them hold ads a source really listed."""
    jobs = {n: ad(n) for n in range(1, 5)}
    stage_run(tmp_path, monkeypatch, "r1", T[0], kept=[canon(9)], dropped=[jobs[1]])
    imported(tmp_path, "r1")
    stage_run(tmp_path, monkeypatch, "r2", T[1], kept=[canon(9)], dropped=[jobs[1], jobs[2]])
    stage_run(tmp_path, monkeypatch, "r3", T[2], kept=[canon(9)], dropped=[jobs[3]], reason="location_not_matched")
    stage_run(tmp_path, monkeypatch, "r4", T[3], kept=[canon(9)], dropped=[jobs[1], jobs[4]], finish=False)
    # r1's record starts over for the test: as the live files will be, with no store at all
    filtered_ads.file_path(tmp_path).unlink()
    return jobs


def everything_else(root):
    found = snapshot(root)
    found.pop("data/jobs/filtered_ads.json", None)
    found.pop("pipeline.lock", None)  # the empty lock file every command takes, moved to tmp_path by conftest
    return found


def test_a_backfill_counts_every_run_oldest_first_imported_or_not(tmp_path, monkeypatch, capsys):
    jobs = five_runs(tmp_path, monkeypatch)
    assert backfill(tmp_path) == 0
    store = filtered_ads.load(tmp_path)
    assert store["appliedRuns"] == ["r1", "r2", "r3", "r4"]
    record = store["ads"][jobs[1]["jobId"]]
    assert (record["firstSeen"], record["lastSeen"], record["lastRunId"], record["timesSeen"]) == (T[0], T[3], "r4", 3)
    assert store["ads"][jobs[3]["jobId"]]["reason"] == "location_not_matched" and len(store["ads"]) == 4


def test_the_result_does_not_depend_on_the_order_the_runs_are_applied_in(tmp_path, monkeypatch):
    jobs = five_runs(tmp_path, monkeypatch)
    assert backfill(tmp_path) == 0
    forward = filtered_ads.load(tmp_path)["ads"]
    store = filtered_ads.empty()
    for run_id in ("r3", "r4", "r1", "r2"):
        run = staging.read_run(tmp_path, run_id)
        filtered_ads.apply_run(store, run_id, importer.import_time(run), run.manifest["searchKey"], run.discards.records)
    filtered_ads.mark_ledger(store, set())
    assert {k: forward[k] for k in sorted(forward)} == {k: store["ads"][k] for k in sorted(store["ads"])}
    assert jobs


def test_a_backfill_twice_gives_the_same_file_and_does_not_rewrite_it(tmp_path, monkeypatch):
    five_runs(tmp_path, monkeypatch)
    assert backfill(tmp_path) == 0
    path = tmp_path / "data/jobs/filtered_ads.json"
    first, stamp = path.read_bytes(), path.stat().st_mtime_ns
    assert backfill(tmp_path) == 0
    assert path.read_bytes() == first and path.stat().st_mtime_ns == stamp


def test_a_backfill_changes_nothing_but_its_own_file(tmp_path, monkeypatch):
    five_runs(tmp_path, monkeypatch)
    before = everything_else(tmp_path)
    assert {"data/jobs/job_history.json", "data/jobs/discovered_jobs.json"} <= set(before)
    assert backfill(tmp_path) == 0
    assert everything_else(tmp_path) == before, "ledger, view, staging, markers: same bytes, same times"
    assert not staging.is_imported(tmp_path, "r2") and (tmp_path / "data/jobs/filtered_ads.json").exists()


def test_a_backfill_starts_no_import_and_no_scoring(tmp_path, monkeypatch):
    five_runs(tmp_path, monkeypatch)
    monkeypatch.setattr(importer, "import_staged_run", lambda *a, **k: pytest.fail("an import was made"))
    monkeypatch.setattr(importer, "plan_import", lambda *a, **k: pytest.fail("an import was planned"))
    monkeypatch.setattr(importer.view_guard, "commit", lambda *a, **k: pytest.fail("a commit was made"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("a process was started"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("a process was started"))
    assert backfill(tmp_path) == 0


def test_a_dry_run_backfill_writes_nothing_and_prints_the_same_counts(tmp_path, monkeypatch, capsys):
    five_runs(tmp_path, monkeypatch)
    before = everything_else(tmp_path)
    assert backfill(tmp_path, "--dry-run") == 0
    dry = capsys.readouterr().out
    assert everything_else(tmp_path) == before and not (tmp_path / "data/jobs/filtered_ads.json").exists()
    assert "dry run" in dry and "4 ads (4 new)" in dry and "would be written" in dry
    assert backfill(tmp_path) == 0
    real = capsys.readouterr().out
    assert "4 ads (4 new)" in real and "written" in real and "would be" not in real


def test_the_backfill_prints_counts_and_never_an_ad(tmp_path, monkeypatch, capsys):
    jobs = five_runs(tmp_path, monkeypatch)
    assert backfill(tmp_path) == 0
    out = capsys.readouterr().out
    assert "Acme" not in out and "Chef" not in out and "example" not in out and not any(j["jobId"] in out for j in jobs.values())
    assert "not imported" in out and "imported    " in out


def test_a_backfilled_run_imported_later_is_not_counted_twice(tmp_path, monkeypatch):
    jobs = five_runs(tmp_path, monkeypatch)
    assert backfill(tmp_path) == 0
    before = filtered_ads.load(tmp_path)["ads"][jobs[2]["jobId"]]["timesSeen"]
    imported(tmp_path, "r2")
    assert filtered_ads.load(tmp_path)["ads"][jobs[2]["jobId"]]["timesSeen"] == before == 1


def test_a_backfill_waits_for_a_run_that_is_active(tmp_path, monkeypatch, capsys):
    five_runs(tmp_path, monkeypatch)
    monkeypatch.setattr(import_run.pipeline_lock, "acquire", lambda: None)
    assert backfill(tmp_path) == 2
    assert not (tmp_path / "data/jobs/filtered_ads.json").exists()


def test_a_backfill_with_a_ledger_it_cannot_read_stops_and_leaves_it_where_it_is(tmp_path, monkeypatch, capsys):
    five_runs(tmp_path, monkeypatch)
    ledger = tmp_path / "data/jobs/job_history.json"
    ledger.write_text("{ broken")
    assert backfill(tmp_path) == 2
    assert ledger.read_text() == "{ broken" and not (tmp_path / "data/jobs/filtered_ads.json").exists()
    assert list(ledger.parent.glob("job_history*corrupt*")) == [], "never set aside by a backfill"


def test_a_backfill_with_no_ledger_and_no_runs_is_fine(tmp_path):
    assert backfill(tmp_path, "--dry-run") == 0


@pytest.mark.parametrize("extra", [["--latest"], ["--run", "a"], ["--import"], ["--lifecycle-report"], ["--allow-older"],
                                   ["--confirm-overwrite-newer"], ["--report-file"]])
def test_the_backfill_goes_only_with_dry_run(tmp_path, extra, capsys):
    staging.jobs_dir(tmp_path).mkdir(parents=True)  # or it would stop for another reason
    assert backfill(tmp_path, *extra) == 2
    assert "goes only with --dry-run" in capsys.readouterr().err
    assert not (tmp_path / "data/jobs/filtered_ads.json").exists()


@pytest.mark.parametrize("argv", [["--dry-run"], ["--run", "a"], []])
def test_the_old_commands_still_need_a_run_and_a_mode(tmp_path, argv, capsys):
    with pytest.raises(SystemExit) as stop:
        import_run.main(argv, root=tmp_path)
    assert stop.value.code == 2


# --- a process killed part way ---------------------------------------------------------------------------------------------


def killed_import(root, run_id, stop_at):
    """The real import in its own process, stopped dead (no exception, no cleanup) at `stop_at`."""
    points = {
        "before the marker": "staging.mark_imported = lambda *a, **k: os._exit(9)",
        "before the store": "filtered_ads.record_run = lambda *a, **k: os._exit(9)",
        "inside the store's rename": textwrap.dedent("""\
            real = os.replace
            os.replace = lambda src, dst: os._exit(9) if str(dst).endswith("filtered_ads.json") else real(src, dst)"""),
    }
    script = "\n".join([
        "import os, sys", "from pathlib import Path", f"sys.path.insert(0, {str(DISCOVERY)!r})", "import filtered_ads, importer, staging",
        points[stop_at], f"importer.import_staged_run(Path({str(root)!r}), {run_id!r})", "os._exit(0)",
    ])
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert done.returncode == 9, done.stderr


def test_killed_between_the_store_and_the_marker_then_imported_again(tmp_path, monkeypatch):
    job = ad(1)
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[job])
    killed_import(tmp_path, "a", "before the marker")
    assert not staging.is_imported(tmp_path, "a"), "the stop came before the marker"
    assert record_of(tmp_path, job)["timesSeen"] == 1, "and after the store"
    generation = json.loads((tmp_path / "data/jobs/job_history.json").read_text())["generation"]

    again = imported(tmp_path, "a")
    assert again.committed is False and staging.is_imported(tmp_path, "a"), "the repeat finishes the job"
    assert json.loads((tmp_path / "data/jobs/job_history.json").read_text())["generation"] == generation
    store = filtered_ads.load(tmp_path)
    assert store["ads"][job["jobId"]]["timesSeen"] == 1 and store["appliedRuns"] == ["a"], "no counter moved"


def test_killed_between_the_ledger_and_the_store_then_imported_again(tmp_path, monkeypatch):
    job = ad(1)
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[job])
    killed_import(tmp_path, "a", "before the store")
    assert (tmp_path / "data/jobs/job_history.json").exists() and not filtered_ads.file_path(tmp_path).exists()
    assert filtered_ads.unrecorded(tmp_path) == {"a"}, "so nothing can prune it meanwhile"
    imported(tmp_path, "a")
    assert record_of(tmp_path, job)["timesSeen"] == 1 and staging.is_imported(tmp_path, "a")


def test_killed_while_the_store_is_being_replaced_leaves_the_old_file_whole(tmp_path, monkeypatch):
    job = ad(1)
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[job])
    imported(tmp_path, "a")
    before = filtered_ads.file_path(tmp_path).read_bytes()
    stage_run(tmp_path, monkeypatch, "b", T[1], kept=[canon(9)], dropped=[job])
    killed_import(tmp_path, "b", "inside the store's rename")
    assert filtered_ads.file_path(tmp_path).read_bytes() == before, "the old file or the new one, never half of one"
    imported(tmp_path, "b")
    record = record_of(tmp_path, job)
    assert (record["timesSeen"], record["lastRunId"]) == (2, "b")


def test_killed_and_then_a_later_run_imported_a_backfill_still_finds_the_first(tmp_path, monkeypatch):
    job = ad(1)
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[job])
    killed_import(tmp_path, "a", "before the store")
    stage_run(tmp_path, monkeypatch, "b", T[1], kept=[canon(9)])
    imported(tmp_path, "b")
    assert filtered_ads.unrecorded(tmp_path) == {"a"} and "a" in staging.list_runs(tmp_path)
    assert backfill(tmp_path) == 0
    assert record_of(tmp_path, job)["timesSeen"] == 1 and filtered_ads.unrecorded(tmp_path) == set()


# --- the same ad, kept or dropped, has the same id: every provider ----------------------------------------------------------


def _board(kind, cls, loader, fetcher):
    field = "text" if kind == "lever" else "title"

    def make(title, monkeypatch):
        provider = cls()
        posting = {**board_postings(kind)[0], field: title}
        monkeypatch.setattr(provider, loader, lambda: [{"board": "b1"}] if kind == "greenhouse" else ["b1"])
        monkeypatch.setattr(provider, fetcher, lambda board: [posting])
        return provider, kind, PLACE

    return make


def _jobspy(title, monkeypatch):
    monkeypatch.setattr(jobspy_provider, "fetch_jobs", lambda term, location, remote=False, country="": frame([jobspy_row(title, 1)]))
    return jobspy_provider.JobSpyProvider(), "jobspy", ["Remote"]


def _infostud(title, monkeypatch):
    monkeypatch.setattr(infostud_client, "fetch_raw", lambda categories=None: ([infostud_row(1001, title, "Zxqville")], 1))
    monkeypatch.setattr(infostud_client, "enrich", lambda job, delay=1.0: job)
    return infostud_provider.InfostudProvider(), "infostud", PLACE


def _workable(title, monkeypatch):
    monkeypatch.setattr(workable_client, "search", lambda term, location="", limit=100: [workable_row(1, title, "Zxqville")])
    monkeypatch.setattr(workable_client.time, "sleep", lambda s: None)
    return workable_provider.WorkableProvider(), "workable", PLACE


def _joberty(title, monkeypatch):
    """Dropped by place, not by title: Joberty's address holds a slug of the title, see the test below."""
    from test_joberty import CITIES, DETAIL, product_ad

    item = product_ad(1) if title != "Chef" else product_ad(1, city="Zagreb (Croatia)")
    monkeypatch.setattr(joberty_client, "fetch_cities", lambda: CITIES)
    monkeypatch.setattr(joberty_client, "fetch_listing", lambda *a, **k: [copy.deepcopy(item)])
    monkeypatch.setattr(joberty_client, "fetch_detail", lambda job_id: copy.deepcopy(DETAIL))
    return joberty_provider.JobertyProvider(ledger_path=Path("/nonexistent/none.json")), "joberty", SERBIA


def _wwr(title, monkeypatch):
    provider = wwr_provider.WWRProvider()
    item = {"guid": "g1", "title": title, "company": "Acme", "link": "https://w.example/1", "description": "d", "pubDate": ""}
    monkeypatch.setattr(provider, "_parse_feed", lambda url: [item] if url == wwr_provider.RSS_FEEDS[0] else [])
    return provider, "wwr", ["Remote"]


def _remoteok(title, monkeypatch):
    provider = remoteok_provider.RemoteOKProvider()
    monkeypatch.setattr(provider, "_fetch_all", lambda: [{"id": "r1", "position": title, "company": "A", "url": "https://r.example/1", "description": "d"}])
    return provider, "remoteok", ["Remote"]


def _yc(title, monkeypatch):
    provider = yc_provider.YCProvider()
    monkeypatch.setattr(provider, "_fetch_all", lambda: [{"id": 7, "title": title, "company": {"name": "Y"}, "location": "Remote", "url": "https://y.example/1"}])
    return provider, "yc", ["Remote"]


PROVIDERS = {
    "greenhouse": _board("greenhouse", greenhouse_provider.GreenhouseProvider, "_load_boards", "_fetch_board"),
    "lever": _board("lever", lever_provider.LeverProvider, "_load_companies", "_fetch_company"),
    "ashby": _board("ashby", ashby_provider.AshbyProvider, "_load_companies", "_fetch_company"),
    "jobspy": _jobspy, "infostud": _infostud, "workable": _workable, "joberty": _joberty, "wwr": _wwr, "remoteok": _remoteok, "yc": _yc,
}


def through(make, title, monkeypatch, folder):
    folder.mkdir()
    provider, name, locations = make(title, monkeypatch)
    run = staging.StagingRun.begin(folder, "r1", search_key="k", terms=TERMS, locations=locations, country=COUNTRY, remote_filters=[], providers=[name])
    returned, _outcome, stage, discards = gather(provider, run, name, folder, locations)
    return returned, stage, discards


@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_an_ad_kept_in_one_run_and_dropped_in_another_has_one_id(name, tmp_path, monkeypatch):
    returned, stage, _ = through(PROVIDERS[name], "Product Manager", monkeypatch, tmp_path / "kept")
    _, _, discards = through(PROVIDERS[name], "Chef", monkeypatch, tmp_path / "dropped")
    assert returned and discards, "the fixture must give one kept and one dropped ad"
    assert len({job["jobId"] for job in returned}) == 1 and len({d["jobId"] for d in discards}) == 1, "jobspy sees it under each search"
    kept, dropped = returned[0], discards[0]
    assert stage.jobs[0]["jobId"] == kept["jobId"] == dropped["jobId"]
    assert kept["jobUrl"] == dropped["url"]
    assert dropped["jobId"] == _make_job_id(dropped["url"], dropped["title"], dropped["company"], dropped["location"])


def test_a_joberty_ad_given_a_new_title_is_a_new_id_kept_or_dropped():
    """Not a difference between the paths: the address holds a slug of the title, so both give the new title a new address."""
    from test_joberty import product_ad

    before, after = product_ad(1), product_ad(1, title="Chef")
    assert joberty_provider.job_url(before) != joberty_provider.job_url(after)
    assert joberty_provider.to_canonical(after, country="Serbia")["jobId"] == _make_job_id(joberty_provider.job_url(after), "", "", "")


def test_infostud_on_its_second_drop_path_and_never_its_raw_rows_sha1(tmp_path, monkeypatch):
    """Infostud drops at the listing (role) and again after the slow read (place), and its raw row has a jobId of its own, a sha1 of
    the address. A record must never carry that one: the ledger would then not match it."""
    def at(city):
        def make(title, patch):
            patch.setattr(infostud_client, "fetch_raw", lambda categories=None: ([infostud_row(1001, title, city)], 1))
            patch.setattr(infostud_client, "enrich", lambda job, delay=1.0: job)
            return infostud_provider.InfostudProvider(), "infostud", PLACE
        return make

    returned, _, _ = through(at("Zxqville"), "Product Manager", monkeypatch, tmp_path / "kept")
    _, _, by_place = through(at("Beograd"), "Product Manager", monkeypatch, tmp_path / "place")
    _, _, by_role = through(at("Zxqville"), "Chef", monkeypatch, tmp_path / "role")
    assert by_place[0]["reason"] == "location_not_matched" and by_role[0]["reason"] == "title_not_matched"
    url = returned[0]["jobUrl"]
    assert returned[0]["jobId"] == by_place[0]["jobId"] == by_role[0]["jobId"] == _make_job_id(url, "", "", "")
    import hashlib
    assert returned[0]["jobId"] != hashlib.sha1(url.encode()).hexdigest()[:16]


# --- small promises ----------------------------------------------------------------------------------------------------------


def test_an_odd_character_in_a_title_cannot_stop_the_write(tmp_path):
    staging.jobs_dir(tmp_path).mkdir(parents=True)
    store = filtered_ads.empty()
    filtered_ads.apply_run(store, "a", T[0], "k", [{**discard_line(ad(1)), "title": "Chef \ud83d lone half of a pair, and Šef"}])
    assert filtered_ads.save(tmp_path, store) is True
    assert filtered_ads.load(tmp_path) == store and filtered_ads.file_path(tmp_path).read_bytes().isascii()


def test_a_run_with_no_usable_time_is_reported_and_left_uncounted_by_the_backfill(tmp_path, monkeypatch):
    five_runs(tmp_path, monkeypatch)
    report = filtered_ads.backfill(tmp_path, lambda run: "", dry_run=True)
    assert report["noTime"] == 4 and report["applied"] == 0 and report["ads"] == 0


def test_the_command_says_when_an_import_left_a_run_unrecorded(tmp_path, monkeypatch, capsys):
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[ad(1)])

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(filtered_ads, "save", broken)
    assert import_run.main(["--run", "a", "--import"], root=tmp_path) == 0
    err = capsys.readouterr().err
    assert "not recorded" in err and "--backfill-filtered" in err


def test_a_scrape_logs_it_when_its_dropped_ads_were_not_recorded(tmp_path, monkeypatch, caplog):
    from test_import import Prov
    from test_staging import discover

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(filtered_ads, "save", broken)
    assert discover(tmp_path, monkeypatch, {"greenhouse": Prov([canon(1)])}) == 0, "the run itself succeeds"
    assert "were not recorded" in caplog.text


# --- appliedRuns only grows, so a run on disk counts once (asked for with S5e2, fixed in S5e2b) -------------------------------------


def test_a_run_still_in_staging_counts_once_however_many_runs_there_are(tmp_path, monkeypatch):
    job = ad(1)
    for n, run_id in enumerate(("a", "b", "c", "d")):
        stage_run(tmp_path, monkeypatch, run_id, T[n], kept=[canon(9)], dropped=[job])
    assert backfill(tmp_path) == 0
    store = filtered_ads.load(tmp_path)
    assert store["appliedRuns"] == ["a", "b", "c", "d"] and store["ads"][job["jobId"]]["timesSeen"] == 4
    assert backfill(tmp_path) == 0
    imported(tmp_path, "a")
    assert record_of(tmp_path, job)["timesSeen"] == 4


def test_a_run_folder_restored_after_it_was_removed_is_not_counted_twice(tmp_path, monkeypatch):
    """The one way the code alone could lose an id while the trim step existed: gone from staging, trimmed, then restored from a copy."""
    job = ad(1)
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[job])
    assert backfill(tmp_path) == 0
    folder, kept = tmp_path / "data/jobs/staging/a", tmp_path / "a.copy"
    shutil.copytree(folder, kept)
    shutil.rmtree(folder)
    assert backfill(tmp_path) == 0
    assert filtered_ads.load(tmp_path)["appliedRuns"] == ["a"], "its id stays after the run has left staging"
    shutil.copytree(kept, folder)
    assert backfill(tmp_path) == 0
    assert record_of(tmp_path, job)["timesSeen"] == 1


def test_nothing_in_the_code_can_remove_an_id():
    source = Path(filtered_ads.__file__).read_text(encoding="utf-8")
    assert '"appliedRuns"] =' not in source and '"appliedRuns"].remove' not in source and '"appliedRuns"].pop' not in source
    assert "MAX_APPLIED_RUNS" not in source and "_trim" not in source


@pytest.mark.xfail(strict=True, reason="Reported in S5e2b: an id taken out of appliedRuns by hand, with its run on disk, is counted again. Removing the trim step means "
                                       "the code can no longer cause this; only an edited file can. Passing it needs a per-ad list of runs, not a one-line fix.")
def test_an_id_edited_out_of_the_list_while_its_run_is_on_disk_is_not_counted_twice(tmp_path, monkeypatch):
    job = ad(1)
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[job])
    stage_run(tmp_path, monkeypatch, "b", T[1], kept=[canon(9)], dropped=[job])
    assert backfill(tmp_path) == 0
    store = filtered_ads.load(tmp_path)
    store["appliedRuns"].remove("a")
    filtered_ads.save(tmp_path, store)
    assert backfill(tmp_path) == 0
    assert record_of(tmp_path, job)["timesSeen"] == 2


def test_the_protection_of_staged_runs_stays(tmp_path, monkeypatch):
    stage_run(tmp_path, monkeypatch, "a", T[0], kept=[canon(9)], dropped=[ad(1)])
    assert filtered_ads.unrecorded(tmp_path) == {"a"}
    assert backfill(tmp_path) == 0
    assert filtered_ads.unrecorded(tmp_path) == set()
    stage_run(tmp_path, monkeypatch, "b", T[1], kept=[canon(9)], dropped=[ad(2)])
    assert filtered_ads.unrecorded(tmp_path) == {"b"}
