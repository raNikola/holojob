"""The lifecycle report (slice S5a): what the S5 rules would do. Offline; every path is under tmp_path; nothing it reads is changed."""

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

import import_run
import lifecycle_report as lr
import staging
from dedupe_jobs import _crosspost_key
from test_import import canon, snapshot

BASE = datetime(2026, 11, 1, 10, tzinfo=timezone.utc)


def at(day):
    return (BASE + timedelta(days=day)).isoformat()


def ad(n, provider="greenhouse", board="acme"):
    return {**canon(n, provider=provider), "source": board}


def entry(job, seen=0, key="k", closed=None):
    return {
        "firstSeen": at(seen), "lastSeen": at(seen), "closedAt": closed, "llmFacts": None, "provider": job["provider"],
        "roleKey": _crosspost_key(job), "seenUnder": key, "job": job,
    }


def ledger(*entries):
    return {"version": 1, "jobs": {e["job"]["jobId"]: e for e in entries}}


class Clock:
    """Runs get ordered ids and times."""

    def __init__(self, root):
        self.root, self.n = root, 0

    def run(self, sources, *, day=None, key="k", status=True, manifest_time=True):
        """`sources`: {name: {"boards": {board: (kept ads, dropped ads)}, "status", "failed", "empty", "mismatch"}}."""
        self.n += 1
        run_id = f"run{self.n:04d}aaaaaa"
        run = staging.StagingRun.begin(
            self.root, run_id, search_key=key, terms=["pm"], locations=["Remote"], country="Serbia", remote_filters=["remote"], providers=list(sources),
        )
        for name, spec in sources.items():
            writer = run.open_source(name)
            total_read = kept = 0
            for board, (ads, dropped) in spec.get("boards", {}).items():
                writer.append(ads, part=board, read=len(ads) + len(dropped),
                              dropped=[{"job": j, "reason": "search_terms_not_matched", "externalId": "x"} for j in dropped])
                total_read += len(ads) + len(dropped)
                kept += len(ads)
            if spec.get("status") != "unfinished":
                writer.finish(status=spec.get("status", "ok"), complete=spec.get("status", "ok") == "ok", read=spec.get("read", total_read), kept=kept,
                              boardsFailed=spec.get("failed", []), boardsEmpty=spec.get("empty", []), mismatch=spec.get("mismatch", False),
                              discardMismatch=spec.get("discardMismatch", False))
        if status:
            run.finish()
        found = staging.read_run(self.root, run_id)
        when = at(self.n if day is None else day)
        found.manifest.update(startedAt=when)
        if isinstance(found.status, dict):
            found.status["finishedAt"] = when
        for stage in found.sources.values():
            if stage.footer:
                stage.footer["finishedAt"] = when
        return found


