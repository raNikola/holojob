"""The ledger is the truth, discovered_jobs.json a view of it (slice S4a): generation check, recovery, locks, interruptions.

Offline; every path is under tmp_path. The cases in tests/fixtures/view-generation.json are also run by tests/js/viewGuard.test.js.
"""

import copy
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import enrich_jobs
import import_run
import importer
import job_history
import pipeline_lock
import run_log
import run_scoring
import staging
import view_guard
from conftest import select_provider
from dedupe_jobs import _crosspost_key, dedupe_jobs
from export_jobs import discovered_payload
from match_engine import shadow
from test_import import Prov, canon, hand_run, latest, load, OK
from test_staging import discover

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "python" / "job_scoring" / "view_guard.py"
CASES = json.loads((ROOT / "tests" / "fixtures" / "view-generation.json").read_text())["cases"]


def paths(root):
    jobs = Path(root) / "data/jobs/discovered_jobs.json"
    return jobs, job_history.ledger_path(jobs)


def world(tmp_path, monkeypatch, runs=2, ads=3):
    """A root after `runs` real discoveries. Returns (root, the view text after the first run: a view that is now behind)."""
    root = tmp_path / "root"
    root.mkdir()
    first_view = None
    for n in range(runs):
        assert discover(root, monkeypatch, {"greenhouse": Prov([canon(i) for i in range(1, ads + n + 1)])}) == 0
        if first_view is None:
            first_view = paths(root)[0].read_text()
    return root, first_view


def make_stale(root, old_view):
    jobs, _ = paths(root)
    jobs.write_text(old_view)
    return jobs.read_bytes()


# --- the state ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_generation_cases_shared_with_the_node_side(tmp_path, case):
    jobs, ledger = paths(tmp_path)
    jobs.parent.mkdir(parents=True)
    if case["ledger"] is not None:
        ledger.write_text(case["ledger"] + " " * 10)
    if case["view"] is not None:
        jobs.write_text(case["view"] + " " * 10)
    assert view_guard.state(jobs, ledger)["consistent"] is case["consistent"]


def test_the_ledger_is_written_with_its_generation_first_and_the_view_with_its_own_first(tmp_path, monkeypatch):
    root, _ = world(tmp_path, monkeypatch, runs=1)
    jobs, ledger = paths(root)
    assert ledger.read_text().startswith('{\n  "generation": 1,')
    assert jobs.read_text().startswith('{\n  "meta": {\n    "ledgerGeneration": 1,')
    assert view_guard.state(jobs, ledger) == {"consistent": True, "ledgerGeneration": 1, "viewGeneration": 1, "reason": "same generation"}


def test_a_consistent_pair_is_left_alone(tmp_path, monkeypatch):
    root, _ = world(tmp_path, monkeypatch)
    jobs, ledger = paths(root)
    before = (jobs.read_bytes(), jobs.stat().st_mtime_ns)
    assert view_guard.ensure(jobs, ledger)["regenerated"] is False
    assert (jobs.read_bytes(), jobs.stat().st_mtime_ns) == before


def test_the_pre_s4a_pair_is_consistent_until_the_first_import_and_is_not_touched(tmp_path):
    jobs, ledger = paths(tmp_path)
    jobs.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"version": 1, "updatedAt": None, "jobs": {}}, indent=2))
    jobs.write_text(json.dumps({"meta": {"generatedAt": "x"}, "jobs": []}, indent=2))
    before = jobs.read_bytes()
    assert view_guard.ensure(jobs, ledger)["regenerated"] is False and jobs.read_bytes() == before


def test_the_real_18_mb_ledger_shape_migrates_without_a_manual_step(tmp_path, monkeypatch):
    """A ledger and a view as the old path wrote them: nothing is converted. The first import carries both over."""
    root = tmp_path / "root"
    jobs, ledger = paths(root)
    jobs.parent.mkdir(parents=True)
    old_ad = canon(1)
    legacy = job_history.empty_ledger()
    job_history.apply_run(legacy, [old_ad], now="2026-10-01T10:00:00+00:00", providers_returned={"greenhouse": 1}, key="k",
                          role_key=_crosspost_key)
    ledger.write_text(json.dumps(legacy, indent=2))
    jobs.write_text(json.dumps({"meta": {"generatedAt": "2026-10-01T10:00:00+00:00"}, "jobs": [old_ad]}, indent=2))
    assert view_guard.ensure(jobs, ledger)["regenerated"] is False, "readable as it is"
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(2)])}) == 0
    migrated = load(root, "job_history.json")
    assert migrated["generation"] == 1 and old_ad["jobId"] in migrated["jobs"]
    assert migrated["jobs"][old_ad["jobId"]]["firstSeen"] == legacy["jobs"][old_ad["jobId"]]["firstSeen"], "history kept"
    assert view_guard.state(jobs, ledger)["consistent"]


# --- recovery --------------------------------------------------------------------------------------------------------------------


def test_a_view_behind_the_ledger_is_rebuilt_and_is_the_derivation_byte_for_byte(tmp_path, monkeypatch):
    root, old_view = world(tmp_path, monkeypatch)
    jobs, ledger = paths(root)
    good = jobs.read_bytes()
    make_stale(root, old_view)
    assert view_guard.state(jobs, ledger)["consistent"] is False
    assert view_guard.ensure(jobs, ledger)["regenerated"] is True
    assert jobs.read_bytes() == good


