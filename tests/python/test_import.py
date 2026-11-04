"""The importer and its dry run (slice S3). Offline; every path is under tmp_path.

The replay tests run the real old discovery (staging on, its commit path untouched) and check that importing the staged run on
the ledger as it was before gives exactly what the old commit wrote.
"""

import copy
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest

import importer
import import_run
import job_history
import pipeline_lock
import run_discovery
import run_log
import staging
from dedupe_jobs import dedupe_jobs
from providers.base_provider import JobProvider, ProviderOutcome, board_read, build_canonical_job
from test_staging import discover, settled

T1, T2 = "2026-11-01T10:00:00+00:00", "2026-11-02T10:00:00+00:00"


def canon(n, provider="greenhouse", title=None, company="Acme", description=None, url=True, scraped=T1, **extra):
    return {
        **build_canonical_job(
            provider=provider, source="acme", title=title or f"Product Manager {n}", company=company, location="Remote",
            job_url=f"https://{provider}.example/{n}" if url is True else (url or ""),
            description="Own the roadmap. " * 30 if description is None else description, is_remote=True, scraped_at=scraped,
        ),
        **extra,
    }


class Prov(JobProvider):
    """`proven`: its one board, acme, is staged as a board and read whole (S5b evidence), so a missing ad of it counts as a miss."""

    def __init__(self, jobs, status="ok", boards_failed=(), boards_empty=(), proven=False):
        self.jobs, self.status, self.failed, self.empty, self.proven = jobs, status, list(boards_failed), list(boards_empty), proven
        self.last_outcome = None

    def fetch_jobs(self, *args):
        if self.proven:
            self.stage(self.jobs, part="acme", read=len(self.jobs))
            self.last_outcome = ProviderOutcome(
                status=self.status, read=len(self.jobs), kept=len(self.jobs), boards_failed=self.failed, boards_empty=self.empty,
                boards_read=[board_read("acme", read=len(self.jobs), postings=len(self.jobs), complete=True, reason=None)])
            return list(self.jobs)
        self.last_outcome = ProviderOutcome(
            status=self.status, read=len(self.jobs), kept=len(self.jobs), boards_failed=self.failed, boards_empty=self.empty)
        return list(self.jobs)


