"""The background Re-scrape: one lock over discovery and scoring, the event log, interrupted runs, the commit marker."""

import fcntl
import json
import os
import signal
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

import enrich_jobs  # noqa: E402
import import_job_url  # noqa: E402
import pipeline_lock  # noqa: E402
import run_discovery  # noqa: E402
import run_log  # noqa: E402
import run_pipeline as rp  # noqa: E402
import run_rescrape  # noqa: E402
import run_scoring  # noqa: E402

from providers.base_provider import JobProvider, ProviderOutcome  # noqa: E402

RUN_ID = "abc123def456"
MANUAL_ID = "manual-123e4567-e89b-12d3-a456-426614174000"


def wait_for(condition, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def lock_is_free():
    fd = os.open(os.environ["CAREER_OS_PIPELINE_LOCK"], os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


@pytest.fixture
def held():
    """The lock held by someone else: another open of the file, as another process would have it."""
    fd = os.open(os.environ["CAREER_OS_PIPELINE_LOCK"], os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    yield
    os.close(fd)


def running_record(run_id="dead", started="2026-11-03T10:00:00+00:00"):
    record = run_log.new_record(run_id, "manual")
    record["startedAt"] = started
    run_log.save(record)
    return record


def events_of(record):
    path = run_log.events_path(record)
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def on_disk(run_id):
    return run_log.find_record(run_id)


# --- the lock -----------------------------------------------------------------------------------------------------


def test_one_holder_at_a_time_and_release_frees_it():
    first = pipeline_lock.acquire()
    assert first is not None
    assert pipeline_lock.acquire() is None
    first.release()
    second = pipeline_lock.acquire()
    assert second is not None
    second.release()


def test_the_path_comes_from_the_override_never_the_real_file(tmp_path):
    assert pipeline_lock.lock_path() == tmp_path / "pipeline.lock"


def test_a_child_takes_the_lock_it_was_handed_and_nobody_else_can(tmp_path):
    lock = pipeline_lock.acquire()
    code = "import sys; sys.path.insert(0, sys.argv[1]); import pipeline_lock as p; sys.exit(0 if p.acquire() else 75)"
    args = [sys.executable, "-c", code, str(ROOT / "python" / "job_scoring")]
    with_lock = subprocess.run(args, pass_fds=(lock.fd,), env=lock.child_env())
    assert with_lock.returncode == 0
    without = subprocess.run(args, env=dict(os.environ))
    assert without.returncode == 75
    lock.release()


def test_a_stale_fd_number_in_the_environment_is_no_way_past_the_lock(held, monkeypatch, tmp_path):
    other = os.open(tmp_path / "other-file", os.O_RDWR | os.O_CREAT)
    monkeypatch.setenv(pipeline_lock.FD_ENV, str(other))
    assert pipeline_lock.acquire() is None, "an fd on another file is not the lock"
    monkeypatch.setenv(pipeline_lock.FD_ENV, "not a number")
    assert pipeline_lock.acquire() is None
    monkeypatch.setenv(pipeline_lock.FD_ENV, "4095")
    assert pipeline_lock.acquire() is None
    os.close(other)


# --- every other route is refused while a run holds it ---------------------------------------------------------------


def test_direct_discovery_is_refused_and_writes_no_record(held, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_discovery.py", "--providers", "serbia"])
    assert run_discovery.main() == pipeline_lock.EXIT_LOCKED
    assert not run_log.runs_dir().exists() or not list(run_log.runs_dir().iterdir())


@pytest.mark.parametrize("extra", [[], ["--judge"]])
def test_re_score_and_judge_are_refused_and_write_nothing(held, monkeypatch, tmp_path, extra):
    output = tmp_path / "scored.json"
    monkeypatch.setattr(sys, "argv", ["run_scoring.py", "--output", str(output), *extra])
    assert run_scoring.main() == pipeline_lock.EXIT_LOCKED
    assert not output.exists()


def test_the_judge_preview_writes_nothing_so_it_takes_no_lock(held, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["run_scoring.py", "--judge-preview", "--intelligence", str(tmp_path / "none.json")])
    assert run_scoring.main() == 1  # got past the lock to its own "missing intelligence"


def test_standalone_enrichment_is_refused(held, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["enrich_jobs.py"])
    assert enrich_jobs.main() == pipeline_lock.EXIT_LOCKED


def test_the_pipeline_is_refused_when_a_re_scrape_holds_the_lock(held, monkeypatch, tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(rp, "INTELLIGENCE", tmp_path / "intel.json")
    monkeypatch.setattr(rp, "DISCOVERED", jobs / "discovered_jobs.json")
    monkeypatch.setattr(rp, "SCORED", jobs / "scored_jobs.json")
    monkeypatch.setattr(rp, "LAST_RUN", jobs / "pipeline_last_run.json")
    monkeypatch.setattr(rp, "LOCK", jobs / ".pipeline.lock")
    rp.INTELLIGENCE.write_text("{}")
    assert rp.main([]) == pipeline_lock.EXIT_LOCKED


def test_the_pipeline_hands_the_lock_to_its_steps(monkeypatch, tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(rp, "LOCK", jobs / ".pipeline.lock")
    seen = {}

    class Popen:
        stdout = iter(())

        def __init__(self, cmd, **kwargs):
            seen.update(kwargs)

        def wait(self):
            return 0

    monkeypatch.setattr(rp.subprocess, "Popen", Popen)
    monkeypatch.setattr(rp, "_held_lock", pipeline_lock.acquire())
    rp.run_step("scoring", ["x.py"], [])
    assert seen["pass_fds"] == (rp._held_lock.fd,)
    assert seen["env"][pipeline_lock.FD_ENV] == str(rp._held_lock.fd)
    assert seen["env"]["CAREER_OS_AI_TRIGGER"] == "automation"
    rp._held_lock.release()


# --- manual add and URL import during a run: blocked ---------------------------------------------------------------


@pytest.fixture
def manual_paths(tmp_path, monkeypatch):
    paths = SimpleNamespace(
        discovered=tmp_path / "discovered.json", scored=tmp_path / "scored.json",
        manual=tmp_path / "manual.json", intelligence=tmp_path / "intel.json",
    )
    paths.intelligence.write_text("{}")
    paths.argv = ["--discovered", str(paths.discovered), "--scored", str(paths.scored), "--manual", str(paths.manual),
                  "--intelligence", str(paths.intelligence)]
    return paths


def feed_job(monkeypatch):
    job = {"jobId": MANUAL_ID, "title": "PM", "company": "Acme", "description": "Own the roadmap."}
    monkeypatch.setattr(import_job_url, "_read_job_json", lambda source: job)


@pytest.mark.parametrize("flag", [[], ["--store-only"]])
def test_manual_add_during_a_run_is_refused_and_writes_nothing(held, monkeypatch, manual_paths, flag):
    feed_job(monkeypatch)
    assert import_job_url.main(["--job-json", "-", *manual_paths.argv, *flag]) == pipeline_lock.EXIT_LOCKED
    assert not manual_paths.manual.exists() and not manual_paths.scored.exists()


def test_the_duplicate_check_writes_nothing_so_it_still_answers_during_a_run(held, monkeypatch, manual_paths):
    feed_job(monkeypatch)
    assert import_job_url.main(["--job-json", "-", "--check-only", *manual_paths.argv]) == 0


def test_manual_add_works_again_when_the_run_is_over(monkeypatch, manual_paths):
    feed_job(monkeypatch)
    assert import_job_url.main(["--job-json", "-", "--store-only", *manual_paths.argv]) == 0
    assert manual_paths.manual.exists() and lock_is_free(), "a manual add holds the lock only for its own writes"


def test_url_import_during_a_run_is_refused_before_it_fetches_anything(held, monkeypatch, manual_paths):
    monkeypatch.setattr(import_job_url, "extract_job", lambda *a: pytest.fail("fetched during a run"))
    assert import_job_url.main(["--url", "https://a.example/1", *manual_paths.argv]) == pipeline_lock.EXIT_LOCKED


# --- the event log -------------------------------------------------------------------------------------------------


def test_events_are_appended_line_by_line_private_and_one_write_each(monkeypatch):
    record = run_log.new_record(RUN_ID, "manual")
    writes = []
    real_write = os.write
    with monkeypatch.context() as patch:
        patch.setattr(os, "write", lambda fd, data: writes.append(data) or real_write(fd, data))
        run_log.event(record, "run_start")
        run_log.event(record, "source_end", source="greenhouse", status="ok", read=3, kept=2)
    assert len(writes) == 2 and all(w.endswith(b"\n") and w.count(b"\n") == 1 for w in writes)
    path = run_log.events_path(record)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert path.name.endswith(f"-{RUN_ID}.events.jsonl")
    first, second = events_of(record)
    assert first["type"] == "run_start" and first["at"]
    assert (second["type"], second["source"], second["kept"]) == ("source_end", "greenhouse", 2)


def test_a_torn_last_line_does_not_swallow_the_next_event():
    record = run_log.new_record(RUN_ID, "manual")
    run_log.event(record, "run_start")
    with run_log.events_path(record).open("a") as handle:
        handle.write('{"type": "source_st')
    run_log.event(record, "interrupted")
    lines = run_log.events_path(record).read_text().splitlines()
    assert lines[1] == '{"type": "source_st'
    assert json.loads(lines[2])["type"] == "interrupted"


def test_no_credential_reaches_an_event():
    record = run_log.new_record(RUN_ID, "manual")
    run_log.event(record, "error", message="GET https://a/b?api_key=hunter2 sk-abcdefghijkl " + "x" * 2000)
    message = events_of(record)[0]["message"]
    assert "hunter2" not in message and "sk-abcdefghijkl" not in message and len(message) <= run_log.MAX_MESSAGE_CHARS


def test_an_event_that_cannot_be_written_never_stops_the_run(monkeypatch, tmp_path):
    (tmp_path / "blocked").write_text("a file where the folder should be")
    monkeypatch.setenv("CAREER_OS_ANALYTICS_DIR", str(tmp_path / "blocked"))
    run_log.event(run_log.new_record(RUN_ID, "manual"), "run_start")


# --- interrupted ---------------------------------------------------------------------------------------------------


def test_a_dead_running_record_becomes_interrupted():
    record = running_record()
    result = run_rescrape.reconcile()
    assert result["busy"] is False and result["interrupted"] == ["dead"]
    saved = on_disk("dead")
    assert saved["status"] == "interrupted"
    assert saved["finishedAt"] is None, "nobody saw it end, so no end time is invented"
    assert any("did not finish" in issue["message"] for issue in saved["issues"])
    assert [e["type"] for e in events_of(record)] == ["interrupted"]


def test_a_live_running_record_stays_running(held):
    record = running_record("live")
    result = run_rescrape.reconcile()
    assert result == {"busy": True, "interrupted": [], "incompleteCommit": None}
    assert on_disk("live")["status"] == "running" and events_of(record) == []


def test_interrupted_names_the_step_that_did_not_finish():
    record = running_record()
    record["steps"] = [{"name": "discovery", "status": "ok"}, {"name": "scoring", "status": "running"}]
    run_log.save(record)
    run_rescrape.reconcile()
    saved = on_disk("dead")
    assert saved["steps"][1]["status"] == "interrupted"
    assert any("scoring" in issue["message"] for issue in saved["issues"])


def test_reconcile_leaves_finished_records_alone_and_releases_the_lock():
    run_log.save(run_log.finish(run_log.new_record("done", "manual"), exit_ok=True))
    assert run_rescrape.reconcile()["interrupted"] == []
    assert lock_is_free()


def test_nothing_is_resumed_a_reconcile_starts_no_process(monkeypatch):
    running_record()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("a reconcile started a process"))
    run_rescrape.reconcile()


# --- the commit marker ---------------------------------------------------------------------------------------------


def job(job_id="g1"):
    from providers.base_provider import build_canonical_job

    return {**build_canonical_job(provider="greenhouse", source="acme", title="PM", company="Acme", location="Remote",
                                  job_url=f"https://a.example/{job_id}", description="Own the roadmap."), "jobId": job_id}


class Provider(JobProvider):
    name = "greenhouse"

    def __init__(self):
        self.last_outcome = None

    def fetch_jobs(self, *args):
        self.last_outcome = ProviderOutcome(status="ok", read=1, kept=1)
        return [job()]


@pytest.fixture
def discovery(tmp_path, monkeypatch):
    monkeypatch.setattr(run_discovery, "ROOT", tmp_path)
    intelligence = tmp_path / "intel.json"
    intelligence.write_text(json.dumps({"searchStrategy": {
        "country": "Serbia", "jobSpySearchTerms": ["pm"], "locationFilters": ["Remote"], "remoteFilters": ["remote"],
    }}))
    monkeypatch.setattr(run_discovery, "get_provider", lambda name: Provider())

    def run(*extra):
        monkeypatch.setattr(sys, "argv", ["run_discovery.py", "--providers", "greenhouse",
                                          "--intelligence", str(intelligence), *extra])
        return run_discovery.main()

    return run


def test_a_clean_commit_leaves_no_marker_and_says_so_in_the_events(discovery):
    assert discovery() == 0
    assert run_log.read_commit_marker() is None


def test_the_commit_writes_no_marker_and_writes_the_ledger_before_the_view(discovery, monkeypatch, tmp_path):
    """S4a: the ledger is the commit point and the view follows it; there is no marker to write."""
    order, markers = [], []
    real = run_discovery.importer.view_guard._atomic.write_text_atomic

    def write(path, *args, **kwargs):
        order.append(Path(path).name)
        markers.append(run_log.read_commit_marker())
        return real(path, *args, **kwargs)

    monkeypatch.setattr(run_discovery.importer.view_guard._atomic, "write_text_atomic", write)
    assert discovery() == 0
    commit_writes = [name for name in order if name in ("job_history.json", "discovered_jobs.json")]
    assert commit_writes == ["job_history.json", "discovered_jobs.json"]
    assert markers == [None] * len(markers) and run_log.read_commit_marker() is None


def test_a_view_write_that_fails_leaves_the_ledger_committed_and_the_next_reader_rebuilds_the_view(discovery, monkeypatch, tmp_path):
    jobs = tmp_path / "data" / "jobs"
    real = run_discovery.importer.view_guard._atomic.write_text_atomic

    def write(path, *args, **kwargs):
        if Path(path).name == "discovered_jobs.json":
            raise OSError("disk full")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(run_discovery.importer.view_guard._atomic, "write_text_atomic", write)
    assert discovery() == 1, "the run says it did not finish"
    monkeypatch.undo()
    assert run_log.read_commit_marker() is None
    assert not (jobs / "discovered_jobs.json").exists()
    assert run_discovery.view_guard.state(jobs / "discovered_jobs.json", jobs / "job_history.json")["consistent"] is False
    fixed = run_discovery.view_guard.ensure(jobs / "discovered_jobs.json", jobs / "job_history.json")
    assert fixed["regenerated"] is True and json.loads((jobs / "discovered_jobs.json").read_text())["jobs"]


def test_a_marker_seen_while_the_lock_is_held_is_the_live_commit_not_a_stale_one(held):
    record = running_record("live")
    run_log.begin_commit(record, ["job_history"])
    assert run_rescrape.reconcile()["incompleteCommit"] is None


def test_an_unreadable_marker_still_counts_as_incomplete():
    run_log._atomic.make_private_dirs(run_log.runs_dir())
    run_log.commit_marker_path().write_text("{ torn")
    assert run_rescrape.reconcile()["incompleteCommit"]["unreadable"] is True


def test_sigkill_between_the_ledger_and_the_view_is_recovered_by_the_next_reader(tmp_path):
    """The real thing: a discovery killed after the ledger was written and before the view was."""
    intelligence = tmp_path / "intel.json"
    intelligence.write_text(json.dumps({"searchStrategy": {
        "country": "Serbia", "jobSpySearchTerms": ["pm"], "locationFilters": ["Remote"], "remoteFilters": ["remote"],
    }}))
    driver = tmp_path / "driver.py"
    driver.write_text(textwrap.dedent(f"""
        import os, signal, sys
        from pathlib import Path
        for sub in ("job_discovery", "job_scoring"):
            sys.path.append(str(Path({str(ROOT)!r}) / "python" / sub))
        sys.path.insert(0, str(Path({str(ROOT)!r}) / "tests" / "python"))
        sys.path.insert(0, str(Path({str(ROOT)!r}) / "python" / "job_discovery"))
        import run_discovery
        from providers.base_provider import JobProvider, ProviderOutcome, build_canonical_job
        class P(JobProvider):
            name = "greenhouse"
            last_outcome = None
            def fetch_jobs(self, *a):
                self.last_outcome = ProviderOutcome(status="ok", read=1, kept=1)
                return [build_canonical_job(provider="greenhouse", source="acme", title="PM", company="A", location="Remote",
                                            job_url="https://a.example/1", description="d")]
        run_discovery.ROOT = Path({str(tmp_path)!r})
        run_discovery.get_provider = lambda name: P()
        real = run_discovery.importer.view_guard._atomic.write_text_atomic
        def write(path, *a, **k):
            if Path(path).name == "discovered_jobs.json":
                os.kill(os.getpid(), signal.SIGKILL)
            return real(path, *a, **k)
        run_discovery.importer.view_guard._atomic.write_text_atomic = write
        sys.argv = ["run_discovery.py", "--providers", "greenhouse", "--intelligence", {str(intelligence)!r}]
        run_discovery.main()
    """))
    done = subprocess.run([sys.executable, str(driver)], env=dict(os.environ), capture_output=True)
    assert done.returncode == -signal.SIGKILL, done.stderr.decode()[-800:]
    jobs = tmp_path / "data" / "jobs"
    assert run_log.read_commit_marker() is None, "there is no marker any more"
    assert (jobs / "job_history.json").exists() and not (jobs / "discovered_jobs.json").exists()

    result = run_rescrape.reconcile()
    assert result["incompleteCommit"] is None
    [dead] = result["interrupted"]
    assert on_disk(dead)["status"] == "interrupted"

    guard = run_discovery.view_guard
    assert guard.state(jobs / "discovered_jobs.json", jobs / "job_history.json")["consistent"] is False
    assert guard.ensure(jobs / "discovered_jobs.json", jobs / "job_history.json")["regenerated"] is True
    view = json.loads((jobs / "discovered_jobs.json").read_text())
    assert view["meta"]["ledgerGeneration"] == 1 and [j["title"] for j in view["jobs"]] == ["PM"]


# --- discovery under the orchestrator ------------------------------------------------------------------------------


def test_managed_discovery_fills_the_run_s_record_and_does_not_finish_it(discovery, tmp_path):
    record = run_log.new_record(RUN_ID, "manual")
    run_log.save(record)
    assert discovery("--run-id", RUN_ID) == 0
    saved = on_disk(RUN_ID)
    assert saved["status"] == "running" and saved["finishedAt"] is None
    assert [s["name"] for s in saved["sources"]] == ["greenhouse"]
    file = json.loads((tmp_path / "data" / "jobs" / "discovered_jobs.json").read_text())
    assert file["meta"]["sourceRunId"] == RUN_ID, "one run id from the record to the jobs file"
    kinds = [e["type"] for e in events_of(record)]
    assert kinds == ["source_start", "source_end", "commit_start", "commit_end"]


def test_managed_discovery_with_an_unknown_run_id_stops(discovery):
    assert discovery("--run-id", "nosuchrun") == 1
    assert run_log.read_commit_marker() is None


def test_the_record_is_on_disk_at_the_start_and_after_every_source(discovery, monkeypatch):
    seen = []

    class Spy(Provider):
        def fetch_jobs(self, *args):
            found = [p for p in run_log.runs_dir().iterdir() if run_log.is_record_name(p.name)]
            seen.append(json.loads(found[0].read_text()))
            return super().fetch_jobs(*args)

    monkeypatch.setattr(run_discovery, "get_provider", lambda name: Spy())
    monkeypatch.setattr(run_discovery, "effective_provider_names", lambda spec: ["one", "two"])
    assert discovery() == 0
    assert [(r["status"], len(r["sources"])) for r in seen] == [("running", 0), ("running", 1)]


def test_a_direct_discovery_is_finished_by_itself_and_logs_events(discovery):
    assert discovery() == 0
    found = [p for p in run_log.runs_dir().iterdir() if run_log.is_record_name(p.name)]
    saved = json.loads(found[0].read_text())
    assert saved["status"] == "ok" and saved["finishedAt"]
    kinds = [e["type"] for e in events_of(saved)]
    assert kinds[0] == "run_start" and kinds[-1] == "run_end"


def test_a_direct_discovery_sweeps_a_dead_record_first(discovery):
    running_record()
    assert discovery() == 0
    assert on_disk("dead")["status"] == "interrupted"


# --- the orchestrator ----------------------------------------------------------------------------------------------


def test_the_steps_are_today_s_no_enrichment_and_no_judge():
    args = SimpleNamespace(run_id=RUN_ID, providers="serbia", country="Serbia")
    steps = run_rescrape.step_commands(args)
    assert [name for name, _ in steps] == ["discovery", "scoring"]
    discovery_cmd, scoring_cmd = steps[0][1], steps[1][1]
    assert discovery_cmd[0].endswith("job_discovery/run_discovery.py")
    assert discovery_cmd[1:] == ["--providers", "serbia", "--run-id", RUN_ID, "--country", "Serbia"]
    assert scoring_cmd[0].endswith("job_scoring/run_scoring.py") and scoring_cmd[1:] == []
    assert "enrich" not in " ".join(discovery_cmd + scoring_cmd)
    assert "--judge" not in discovery_cmd + scoring_cmd


FAKE_DISCOVERY = """
import json, os, sys, time
from pathlib import Path
from types import SimpleNamespace
sys.path.append({job_discovery!r}); sys.path.append({job_scoring!r})
import pipeline_lock, run_log
lock = pipeline_lock.acquire()
marks = Path({marks!r})
if lock is None:
    (marks / "discovery-no-lock").write_text("x")
    sys.exit(75)
run_id = sys.argv[sys.argv.index("--run-id") + 1]
record = run_log.find_record(run_id)
run_log.add_source(record, "greenhouse", SimpleNamespace(status="ok", read=1, kept=1, error=None, boards_failed=[], skip_reason=None, warnings=[]))
run_log.save(record)
(marks / "discovery-started").write_text(str(os.getpid()))
for _ in range(50):  # noisy on purpose: a closed output must not stop a step
    print("discovery says something", flush=True)
time.sleep(float(os.environ.get("FAKE_DISCOVERY_SECONDS", "0")))
(marks / "discovery-done").write_text("x")
sys.exit(int(os.environ.get("FAKE_DISCOVERY_EXIT", "0")))
"""

FAKE_SCORING = """
import os, sys
from pathlib import Path
marks = Path({marks!r})
print("scoring output line one\\nthe reason it failed api_key=hunter2", flush=True)
if os.environ.get("FAKE_SCORING_WAIT"):
    (marks / "scoring-started").write_text("x")
    while not (marks / "scoring-go").exists():
        pass
(marks / "scoring-done").write_text("x")
sys.exit(int(os.environ.get("FAKE_SCORING_EXIT", "0")))
"""

DRIVER = """
import sys
sys.path.insert(0, {python!r})
import run_rescrape
run_rescrape.DISCOVERY = {discovery!r}
run_rescrape.SCORING = {scoring!r}
sys.exit(run_rescrape.main(sys.argv[1:]))
"""


@pytest.fixture
def fake(tmp_path):
    """The real orchestrator, in its own process, over fake steps. `start` launches it the way Node does."""
    marks = tmp_path / "marks"
    marks.mkdir()
    py = ROOT / "python"
    (tmp_path / "fake_discovery.py").write_text(FAKE_DISCOVERY.format(
        job_discovery=str(py / "job_discovery"), job_scoring=str(py / "job_scoring"), marks=str(marks)))
    (tmp_path / "fake_scoring.py").write_text(FAKE_SCORING.format(marks=str(marks)))
    (tmp_path / "driver.py").write_text(DRIVER.format(
        python=str(py), discovery=str(tmp_path / "fake_discovery.py"), scoring=str(tmp_path / "fake_scoring.py")))
    started = []

    def start(*, run_id=RUN_ID, stdout=subprocess.DEVNULL, **env):
        proc = subprocess.Popen(
            [sys.executable, str(tmp_path / "driver.py"), "start", "--run-id", run_id, "--providers", "serbia"],
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stdout, start_new_session=True,
            env={**os.environ, **env},
        )
        started.append(proc)
        return proc

    yield SimpleNamespace(start=start, marks=marks)
    for proc in started:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    for name in ("discovery-started",):
        pid = marks / name
        if pid.exists():
            try:
                os.kill(int(pid.read_text()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass


def test_a_full_run_ends_ok_with_every_event_and_frees_the_lock(fake):
    assert fake.start().wait(30) == 0
    assert (fake.marks / "discovery-done").exists() and (fake.marks / "scoring-done").exists()
    assert not (fake.marks / "discovery-no-lock").exists(), "the step used the lock it was handed"
    saved = on_disk(RUN_ID)
    assert saved["status"] == "ok" and saved["finishedAt"] and saved["trigger"] == "manual"
    assert [(s["name"], s["status"]) for s in saved["steps"]] == [("discovery", "ok"), ("scoring", "ok")]
    assert [s["name"] for s in saved["sources"]] == ["greenhouse"], "the record the step filled is the one finished"
    assert [e["type"] for e in events_of(saved)] == ["run_start", "step_start", "step_end", "step_start", "step_end", "run_end"]
    assert lock_is_free()


def test_a_second_start_exits_75_and_leaves_the_first_alone(fake):
    first = fake.start(FAKE_DISCOVERY_SECONDS="60")
    assert wait_for((fake.marks / "discovery-started").exists)
    second = fake.start(run_id="second00000")
    assert second.wait(30) == pipeline_lock.EXIT_LOCKED
    assert on_disk("second00000") is None
    assert on_disk(RUN_ID)["status"] == "running"
    assert first.poll() is None


def test_the_run_goes_on_to_scoring_when_whoever_started_it_is_gone(fake):
    """The browser, or Node itself: output closed from the far end while discovery still prints."""
    read_end, write_end = os.pipe()
    proc = fake.start(stdout=write_end, FAKE_DISCOVERY_SECONDS="0.2")
    os.close(write_end)
    os.close(read_end)
    assert proc.wait(30) == 0
    assert (fake.marks / "scoring-done").exists()
    assert on_disk(RUN_ID)["status"] == "ok"


def test_sigkill_of_the_whole_run_frees_the_lock_and_the_record_becomes_interrupted(fake):
    proc = fake.start(FAKE_DISCOVERY_SECONDS="60")
    assert wait_for((fake.marks / "discovery-started").exists)
    assert not lock_is_free()
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(10)
    assert wait_for(lock_is_free), "the kernel drops the lock with its last holder"
    assert on_disk(RUN_ID)["status"] == "running", "nobody has looked yet"
    assert run_rescrape.reconcile()["interrupted"] == [RUN_ID]
    saved = on_disk(RUN_ID)
    assert saved["status"] == "interrupted" and saved["steps"][0]["status"] == "interrupted"


def test_sigkill_of_the_orchestrator_alone_keeps_the_lock_while_its_step_still_writes(fake):
    proc = fake.start(FAKE_DISCOVERY_SECONDS="60")
    assert wait_for((fake.marks / "discovery-started").exists)
    child = int((fake.marks / "discovery-started").read_text())
    proc.kill()
    proc.wait(10)
    time.sleep(0.1)

    assert not lock_is_free(), "an orphaned writer still holds it: no second run can start under it"
    assert run_rescrape.reconcile() == {"busy": True, "interrupted": [], "incompleteCommit": None}
    second = fake.start(run_id="second00000")
    assert second.wait(30) == pipeline_lock.EXIT_LOCKED

    os.kill(child, signal.SIGKILL)
    assert wait_for(lock_is_free)
    assert run_rescrape.reconcile()["interrupted"] == [RUN_ID]


def test_a_failed_discovery_stops_before_scoring_as_today(fake):
    assert fake.start(FAKE_DISCOVERY_EXIT="1").wait(30) == 1
    assert not (fake.marks / "scoring-done").exists()
    saved = on_disk(RUN_ID)
    assert saved["status"] == "failed"
    assert [(s["name"], s["status"]) for s in saved["steps"]] == [("discovery", "failed")]
    assert any("discovery" in i["message"] for i in saved["issues"])


def test_a_failed_scoring_fails_the_run_and_names_the_reason_without_secrets(fake):
    assert fake.start(FAKE_SCORING_EXIT="1").wait(30) == 1
    saved = on_disk(RUN_ID)
    assert saved["status"] == "failed"
    assert saved["steps"][-1] == {**saved["steps"][-1], "name": "scoring", "status": "failed", "exitCode": 1}
    message = next(i["message"] for i in saved["issues"] if "scoring" in i["message"])
    assert "the reason it failed" in message and "hunter2" not in message
    assert "hunter2" not in run_log.events_path(saved).read_text()


def test_the_start_sweeps_a_dead_record(fake):
    running_record()
    assert fake.start().wait(30) == 0
    assert on_disk("dead")["status"] == "interrupted"


def test_a_bad_run_id_starts_nothing():
    assert run_rescrape.main(["start", "--run-id", "../../etc", "--providers", "serbia"]) == 2
    assert lock_is_free()


def test_hold_keeps_the_lock_until_its_stdin_closes():
    env = dict(os.environ)
    proc = subprocess.Popen([sys.executable, str(ROOT / "python" / "run_rescrape.py"), "hold"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
    assert proc.stdout.readline().strip() == "locked"
    assert not lock_is_free()
    proc.stdin.close()
    assert proc.wait(10) == 0
    assert lock_is_free()


def test_hold_answers_75_when_a_run_holds_it(held):
    done = subprocess.run([sys.executable, str(ROOT / "python" / "run_rescrape.py"), "hold"],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, env=dict(os.environ))
    assert done.returncode == pipeline_lock.EXIT_LOCKED and "locked" not in done.stdout