def test_a_missing_view_is_rebuilt(tmp_path, monkeypatch):
    root, _ = world(tmp_path, monkeypatch)
    jobs, ledger = paths(root)
    good = jobs.read_bytes()
    jobs.unlink()
    assert view_guard.ensure(jobs, ledger)["regenerated"] is True and jobs.read_bytes() == good


def test_the_command_line_checks_and_ensures(tmp_path, monkeypatch):
    root, old_view = world(tmp_path, monkeypatch)
    jobs, _ = paths(root)
    make_stale(root, old_view)
    check = subprocess.run([sys.executable, str(GUARD), "check", "--jobs", str(jobs)], capture_output=True, text=True)
    assert check.returncode == 1 and json.loads(check.stdout)["consistent"] is False
    ensure = subprocess.run([sys.executable, str(GUARD), "ensure", "--jobs", str(jobs)], capture_output=True, text=True)
    assert ensure.returncode == 0 and json.loads(ensure.stdout)["regenerated"] is True
    assert subprocess.run([sys.executable, str(GUARD), "check", "--jobs", str(jobs)], capture_output=True).returncode == 0


# --- (a) the caller already holds the pipeline lock -----------------------------------------------------------------------------------


def test_recovery_while_the_caller_holds_the_pipeline_lock(tmp_path, monkeypatch):
    """Recovery takes only the view lock, never the pipeline lock: holding the pipeline lock changes nothing, and nothing waits."""
    root, old_view = world(tmp_path, monkeypatch)
    jobs, ledger = paths(root)
    make_stale(root, old_view)
    lock = pipeline_lock.acquire()
    assert lock is not None
    try:
        started = time.monotonic()
        assert view_guard.ensure(jobs, ledger, wait=5)["regenerated"] is True, "in the process that holds it"
        make_stale(root, old_view)
        child = subprocess.run(
            [sys.executable, str(GUARD), "ensure", "--jobs", str(jobs)], capture_output=True, text=True, timeout=20,
            pass_fds=(lock.fd,), env={**os.environ, **lock.child_env()},
        )
        assert child.returncode == 0 and json.loads(child.stdout)["regenerated"] is True, "in a step that was handed the lock"
        make_stale(root, old_view)
        other = subprocess.run([sys.executable, str(GUARD), "ensure", "--jobs", str(jobs)], capture_output=True, text=True, timeout=20)
        assert other.returncode == 0, "in a process that does not hold it (a status route, a backup export)"
        assert time.monotonic() - started < 15
    finally:
        lock.release()


def test_the_view_lock_is_never_taken_before_the_pipeline_lock_and_a_commit_needs_only_the_view_lock(tmp_path, monkeypatch):
    """The order is pipeline lock, then view lock. A commit under a held pipeline lock does not try for it again."""
    root, _ = world(tmp_path, monkeypatch, runs=1)
    jobs, ledger = paths(root)
    lock = pipeline_lock.acquire()
    try:
        taken = []
        real = view_guard.view_lock

        import contextlib

        @contextlib.contextmanager
        def spy(directory, wait=60.0):
            taken.append(directory)
            with real(directory, wait):
                yield

        monkeypatch.setattr(view_guard, "view_lock", spy)
        ledger_doc = json.loads(ledger.read_text())
        ledger_doc["generation"] += 1
        view_guard.commit(ledger_doc, jobs, ledger, wait=5)
        assert taken == [jobs.parent]
    finally:
        lock.release()


def test_a_view_lock_held_too_long_is_an_explicit_error_not_a_hang(tmp_path, monkeypatch):
    root, old_view = world(tmp_path, monkeypatch)
    jobs, ledger = paths(root)
    stale = make_stale(root, old_view)
    with view_guard.view_lock(jobs.parent, 1):
        started = time.monotonic()
        with pytest.raises(view_guard.ViewRecoveryError, match="held for more than"):
            view_guard.ensure(jobs, ledger, wait=0.3)
        assert time.monotonic() - started < 3
    assert jobs.read_bytes() == stale, "and the stale view was not used"


# --- (b) parallel readers ----------------------------------------------------------------------------------------------------------------


def test_parallel_processes_hitting_a_mismatch_at_once_one_rebuilds_the_others_wait_and_nobody_reads_half_a_file(tmp_path, monkeypatch):
    root, old_view = world(tmp_path, monkeypatch, runs=2, ads=60)
    jobs, ledger = paths(root)
    good = jobs.read_bytes()
    make_stale(root, old_view)

    seen_bad = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                json.loads(jobs.read_text())
            except FileNotFoundError:
                pass
            except ValueError as exc:  # a half-written file
                seen_bad.append(exc)

    watcher = threading.Thread(target=reader)
    watcher.start()
    try:
        with view_guard.view_lock(jobs.parent, 5):  # all eight are started and queue on the lock before it is released
            procs = [subprocess.Popen([sys.executable, str(GUARD), "ensure", "--jobs", str(jobs)],
                                      stdout=subprocess.PIPE, text=True) for _ in range(8)]
            time.sleep(1.0)
        answers = []
        for proc in procs:
            out, _ = proc.communicate(timeout=30)
            assert proc.returncode == 0
            answers.append(json.loads(out))
    finally:
        stop.set()
        watcher.join()
    assert sum(1 for a in answers if a["regenerated"]) == 1, "exactly one rebuilt it"
    assert all(a["consistent"] for a in answers)
    assert jobs.read_bytes() == good and not seen_bad