def snapshot(root):
    """Every file under root: path, size, mtime and content hash."""
    found = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            found[str(path.relative_to(root))] = (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
    return found


def load(root, name):
    return json.loads((Path(root) / "data/jobs" / name).read_text())


def latest(root):
    return staging.list_runs(root)[0]


def assert_zero(dry):
    assert dry.errors == [] and dry.comparable
    assert dry.ledger_diff.items == [] and dry.view_diff.items == []
    assert dry.derived_vs_replay.items == [] and dry.derived_vs_committed.items == []
    assert dry.difference_count == 0


# --- hand-made staging runs ----------------------------------------------------------------------------------------------


def hand_run(root, run_id, sources, *, ledger_path=None, status=True):
    """A staging run written directly. `sources`: {name: (ads, footer or None)}; a footer of None leaves the source unfinished."""
    run = staging.StagingRun.begin(
        root, run_id, search_key="k", terms=["pm"], locations=["Remote"], country="Serbia", remote_filters=["remote"],
        providers=list(sources), ledger_path=ledger_path,
    )
    for name, (ads, footer) in sources.items():
        writer = run.open_source(name)
        writer.append(ads, part="p", read=len(ads))
        if footer is not None:
            extra = {k: v for k, v in footer.items() if k not in ("status", "complete")}
            writer.finish(status=footer.get("status", "ok"), complete=footer.get("complete", footer.get("status", "ok") == "ok"),
                          read=len(ads), kept=len(ads), **extra)
    if status:
        run.finish()
    return staging.read_run(root, run_id)


OK = {"status": "ok"}


# --- full validation -------------------------------------------------------------------------------------------------------


def test_a_whole_ad_has_no_rejection():
    assert importer.validate_ad(canon(1), "greenhouse") == []


@pytest.mark.parametrize("mutate, code", [
    (lambda j: j.pop("title"), "missing_field:title"),
    (lambda j: j.pop("scrapedAt"), "missing_field:scrapedAt"),
    (lambda j: j.pop("isRemote"), "missing_field:isRemote"),
    (lambda j: j.update(salary=5), "not_text:salary"),
    (lambda j: j.update(description=None), "not_text:description"),
    (lambda j: j.update(isRemote="yes"), "not_boolean:isRemote"),
    (lambda j: j.update(jobId=""), "empty:jobId"),
    (lambda j: j.update(provider="  "), "empty:provider"),
    (lambda j: j.update(title=""), "empty:title"),
    (lambda j: j.update(title="x" * 501), "too_long:title"),
    (lambda j: j.update(description="x" * 1_000_001), "too_long:description"),
    (lambda j: j.update(jobId="a b"), "jobid_has_whitespace"),
    (lambda j: j.update(provider="lever"), "provider_mismatch"),
    (lambda j: j.update(jobUrl="javascript:alert(1)"), "bad_url"),
    (lambda j: j.update(jobUrl="https://"), "bad_url"),
    (lambda j: j.update(jobUrl="https://a.example/has space"), "bad_url"),
    (lambda j: j.update(scrapedAt="yesterday"), "bad_scraped_at"),
    (lambda j: j.update(extra={1, 2}), "not_storable_json"),
    (lambda j: j.update(extra=float("nan")), "not_storable_json"),
])
def test_every_rejection_reason(mutate, code):
    job = canon(1)
    mutate(job)
    assert code in importer.validate_ad(job, "greenhouse")


def test_a_row_that_is_not_an_object_is_rejected():
    assert importer.validate_ad("text", "greenhouse") == ["not_an_object"]


def test_an_empty_job_url_is_allowed_and_a_good_one_passes():
    assert importer.validate_ad(canon(1, url=""), "greenhouse") == []
    assert importer.validate_ad(canon(1, url="http://a.example/x?y=1#z"), "greenhouse") == []


def test_invalid_ads_are_reported_and_left_out_never_imported_and_their_source_closes_nothing(tmp_path):
    known = hand_run(tmp_path, "r0", {"greenhouse": ([canon(1), canon(2)], OK)})
    ledger = importer.plan_import(known, job_history.empty_ledger(), None).ledger
    bad = canon(9)
    bad.pop("scrapedAt")
    run = hand_run(tmp_path, "r1", {"greenhouse": ([canon(1), bad], OK)})  # the staging writer accepts it: jobId, provider, title
    result = importer.plan_import(run, ledger, None)
    assert result.ok and result.report["rejected"] == 1 and result.report["complete"] is False
    assert result.report["reasons"] == {"invalid:missing_field:scrapedAt": 1}
    assert result.report["rejectedExamples"][0]["jobId"] == bad["jobId"]
    assert bad["jobId"] not in result.ledger["jobs"]
    # ad 2 is missing from the run, but a source that lost an ad cannot say it is gone
    assert result.ledger["jobs"][canon(2)["jobId"]]["closedAt"] is None and result.report["heldSourceNotRun"] >= 1
    assert result.report["sources"][0]["heldAsNotRun"] is True


# --- sources that did not run to their end --------------------------------------------------------------------------------


def seeded_ledger(tmp_path):
    first = hand_run(tmp_path, "r0", {
        "greenhouse": ([canon(1), canon(2)], OK), "lever": ([canon(3, "lever"), canon(4, "lever")], OK),
        "ashby": ([canon(5, "ashby")], OK),
    })
    return importer.plan_import(first, job_history.empty_ledger(), None).ledger


def closed(result, ad):
    return result.ledger["jobs"][ad["jobId"]]["closedAt"]


def test_a_run_staged_before_s5b_has_no_closing_evidence_and_counts_no_miss(tmp_path):
    ledger = seeded_ledger(tmp_path)
    run = hand_run(tmp_path, "r1", {"greenhouse": ([canon(1)], OK), "lever": ([canon(3, "lever"), canon(4, "lever")], OK),
                                     "ashby": ([canon(5, "ashby")], OK)})
    result = importer.plan_import(run, ledger, None)
    assert closed(result, canon(2)) is None and result.stats["closed"] == 0
    assert "absentRuns" not in result.ledger["jobs"][canon(2)["jobId"]] and result.stats["keptUnproven"] >= 1


def test_an_unfinished_source_imports_what_it_wrote_and_closes_and_changes_nothing_else(tmp_path):
    ledger = seeded_ledger(tmp_path)
    run = hand_run(tmp_path, "r1", {
        "greenhouse": ([canon(1, description="a new text " * 40)], None),  # killed: no footer
        "lever": ([canon(3, "lever"), canon(4, "lever")], OK), "ashby": ([canon(5, "ashby")], OK),
    })
    result = importer.plan_import(run, ledger, None)
    assert result.ok and result.report["sources"][0]["state"] == "unfinished" and result.report["complete"] is False
    assert closed(result, canon(2)) is None, "ad 2 was not written, which proves nothing"
    assert result.ledger["jobs"][canon(1)["jobId"]]["job"]["description"].startswith("a new text"), "ad 1 was written: imported"
    untouched = lambda l: importer.normalized_ledger(l)["jobs"][canon(2)["jobId"]]
    assert untouched(result.ledger) == untouched(ledger), "untouched, bit for bit (apart from the importer's own stamp)"
    assert result.stats["keptSourceNotRun"] == 1 and result.stats["closed"] == 0
    assert "greenhouse" in result.report["incompleteSources"]


@pytest.mark.parametrize("footer", [
    {"status": "failed", "complete": False}, {"status": "skipped", "complete": False}, {"status": "weird"},
    {"status": "ok", "mismatch": True}, {"status": "ok", "invalid": 2},
])
def test_a_failed_skipped_or_doubtful_source_closes_nothing(tmp_path, footer):
    ledger = seeded_ledger(tmp_path)
    run = hand_run(tmp_path, "r1", {"greenhouse": ([canon(1)], footer), "lever": ([canon(3, "lever"), canon(4, "lever")], OK),
                                     "ashby": ([canon(5, "ashby")], OK)})
    result = importer.plan_import(run, ledger, None)
    assert closed(result, canon(2)) is None and result.stats["closed"] == 0
    assert result.report["sources"][0]["heldAsNotRun"] is True and result.report["complete"] is False


def test_a_partial_source_holds_the_ads_of_its_failed_boards_as_before(tmp_path):
    ledger = seeded_ledger(tmp_path)
    acme = canon(2)
    run = hand_run(tmp_path, "r1", {"greenhouse": ([canon(1)], {"status": "partial", "complete": False, "boardsFailed": ["acme"]}),
                                     "lever": ([canon(3, "lever"), canon(4, "lever")], OK), "ashby": ([canon(5, "ashby")], OK)})
    result = importer.plan_import(run, ledger, None)
    assert closed(result, acme) is None and result.stats["keptFailedBoard"] == 1
    assert result.report["sources"][0]["state"] == "partial" and result.report["heldFailedBoard"] == 1


def test_an_empty_board_holds_its_ads(tmp_path):
    ledger = seeded_ledger(tmp_path)
    run = hand_run(tmp_path, "r1", {"greenhouse": ([], {"status": "ok", "boardsEmpty": ["acme"]}),
                                     "lever": ([canon(3, "lever"), canon(4, "lever")], OK), "ashby": ([canon(5, "ashby")], OK)})
    result = importer.plan_import(run, ledger, None)
    assert result.stats["closed"] == 0 and result.report["heldEmptyBoard"] >= 1


def test_a_source_that_never_started_closes_nothing(tmp_path):
    ledger = seeded_ledger(tmp_path)
    run = hand_run(tmp_path, "r1", {"greenhouse": ([canon(1), canon(2)], OK), "lever": ([], None)})
    (run.dir / "ashby.jsonl").unlink(missing_ok=True)
    manifest = json.loads((run.dir / "run.json").read_text())
    manifest["providers"].append("ashby")
    (run.dir / "run.json").write_text(json.dumps(manifest))
    result = importer.plan_import(staging.read_run(tmp_path, "r1"), ledger, None)
    assert result.stats["closed"] == 0
    assert {s["name"]: s["state"] for s in result.report["sources"]} == {"greenhouse": "complete", "lever": "unfinished", "ashby": "unfinished"}


# --- refusals -------------------------------------------------------------------------------------------------------------


def test_a_run_whose_staging_failed_is_refused_and_nothing_is_planned(tmp_path):
    run = hand_run(tmp_path, "r1", {"greenhouse": ([canon(1)], OK)})
    (run.dir / "status.json").write_text(json.dumps({"version": 1, "ok": False, "problems": ["greenhouse: staging stopped writing"]}))
    result = importer.plan_import(staging.read_run(tmp_path, "r1"), job_history.empty_ledger(), None)
    assert not result.ok and result.refused[0].startswith("staging_failed") and result.view is None
    assert result.ledger == job_history.empty_ledger()


def test_a_missing_or_foreign_manifest_is_refused(tmp_path):
    run = hand_run(tmp_path, "r1", {"greenhouse": ([canon(1)], OK)})
    (run.dir / "run.json").write_text("{")
    assert importer.plan_import(staging.read_run(tmp_path, "r1"), job_history.empty_ledger(), None).refused[0].startswith("no_manifest")
    (run.dir / "run.json").write_text(json.dumps({"version": 99, "providers": []}))
    assert importer.plan_import(staging.read_run(tmp_path, "r1"), job_history.empty_ledger(), None).refused[0].startswith("unsupported_version")


def test_a_run_that_never_reached_its_end_is_planned_and_marked_unfinished(tmp_path):
    run = hand_run(tmp_path, "r1", {"greenhouse": ([canon(1)], None)}, status=False)  # killed: no status.json
    result = importer.plan_import(run, job_history.empty_ledger(), None)
    assert result.ok and result.report["stagingStatus"] == "unfinished" and result.report["complete"] is False


# --- dedupe and merge ---------------------------------------------------------------------------------------------------------


def test_duplicates_and_cross_posts_are_counted_and_the_result_is_dedupe_jobs(tmp_path):
    ads = [
        canon(1), canon(1),  # the same ad twice (a search finds it twice)
        canon(2, title="Product Manager Pay", company="Pay Co"),
        canon(3, title="Product Manager Pay", company="Pay Co", url="https://greenhouse.example/other"),  # the same role, another post
        canon(4, url=""), canon(5, title="Product Manager 4", url=""),  # no address: told apart by title, company, place
    ]
    run = hand_run(tmp_path, "r1", {"greenhouse": (ads, OK)})
    result = importer.plan_import(run, job_history.empty_ledger(), None)
    kept = dedupe_jobs([a for a in ads])
    assert result.report["duplicatesRemoved"] + result.report["crosspostsMerged"] == len(ads) - len(kept)
    assert result.report["duplicatesRemoved"] == 2 and result.report["crosspostsMerged"] == 1
    assert [j["jobId"] for j in result.view["jobs"]] == [j["jobId"] for j in kept]
    assert result.view["meta"]["rawCount"] == 6 and result.view["meta"]["dedupedCount"] == 3


def test_a_thin_description_is_replaced_by_the_stored_one_and_counted(tmp_path):
    first = hand_run(tmp_path, "r0", {"greenhouse": ([canon(1)], OK)})
    ledger = importer.plan_import(first, job_history.empty_ledger(), None).ledger
    run = hand_run(tmp_path, "r1", {"greenhouse": ([canon(1, description="short")], OK)})
    result = importer.plan_import(run, ledger, None)
    assert result.report["thinDescriptionReplaced"] == 1
    assert result.ledger["jobs"][canon(1)["jobId"]]["job"]["description"] == canon(1)["description"]


# --- pure, idempotent, order as the rules have it ----------------------------------------------------------------------------


def test_planning_changes_none_of_its_inputs_and_gives_the_same_answer_twice(tmp_path):
    first = hand_run(tmp_path, "r0", {"greenhouse": ([canon(1), canon(2)], OK)})
    ledger = importer.plan_import(first, job_history.empty_ledger(), None).ledger
    run = hand_run(tmp_path, "r1", {"greenhouse": ([canon(1)], OK)})
    previous = {"meta": {"generatedAt": T1}, "jobs": [{"jobId": canon(1)["jobId"], "llmFacts": {"x": 1}}]}
    before = (copy.deepcopy(ledger), copy.deepcopy(previous), copy.deepcopy(run.sources["greenhouse"].batches))
    one = importer.plan_import(run, ledger, previous)
    two = importer.plan_import(run, ledger, previous)
    assert (ledger, previous, run.sources["greenhouse"].batches) == before
    assert importer.ledger_bytes(one.ledger) == importer.ledger_bytes(two.ledger)
    assert json.dumps(one.view) == json.dumps(two.view) and one.report == two.report


def test_importing_the_same_run_twice_gives_identical_bytes(tmp_path):
    first = hand_run(tmp_path, "r0", {"greenhouse": ([canon(1), canon(2)], OK), "lever": ([canon(3, "lever")], OK)})
    ledger = importer.plan_import(first, job_history.empty_ledger(), None).ledger
    run = hand_run(tmp_path, "r1", {"greenhouse": ([canon(1), canon(9)], OK), "lever": ([canon(3, "lever")], None)})
    once = importer.plan_import(run, ledger, None)
    twice = importer.plan_import(run, once.ledger, None)
    assert twice.report["alreadyImported"] is True
    assert importer.ledger_bytes(twice.ledger) == importer.ledger_bytes(once.ledger)
    assert json.dumps(twice.view) == json.dumps(once.view), "the view too, byte for byte"
    assert twice.stats == once.stats


def test_apply_run_alone_is_idempotent_on_the_ledger_data(tmp_path):
    """Forced to apply the run again, the ledger's data is the same; only the importer's account of what that application changed differs."""
    first = hand_run(tmp_path, "r0", {"greenhouse": ([canon(1), canon(2)], OK), "lever": ([canon(3, "lever")], OK)})
    ledger = importer.plan_import(first, job_history.empty_ledger(), None).ledger
    run = hand_run(tmp_path, "r1", {"greenhouse": ([canon(1), canon(9)], OK), "lever": ([canon(3, "lever")], None)})
    once = importer.plan_import(run, ledger, None)
    again = importer.plan_import(run, once.ledger, None, force=True)
    assert again.report.get("alreadyImported") is None
    assert importer.compare_ledgers(again.ledger, once.ledger, "again", "once").items == []
    assert [j["jobId"] for j in again.view["jobs"]] == [j["jobId"] for j in once.view["jobs"]]
    assert once.stats["new"] == 1 and again.stats["new"] == 0 and again.stats["known"] >= 2, "its counts say nothing was new the second time"


def test_import_order_changes_the_result_exactly_as_apply_run_does(tmp_path, monkeypatch):
    """apply_run itself has no ordering rule: applied backwards (here, with the recovery override), an older run moves lastSeen
    back. The importer's order guard (S4a) refuses that by default."""
    root = tmp_path / "root"
    root.mkdir()
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(2)], proven=True)}) == 0
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(3)], proven=True)}) == 0
    older, newer = (staging.read_run(root, r) for r in reversed(staging.list_runs(root)))
    empty = job_history.empty_ledger()
    forward = importer.plan_import(newer, importer.plan_import(older, empty, None).ledger, None)
    refused = importer.plan_import(older, importer.plan_import(newer, empty, None).ledger, None)
    assert not refused.ok and refused.refused[0].startswith("older_run"), "S4a: a real import refuses to go backwards"
    assert "lastSeen backwards" in refused.refused[0] and "allow_older" in refused.refused[0], "with an explicit message"
    backward = importer.plan_import(older, importer.plan_import(newer, empty, None).ledger, None, allow_older=True)
    ad1 = canon(1)["jobId"]
    assert forward.ledger["jobs"][ad1]["lastSeen"] == importer.import_time(newer) != importer.import_time(older)
    assert backward.ledger["jobs"][ad1]["lastSeen"] == importer.import_time(older), "an older run moved lastSeen back"
    assert importer.ledger_bytes(forward.ledger) != importer.ledger_bytes(backward.ledger)
    # what forward gives is what the old path left behind
    assert importer.compare_ledgers(forward.ledger, load(root, "job_history.json"), "forward", "committed").total >= 0
    ad2 = canon(2)["jobId"]
    assert forward.ledger["jobs"][ad2]["absentRuns"] == 1, "a miss in the newer run, which no longer lists it"
    assert "absentRuns" not in backward.ledger["jobs"][ad2], "backwards, the older run clears it"