@pytest.fixture
def clock(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    return Clock(root)


def counts(sim, cls, n=-1):
    return sim["runs"][n]["transitions"].get(cls, {})


def simulate(start, runs, proven=True):
    return lr.simulate(start, runs, trust_balanced=proven)


def full(ads, dropped=()):
    return {"boards": {"acme": (list(ads), list(dropped))}}


# --- snapshot ----------------------------------------------------------------------------------------------------------


def test_one_miss_is_absent_two_consecutive_misses_close_and_a_new_listing_reopens(clock):
    keep, gone = ad(1), ad(2)
    start = ledger(entry(keep), entry(gone))
    runs = [clock.run({"greenhouse": full([keep])}), clock.run({"greenhouse": full([keep])}), clock.run({"greenhouse": full([keep, gone])})]
    sim = simulate(start, runs)
    assert counts(sim, "snapshot", 0)["absentNew"] == 1 and "closed" not in counts(sim, "snapshot", 0)
    assert counts(sim, "snapshot", 1)["closed"] == 1
    assert counts(sim, "snapshot", 2)["reopened"] == 1
    assert sim["entries"][gone["jobId"]]["closedAt"] is None and sim["state"][gone["jobId"]]["absentRuns"] == 0


def test_seen_again_resets_the_miss_count(clock):
    keep, come_and_go = ad(1), ad(2)
    runs = [clock.run({"greenhouse": full([keep])}), clock.run({"greenhouse": full([keep, come_and_go])}), clock.run({"greenhouse": full([keep])})]
    sim = simulate(ledger(entry(keep), entry(come_and_go)), runs)
    assert not any("closed" in counts(sim, "snapshot", i) for i in range(3))
    assert sim["state"][come_and_go["jobId"]]["absentRuns"] == 1


@pytest.mark.parametrize("spec, held", [
    ({"boards": {"acme": ([], [])}, "failed": ["acme"], "status": "partial"}, "heldBoardFailedOrEmpty"),
    ({"boards": {"acme": ([], [])}, "empty": ["acme"]}, "heldBoardFailedOrEmpty"),
    ({"boards": {"other": ([ad(9, board="other")], [])}}, "heldBoardNotRead"),
    ({"boards": {"acme": ([], [])}, "status": "failed"}, "heldSourceDidNotRun"),
    ({"boards": {"acme": ([], [])}, "status": "skipped"}, "heldSourceDidNotRun"),
    ({"boards": {"acme": ([], [])}, "status": "unfinished"}, "heldSourceDidNotRun"),
    ({"boards": {"acme": ([], [])}, "mismatch": True}, "heldSourceDidNotRun"),
])
def test_an_unread_failed_or_doubtful_board_neither_counts_a_miss_nor_resets_one(clock, spec, held):
    gone = ad(2)
    one_miss = clock.run({"greenhouse": full([ad(1)])})
    sim = simulate(ledger(entry(gone)), [one_miss, clock.run({"greenhouse": spec})])
    assert counts(sim, "snapshot")[held] >= 1
    assert sim["entries"][gone["jobId"]]["closedAt"] is None
    assert sim["state"][gone["jobId"]]["absentRuns"] == 1, "not raised, not reset"


def test_a_failed_board_in_between_keeps_the_two_misses_consecutive(clock):
    gone = ad(2)
    runs = [clock.run({"greenhouse": full([ad(1)])}), clock.run({"greenhouse": {"boards": {"acme": ([], [])}, "failed": ["acme"], "status": "partial"}}),
            clock.run({"greenhouse": full([ad(1)])})]
    assert counts(simulate(ledger(entry(gone)), runs), "snapshot")["closed"] == 1


def test_a_listed_ad_the_filter_dropped_is_no_miss_and_clears_an_earlier_one(clock):
    filtered = ad(2)
    runs = [clock.run({"greenhouse": full([ad(1)])}), clock.run({"greenhouse": full([ad(1)], [filtered])}), clock.run({"greenhouse": full([ad(1)])})]
    sim = simulate(ledger(entry(filtered)), runs)
    assert counts(sim, "snapshot", 1)["listedButFiltered"] == 1
    assert sim["state"][filtered["jobId"]]["absentRuns"] == 1, "reset by the listing, then the third run is the first miss again"
    assert sim["entries"][filtered["jobId"]]["closedAt"] is None


def test_strict_closes_nothing_because_no_board_has_proof(clock):
    gone = ad(2)
    runs = [clock.run({"greenhouse": full([ad(1)])}) for _ in range(4)]
    sim = simulate(ledger(entry(gone)), runs, proven=False)
    assert all("closed" not in counts(sim, "snapshot", i) for i in range(4))
    assert counts(sim, "snapshot")["noEvidenceOfCompleteRead"] == 1 and sim["state"][gone["jobId"]]["absentRuns"] == 0


def test_a_board_with_a_read_that_does_not_balance_is_not_taken_as_proven(clock):
    gone = ad(2)
    one = clock.run({"greenhouse": full([ad(1)])})
    one.sources["greenhouse"].batches[0].read = 99
    sim = simulate(ledger(entry(gone)), [one])
    assert counts(sim, "snapshot")["noEvidenceOfCompleteRead"] == 1


def test_closing_ignores_the_search_key_d4_when_the_board_is_read(clock):
    gone = ad(2)
    start = ledger(entry(gone, key="older"))
    runs = [clock.run({"greenhouse": full([ad(1)])}), clock.run({"greenhouse": full([ad(1)])})]
    assert counts(simulate(start, runs), "snapshot")["closed"] == 1


def test_a_cross_post_still_listed_is_no_miss(clock):
    copy_a = ad(2)
    copy_b = {**ad(3), "title": copy_a["title"], "company": copy_a["company"]}
    start = ledger(entry(copy_a))
    start["jobs"][copy_a["jobId"]]["roleKey"] = _crosspost_key(copy_b)
    runs = [clock.run({"greenhouse": full([copy_b])}), clock.run({"greenhouse": full([copy_b])})]
    sim = simulate(start, runs)
    assert counts(sim, "snapshot")["crossPostListed"] == 1 and sim["entries"][copy_a["jobId"]]["closedAt"] is None


# --- search-based and unclassified -------------------------------------------------------------------------------------


@pytest.mark.parametrize("provider, cls", [("jobspy", "search"), ("workable", "search"), ("joberty", "search"), ("somethingnew", "search"), ("infostud", "unclassified")])
def test_a_search_based_or_unclassified_ad_is_never_closed_over_any_number_of_runs(clock, provider, cls):
    gone = ad(2, provider)
    runs = [clock.run({provider: {"boards": {"all": ([], [])}}}) for _ in range(6)]
    sim = simulate(ledger(entry(gone)), runs)
    assert sim["entries"][gone["jobId"]]["closedAt"] is None
    assert counts(sim, cls, 0)["absentNew"] == 1 and counts(sim, cls)["absentTotal"] == 1
    assert not any("closed" in counts(sim, cls, i) for i in range(6))


@pytest.mark.parametrize("status", ["failed", "skipped", "partial", "unfinished"])
def test_a_source_that_was_not_successful_changes_nothing(clock, status):
    gone = ad(2, "jobspy")
    sim = simulate(ledger(entry(gone)), [clock.run({"jobspy": {"boards": {"all": ([], [])}, "status": status}})])
    assert counts(sim, "search")["heldSourceDidNotRun"] == 1 and sim["state"][gone["jobId"]]["absentSince"] is None


def test_a_row_under_an_older_key_is_counted_apart_and_never_absent_or_stale(clock):
    old = ad(2, "jobspy")
    runs = [clock.run({"jobspy": {"boards": {"all": ([], [])}}}, day=40 + i) for i in range(5)]
    sim = simulate(ledger(entry(old, key="older")), runs)
    assert counts(sim, "search")["olderKey"] == 1 and "staleTotal" not in counts(sim, "search") and "absentTotal" not in counts(sim, "search")


@pytest.mark.parametrize("day, successful, stale", [(29, 3, False), (30, 2, False), (30, 3, True)])
def test_stale_needs_30_days_and_3_successful_runs(clock, day, successful, stale):
    gone = ad(2, "jobspy")
    runs = [clock.run({"jobspy": {"boards": {"all": ([], [])}}}, day=day - successful + 1 + i) for i in range(successful)]
    assert runs[-1].manifest["startedAt"] == at(day)
    sim = simulate(ledger(entry(gone)), runs)
    assert bool(sim["state"][gone["jobId"]]["staleSince"]) is stale
    assert sim["entries"][gone["jobId"]]["closedAt"] is None and gone["jobId"] in sim["entries"], "a flag only"


def test_a_partial_run_does_not_count_toward_stale_and_being_seen_clears_the_flag(clock):
    gone = ad(2, "jobspy")
    partial = [clock.run({"jobspy": {"boards": {"all": ([], [])}, "status": "partial"}}, day=40 + i) for i in range(3)]
    assert "staleTotal" not in counts(simulate(ledger(entry(gone)), partial), "search")
    ok = [clock.run({"jobspy": {"boards": {"all": ([], [])}}}, day=50 + i) for i in range(3)]
    back = clock.run({"jobspy": {"boards": {"all": ([gone], [])}}}, day=60)
    sim = simulate(ledger(entry(gone)), ok + [back])
    assert counts(sim, "search", 2)["staleNew"] == 1 and counts(sim, "search")["staleCleared"] == 1
    assert sim["state"][gone["jobId"]]["staleSince"] is None


# --- purity and the report ---------------------------------------------------------------------------------------------


def report_for(clock, start, runs, **extra):
    kw = {"view_bytes": 3000, "view_rows": 1, "scored_bytes": 4000, "scored_rows": 1, "user_data": {"applications": set()}, "as_of": at(10), **extra}
    return lr.build_report(start, start, runs, **kw)


def test_the_functions_mutate_nothing_and_give_the_same_answer_twice(clock):
    keep, gone = ad(1), ad(2)
    start = ledger(entry(keep), entry(gone), entry(ad(3, "jobspy")))
    before = copy.deepcopy(start)
    runs = [clock.run({"greenhouse": full([keep]), "jobspy": {"boards": {"all": ([], [])}}}) for _ in range(3)]
    stored = copy.deepcopy([r.manifest for r in runs]), copy.deepcopy([[b.jobs for b in r.sources["greenhouse"].batches] for r in runs])
    first = report_for(clock, start, runs)
    second = report_for(clock, start, runs)
    assert first == second and start == before
    assert stored == (copy.deepcopy([r.manifest for r in runs]), copy.deepcopy([[b.jobs for b in r.sources["greenhouse"].batches] for r in runs]))
    json.dumps(first)  # a report file can always be written


def test_older_key_options_and_sizes_are_priced_and_a_cross_post_takes_no_extra_row(clock):
    keep = ad(1, "jobspy")
    absent = ad(2, "jobspy")
    old = ad(3, "jobspy")
    start = ledger(entry(keep), entry(absent), entry(old, key="older"))
    report = report_for(clock, start, [clock.run({"jobspy": {"boards": {"all": ([keep], [])}}})])
    options = report["olderKey"]
    assert options["rows"] == 1 and [o["fileRowsAdded"] for o in options["options"]] == [1, 1, 0]
    assert options["options"][0]["defaultListRows"] == options["options"][1]["defaultListRows"] + 1 == 3
    assert options["slimBytes"] < options["fullBytes"]
    by_name = {r["scenario"]: r for r in report["sizes"]}
    assert by_name["S5, full rows, older-key rows kept"]["rows"] == 3 and by_name["S5, full rows, older-key rows out"]["rows"] == 2
    assert by_name["S5, slim absent rows, older-key rows kept"]["discoveredBytes"] < by_name["S5, full rows, older-key rows kept"]["discoveredBytes"]
    rows = {(r["searchKey"], r["current"]): r for r in report["perKey"]}
    assert rows[("older", False)]["rows"] == 1 and rows[("k", True)]["found"] == 1


def test_user_data_is_reported_per_state_and_a_job_outside_the_ledger_is_counted(clock):
    keep, absent, old = ad(1, "jobspy"), ad(2, "jobspy"), ad(3, "jobspy")
    start = ledger(entry(keep), entry(absent), entry(old, key="older"))
    user = {"applications": {absent["jobId"]}, "tailoredDocuments": {old["jobId"], "notInLedger"}}
    report = report_for(clock, start, [clock.run({"jobspy": {"boards": {"all": ([keep], [])}}})], user_data=user)
    data = report["userData"]
    assert data["byState"] == {"absent": 1, "olderKey": 1}
    assert data["notInLedger"] == {"applications": 0, "tailoredDocuments": 1}


def test_every_snapshot_provider_says_what_it_cannot_prove_and_no_board_is_called_proven_today(clock):
    assert set(lr.BOARD_EVIDENCE) == set(lr.SNAPSHOT)
    assert all(e["cannotProveToday"] and e["couldProve"] for e in lr.BOARD_EVIDENCE.values())
    report = report_for(clock, ledger(), [clock.run({"greenhouse": full([ad(1)])})])
    assert report["boards"] and not any(b["reliableProof"] for b in report["boards"])
    assert report["boards"][0]["balanced"]
    assert {i["where"] for i in report["storage"]} == {"backend", "browser", "both"}


def test_the_backend_data_join_finds_each_kind(tmp_path):
    data = tmp_path / "data"
    (data / "resumes" / "j2").mkdir(parents=True)
    (data / "outreach" / "j3").mkdir(parents=True)
    (data / "ai" / "findings" / "job").mkdir(parents=True)
    (data / "ai" / "findings" / "job" / f"{lr.job_key('j4')}.json").write_text("{}")
    (data / "jobs").mkdir()
    (data / "jobs" / "scored_jobs.json").write_text(json.dumps({"jobs": [{"jobId": "j5", "tailoredAssets": {"x": 1}}, {"jobId": "j6"}]}))
    assert lr.backend_user_data(tmp_path, {"j4", "j9"}, {"j1"}) == {
        "applications": {"j1"}, "tailoredDocuments": {"j2"}, "outreachContacts": {"j3"}, "aiFindings": {"j4"}, "tailoredLinkInScored": {"j5"},
    }
    assert lr.backend_user_data(tmp_path / "nothing", set()) == {k: set() for k in ("applications", "tailoredDocuments", "outreachContacts", "aiFindings", "tailoredLinkInScored")}


def test_python_never_reads_the_application_store_and_the_report_says_applications_were_not_joined(clock, tmp_path, capsys):
    store = tmp_path / "data" / "applications"
    store.mkdir(parents=True)
    (store / "applications.json").write_text(json.dumps({"applications": {"a": {"posting": {"jobId": "fromStore"}}}}))
    assert lr.backend_user_data(tmp_path, set())["applications"] == set(), "the store is not read, even when it is there"
    on_disk(clock.root, clock, [ad(1)])
    assert import_run.main(["--latest", "--lifecycle-report"], root=clock.root) == 0
    assert "APPLICATIONS NOT JOINED" in capsys.readouterr().out
    ids = tmp_path / "ids.txt"
    gone = ad(1)["jobId"]
    ids.write_text(f"{gone}\n\n")
    assert import_run.main(["--latest", "--lifecycle-report", "--application-job-ids", str(ids)], root=clock.root) == 0
    out = capsys.readouterr().out
    assert "APPLICATIONS NOT JOINED" not in out and "would be: found 1" in out


# --- the command line --------------------------------------------------------------------------------------------------


def on_disk(root, clock, jobs):
    """A root as a real install leaves it: a run, its ledger, the view and the scored file."""
    jobs_dir = root / "data" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    start = ledger(*[entry(j) for j in jobs])
    (jobs_dir / "job_history.json").write_text(json.dumps(start))
    (jobs_dir / "discovered_jobs.json").write_text(json.dumps({"meta": {}, "jobs": [{"jobId": j["jobId"]} for j in jobs]}))
    (jobs_dir / "scored_jobs.json").write_text(json.dumps({"meta": {}, "jobs": [{"jobId": j["jobId"]} for j in jobs]}))
    clock.run({"greenhouse": full(jobs[:1])})


def test_the_flag_prints_the_report_and_writes_nothing(clock, capsys):
    jobs = [ad(1), ad(2)]
    on_disk(clock.root, clock, jobs)
    before = snapshot(clock.root)
    assert import_run.main(["--latest", "--lifecycle-report"], root=clock.root) == 0
    out = capsys.readouterr().out
    assert snapshot(clock.root) == before
    for heading in ("Transitions, STRICT", "Transitions, IF PROVEN", "Rows per source and search key", "Older-key rows (D3, not decided)", "Sizes.", "Scoring time",
                    "what each provider can prove", "Where the owner's work is stored", "Ads with the owner's work"):
        assert heading in out
    assert "not measured" in out, "a root with no candidate file says so and does not stop the report"


def test_report_file_is_the_only_file_written_and_stays_in_the_run_folder(clock, capsys):
    on_disk(clock.root, clock, [ad(1)])
    before = snapshot(clock.root)
    assert import_run.main(["--latest", "--lifecycle-report", "--report-file"], root=clock.root) == 0
    after = snapshot(clock.root)
    added = set(after) - set(before)
    assert len(added) == 1 and next(iter(added)).endswith("lifecycle-report.json") and "staging" in next(iter(added))
    assert {k: v for k, v in after.items() if k in before} == before


def test_the_flag_excludes_the_other_modes_and_stops_clearly_without_a_run(clock, capsys, tmp_path):
    with pytest.raises(SystemExit):
        import_run.main(["--latest", "--lifecycle-report", "--dry-run"], root=clock.root)
    capsys.readouterr()
    empty = tmp_path / "empty"
    empty.mkdir()
    assert import_run.main(["--latest", "--lifecycle-report"], root=empty) == 2
    assert import_run.main(["--run", "nosuchrun", "--lifecycle-report"], root=clock.root) == 2