def test_parallel_threads_in_one_process_rebuild_once(tmp_path, monkeypatch):
    root, old_view = world(tmp_path, monkeypatch, ads=40)
    jobs, ledger = paths(root)
    make_stale(root, old_view)
    barrier = threading.Barrier(8)
    results = []

    def go():
        barrier.wait()
        results.append(view_guard.ensure(jobs, ledger, wait=20)["regenerated"])

    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [False] * 7 + [True]


# --- (c) a recovery that fails ---------------------------------------------------------------------------------------------------------


def stale_with_ledger(tmp_path, monkeypatch, ledger_text=None):
    root, old_view = world(tmp_path, monkeypatch)
    jobs, ledger = paths(root)
    stale = make_stale(root, old_view)
    if ledger_text is not None:
        ledger.write_text(ledger_text)
    return jobs, ledger, stale


def test_an_unreadable_ledger_gives_an_explicit_error_and_the_stale_view_is_never_served(tmp_path, monkeypatch):
    jobs, ledger, stale = stale_with_ledger(tmp_path, monkeypatch, '{\n  "generation": 9,\n  "jobs": {"torn')
    with pytest.raises(view_guard.ViewRecoveryError, match="cannot be read"):
        view_guard.ensure(jobs, ledger)
    assert jobs.read_bytes() == stale
    run = subprocess.run([sys.executable, str(GUARD), "ensure", "--jobs", str(jobs)], capture_output=True, text=True)
    answer = json.loads(run.stdout)
    assert run.returncode == 1 and answer["ok"] is False and answer["error"] == "view_unrecoverable" and "cannot be read" in answer["message"]


def test_a_disk_error_gives_an_explicit_error_and_leaves_the_view_as_it_was(tmp_path, monkeypatch):
    jobs, ledger, stale = stale_with_ledger(tmp_path, monkeypatch)

    def full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(view_guard._atomic, "write_text_atomic", full)
    with pytest.raises(view_guard.ViewRecoveryError, match="could not be rebuilt"):
        view_guard.ensure(jobs, ledger)
    assert jobs.read_bytes() == stale


def test_a_ledger_no_import_produced_cannot_give_a_view(tmp_path, monkeypatch):
    jobs, ledger, stale = stale_with_ledger(tmp_path, monkeypatch, json.dumps({"generation": 7, "version": 1, "jobs": {}}, indent=2))
    with pytest.raises(view_guard.ViewRecoveryError, match="no import produced"):
        view_guard.ensure(jobs, ledger)
    assert jobs.read_bytes() == stale


def test_a_restored_old_ledger_beside_a_newer_view_is_an_explicit_error(tmp_path, monkeypatch):
    """The owner restores job_history.json from a backup made before S4a: the view is ahead of it, and that is not served."""
    root, _ = world(tmp_path, monkeypatch)
    jobs, ledger = paths(root)
    ledger.write_text(json.dumps({"version": 1, "updatedAt": None, "jobs": {}}, indent=2))
    with pytest.raises(view_guard.ViewRecoveryError, match="the view is generation 2 but the ledger has none"):
        view_guard.ensure(jobs, ledger)


def test_a_script_that_cannot_rebuild_the_view_stops_with_the_reason(tmp_path, monkeypatch, capsys):
    jobs, ledger, _ = stale_with_ledger(tmp_path, monkeypatch, '{\n  "generation": 9,\n  "jobs": {"torn')
    with pytest.raises(SystemExit) as stop:
        view_guard.ensure_or_exit(jobs, ledger)
    assert stop.value.code == 1 and "could not be rebuilt" in capsys.readouterr().err


# --- the readers ---------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def scoring(tmp_path, monkeypatch):
    """run_scoring.main() over a world's own view and temp files."""
    (tmp_path / "intel.json").write_text(json.dumps({"jobFitPreferences": {}, "roleFamily": "product"}))
    (tmp_path / "profile.json").write_text(json.dumps({}))
    (tmp_path / "out").mkdir()
    monkeypatch.setattr(run_scoring, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "llm_fit.json")
    monkeypatch.setattr(shadow, "CACHE_PATH", tmp_path / "engine.json")
    monkeypatch.setattr("confirmed_facts.load", lambda *a, **k: [])
    monkeypatch.setattr(shadow, "load_remap", lambda: {})

    def run(jobs):
        monkeypatch.setattr(sys, "argv", [
            "run_scoring.py", "--intelligence", str(tmp_path / "intel.json"), "--jobs", str(jobs),
            "--manual", str(tmp_path / "manual.json"), "--output", str(tmp_path / "out" / "scored_jobs.json"),
        ])
        return run_scoring.main()

    return run


def test_scoring_rebuilds_a_stale_view_before_it_reads_it(tmp_path, monkeypatch, scoring):
    root, old_view = world(tmp_path, monkeypatch, ads=3)
    jobs, _ = paths(root)
    make_stale(root, old_view)
    assert scoring(jobs) == 0
    scored = json.loads((tmp_path / "out" / "scored_jobs.json").read_text())["jobs"]
    assert len(scored) == len(json.loads(jobs.read_text())["jobs"]) == 4, "scored from the rebuilt view, not the 3-ad one"


