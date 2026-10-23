"""The orchestrator stops at the first failed step and reports what ran."""

import fcntl
import json
from datetime import datetime, timezone

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))
import run_pipeline as rp  # noqa: E402


def _now():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def env(tmp_path, monkeypatch):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(rp, "INTELLIGENCE", tmp_path / "intel.json")
    monkeypatch.setattr(rp, "DISCOVERED", jobs / "discovered_jobs.json")
    monkeypatch.setattr(rp, "SCORED", jobs / "scored_jobs.json")
    monkeypatch.setattr(rp, "LAST_RUN", jobs / "pipeline_last_run.json")
    monkeypatch.setattr(rp, "LOCK", jobs / ".pipeline.lock")
    rp.INTELLIGENCE.write_text("{}")
    return tmp_path


def fake_steps(monkeypatch, *, enriched=10, total=10, fail=None, deduped=10, calls=None):
    """Replace run_step: each step writes the file the real one would."""
    calls = calls if calls is not None else []

    def run_step(name, cmd, steps):
        calls.append(name)
        steps.append({"step": name, "seconds": 0.1, "exitCode": 1 if name == fail else 0})
        if name == fail:
            raise rp.StepFailed(name, "exited with code 1: boom")
        if name == "discovery":
            jobs = [{"jobId": str(i), "title": "PM"} for i in range(total)]
            rp.DISCOVERED.write_text(json.dumps({
                "meta": {"generatedAt": _now(), "dedupedCount": deduped, "rawCount": deduped * 2,
                         "providerCounts": {"jobspy": deduped}, "history": {"new": 3, "known": 7, "closed": 0}},
                "jobs": jobs,
            }))
        if name == "enrichment":
            payload = json.loads(rp.DISCOVERED.read_text())
            for job in payload["jobs"][:enriched]:
                job["llmFacts"] = {"_fingerprint": "x"}
            rp.DISCOVERED.write_text(json.dumps(payload))
            return f"extracted {enriched}, cached 0 (0 from the ledger), failed {total - enriched}\n"
        if name == "scoring":
            rp.SCORED.write_text(json.dumps({
                "meta": {"summary": {"strong": 2}},
                "jobs": [{"matchScore": s, "priority": "P1" if s >= 70 else "P3",
                          "workAuthorization": {"status": "authorized"}, "hardCapped": s < 40}
                         for s in (90, 75, 60, 45, 10)],
            }))
        return ""

    monkeypatch.setattr(rp, "run_step", run_step)
    return calls


def test_a_clean_run_runs_every_step_and_summarises(env, monkeypatch, capsys):
    calls = fake_steps(monkeypatch)
    assert rp.main(["--json"]) == 0
    assert calls == ["discovery", "enrichment", "scoring"]

    record = json.loads(rp.LAST_RUN.read_text())
    assert record["status"] == "ok"
    assert record["discovery"]["providerCounts"] == {"jobspy": 10}
    assert record["enrichment"]["enrichedShare"] == 1.0
    assert record["scoring"]["scoreBands"] == {"85-100": 1, "70-84": 1, "55-69": 1, "40-54": 1, "0-39": 1}
    assert record["scoring"]["hardCapped"] == 1 and record["scoring"]["applyNow"] == 2
    assert "=== Summary ===" in capsys.readouterr().out


@pytest.mark.parametrize("failing, ran", [
    ("discovery", ["discovery"]),
    ("enrichment", ["discovery", "enrichment"]),
    ("scoring", ["discovery", "enrichment", "scoring"]),
])
def test_a_failed_step_stops_the_run_and_names_it(env, monkeypatch, capsys, failing, ran):
    calls = fake_steps(monkeypatch, fail=failing)
    assert rp.main([]) == rp.EXIT_FAILED
    assert calls == ran
    record = json.loads(rp.LAST_RUN.read_text())
    assert record["status"] == "failed" and record["failedStep"] == failing
    assert f"PIPELINE STOPPED at {failing}" in capsys.readouterr().err


def test_too_few_enriched_jobs_stops_before_scoring(env, monkeypatch, capsys):
    calls = fake_steps(monkeypatch, enriched=5, total=10)
    assert rp.main([]) == rp.EXIT_FAILED
    assert "scoring" not in calls
    assert "only 50% of jobs have facts" in capsys.readouterr().err


def test_min_enriched_can_be_relaxed(env, monkeypatch):
    calls = fake_steps(monkeypatch, enriched=5, total=10)
    assert rp.main(["--min-enriched", "0.4"]) == 0
    assert "scoring" in calls


def test_discovery_that_finds_nothing_does_not_score_stale_results(env, monkeypatch, capsys):
    calls = fake_steps(monkeypatch, deduped=0, total=0)
    assert rp.main([]) == rp.EXIT_FAILED
    assert calls == ["discovery"]
    assert "no provider returned a job" in capsys.readouterr().err


def test_a_stale_jobs_file_is_not_taken_for_a_fresh_run(env, monkeypatch):
    rp.DISCOVERED.write_text(json.dumps({"meta": {"generatedAt": "2020-01-01T00:00:00+00:00", "dedupedCount": 5}, "jobs": []}))
    monkeypatch.setattr(rp, "run_step", lambda name, cmd, steps: steps.append({"step": name, "seconds": 0, "exitCode": 0}) or "")
    assert rp.main([]) == rp.EXIT_FAILED
    assert json.loads(rp.LAST_RUN.read_text())["reason"] == "the jobs file was not refreshed by this run"


def test_missing_intelligence_is_a_setup_error_and_runs_nothing(env, monkeypatch):
    rp.INTELLIGENCE.unlink()
    calls = fake_steps(monkeypatch)
    assert rp.main([]) == rp.EXIT_SETUP
    assert calls == []


def test_a_second_run_while_one_is_active_is_refused(env, monkeypatch):
    calls = fake_steps(monkeypatch)
    with open(rp.LOCK, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert rp.main([]) == rp.EXIT_LOCKED
    assert calls == []


def test_the_pipeline_never_judges(env, monkeypatch):
    commands = []
    inner = fake_steps(monkeypatch)
    real = rp.run_step
    monkeypatch.setattr(rp, "run_step", lambda name, cmd, steps: commands.append(cmd) or real(name, cmd, steps))
    assert rp.main(["--tailor"]) == 0
    assert commands and not any("--judge" in part for cmd in commands for part in cmd)
    assert inner == ["discovery", "enrichment", "scoring", "tailoring"]


def test_unwritable_data_dir_is_a_setup_error_before_anything_runs(env, monkeypatch, capsys):
    calls = fake_steps(monkeypatch)
    real_write = rp.Path.write_text

    def deny(self, *a, **k):
        if self.name == ".write-probe":
            raise PermissionError(13, "Permission denied", str(self))
        return real_write(self, *a, **k)

    monkeypatch.setattr(rp.Path, "write_text", deny)
    assert rp.main([]) == rp.EXIT_SETUP
    assert calls == []
    assert "Nothing started" in capsys.readouterr().err