# --- replay equals what the old commit wrote ---------------------------------------------------------------------------------


def run_and_replay(root, monkeypatch, providers):
    assert discover(root, monkeypatch, providers) == 0
    run_id = latest(root)
    dry = importer.dry_run(root, run_id)
    assert_zero(dry)
    return run_id, dry


def test_the_replay_of_every_run_of_a_history_equals_the_committed_files(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "data/jobs").mkdir(parents=True)
    # An install that predates the ledger: the discovered file holds an ad with facts the ledger must be seeded with.
    seed = canon(1)
    (root / "data/jobs/discovered_jobs.json").write_text(json.dumps({
        "meta": {"generatedAt": "2026-10-01T00:00:00+00:00"}, "jobs": [{**seed, "llmFacts": {"_fingerprint": job_history.job_fingerprint(seed), "workMode": "remote"}}],
    }))
    history = [
        {"greenhouse": Prov([canon(1), canon(2), canon(3)], proven=True), "lever": Prov([canon(10, "lever"), canon(11, "lever")])},
        # 3 misses a proven board; 2 changes; a cross-post of ad 10 arrives from ashby; a duplicate of 1 from lever
        {"greenhouse": Prov([canon(1), canon(2, description="rewritten " * 40), canon(4)], proven=True),
         "lever": Prov([canon(10, "lever"), canon(11, "lever"), canon(1, "lever", url=seed["jobUrl"])]),
         "ashby": Prov([canon(20, "ashby", title="Product Manager 10")])},
        # 3 misses it again and closes
        {"greenhouse": Prov([canon(1), canon(2, description="rewritten " * 40), canon(4)], proven=True),
         "lever": Prov([canon(10, "lever"), canon(11, "lever")]), "ashby": Prov([canon(20, "ashby", title="Product Manager 10")])},
        # a thin description after a full one; lever fails; greenhouse has a failed board and an empty one
        {"greenhouse": Prov([canon(1, description="x"), canon(2)], status="partial", boards_failed=["acme"], boards_empty=["b2"]),
         "lever": Prov([], status="failed"), "ashby": Prov([canon(20, "ashby", title="Product Manager 10")])},
        # ad 3 comes back (reopened); ashby is skipped
        {"greenhouse": Prov([canon(1), canon(2), canon(3)], proven=True), "lever": Prov([canon(10, "lever")]), "ashby": Prov([], status="skipped")},
        {"greenhouse": Prov([], boards_empty=["acme"]), "lever": Prov([canon(10, "lever")]),
         "ashby": Prov([canon(20, "ashby", title="Product Manager 10")])},
    ]
    stats = []
    for providers in history:
        run_id, dry = run_and_replay(root, monkeypatch, providers)
        assert dry.replay_exact
        stats.append(dry.result.stats)
    assert sum(s["closed"] for s in stats) >= 1 and sum(s["reopened"] for s in stats) >= 1
    assert sum(s["keptFullerDescription"] for s in stats) >= 1 and sum(s["keptFailedBoard"] for s in stats) >= 1
    assert sum(s["keptEmptyBoard"] for s in stats) >= 1 and sum(s["keptSourceNotRun"] for s in stats) >= 1
    assert stats[0]["carriedFacts"] == 1, "the seed's facts came from the discovered file the run replaced"