def test_scoring_stops_with_the_reason_when_the_view_cannot_be_rebuilt_and_scores_nothing(tmp_path, monkeypatch, scoring):
    jobs, ledger, stale = stale_with_ledger(tmp_path, monkeypatch, '{\n  "generation": 9,\n  "jobs": {"torn')
    with pytest.raises(SystemExit) as stop:
        scoring(jobs)
    assert stop.value.code == 1
    assert not (tmp_path / "out" / "scored_jobs.json").exists() and jobs.read_bytes() == stale


# --- (d) during a running Re-scrape, and a backup export -------------------------------------------------------------------------------------


def test_recovery_while_another_process_holds_the_pipeline_lock_like_a_run_or_an_export(tmp_path, monkeypatch):
    """`run_rescrape.py hold` is what Node uses to hold the lock for a backup export; a Re-scrape holds it the same way."""
    root, old_view = world(tmp_path, monkeypatch)
    jobs, _ = paths(root)
    make_stale(root, old_view)
    holder = subprocess.Popen([sys.executable, str(ROOT / "python" / "run_rescrape.py"), "hold"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "locked"
        assert pipeline_lock.acquire() is None, "the lock really is held by the other process"
        out = subprocess.run([sys.executable, str(GUARD), "ensure", "--jobs", str(jobs)], capture_output=True, text=True, timeout=20)
        assert out.returncode == 0 and json.loads(out.stdout)["regenerated"] is True
    finally:
        holder.stdin.close()
        holder.wait(timeout=10)


def test_readers_recovering_while_commits_go_on_never_see_a_half_file_and_end_consistent(tmp_path, monkeypatch):
    """A run commits again and again under the pipeline lock while readers keep asking: no error, no torn view, one answer at the end."""
    root, _ = world(tmp_path, monkeypatch, runs=1, ads=20)
    jobs, ledger = paths(root)
    lock = pipeline_lock.acquire()
    errors, stop = [], threading.Event()

    def committer():
        doc = json.loads(ledger.read_text())
        for _ in range(25):
            doc["generation"] += 1
            view_guard.commit(doc, jobs, ledger, wait=20)

    def reader():
        while not stop.is_set():
            try:
                view_guard.ensure(jobs, ledger, wait=20)
                json.loads(jobs.read_text())
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

    readers = [threading.Thread(target=reader) for _ in range(3)]
    [t.start() for t in readers]
    try:
        committer()
    finally:
        stop.set()
        [t.join() for t in readers]
        lock.release()
    assert errors == []
    assert view_guard.ensure(jobs, ledger)["consistent"] and json.loads(jobs.read_text())["meta"]["ledgerGeneration"] == 26


# --- interruptions ---------------------------------------------------------------------------------------------------------------------------


def test_a_crash_between_the_ledger_write_and_the_view_write_of_a_commit_is_recovered_by_the_next_reader(tmp_path, monkeypatch):
    root, _ = world(tmp_path, monkeypatch, runs=1)
    jobs, ledger = paths(root)
    doc = json.loads(ledger.read_text())
    doc["generation"] += 1
    real = view_guard._atomic.write_text_atomic

    def crash_on_view(path, *args, **kwargs):
        if Path(path).name == "discovered_jobs.json":
            raise RuntimeError("power cut")
        return real(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(view_guard._atomic, "write_text_atomic", crash_on_view)
        with pytest.raises(RuntimeError, match="power cut"):
            view_guard.commit(doc, jobs, ledger)
    assert json.loads(ledger.read_text())["generation"] == 2 and view_guard.view_generation(jobs) == 1
    assert view_guard.state(jobs, ledger)["consistent"] is False
    assert view_guard.ensure(jobs, ledger)["regenerated"] is True and view_guard.view_generation(jobs) == 2


FACTS = {"workMode": "remote", "roleTrack": "product_management", "seniority": "senior", "yearsRequired": 5}


@pytest.fixture
def enrichment(tmp_path, monkeypatch, open_ai_budget):
    root, _ = world(tmp_path, monkeypatch, runs=1, ads=3)
    jobs, ledger = paths(root)
    intel = tmp_path / "intel.json"
    intel.write_text(json.dumps({}))
    monkeypatch.setattr(enrich_jobs, "extract", lambda j, model, provider, previous=None: {**FACTS, "_fingerprint": enrich_jobs._fingerprint(j)})
    monkeypatch.setattr(sys, "argv", ["enrich_jobs.py", "--jobs", str(jobs), "--intelligence", str(intel)])
    select_provider(tmp_path, monkeypatch, "claude-code")
    return jobs, ledger


def test_enrichment_writes_the_ledger_first_and_the_view_after_it(enrichment, monkeypatch):
    jobs, ledger = enrichment
    order = []
    real = enrich_jobs.view_guard._atomic.write_text_atomic

    def spy(path, *args, **kwargs):
        order.append(Path(path).name)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(enrich_jobs.view_guard._atomic, "write_text_atomic", spy)
    assert enrich_jobs.main() == 0
    assert [name for name in order if name in ("job_history.json", "discovered_jobs.json")] == ["job_history.json", "discovered_jobs.json"]
    assert json.loads(ledger.read_text())["generation"] == 2 and view_guard.view_generation(jobs) == 2
    assert all(j["llmFacts"]["workMode"] == "remote" for j in json.loads(jobs.read_text())["jobs"])


def test_enrichment_that_finds_nothing_new_writes_nothing(enrichment, monkeypatch):
    jobs, ledger = enrichment
    assert enrich_jobs.main() == 0
    before = (jobs.stat().st_mtime_ns, ledger.stat().st_mtime_ns, ledger.read_bytes())
    assert enrich_jobs.main() == 0
    assert (jobs.stat().st_mtime_ns, ledger.stat().st_mtime_ns, ledger.read_bytes()) == before


def test_a_crash_between_enrichments_ledger_write_and_view_write_is_recovered_by_the_next_reader(enrichment, monkeypatch):
    jobs, ledger = enrichment
    real = enrich_jobs.view_guard._atomic.write_text_atomic

    def crash_on_view(path, *args, **kwargs):
        if Path(path).name == "discovered_jobs.json":
            raise RuntimeError("power cut")
        return real(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(enrich_jobs.view_guard._atomic, "write_text_atomic", crash_on_view)
        with pytest.raises(RuntimeError, match="power cut"):
            enrich_jobs.main()
    doc = json.loads(ledger.read_text())
    assert doc["generation"] == 2 and all(e["llmFacts"] for e in doc["jobs"].values()), "the ledger got the facts first"
    assert view_guard.view_generation(jobs) == 1 and not any("llmFacts" in j for j in json.loads(jobs.read_text())["jobs"])
    assert view_guard.ensure(jobs, ledger)["regenerated"] is True
    assert all(j["llmFacts"]["workMode"] == "remote" for j in json.loads(jobs.read_text())["jobs"]), "the facts are in the rebuilt view"
    assert enrich_jobs.main() == 0, "and the next enrichment has nothing left to read"


def test_enrichment_rebuilds_a_stale_view_before_it_reads_it(enrichment, monkeypatch, tmp_path):
    jobs, ledger = enrichment
    doc = json.loads(ledger.read_text())
    doc["generation"] += 1
    view_guard._atomic.write_text_atomic(ledger, view_guard.serialize_ledger(doc))  # a commit that stopped after the ledger
    assert view_guard.state(jobs, ledger)["consistent"] is False
    assert enrich_jobs.main() == 0
    assert view_guard.state(jobs, ledger)["consistent"] is True


def test_a_pre_s4a_ledger_is_enriched_the_old_way_but_ledger_first(tmp_path, monkeypatch, open_ai_budget):
    jobs, ledger = paths(tmp_path)
    jobs.parent.mkdir(parents=True)
    ad = canon(1)
    jobs.write_text(json.dumps({"meta": {}, "jobs": [ad]}))
    legacy = job_history.empty_ledger()
    job_history.apply_run(legacy, [ad], now="2026-10-01T10:00:00+00:00", providers_returned={"greenhouse": 1}, key="k", role_key=_crosspost_key)
    ledger.write_text(json.dumps(legacy, indent=2))
    intel = tmp_path / "intel.json"
    intel.write_text(json.dumps({}))
    monkeypatch.setattr(enrich_jobs, "extract", lambda j, model, provider, previous=None: {**FACTS, "_fingerprint": enrich_jobs._fingerprint(j)})
    monkeypatch.setattr(sys, "argv", ["enrich_jobs.py", "--jobs", str(jobs), "--intelligence", str(intel)])
    select_provider(tmp_path, monkeypatch, "claude-code")
    order = []
    real = enrich_jobs.write_text_atomic
    monkeypatch.setattr(enrich_jobs, "write_text_atomic", lambda path, *a, **k: (order.append(Path(path).name), real(path, *a, **k))[1])
    real_save = enrich_jobs.job_history.save
    monkeypatch.setattr(enrich_jobs.job_history, "save", lambda path, doc: (order.append(Path(path).name), real_save(path, doc))[1])
    assert enrich_jobs.main() == 0
    assert order == ["job_history.json", "discovered_jobs.json"]
    assert "generation" not in json.loads(ledger.read_text()), "nothing converts a ledger no import has produced"


# --- the live path is the old path's result ----------------------------------------------------------------------------------------------------


def old_commit(ledger_before, previous, run, providers, now):
    """The commit of the old path (slice A2a), reproduced from its code: dedupe, apply_run with its 90-day prune, the payload."""
    all_jobs, counts, failed, empty, not_run = [], {}, {}, {}, set()
    for name, provider in providers.items():
        all_jobs += provider.jobs
        counts[name] = len(provider.jobs)
        if provider.failed:
            failed[name] = set(provider.failed)
        elif provider.status == "failed":
            failed[name] = None
        if provider.status in ("skipped", "failed"):
            not_run.add(name)
        if provider.empty:
            empty[name] = set(provider.empty)
    deduped = dedupe_jobs(all_jobs)
    facts = {j["jobId"]: j["llmFacts"] for j in (previous or {}).get("jobs", []) if j.get("jobId") and j.get("llmFacts")}
    written = ((previous or {}).get("meta") or {}).get("generatedAt")
    seen = {j["jobId"]: written for j in (previous or {}).get("jobs", []) if j.get("jobId") and written}
    ledger = copy.deepcopy(ledger_before)
    to_write, stats = job_history.apply_run(
        ledger, deduped, now=now, providers_returned=counts, key=run.manifest["searchKey"], role_key=_crosspost_key,
        previous_facts=facts, seen_before=seen, failed_boards=failed, empty_boards=empty, sources_not_run=not_run,
    )
    m = run.manifest
    payload = discovered_payload(
        to_write, search_terms=m["terms"], locations=m["locations"], remote_filters=m["remoteFilters"], raw_count=len(all_jobs),
        country=m["country"], source_run_id=run.run_id, providers=m["providers"], provider_counts=counts, deduped_count=len(deduped),
        history=stats, generated_at=now,
    )
    return ledger, payload


def test_a_full_discovery_through_staging_and_import_gives_what_the_old_path_gave_from_the_same_inputs(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "data/jobs").mkdir(parents=True)
    seed = canon(1)
    (root / "data/jobs/discovered_jobs.json").write_text(json.dumps({
        "meta": {"generatedAt": "2026-10-01T00:00:00+00:00"},
        "jobs": [{**seed, "llmFacts": {"_fingerprint": job_history.job_fingerprint(seed), "workMode": "remote"}}],
    }))
    history = [
        {"greenhouse": Prov([canon(1), canon(2), canon(3)]), "lever": Prov([canon(10, "lever"), canon(11, "lever")])},
        {"greenhouse": Prov([canon(1), canon(2, description="rewritten " * 40), canon(4)]),
         "lever": Prov([canon(10, "lever"), canon(1, "lever", url=seed["jobUrl"])]), "ashby": Prov([canon(20, "ashby", title="Product Manager 10")])},
        {"greenhouse": Prov([canon(1, description="x"), canon(2)], status="partial", boards_failed=["acme"], boards_empty=["b2"]),
         "lever": Prov([], status="failed"), "ashby": Prov([canon(20, "ashby", title="Product Manager 10")])},
        {"greenhouse": Prov([canon(1), canon(2), canon(3)]), "lever": Prov([canon(10, "lever")]), "ashby": Prov([], status="skipped")},
    ]
    for providers in history:
        assert discover(root, monkeypatch, providers) == 0
        run_id = latest(root)
        run = staging.read_run(root, run_id)
        before = json.loads(run.ledger_before.read_text()) if run.ledger_before else job_history.empty_ledger()
        previous = json.loads(run.discovered_before.read_text()) if run.discovered_before else None
        live_ledger, live_view = load(root, "job_history.json"), load(root, "discovered_jobs.json")
        old_ledger, old_view = old_commit(before, previous, run, providers, live_ledger["lastImport"]["at"])
        assert importer.compare_ledgers(live_ledger, old_ledger, "live", "old").items == []
        assert importer.compare_views(live_view, old_view, "live", "old").items == []
        assert live_view["meta"]["ledgerGeneration"] == live_ledger["generation"]


# --- import is final; retention; the ledger prune; the order guard --------------------------------------------------------------------------------


def test_import_is_final_a_failed_scoring_does_not_undo_it_and_re_score_needs_neither_scrape_nor_import(tmp_path, monkeypatch, scoring):
    root = tmp_path / "root"
    root.mkdir()
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(2)])}) == 0
    jobs, ledger = paths(root)
    run_id = latest(root)
    committed = (jobs.read_bytes(), ledger.read_bytes())
    assert staging.is_imported(root, run_id)

    # scoring fails (no intelligence file): the imported data is exactly as it was
    monkeypatch.setattr(sys, "argv", ["run_scoring.py", "--intelligence", str(tmp_path / "missing.json"), "--jobs", str(jobs),
                                      "--output", str(tmp_path / "out" / "scored_jobs.json")])
    assert run_scoring.main() == 1
    assert (jobs.read_bytes(), ledger.read_bytes()) == committed and staging.is_imported(root, run_id)

    # Re-score alone: no provider is asked, no import is made, no staging is read
    monkeypatch.setattr(run_discovery_module(), "get_provider", lambda name: pytest.fail("a scrape was started"))
    monkeypatch.setattr(importer, "import_staged_run", lambda *a, **k: pytest.fail("an import was made"))
    monkeypatch.setattr(staging, "read_run", lambda *a, **k: pytest.fail("staging was read"))
    assert scoring(jobs) == 0
    assert len(json.loads((tmp_path / "out" / "scored_jobs.json").read_text())["jobs"]) == 2
    assert (jobs.read_bytes(), ledger.read_bytes()) == committed


