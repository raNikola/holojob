"""Tailoring never writes back the copy it read: it adds its assets to the scored file as that file stands at write time."""

import fcntl
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import pipeline_lock
import run_tailor

ROOT = Path(__file__).resolve().parents[2]
ASSETS = {"contentEngine": "rule", "resumeMd": "data/resumes/a/tailored_resume.md"}


def doc(*jobs, **meta):
    return {"meta": {"sourceRunId": "old", **meta}, "jobs": list(jobs)}


def job(job_id, score=50, **extra):
    return {"jobId": job_id, "title": "PM", "company": "Acme", "matchScore": score, **extra}


@pytest.fixture
def tailor(tmp_path, monkeypatch):
    """run_tailor.main() on temp files. `during`, when set, runs while the job is being tailored, as a run would."""
    folder = tmp_path / "scored"
    folder.mkdir()
    scored = folder / "scored_jobs.json"
    scored.write_text(json.dumps(doc(job("a"), job("b", tailoredAssets={"contentEngine": "earlier"}))))
    (tmp_path / "profile.json").write_text("{}")
    (tmp_path / "intel.json").write_text("{}")
    state = {"during": None}

    def tailor_job(job, *args, **kwargs):
        if state["during"]:
            state["during"](scored)
        return {**job, "matchScore": -1, "title": "stale copy", "tailoredAssets": dict(ASSETS)}

    monkeypatch.setattr(run_tailor, "tailor_job", tailor_job)
    monkeypatch.setattr("sys.argv", ["run_tailor.py", "--job-id", "a", "--no-llm", "--scored", str(scored),
                                     "--profile", str(tmp_path / "profile.json"), "--intelligence", str(tmp_path / "intel.json")])
    state["scored"] = scored
    return state


def read(path):
    return json.loads(path.read_text())


def test_scores_written_while_it_worked_survive_and_only_the_assets_are_added(tailor):
    newer = doc(job("a", 91, title="new title"), job("c", 70), sourceRunId="new")
    tailor["during"] = lambda scored: scored.write_text(json.dumps(newer))
    assert run_tailor.main() == 0
    after = read(tailor["scored"])
    assert after["meta"]["sourceRunId"] == "new"
    assert after["jobs"] == [job("a", 91, title="new title", tailoredAssets=ASSETS), job("c", 70)]


def test_a_row_the_run_removed_does_not_come_back(tailor, capsys):
    newer = doc(job("c", 70), sourceRunId="new")
    tailor["during"] = lambda scored: scored.write_text(json.dumps(newer))
    before = None

    def during(scored):
        nonlocal before
        scored.write_text(json.dumps(newer))
        before = scored.stat().st_mtime_ns

    tailor["during"] = during
    assert run_tailor.main() == 0
    assert read(tailor["scored"]) == newer
    assert tailor["scored"].stat().st_mtime_ns == before, "nothing to add, so nothing is written"
    assert "no longer in the job list" in capsys.readouterr().err


def test_other_rows_keep_what_they_had(tailor):
    assert run_tailor.main() == 0
    after = read(tailor["scored"])
    assert after["jobs"][1] == job("b", tailoredAssets={"contentEngine": "earlier"})
    assert after["jobs"][0]["matchScore"] == 50 and after["jobs"][0]["title"] == "PM"


def test_a_file_gone_by_write_time_is_a_failure_and_is_not_written_from_the_old_copy(tailor):
    tailor["during"] = lambda scored: scored.unlink()
    assert run_tailor.main() == 1
    assert not tailor["scored"].exists()


def test_the_lock_is_free_while_it_tailors_and_after_it_wrote(tailor):
    seen = []

    def during(scored):
        lock = pipeline_lock.acquire()
        seen.append(lock is not None)
        if lock:
            lock.release()

    tailor["during"] = during
    assert run_tailor.main() == 0
    assert seen == [True], "minutes of tailoring must not block a run"
    lock = pipeline_lock.acquire()
    assert lock is not None
    lock.release()


def test_it_waits_for_a_run_and_merges_into_what_the_run_wrote(tailor, capsys):
    fd = os.open(pipeline_lock.lock_path(), os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    result = {}
    worker = threading.Thread(target=lambda: result.update(code=run_tailor.main()))
    worker.start()
    worker.join(0.5)
    assert worker.is_alive(), "it must wait while a run holds the lock"
    assert "tailoredAssets" not in read(tailor["scored"])["jobs"][0]

    # What the run writes last is what the tailoring lands on.
    tailor["scored"].write_text(json.dumps(doc(job("a", 91), sourceRunId="new")))
    os.close(fd)
    worker.join(30)
    assert result["code"] == 0
    assert read(tailor["scored"]) == doc(job("a", 91, tailoredAssets=ASSETS), sourceRunId="new")
    assert "job run is in progress" in capsys.readouterr().out


def test_under_the_pipeline_it_uses_the_lock_it_was_handed_and_does_not_wait_for_its_own_parent(tmp_path):
    scored = tmp_path / "scored_jobs.json"
    scored.write_text(json.dumps(doc(job("a"))))
    code = (
        "import sys; [sys.path.insert(0, p) for p in sys.argv[2:]]; from pathlib import Path; import run_tailor; "
        f"sys.exit(run_tailor.save_tailored(Path(sys.argv[1]), {{'a': {ASSETS!r}}}))"
    )
    py = ROOT / "python"
    lock = pipeline_lock.acquire()
    done = subprocess.run(
        [sys.executable, "-c", code, str(scored), str(py / "job_scoring"), str(py / "resume_generator")],
        pass_fds=(lock.fd,), env=lock.child_env(), timeout=60, capture_output=True, text=True,
    )
    lock.release()
    assert done.returncode == 0, done.stderr[-500:]
    assert read(scored)["jobs"][0]["tailoredAssets"] == ASSETS