def test_the_live_commit_writes_the_ledger_with_a_generation_and_the_view_derived_from_it(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    run_id, dry = run_and_replay(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(2)])})
    committed = load(root, "job_history.json")
    assert committed["lastImport"]["runId"] == run_id and committed["generation"] == 1
    assert next(iter(committed)) == "generation", "first in the file, so a reader can peek at it"
    assert all({"lastRunId", "lastRunPos"} <= set(e) for e in committed["jobs"].values())
    view = load(root, "discovered_jobs.json")
    assert next(iter(view["meta"])) == "ledgerGeneration" and view["meta"]["ledgerGeneration"] == 1
    assert json.dumps(view, indent=2) == json.dumps(importer.derive_view(committed), indent=2), "the file is the derivation, byte for byte"
    _, second = run_and_replay(root, monkeypatch, {"greenhouse": Prov([canon(1)])})
    assert load(root, "job_history.json")["generation"] == 2 == load(root, "discovered_jobs.json")["meta"]["ledgerGeneration"]


def test_a_difference_in_the_committed_files_is_found_and_named(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    run_id, _ = run_and_replay(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(2)])})
    ledger = load(root, "job_history.json")
    victim = canon(1)["jobId"]
    ledger["jobs"][victim]["roleKey"] = "tampered"
    del ledger["jobs"][canon(2)["jobId"]]
    (root / "data/jobs/job_history.json").write_text(json.dumps(ledger, indent=2))
    view = load(root, "discovered_jobs.json")
    view["jobs"][0]["title"] = "Something else"
    view["meta"]["rawCount"] = 99
    (root / "data/jobs/discovered_jobs.json").write_text(json.dumps(view, indent=2))
    dry = importer.dry_run(root, run_id)
    texts = dry.ledger_diff.items + dry.view_diff.items
    assert any("roleKey" in t and "tampered" in t for t in texts) and any(canon(2)["jobId"] in t for t in dry.ledger_diff.items)
    assert any("title" in t for t in dry.view_diff.items) and any("rawCount" in t for t in dry.view_diff.items)
    assert dry.derived_vs_replay.total == 0, "derive_view still agrees with the replay"
    assert dry.derived_vs_committed.total >= 2 and dry.difference_count >= 4