def run_discovery_module():
    import run_discovery
    return run_discovery


def test_only_a_real_import_marks_a_run_imported_and_a_dry_run_never_does(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1)])}) == 0
    run_id = latest(root)
    assert staging.is_imported(root, run_id)
    marker = json.loads((root / "data/jobs/staging" / run_id / "imported.json").read_text())
    assert marker["runId"] == run_id and marker["generation"] == 1 and marker["committed"] is True
    (root / "data/jobs/staging" / run_id / "imported.json").unlink()
    importer.dry_run(root, run_id)
    assert import_run.main(["--run", run_id, "--dry-run"], root=root) in (0, 1, 3)
    assert not staging.is_imported(root, run_id), "a dry run writes no marker"


def test_retention_keeps_the_last_three_imported_runs_and_never_one_that_waits(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    # a run staged but never imported (the import was refused or the run stopped), and a run whose staging failed
    waiting = hand_run(root, "waiting1", {"greenhouse": ([canon(1)], OK)})
    failed = hand_run(root, "failed1", {"greenhouse": ([canon(1)], OK)}, status=False)
    (failed.dir / "status.json").write_text(json.dumps({"version": 1, "ok": False, "problems": ["x"]}))
    for n in range(5):
        assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(2 + n)])}) == 0
    base = root / "data/jobs/staging"
    imported = [r for r in staging.list_runs(root) if staging.is_imported(root, r)]
    assert len(imported) == 3, "the last 3 imported runs"
    assert (base / "waiting1").is_dir() and (base / "failed1").is_dir(), "a run that waits, or whose staging failed, is never removed"
    names = {p.name for p in base.iterdir()}
    for run_id in imported:
        assert {run_id, f"{run_id}.ledger-before.json", f"{run_id}.discovered-before.json"} <= names
    # a removed run takes its two links with it: no link is left without its run
    for name in names:
        if name.endswith("-before.json"):
            assert name.split(".")[0] in names, f"{name} outlived its run"


