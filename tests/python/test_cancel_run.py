"""Cancel a running Re-scrape (slice S6), process level: the request, the signal, the commit claim, the kill, the process tree.

The orchestrator is the real one over fake steps; discovery is the real one over a fake provider; the last test runs the real
orchestrator, the real discovery and the real importer in a scratch copy of the code, with a slow provider.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]

import filtered_ads  # noqa: E402
import pipeline_lock  # noqa: E402
import run_discovery  # noqa: E402
import run_log  # noqa: E402
import run_rescrape  # noqa: E402
from providers.base_provider import JobProvider, ProviderOutcome, build_canonical_job  # noqa: E402
from test_rescrape import RUN_ID, events_of, held, lock_is_free, on_disk, running_record, wait_for  # noqa: E402, F401

PY = ROOT / "python"

# --- fake steps -------------------------------------------------------------------------------------------------------------

FAKE_DISCOVERY = """
import json, os, signal, subprocess, sys, time
from pathlib import Path
from types import SimpleNamespace
sys.path.append({job_discovery!r}); sys.path.append({job_scoring!r})
import pipeline_lock, run_log
lock = pipeline_lock.acquire()
marks = Path({marks!r})
if lock is None:
    sys.exit(75)
run_id = sys.argv[sys.argv.index("--run-id") + 1]
record = run_log.find_record(run_id)
mode = os.environ.get("FAKE_MODE", "cooperate")
run_log.add_source(record, "greenhouse", SimpleNamespace(status="ok", read=1, kept=1, error=None, boards_failed=[], skip_reason=None, warnings=[]))
run_log.save(record)
# a grandchild in a session of its own, as a browser a provider started would be
if os.environ.get("FAKE_STUBBORN_CHILD"):  # a browser that does not hear SIGTERM
    child = subprocess.Popen([sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(300)"], start_new_session=True)
else:
    child = subprocess.Popen(["sleep", "300"], start_new_session=True)
(marks / "grandchild").write_text(str(child.pid))

def term(*_):
    (marks / "term-seen").write_text("x")
    if mode == "cooperate":
        record["cancel"] = {{"requestedAt": run_log.cancel_info(record)["requestedAt"], "outcome": "collected_ads_imported"}}
        run_log.save(record)
        sys.exit(run_log.EXIT_CANCELLED)

if mode == "ignore":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
else:
    signal.signal(signal.SIGTERM, term)
(marks / "discovery-started").write_text(str(os.getpid()))
if mode == "commit":
    assert run_log.claim(record, "commit")
    (marks / "committing").write_text("x")
if mode == "cancel-at-end":
    run_log.request_cancel(record)
time.sleep(float(os.environ.get("FAKE_DISCOVERY_SECONDS", "0")))
(marks / "discovery-done").write_text("x")
child.kill()  # a run that was not cancelled cleans up after itself; a cancelled one is swept by the orchestrator
sys.exit(0)
"""

FAKE_SCORING = """
import os, sys, time
from pathlib import Path
marks = Path({marks!r})
(marks / "scoring-started").write_text(str(os.getpid()))
time.sleep(float(os.environ.get("FAKE_SCORING_SECONDS", "0")))
(marks / "scoring-done").write_text("x")
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
    marks = tmp_path / "marks"
    marks.mkdir()
    (tmp_path / "fake_discovery.py").write_text(FAKE_DISCOVERY.format(job_discovery=str(PY / "job_discovery"), job_scoring=str(PY / "job_scoring"), marks=str(marks)))
    (tmp_path / "fake_scoring.py").write_text(FAKE_SCORING.format(marks=str(marks)))
    (tmp_path / "driver.py").write_text(DRIVER.format(python=str(PY), discovery=str(tmp_path / "fake_discovery.py"), scoring=str(tmp_path / "fake_scoring.py")))
    started = []

    def start(run_id=RUN_ID, **env):
        proc = subprocess.Popen(
            [sys.executable, str(tmp_path / "driver.py"), "start", "--run-id", run_id, "--providers", "serbia"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            env={**os.environ, "CAREER_OS_CANCEL_GRACE_SECONDS": "1", **env},
        )
        started.append(proc)
        return proc

    yield SimpleNamespace(start=start, marks=marks)
    for proc in started:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    for name in ("grandchild", "discovery-started", "scoring-started"):
        mark = marks / name
        if mark.exists():
            try:
                os.kill(int(mark.read_text()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass


def alive(pid: int) -> bool:
    """Running, not a zombie waiting to be reaped."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


def grandchild(fake) -> int:
    return int((fake.marks / "grandchild").read_text())


def started(fake, name="discovery-started"):
    assert wait_for((fake.marks / name).exists), f"{name} never appeared"


# --- the request ------------------------------------------------------------------------------------------------------------


def test_cancel_during_discovery_stops_the_step_and_records_a_cancelled_run(fake):
    proc = fake.start(FAKE_DISCOVERY_SECONDS="60")
    started(fake)
    pid = int((fake.marks / "discovery-started").read_text())
    assert run_rescrape.cancel(RUN_ID)["result"] == "cancel_requested"
    assert proc.wait(30) == 0, "a cancelled run is not a failed one"
    assert (fake.marks / "term-seen").exists()
    saved = on_disk(RUN_ID)
    assert saved["status"] == "cancelled" and saved["finishedAt"]
    assert [(s["name"], s["status"]) for s in saved["steps"]] == [("discovery", "cancelled")], "scoring was not started"
    assert not (fake.marks / "scoring-started").exists()
    assert saved["cancel"]["outcome"] == "collected_ads_imported" and saved["cancel"]["requestedAt"]
    types = [e["type"] for e in events_of(saved)]
    assert types.index("cancel_requested") < types.index("cancel_signal") < types.index("step_end") < types.index("run_end")
    assert not alive(pid) and not alive(grandchild(fake)), "the step and what it started are gone"
    assert lock_is_free()


def test_a_child_that_ignores_sigterm_is_killed_when_the_step_is_gone(fake):
    """The step obeys and exits; the browser it started does not. Nothing may outlive a cancelled run, or it would keep the lock."""
    proc = fake.start(FAKE_STUBBORN_CHILD="1", FAKE_DISCOVERY_SECONDS="60")
    started(fake)
    child = grandchild(fake)
    assert alive(child)
    run_rescrape.cancel(RUN_ID)
    assert proc.wait(30) == 0
    assert wait_for(lambda: not alive(child), 5), "swept after the step ended"
    assert lock_is_free() and on_disk(RUN_ID)["status"] == "cancelled"


def test_a_step_that_ignores_sigterm_is_killed_after_the_grace_and_nothing_survives(fake):
    proc = fake.start(FAKE_MODE="ignore", FAKE_DISCOVERY_SECONDS="60")
    started(fake)
    assert run_rescrape.cancel(RUN_ID)["result"] == "cancel_requested"
    assert proc.wait(30) == 0
    saved = on_disk(RUN_ID)
    assert saved["status"] == "cancelled"
    assert saved["steps"][0]["status"] == "cancelled" and saved["steps"][0]["exitCode"] == -signal.SIGKILL
    assert saved["cancel"]["outcome"] == "stopped_nothing_imported"
    assert run_log.decision(saved) == "kill"
    assert "cancel_kill" in [e["type"] for e in events_of(saved)]
    assert not alive(grandchild(fake)), "a child in a session of its own is found by its parent links and stopped"
    assert lock_is_free()


def test_a_step_that_has_claimed_its_commit_is_never_killed(fake):
    """The commit point: SIGTERM is ignored (deferred), the grace passes, and the orchestrator still does not kill, because it cannot win the claim."""
    proc = fake.start(FAKE_MODE="commit", FAKE_DISCOVERY_SECONDS="3")
    started(fake, "committing")
    assert run_rescrape.cancel(RUN_ID)["result"] == "cancel_requested"
    assert proc.wait(30) == 0
    assert (fake.marks / "discovery-done").exists(), "the commit ran to its end"
    saved = on_disk(RUN_ID)
    assert run_log.decision(saved) == "commit" and "cancel_kill" not in [e["type"] for e in events_of(saved)]
    assert saved["status"] == "ok", "it was imported as any import is"
    assert [(s["name"], s["status"]) for s in saved["steps"]] == [("discovery", "ok")], "scoring was skipped"
    assert saved["cancel"]["outcome"] == "imported_before_cancel"
    assert any("Scoring was skipped" in i["message"] for i in saved["issues"])
    assert lock_is_free()


def test_a_run_whose_kill_was_claimed_never_commits(tmp_path):
    record = run_log.new_record("claimrun1", "manual")
    run_log.save(record)
    assert run_log.claim(record, "kill") is True
    assert run_log.claim(record, "commit") is False, "exactly one of them has it"
    other = run_log.new_record("claimrun2", "manual")
    run_log.save(other)
    assert run_log.claim(other, "commit") is True and run_log.claim(other, "kill") is False


def test_cancel_during_scoring_stops_scoring_and_keeps_the_import(fake):
    proc = fake.start(FAKE_SCORING_SECONDS="60")
    started(fake, "scoring-started")
    assert run_rescrape.cancel(RUN_ID)["result"] == "cancel_requested"
    assert proc.wait(30) == 0
    saved = on_disk(RUN_ID)
    assert [(s["name"], s["status"]) for s in saved["steps"]] == [("discovery", "ok"), ("scoring", "cancelled")]
    assert saved["status"] == "ok" and saved["cancel"]["outcome"] == "imported_before_cancel", "the scrape was imported and counts"
    assert not (fake.marks / "scoring-done").exists() and lock_is_free()


def test_a_request_that_arrives_between_the_steps_skips_scoring(fake):
    proc = fake.start(FAKE_MODE="cancel-at-end")
    assert proc.wait(30) == 0
    saved = on_disk(RUN_ID)
    assert [s["name"] for s in saved["steps"]] == ["discovery"] and not (fake.marks / "scoring-started").exists()
    assert saved["status"] == "ok" and saved["cancel"]["outcome"] == "imported_before_cancel"
    assert "step_skipped" in [e["type"] for e in events_of(saved)]


def test_a_request_after_the_run_finished_is_answered_and_changes_nothing(fake):
    assert fake.start().wait(30) == 0
    before = run_log.record_path(on_disk(RUN_ID)).read_bytes()
    answer = run_rescrape.cancel(RUN_ID)
    assert answer["result"] == "already_finished" and answer["status"] == "ok"
    assert not run_log.cancel_requested(on_disk(RUN_ID))
    assert run_log.record_path(on_disk(RUN_ID)).read_bytes() == before


def test_cancel_is_idempotent(fake):
    proc = fake.start(FAKE_DISCOVERY_SECONDS="60")
    started(fake)
    assert run_rescrape.cancel(RUN_ID)["result"] == "cancel_requested"
    again = run_rescrape.cancel(RUN_ID)
    assert again["result"] in ("cancel_already_requested", "already_cancelled")
    assert proc.wait(30) == 0
    assert run_rescrape.cancel(RUN_ID)["result"] == "already_cancelled"
    assert run_rescrape.cancel(RUN_ID)["result"] == "already_cancelled"
    events = [e["type"] for e in events_of(on_disk(RUN_ID))]
    assert events.count("cancel_requested") == 1 and events.count("cancel_signal") == 1


def test_an_unknown_or_malformed_run_id_writes_nothing(tmp_path):
    assert run_rescrape.cancel("nosuchrun1")["result"] == "unknown_run"
    for bad in ("../../etc", "a b", "", "x" * 40):
        assert run_rescrape.cancel(bad)["result"] == "invalid_run_id"
    assert not list((tmp_path / "analytics").glob("**/*")) or not any(p.suffix == ".cancel" for p in (tmp_path / "analytics").rglob("*"))


def test_a_run_this_orchestrator_does_not_own_is_not_cancellable(held):
    record = running_record("pipeline1")  # no `orchestrator` field: a pipeline run or a direct discovery
    assert run_rescrape.cancel("pipeline1")["result"] == "not_cancellable"
    assert not run_log.cancel_requested(record)


def test_a_record_that_says_running_with_nobody_holding_the_lock_is_not_a_run():
    record = running_record("dead0001")
    record["orchestrator"] = "rescrape"
    run_log.save(record)
    assert run_rescrape.cancel("dead0001")["result"] == "not_running"
    assert not run_log.cancel_requested(record)


def test_a_request_for_one_run_never_reaches_the_next(fake):
    assert fake.start(run_id="first00000001").wait(30) == 0
    old = run_rescrape.cancel("first00000001")
    assert old["result"] == "already_finished"
    proc = fake.start(run_id="second0000002")
    assert proc.wait(30) == 0
    saved = on_disk("second0000002")
    assert saved["status"] == "ok" and "cancel" not in saved and [s["status"] for s in saved["steps"]] == ["ok", "ok"]


def test_the_run_after_a_cancelled_one_starts_at_once_and_finishes(fake):
    proc = fake.start(run_id="cancelled0001", FAKE_DISCOVERY_SECONDS="60")
    started(fake)
    run_rescrape.cancel("cancelled0001")
    assert proc.wait(30) == 0 and lock_is_free()
    (fake.marks / "discovery-started").unlink()
    (fake.marks / "term-seen").unlink()
    assert fake.start(run_id="next000000002").wait(30) == 0
    assert on_disk("next000000002")["status"] == "ok"
    assert run_log.sweep_interrupted() == [], "the cancelled record is not a dead running one"


def test_cancel_and_decision_files_are_pruned_with_their_record(tmp_path):
    folder = run_log.runs_dir()
    folder.mkdir(parents=True)
    for suffix in ("json", "events.jsonl", "cancel", "decision"):
        (folder / f"20200101T000000Z-oldrun.{suffix}").write_text("{}")
    (folder / "20200101T000000Z-oldrun.json").write_text(json.dumps({"runId": "oldrun", "startedAt": "2020-01-01T00:00:00+00:00"}))
    assert run_log.prune(folder) == 4 and not any(folder.iterdir())


def test_a_cancel_request_file_is_not_mistaken_for_a_record(tmp_path):
    record = run_log.new_record("recordid01", "manual")
    run_log.save(record)
    run_log.request_cancel(record)
    run_log.claim(record, "commit")
    assert [r["runId"] for r in run_log._records()] == ["recordid01"]
    assert not run_log.is_record_name(run_log.cancel_path(record).name)
    assert not run_log.is_record_name(run_log.decision_path(record).name)


def test_the_lock_probe_matches_the_inode_and_not_the_device(tmp_path, monkeypatch):
    """/proc/locks may print another device number than stat() for the same file (bind mount, subvolume). That must still read as held."""
    lock = tmp_path / "pipeline.lock"
    lock.write_text("")
    inode = lock.stat().st_ino
    table = tmp_path / "locks"
    table.write_text(f"1: FLOCK  ADVISORY  WRITE 4242 de:ad:{inode} 0 EOF\n2: POSIX  ADVISORY  READ 7 fc:00:{inode + 1} 0 EOF\n")
    assert run_rescrape.lock_is_held(table) is True
    table.write_text(f"1: FLOCK  ADVISORY  WRITE 4242 de:ad:{inode + 1} 0 EOF\n2: POSIX  ADVISORY  WRITE 7 fc:00:{inode} 0 EOF\n")
    assert run_rescrape.lock_is_held(table) is False, "only a flock on this inode, not a POSIX lock on another"
    assert run_rescrape.lock_is_held(tmp_path / "missing") is None, "cannot tell: the caller treats it as alive"
    lock.unlink()
    assert run_rescrape.lock_is_held(table) is False


def test_a_cancel_takes_no_lock_and_no_data_file(held, tmp_path):
    """Asked while another process holds the lock: it answers, and the only thing written is the request file."""
    record = run_log.new_record("busyrun001", "manual")
    record["orchestrator"] = "rescrape"
    run_log.save(record)
    before = {p: p.stat().st_mtime_ns for p in (tmp_path).rglob("*") if p.is_file()}
    assert run_rescrape.cancel("busyrun001")["result"] == "cancel_requested"
    added = [p for p in (tmp_path).rglob("*") if p.is_file() and p not in before]
    assert sorted(p.suffix for p in added) == [".cancel", ".jsonl"], "the request and one event"
    assert all(p.stat().st_mtime_ns == t for p, t in before.items() if p.exists() and p.name != "pipeline.lock")


# --- real discovery, in process ---------------------------------------------------------------------------------------------


def job(job_id):
    return {**build_canonical_job(provider="jobspy", source="jobspy", title=f"PM {job_id}", company="Acme", location="Remote",
                                  job_url=f"https://a.example/{job_id}", description="Own the roadmap."), "jobId": job_id}


class Provider(JobProvider):
    """Stages one batch, then does what `act` says while 'fetching the rest'."""
    name = "jobspy"
    act = staticmethod(lambda provider: None)
    jobs = ("g1", "g2")

    def __init__(self):
        self.last_outcome = None

    def fetch_jobs(self, *args):
        ads = [job(j) for j in self.jobs]
        if self.stage_writer is not None:
            self.stage_writer.append(ads, part="p", read=len(ads))
        type(self).act(self)
        self.last_outcome = ProviderOutcome(status="ok", read=len(ads), kept=len(ads))
        return ads


@pytest.fixture
def managed(tmp_path, monkeypatch):
    """The real discovery, managed (as the orchestrator starts it), over a provider the test controls. No signal handler is installed."""
    monkeypatch.setattr(run_discovery, "ROOT", tmp_path)
    monkeypatch.setattr(run_discovery.CancelState, "install", lambda self: self)
    intelligence = tmp_path / "intel.json"
    intelligence.write_text(json.dumps({"searchStrategy": {"country": "Serbia", "jobSpySearchTerms": ["pm"], "locationFilters": ["Remote"], "remoteFilters": ["remote"]}}))

    def run(run_id, act=lambda provider, record: None, jobs=("g1", "g2"), before=None, providers="jobspy"):
        record = run_log.new_record(run_id, "manual")
        record["orchestrator"] = "rescrape"
        run_log.save(record)
        if before:
            before(record)
        provider = type("P", (Provider,), {"act": staticmethod(lambda p: act(p, record)), "jobs": jobs})
        monkeypatch.setattr(run_discovery, "get_provider", lambda name: provider())
        monkeypatch.setattr(sys, "argv", ["run_discovery.py", "--providers", providers, "--intelligence", str(intelligence), "--run-id", run_id])
        return run_discovery.main(), run_log.find_record(run_id)

    return run


def proven(root):
    """Every run id the ledger counts for the Stale rule, for this one source."""
    return [run["runId"] for bucket in (ledger_of(root).get("sourceRuns", {}).get("jobspy") or {}).values() for run in bucket]


def ledger_of(root):
    return json.loads((root / "data/jobs/job_history.json").read_text())


def test_a_request_that_arrives_while_the_source_is_read_imports_what_was_collected_held(managed, tmp_path):
    assert managed("run00000001")[0] == 0
    code, record = managed("run00000002", act=lambda provider, record: run_log.request_cancel(record), jobs=("g1", "g3"))
    assert code == run_log.EXIT_CANCELLED
    ledger = ledger_of(tmp_path)
    assert ledger["lastImport"]["runId"] == "run00000002" and ledger["lastImport"]["cancelled"] is True
    assert "g3" in ledger["jobs"] and ledger["generation"] == 2
    assert not ledger["jobs"]["g2"].get("absentSince") and not ledger["jobs"]["g2"].get("closedAt")
    assert proven(tmp_path) == ["run00000001"]
    assert filtered_ads.load(tmp_path)["appliedRuns"] == ["run00000001"]
    assert record["cancel"]["outcome"] == "collected_ads_imported" and record["status"] == "running", "the orchestrator finishes the record"
    assert (tmp_path / "data/jobs/staging/run00000002" / "cancelled.json").is_file()
    assert "cancelled" in [e["type"] for e in events_of(record)]
    assert json.loads((tmp_path / "data/jobs/discovered_jobs.json").read_text())["meta"]["ledgerGeneration"] == 2


def test_a_request_during_the_first_source_means_the_second_never_starts(managed, tmp_path):
    asked = []
    code, record = managed("run00000001", providers="jobspy,remoteok", act=lambda provider, record: (asked.append(1), run_log.request_cancel(record)))
    assert code == run_log.EXIT_CANCELLED and asked == [1], "the second source was not fetched"
    assert [source["name"] for source in record["sources"]] == ["jobspy"]
    assert "remoteok" not in [e.get("source") for e in events_of(record) if e["type"] == "source_start"]


def test_a_request_made_in_the_same_instant_as_the_commit_claim_still_cancels(managed, tmp_path, monkeypatch):
    """The request lands between the loop and the claim's re-read: the file is checked after the claim, not before."""
    managed("run00000001")
    real = run_log.claim

    def claim_then_request(record, role):
        won = real(record, role)
        run_log.request_cancel(record)
        return won

    monkeypatch.setattr(run_log, "claim", claim_then_request)
    code, _ = managed("run00000002")
    assert code == run_log.EXIT_CANCELLED and ledger_of(tmp_path)["lastImport"]["cancelled"] is True
    assert proven(tmp_path) == ["run00000001"]


def test_a_request_before_the_scrape_starts_collects_and_changes_nothing(managed, tmp_path):
    assert managed("run00000001")[0] == 0
    before = {p: p.read_bytes() for p in (tmp_path / "data/jobs").glob("*.json")}
    code, record = managed("run00000002", before=run_log.request_cancel)
    assert code == run_log.EXIT_CANCELLED
    assert {p: p.read_bytes() for p in (tmp_path / "data/jobs").glob("*.json")} == before
    assert not (tmp_path / "data/jobs/staging/run00000002").exists(), "nothing was collected"
    assert record["cancel"]["outcome"] == "stopped_nothing_imported"


def test_a_cancel_inside_the_fetch_leaves_the_source_unfinished_and_imports_its_ads_held(managed, tmp_path):
    managed("run00000001")

    def term(provider, record):
        raise run_discovery.RunCancelled()  # what the SIGTERM handler raises while a source is being read

    code, record = managed("run00000002", act=term, jobs=("g1", "g4"))
    assert code == run_log.EXIT_CANCELLED
    staged = (tmp_path / "data/jobs/staging/run00000002/jobspy.jsonl").read_text().splitlines()
    assert json.loads(staged[-1])["t"] == "batch", "no footer: the source did not finish"
    ledger = ledger_of(tmp_path)
    assert "g4" in ledger["jobs"] and not ledger["jobs"]["g2"].get("absentSince") and ledger["jobs"]["g2"]["heldRunId"] == "run00000002"
    assert "run00000002" not in proven(tmp_path)


def test_a_run_whose_kill_was_claimed_imports_nothing(managed, tmp_path):
    managed("run00000001")
    before = {p: p.read_bytes() for p in (tmp_path / "data/jobs").glob("*.json")}
    code, _ = managed("run00000002", before=lambda record: run_log.claim(record, "kill"))
    assert code == run_log.EXIT_CANCELLED
    assert {p: p.read_bytes() for p in (tmp_path / "data/jobs").glob("*.json")} == before
    assert not (tmp_path / "data/jobs/staging/run00000002" / "imported.json").exists()


def test_a_run_nobody_cancelled_is_unchanged(managed, tmp_path):
    managed("run00000001")
    code, record = managed("run00000002")
    assert code == 0 and "cancel" not in record and "cancelled" not in ledger_of(tmp_path)["lastImport"]
    assert proven(tmp_path) == ["run00000001", "run00000002"]
    assert filtered_ads.load(tmp_path)["appliedRuns"] == ["run00000001", "run00000002"]


def test_the_signal_only_raises_while_the_scrape_loop_runs():
    state = run_discovery.CancelState()
    state.handle(signal.SIGTERM, None)
    assert state.pending is True, "outside the loop it only sets a flag"
    state = run_discovery.CancelState()
    state.interruptible = True
    with pytest.raises(run_discovery.RunCancelled):
        state.handle(signal.SIGTERM, None)
    assert state.interruptible is False
    state.handle(signal.SIGTERM, None)  # a second one, in the cleanup after the first, does not raise again
    assert not issubclass(run_discovery.RunCancelled, Exception), "a provider's `except Exception` cannot swallow it"


def test_a_provider_that_catches_exceptions_cannot_swallow_a_cancel(managed, tmp_path):
    def swallow(provider, record):
        try:
            raise run_discovery.RunCancelled()
        except Exception:  # noqa: BLE001 - what a careless provider does
            pass

    code, _ = managed("run00000001", act=swallow)
    assert code == run_log.EXIT_CANCELLED, "not an Exception, so the provider's handler let it through to the loop's own"


# --- the real thing: real orchestrator, real discovery, real importer, a slow provider ---------------------------------------

SLOW_PROVIDER = '''
import os, signal, subprocess, time
from pathlib import Path
from providers.base_provider import JobProvider, ProviderOutcome, build_canonical_job


def ad(n):
    return build_canonical_job(provider="slowtest", source="slowtest", title=f"Role {n}", company="Acme", location="Remote",
                               job_url=f"https://slow.example/{n}", description="Own the roadmap and the discovery.")


class SlowTestProvider(JobProvider):
    name = "slowtest"

    def __init__(self):
        self.last_outcome = None

    def fetch_jobs(self, *args):
        mode = os.environ.get("SLOW_MODE", "fast")
        ads = [ad(n) for n in os.environ.get("SLOW_ADS", "1,2").split(",")]
        if self.stage_writer is not None:
            self.stage_writer.append(ads, part="page-1", read=len(ads))
        if mode in ("slow", "stubborn"):
            if mode == "stubborn":
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            marks = Path(os.environ["SLOW_MARKS"])
            browser = subprocess.Popen(["sleep", "300"], start_new_session=True)  # a browser the provider started, in a session of its own
            (marks / "browser").write_text(str(browser.pid))
            (marks / "in-flight").write_text(str(os.getpid()))
            time.sleep(300)
        self.last_outcome = ProviderOutcome(status="ok", read=len(ads), kept=len(ads))
        return ads
'''

COMMIT_DELAY = '''

_real_commit = commit


def commit(*args, **kwargs):
    """A slow disk, for the test that cancels during the commit."""
    import os, time
    time.sleep(float(os.environ.get("TEST_COMMIT_DELAY") or 0))
    return _real_commit(*args, **kwargs)
'''

TRIVIAL_SCORING = "import os, time; time.sleep(float(os.environ.get('TEST_SCORING_SECONDS') or 0))\n"

SCRATCH_DRIVER = """
import sys
sys.path.insert(0, {python!r})
import run_rescrape
run_rescrape.SCORING = {scoring!r}
sys.exit(run_rescrape.main(sys.argv[1:]))
"""


@pytest.fixture
def scratch(tmp_path):
    """A copy of the code in its own tree, so the real discovery's ROOT is a throwaway one. Only two seams differ from the original: a
    provider that is slow on demand, and a delay inside the commit."""
    repo = tmp_path / "repo"
    shutil.copytree(PY, repo / "python", ignore=shutil.ignore_patterns("__pycache__"))
    (repo / "python/job_discovery/providers/slowtest_provider.py").write_text(SLOW_PROVIDER)
    registry = repo / "python/job_discovery/providers/provider_registry.py"
    registry.write_text(registry.read_text() + "\nfrom providers.slowtest_provider import SlowTestProvider  # noqa: E402\nPROVIDER_CLASSES['slowtest'] = SlowTestProvider\n")
    guard = repo / "python/job_scoring/view_guard.py"
    guard.write_text(guard.read_text() + COMMIT_DELAY)
    (repo / "data/intelligence").mkdir(parents=True)
    (repo / "data/intelligence/candidate-intelligence.json").write_text(json.dumps({"searchStrategy": {
        "country": "Serbia", "jobSpySearchTerms": ["pm"], "locationFilters": ["Remote"], "remoteFilters": ["remote"]}}))
    (tmp_path / "scoring.py").write_text(TRIVIAL_SCORING)
    (tmp_path / "driver.py").write_text(SCRATCH_DRIVER.format(python=str(repo / "python"), scoring=str(tmp_path / "scoring.py")))
    marks = tmp_path / "slow-marks"
    marks.mkdir()
    procs = []

    def start(run_id, **env):
        for name in marks.iterdir():
            name.unlink()
        proc = subprocess.Popen(
            [sys.executable, str(tmp_path / "driver.py"), "start", "--run-id", run_id, "--providers", "slowtest"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            env={**os.environ, "SLOW_MARKS": str(marks), "CAREER_OS_CANCEL_GRACE_SECONDS": "1", **env},
        )
        procs.append(proc)
        return proc

    def cancel_cli(run_id):
        done = subprocess.run([sys.executable, str(repo / "python/run_rescrape.py"), "cancel", "--run-id", run_id], capture_output=True, text=True, timeout=30)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    yield SimpleNamespace(repo=repo, marks=marks, start=start, cancel=cancel_cli)
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    for name in ("browser", "in-flight"):
        if (marks / name).exists():
            try:
                os.kill(int((marks / name).read_text()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass


def tree_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file() and "staging" not in p.parts}


def view_lock_free(jobs) -> bool:
    """Nothing holds data/jobs/.view.lock (the lock readers take to rebuild the view)."""
    import fcntl

    fd = os.open(jobs / ".view.lock", os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


def leftover(repo):
    listing = subprocess.run(["ps", "-eo", "pid,pgid,stat,cmd"], capture_output=True, text=True).stdout.splitlines()
    return [line for line in listing if str(repo) in line and "pytest" not in line]


def test_the_real_run_cancelled_mid_scrape_commit_point_and_hard_kill(scratch):
    repo = scratch.repo
    jobs = repo / "data/jobs"
    ledger = lambda: json.loads((jobs / "job_history.json").read_text())  # noqa: E731
    counted_runs = lambda: [r["runId"] for b in (ledger().get("sourceRuns", {}).get("slowtest") or {}).values() for r in b]  # noqa: E731
    applied_runs = lambda: json.loads((jobs / "filtered_ads.json").read_text())["appliedRuns"]  # noqa: E731

    # A: an ordinary run. Two ads, and it counts.
    assert scratch.start("runA00000001").wait(60) == 0
    assert on_disk("runA00000001")["status"] == "ok"
    assert ledger()["generation"] == 1 and counted_runs() == ["runA00000001"] and applied_runs() == ["runA00000001"]

    # B: slow. It has staged ads 1 and 3 and is still "reading", with a browser of its own in another session.
    proc = scratch.start("runB00000002", SLOW_MODE="slow", SLOW_ADS="1,3")
    assert wait_for((scratch.marks / "in-flight").exists, 60)
    browser = int((scratch.marks / "browser").read_text())
    provider = int((scratch.marks / "in-flight").read_text())
    assert alive(browser) and alive(provider) and not lock_is_free()
    asked = time.monotonic()
    answer = scratch.cancel("runB00000002")
    assert answer["result"] == "cancel_requested"
    assert proc.wait(30) == 0
    assert time.monotonic() - asked < 15, "a cooperative cancel does not wait out the slow source"
    saved = on_disk("runB00000002")
    assert saved["status"] == "cancelled" and saved["cancel"]["outcome"] == "collected_ads_imported"
    assert [(s["name"], s["status"], s["exitCode"]) for s in saved["steps"]] == [("discovery", "cancelled", run_log.EXIT_CANCELLED)]
    assert not alive(browser) and not alive(provider) and lock_is_free() and leftover(repo) == []
    after_b = ledger()
    assert after_b["generation"] == 2 and after_b["lastImport"]["runId"] == "runB00000002" and after_b["lastImport"]["cancelled"] is True
    assert len(after_b["jobs"]) == 3, "ads 1 and 2 from A, and ad 3 which B collected"
    ad2 = next(e for e in after_b["jobs"].values() if e["job"]["title"] == "Role 2")
    assert not ad2.get("closedAt") and not ad2.get("absentSince") and ad2["heldRunId"] == "runB00000002", "B did not return it and said nothing about it"
    assert counted_runs() == ["runA00000001"] and applied_runs() == ["runA00000001"], "B is neither a proven run nor an applied one"
    assert (jobs / "staging/runB00000002/cancelled.json").is_file()
    guard = json.loads((jobs / "discovered_jobs.json").read_text())
    assert guard["meta"]["ledgerGeneration"] == 2 and len(guard["jobs"]) == 3
    assert run_log.sweep_interrupted() == []

    # C: a source that ignores SIGTERM. After the grace it is killed, and nothing is imported.
    before_c = tree_bytes(jobs)
    proc = scratch.start("runC00000003", SLOW_MODE="stubborn", SLOW_ADS="1,4")
    assert wait_for((scratch.marks / "in-flight").exists, 60)
    browser = int((scratch.marks / "browser").read_text())
    assert scratch.cancel("runC00000003")["result"] == "cancel_requested"
    assert proc.wait(30) == 0
    saved = on_disk("runC00000003")
    assert saved["status"] == "cancelled" and saved["cancel"]["outcome"] == "stopped_nothing_imported" and saved["steps"][0]["exitCode"] == -signal.SIGKILL
    assert not alive(browser) and lock_is_free() and leftover(repo) == []
    assert tree_bytes(jobs) == before_c, "no data file changed"
    assert (jobs / "staging/runC00000003/cancelled.json").is_file() and not (jobs / "staging/runC00000003/imported.json").exists()
    assert view_lock_free(jobs), "a killed run left the view lock free"
    assert "runC00000003" not in filtered_ads.unrecorded(repo), "and no later path will count it"

    # D: the cancel arrives while the commit is being written. The commit finishes, the run is not killed, scoring is skipped.
    proc = scratch.start("runD00000004", TEST_COMMIT_DELAY="4", SLOW_ADS="1,2,5")
    record = None
    assert wait_for(lambda: (record := on_disk("runD00000004")) is not None and "commit_start" in [e["type"] for e in events_of(record)], 60)
    assert scratch.cancel("runD00000004")["result"] == "cancel_requested"
    assert proc.wait(60) == 0
    saved = on_disk("runD00000004")
    assert "cancel_kill" not in [e["type"] for e in events_of(saved)] and run_log.decision(saved) == "commit"
    assert saved["status"] == "ok" and saved["cancel"]["outcome"] == "imported_before_cancel" and [s["name"] for s in saved["steps"]] == ["discovery"]
    assert ledger()["generation"] == 3 and "cancelled" not in ledger()["lastImport"] and counted_runs() == ["runA00000001", "runD00000004"]
    assert applied_runs() == ["runA00000001", "runD00000004"]
    assert json.loads((jobs / "discovered_jobs.json").read_text())["meta"]["ledgerGeneration"] == 3, "the view matches the ledger"
    assert lock_is_free() and leftover(repo) == []

    # E: the next run starts at once and runs to its end, scoring included, whatever was requested before.
    assert scratch.start("runE00000005").wait(60) == 0
    saved = on_disk("runE00000005")
    assert saved["status"] == "ok" and "cancel" not in saved and [s["status"] for s in saved["steps"]] == ["ok", "ok"]
    assert ledger()["generation"] == 4 and counted_runs()[-1] == "runE00000005" and applied_runs()[-1] == "runE00000005"
    assert view_lock_free(jobs) and lock_is_free()
