"""scored_jobs.json is replaced whole: a failed write keeps the previous file and leaves no temp file."""

import json
import os
import stat
import sys

import pytest

import run_scoring
from match_engine import shadow


@pytest.fixture
def run(tmp_path, monkeypatch):
    """run_scoring.main() on temp files only; the output has a directory of its own, so stray files show."""
    (tmp_path / "intel.json").write_text(json.dumps({"jobFitPreferences": {}, "roleFamily": "product"}))
    (tmp_path / "jobs.json").write_text(json.dumps({"jobs": [{
        "jobId": "a", "title": "Product Manager", "company": "Acme", "location": "Niš, Serbia",
        "description": "Own the roadmap.", "jobUrl": "https://jobs.example/a", "provider": "jobspy", "status": "new",
    }]}))
    (tmp_path / "profile.json").write_text(json.dumps({}))
    (tmp_path / "out").mkdir()
    monkeypatch.setattr(run_scoring, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "llm_fit.json")
    monkeypatch.setattr(shadow, "CACHE_PATH", tmp_path / "engine.json")
    monkeypatch.setattr("confirmed_facts.load", lambda *a, **k: [])
    monkeypatch.setattr(shadow, "load_remap", lambda: {})
    monkeypatch.setattr(sys, "argv", [
        "run_scoring.py", "--intelligence", str(tmp_path / "intel.json"), "--jobs", str(tmp_path / "jobs.json"),
        "--manual", str(tmp_path / "manual.json"), "--output", str(tmp_path / "out" / "scored_jobs.json"),
    ])
    return run_scoring.main


@pytest.fixture
def output(tmp_path):
    return tmp_path / "out" / "scored_jobs.json"


@pytest.mark.parametrize("failing_call", ["fsync", "replace"])
def test_a_failed_write_keeps_the_previous_file_and_leaves_no_temp_file(run, output, monkeypatch, failing_call):
    output.write_text('{"previous": true}', encoding="utf-8")
    on_disk_at_failure = []

    def fail(*_args, **_kwargs):
        on_disk_at_failure.extend(p.name for p in output.parent.iterdir())
        raise OSError("disk full")

    monkeypatch.setattr(os, failing_call, fail)
    with pytest.raises(OSError, match="disk full"):
        run()

    assert any(name.endswith(".tmp") for name in on_disk_at_failure)  # it failed with the temp file there
    assert output.read_text(encoding="utf-8") == '{"previous": true}'
    assert [p.name for p in output.parent.iterdir()] == ["scored_jobs.json"]


def test_a_successful_write_replaces_the_file_and_keeps_its_mode_and_encoding(run, output):
    output.write_text('{"previous": true}', encoding="utf-8")
    output.chmod(0o640)

    assert run() == 0

    assert stat.S_IMODE(output.stat().st_mode) == 0o640
    assert [p.name for p in output.parent.iterdir()] == ["scored_jobs.json"]
    text = output.read_bytes().decode("utf-8")
    doc = json.loads(text)
    assert [j["jobId"] for j in doc["jobs"]] == ["a"]
    assert text == json.dumps(doc, indent=2)  # same bytes as before: no trailing newline, non-ASCII escaped


def test_a_new_file_gets_the_umask_default_as_before(run, output):
    old = os.umask(0o027)
    try:
        assert run() == 0
    finally:
        os.umask(old)
    assert stat.S_IMODE(output.stat().st_mode) == 0o640