def test_the_ninety_day_ledger_prune_is_off_for_an_import_and_still_there_for_a_direct_apply_run(tmp_path, monkeypatch):
    old = canon(9)
    ledger = job_history.empty_ledger()
    job_history.apply_run(ledger, [old], now="2026-06-01T10:00:00+00:00", providers_returned={"greenhouse": 1}, key="k", role_key=_crosspost_key)
    job_history.apply_run(ledger, [canon(1)], now="2026-06-02T10:00:00+00:00", providers_returned={"greenhouse": 1}, key="k", role_key=_crosspost_key)
    assert ledger["jobs"][old["jobId"]]["closedAt"] is not None, "closed long ago"
    run = hand_run(tmp_path, "r1", {"greenhouse": ([canon(1)], OK)})
    kept = importer.plan_import(run, copy.deepcopy(ledger), None, now="2026-11-03T10:00:00+00:00")
    assert old["jobId"] in kept.ledger["jobs"], "nothing is deleted automatically"
    assert old["jobId"] not in [j["jobId"] for j in kept.view["jobs"]], "and it is not shown after 14 days"
    pruned = copy.deepcopy(ledger)
    job_history.apply_run(pruned, [canon(1)], now="2026-11-03T10:00:00+00:00", providers_returned={"greenhouse": 1}, key="k", role_key=_crosspost_key)
    assert old["jobId"] not in pruned["jobs"], "apply_run's own default is unchanged for its other callers"