def test_when_the_committed_files_belong_to_another_run_nothing_is_compared(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    first, _ = run_and_replay(root, monkeypatch, {"greenhouse": Prov([canon(1)])})
    run_and_replay(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(2)])})
    dry = importer.dry_run(root, first)
    assert not dry.comparable and dry.committed_run_id == latest(root) and dry.errors == []
    assert dry.difference_count == dry.derived_vs_replay.total == 0 and dry.ledger_diff.total == 0


def test_a_run_staged_before_the_discovered_file_was_kept_is_replayed_but_marked_not_exact(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    run_id, _ = run_and_replay(root, monkeypatch, {"greenhouse": Prov([canon(1)])})
    manifest_path = root / "data/jobs/staging" / run_id / "run.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["discoveredBefore"]
    manifest_path.write_text(json.dumps(manifest))
    assert importer.dry_run(root, run_id).replay_exact is False


# --- derive_view ---------------------------------------------------------------------------------------------------------------


def test_derive_view_changes_nothing_and_gives_the_same_bytes_every_time(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    # A second, whole source in both runs: a run whose only source is partial has no usable source and imports nothing (S8b).
    run_and_replay(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(2)]), "lever": Prov([canon(10, "lever")])})
    _, dry = run_and_replay(root, monkeypatch, {"greenhouse": Prov([canon(1)], status="partial", boards_failed=["acme"]), "lever": Prov([canon(10, "lever")])})
    ledger = dry.result.ledger
    before = copy.deepcopy(ledger)
    one, two = importer.derive_view(ledger), importer.derive_view(ledger)
    assert ledger == before and json.dumps(ledger) == json.dumps(before), "the input is untouched"
    assert json.dumps(one) == json.dumps(two)
    one["jobs"][0]["title"] = "changed by a caller"
    one["jobs"][0]["llmFacts"] = {"mutated": True}
    assert ledger == before, "and what it returns shares nothing with the ledger"
    assert json.dumps(importer.derive_view(ledger)) == json.dumps(two)