def test_more_than_5000_rows_is_a_warning_in_the_log_and_nothing_is_dropped(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(importer, "ROW_WARNING", 3)
    root = tmp_path / "root"
    root.mkdir()
    with caplog.at_level("WARNING"):
        assert discover(root, monkeypatch, {"greenhouse": Prov([canon(n) for n in range(1, 6)])}) == 0
    assert len(load(root, "discovered_jobs.json")["jobs"]) == 5
    assert any("would hold 5 rows" in r.getMessage() for r in caplog.records)
    record = max(run_log.runs_dir().glob("*.json"), key=lambda p: p.stat().st_mtime)
    assert any(i["level"] == "warning" and "rows" in i["message"] for i in json.loads(record.read_text())["issues"])


def test_the_debug_files_are_written_after_the_commit_and_a_failure_to_write_them_fails_nothing(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    import run_discovery

    def boom(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(run_discovery, "export_raw_csv", boom)
    monkeypatch.setattr(run_discovery, "export_normalized_json", boom)
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1)])}) == 0
    assert view_guard.state(*paths(root))["consistent"] and not (root / "data/jobs/normalized_jobs.json").exists()
    record = max(run_log.runs_dir().glob("*.json"), key=lambda p: p.stat().st_mtime)
    body = json.loads(record.read_text())
    assert body["status"] == "ok" and sum("debug output" in i["message"] for i in body["issues"]) == 2


def test_unfinished_and_failed_sources_import_what_they_wrote_through_the_live_path(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(2)]), "lever": Prov([canon(10, "lever")])}) == 0
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1)], status="failed"), "lever": Prov([canon(10, "lever"), canon(11, "lever")])}) == 0
    ledger = load(root, "job_history.json")
    assert ledger["jobs"][canon(2)["jobId"]]["closedAt"] is None, "a failed source closes nothing"
    assert canon(11, "lever")["jobId"] in ledger["jobs"], "and the source that ran is imported"


def test_the_order_guard_refuses_an_older_run_with_a_message_and_the_override_is_explicit(tmp_path, monkeypatch, capsys):
    root = tmp_path / "root"
    root.mkdir()
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(2)])}) == 0
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(3)])}) == 0
    older = staging.list_runs(root)[1]
    ledger_before = (root / "data/jobs/job_history.json").read_bytes()
    view_before = (root / "data/jobs/discovered_jobs.json").read_bytes()
    (root / "data/jobs/staging" / older / "imported.json").unlink()  # as if it had never been imported

    outcome = importer.import_staged_run(root, older)
    assert not outcome.ok and outcome.refused[0].startswith("older_run")
    assert (root / "data/jobs/job_history.json").read_bytes() == ledger_before
    assert (root / "data/jobs/discovered_jobs.json").read_bytes() == view_before, "nothing was written, nothing went backwards"
    assert not staging.is_imported(root, older)

    assert import_run.main(["--run", older, "--import"], root=root) == 2
    err = capsys.readouterr().err
    assert "REFUSED" in err and "older_run" in err and "allow_older" in err

    # the override needs an explicit confirmation: without it, nothing happens
    assert import_run.main(["--run", older, "--import", "--allow-older"], root=root) == 2
    err = capsys.readouterr().err
    assert "may overwrite newer ledger data with older data" in err and "Refused: no confirmation" in err
    assert (root / "data/jobs/job_history.json").read_bytes() == ledger_before and not staging.is_imported(root, older)
    assert import_run.main(["--run", older, "--import", "--confirm-overwrite-newer"], root=root) == 2, "the flag alone is not the override"
    capsys.readouterr()

    class Terminal:
        def __init__(self, answer): self.answer = answer
        def isatty(self): return True
        def readline(self): return self.answer + "\n"

    monkeypatch.setattr(import_run.sys, "stdin", Terminal("yes"))
    assert import_run.main(["--run", older, "--import", "--allow-older"], root=root) == 2, "only the word OVERWRITE counts"
    assert not staging.is_imported(root, older)
    capsys.readouterr()
    monkeypatch.setattr(import_run.sys, "stdin", Terminal("OVERWRITE"))
    assert import_run.main(["--run", older, "--import", "--allow-older"], root=root) == 0, "typed confirmation at a terminal"
    assert staging.is_imported(root, older)
    # again with the flag, from the state before
    (root / "data/jobs/staging" / older / "imported.json").unlink()
    (root / "data/jobs/job_history.json").write_bytes(ledger_before)
    (root / "data/jobs/discovered_jobs.json").write_bytes(view_before)
    assert import_run.main(["--run", older, "--import", "--allow-older", "--confirm-overwrite-newer"], root=root) == 0
    assert "Imported run" in capsys.readouterr().out and staging.is_imported(root, older)
    assert load(root, "job_history.json")["lastImport"]["runId"] == older
    assert view_guard.state(*paths(root))["consistent"]


def test_recovery_import_of_a_staged_run_whose_import_never_happened(tmp_path, monkeypatch, capsys):
    """A run that stopped after staging: import_run.py --import makes the import the run did not."""
    root = tmp_path / "root"
    root.mkdir()
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1)])}) == 0
    import run_discovery

    monkeypatch.setattr(run_discovery.importer, "import_staged_run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("killed")))
    with pytest.raises(RuntimeError):
        discover(root, monkeypatch, {"greenhouse": Prov([canon(1), canon(2)])})
    monkeypatch.undo()
    stranded = latest(root)
    assert not staging.is_imported(root, stranded)
    assert load(root, "job_history.json")["lastImport"]["runId"] != stranded
    assert import_run.main(["--run", stranded, "--import"], root=root) == 0
    assert load(root, "job_history.json")["lastImport"]["runId"] == stranded and staging.is_imported(root, stranded)
    assert import_run.main(["--run", stranded, "--import"], root=root) == 0, "a second time changes nothing"
    assert "already imported" in capsys.readouterr().out


def test_a_leftover_commit_marker_of_the_old_protocol_is_cleared_by_the_first_finished_commit(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    run_log._atomic.make_private_dirs(run_log.runs_dir())
    run_log.commit_marker_path().write_text(json.dumps({"runId": "old", "files": ["job_history"], "written": ["job_history"]}))
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1)])}) == 0
    assert run_log.read_commit_marker() is None


def test_a_run_reads_a_stale_view_as_rebuilt_before_it_keeps_its_discovered_file_beside_its_staging(tmp_path, monkeypatch):
    root, old_view = world(tmp_path, monkeypatch)
    jobs, ledger = paths(root)
    make_stale(root, old_view)
    assert discover(root, monkeypatch, {"greenhouse": Prov([canon(1)])}) == 0
    run_id = latest(root)
    kept = json.loads(staging.read_run(root, run_id).discovered_before.read_text())
    assert kept["meta"]["ledgerGeneration"] == 2, "the run kept the rebuilt view, not the stale one"


def test_the_older_run_override_is_never_reachable_from_an_automatic_path():
    """allow_older is passed by import_run.py (a human at a command line) and nowhere else: not the live run, not recovery, not Node."""
    repo = Path(__file__).resolve().parents[2]
    users = []
    for base in ("python", "scripts"):
        for file in (repo / base).rglob("*"):
            if file.suffix in (".py", ".js") and "__pycache__" not in file.parts:
                text = file.read_text(encoding="utf-8", errors="replace")
                if "allow_older" in text or "allow-older" in text:
                    users.append(file.relative_to(repo).as_posix())
    assert sorted(users) == ["python/job_discovery/import_run.py", "python/job_discovery/importer.py"]
    importer_text = (repo / "python/job_discovery/importer.py").read_text(encoding="utf-8")
    assert importer_text.count("allow_older: bool = False") == 2, "off by default, both signatures"
    assert [l for l in importer_text.splitlines() if "allow_older=True" in l and "`" not in l] == [], "no code passes it"
    discovery = (repo / "python/job_discovery/run_discovery.py").read_text(encoding="utf-8")
    assert "import_staged_run(ROOT, source_run_id)" in discovery, "the live run calls the importer with no override"