def test_derive_view_refuses_a_ledger_no_import_produced():
    with pytest.raises(importer.ViewError):
        importer.derive_view(job_history.empty_ledger())


def test_derive_view_keeps_the_order_of_the_import_not_the_order_of_the_ledger(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    run_and_replay(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(2), canon(3)])})
    _, dry = run_and_replay(root, monkeypatch, {"greenhouse": Prov([canon(3), canon(1), canon(2)])})
    assert [j["jobId"] for j in dry.result.view["jobs"]] == [canon(n)["jobId"] for n in (3, 1, 2)]
    assert [j["jobId"] for j in importer.derive_view(dry.result.ledger)["jobs"]] == [canon(n)["jobId"] for n in (3, 1, 2)]


# --- the dry run writes nothing -------------------------------------------------------------------------------------------------


@pytest.fixture
def readonly_world():
    """A context manager: inside it everything that could write under a root raises. Reads, and the lock outside the root, work."""
    import builtins
    import contextlib
    import shutil

    @contextlib.contextmanager
    def guard(root):
        root = str(root)
        monkeypatch = pytest.MonkeyPatch()

        def inside(path):
            try:
                return str(os.path.abspath(os.fspath(path))).startswith(root)
            except TypeError:
                return False

        real_open, real_os_open = builtins.open, os.open

        def checked_open(file, mode="r", *a, **k):
            if isinstance(file, (str, bytes, os.PathLike)) and inside(file) and set(mode) & set("wax+"):
                raise AssertionError(f"dry run tried to write {file}")
            return real_open(file, mode, *a, **k)

        def checked_os_open(path, flags, *a, **k):
            if inside(path) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
                raise AssertionError(f"dry run tried to open {path} for writing")
            return real_os_open(path, flags, *a, **k)

        def refuse(name):
            def refused(*args, **kwargs):
                if any(inside(a) for a in args if isinstance(a, (str, os.PathLike))):
                    raise AssertionError(f"dry run called {name}")
                return None
            return refused

        monkeypatch.setattr(builtins, "open", checked_open)
        monkeypatch.setattr(os, "open", checked_os_open)
        for name in ("rename", "replace", "link", "symlink", "unlink", "remove", "mkdir", "makedirs", "rmdir", "chmod", "utime", "truncate"):
            monkeypatch.setattr(os, name, refuse(f"os.{name}"))
        for name in ("copyfile", "copy", "copy2", "move", "rmtree"):
            monkeypatch.setattr(shutil, name, refuse(f"shutil.{name}"))
        for name in ("write_text", "write_bytes", "touch", "mkdir", "unlink", "rename", "replace"):
            monkeypatch.setattr(Path, name, refuse(f"Path.{name}"))
        try:
            yield
        finally:
            monkeypatch.undo()  # only the patches made here: this is a MonkeyPatch of its own

    return guard


def make_world(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    run_and_replay(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(2)])})
    run_and_replay(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(3)])})
    return root


def test_the_dry_run_writes_nothing_not_a_byte_not_a_timestamp(tmp_path, monkeypatch, readonly_world, capsys):
    root = make_world(tmp_path, monkeypatch)
    before = snapshot(root)
    with readonly_world(root):
        dry = importer.dry_run(root, latest(root))
        assert_zero(dry)
        assert import_run.main(["--latest", "--dry-run"], root=root) == 0
    assert snapshot(root) == before
    assert "RESULT: ZERO DIFFERENCES" in capsys.readouterr().out


def test_report_file_writes_one_file_in_the_runs_staging_folder_and_nothing_else(tmp_path, monkeypatch, capsys):
    root = make_world(tmp_path, monkeypatch)
    run_id = latest(root)
    before = snapshot(root)
    assert import_run.main(["--run", run_id, "--dry-run", "--report-file"], root=root) == 0
    after = snapshot(root)
    new = set(after) - set(before)
    assert new == {f"data/jobs/staging/{run_id}/import-report.json"}
    assert {k: v for k, v in after.items() if k not in new} == before
    report = root / "data/jobs/staging" / run_id / "import-report.json"
    assert stat.S_IMODE(report.stat().st_mode) == 0o600
    body = json.loads(report.read_text())
    assert body["differences"] == 0 and body["comparable"] is True and body["report"]["runId"] == run_id
    assert "Report written: data/jobs/staging/" in capsys.readouterr().out


def test_the_report_cannot_be_written_outside_a_staging_folder(tmp_path, monkeypatch):
    root = make_world(tmp_path, monkeypatch)
    dry = importer.dry_run(root, latest(root))
    for bad in ("../../x", "nope", ""):
        with pytest.raises(ValueError):
            importer.write_report(root, bad, dry)


# --- the CLI ---------------------------------------------------------------------------------------------------------------------


def test_cli_zero_differences_prints_the_summary_and_exits_0(tmp_path, monkeypatch, capsys):
    root = make_world(tmp_path, monkeypatch)
    assert import_run.main(["--latest", "--dry-run"], root=root) == 0
    out = capsys.readouterr().out
    for expected in ("Import dry-run of run", "Staging on disk: 2 runs", "Sources:", "greenhouse", "duplicates removed 0",
                     "ledger, replay vs committed:            0 differences", "derive_view vs committed:               0 differences",
                     "Excluded as volatile", "RESULT: ZERO DIFFERENCES"):
        assert expected in out, expected


def test_cli_differences_exit_1_and_print_the_first_n(tmp_path, monkeypatch, capsys):
    root = make_world(tmp_path, monkeypatch)
    ledger = load(root, "job_history.json")
    for entry in ledger["jobs"].values():
        entry["roleKey"] = "tampered"
    (root / "data/jobs/job_history.json").write_text(json.dumps(ledger, indent=2))
    assert import_run.main(["--latest", "--dry-run", "--limit", "2"], root=root) == 1
    out = capsys.readouterr().out
    assert out.count("[ledger]") == 2 and "more differences not shown" in out and "DIFFERENCES" in out and "ZERO" not in out


def test_cli_exit_codes_for_nothing_to_compare_errors_and_a_busy_run(tmp_path, monkeypatch, capsys):
    root = make_world(tmp_path, monkeypatch)
    older = staging.list_runs(root)[1]
    assert import_run.main(["--run", older, "--dry-run"], root=root) == 3
    assert "NOT POSSIBLE" in capsys.readouterr().out
    assert import_run.main(["--run", "nosuchrun", "--dry-run"], root=root) == 2
    with pytest.raises(SystemExit) as stop:
        import_run.main(["--latest"], root=root)
    assert stop.value.code == 2, "one of --dry-run and --import is required"
    capsys.readouterr()
    assert import_run.main(["--latest", "--dry-run", "--allow-older"], root=root) == 2
    assert "--allow-older only goes with --import" in capsys.readouterr().err
    lock = pipeline_lock.acquire()
    try:
        assert import_run.main(["--latest", "--dry-run"], root=root) == 2
    finally:
        lock.release()
    assert "in progress" in capsys.readouterr().err
    empty = tmp_path / "empty"
    empty.mkdir()
    assert import_run.main(["--latest", "--dry-run"], root=empty) == 2


def test_cli_refuses_a_run_whose_staging_failed_with_exit_2(tmp_path, monkeypatch, capsys):
    root = make_world(tmp_path, monkeypatch)
    run_id = latest(root)
    (root / "data/jobs/staging" / run_id / "status.json").write_text(json.dumps({"version": 1, "ok": False, "problems": ["x"]}))
    assert import_run.main(["--run", run_id, "--dry-run"], root=root) == 2
    assert "staging_failed" in capsys.readouterr().out


# --- staging failure is marked in the record and nowhere else ----------------------------------------------------------------------


def only_record():
    found = [p for p in run_log.runs_dir().glob("*.json") if run_log.is_record_name(p.name)]
    assert len(found) == 1
    return json.loads(found[0].read_text())


def test_a_run_whose_staging_works_is_marked_ok(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1)])}) == 0
    record = only_record()
    assert record["staging"]["ok"] is True and record["staging"]["problems"] == [] and record["status"] == "ok"
    assert record["staging"]["runs"] >= 1 and record["staging"]["bytes"] > 0, "the disk use is in the record too"
    status = json.loads((root / "data/jobs/staging" / latest(root) / "status.json").read_text())
    assert status["ok"] is True and stat.S_IMODE((root / "data/jobs/staging" / latest(root) / "status.json").stat().st_mode) == 0o600


@pytest.mark.parametrize("how", ["source_stops_writing", "staging_folder_cannot_be_made", "provider_stages_less_than_it_returns"])
def test_a_staging_failure_marks_the_run_commits_nothing_and_is_refused_by_the_importer(tmp_path, monkeypatch, how):
    """S4a: incomplete staging is never imported as if it were a complete scrape. The run fails; the ledger and the view are untouched."""
    root = tmp_path / "root"
    (root / "data/jobs").mkdir(parents=True)
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1)])}) == 0, "a healthy first run"
    live = {p.name: p.read_bytes() for p in (root / "data/jobs").iterdir() if p.is_file()}
    for p in list(run_log.runs_dir().glob("*")):
        p.unlink()
    jobs = [canon(1), canon(2)]

    class Careless(Prov):
        def fetch_jobs(self, *args):
            self.stage([self.jobs[0]], part="first")
            return super().fetch_jobs(*args)

    provider = Careless(jobs) if how == "provider_stages_less_than_it_returns" else Prov(jobs)
    if how == "staging_folder_cannot_be_made":
        import shutil
        shutil.rmtree(root / "data/jobs/staging")
        (root / "data/jobs/staging").write_text("in the way")
        live = {p.name: p.read_bytes() for p in (root / "data/jobs").iterdir() if p.is_file()}
    if how == "source_stops_writing":
        real = staging.os.write

        def failing(fd, data):
            if b'"t":"batch"' in bytes(data):
                raise OSError(28, "No space left on device")
            return real(fd, data)

        with monkeypatch.context() as patch:
            patch.setattr(staging.os, "write", failing)
            assert discover(root, monkeypatch, {"greenhouse": provider}) == 1
    else:
        assert discover(root, monkeypatch, {"greenhouse": provider}) == 1

    record = only_record()
    assert record["staging"]["ok"] is False and record["staging"]["problems"]
    assert record["status"] == "failed", "never reported as saved"
    assert any(i["level"] == "error" and "Staging failed" in i["message"] for i in record["issues"])
    assert any(i["level"] == "error" and "Nothing was imported" in i["message"] for i in record["issues"])
    assert {p.name: p.read_bytes() for p in (root / "data/jobs").iterdir() if p.is_file()} == live, "ledger and view untouched"
    if how != "staging_folder_cannot_be_made":
        folder = root / "data/jobs/staging" / latest(root)
        assert json.loads((folder / "status.json").read_text())["ok"] is False
        result = importer.plan_import(staging.read_run(root, latest(root)), job_history.empty_ledger(), None)
        assert not result.ok and result.refused[0].startswith("staging_failed")
        outcome = importer.import_staged_run(root, latest(root))
        assert not outcome.ok and outcome.refused[0].startswith("staging_failed") and not staging.is_imported(root, latest(root))


def test_apply_run_without_a_run_id_stamps_nothing():
    jobs = [canon(1)]
    ledger = job_history.empty_ledger()
    job_history.apply_run(ledger, jobs, now=T1, providers_returned={"greenhouse": 1}, key="k", role_key=lambda j: "r")
    entry = next(iter(ledger["jobs"].values()))
    assert not set(importer.LEDGER_STAMPS) & set(entry)
    job_history.apply_run(ledger, jobs, now=T2, providers_returned={"greenhouse": 1}, key="k", role_key=lambda j: "r", run_id="r9")
    assert entry["lastRunId"] == "r9" and entry["lastRunPos"] == 0


def test_staging_usage_counts_a_hard_linked_file_once(tmp_path, monkeypatch):
    root = make_world(tmp_path, monkeypatch)
    used = staging.usage(root)
    assert used["runs"] == 2 and used["files"] > 0 and used["bytes"] > 0
    assert staging.usage(tmp_path / "nowhere") == {"runs": 0, "files": 0, "bytes": 0}
