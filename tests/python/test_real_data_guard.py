"""The guard that fails a test run when real data changed (tests/python/real_data_guard.py)."""

from __future__ import annotations

import os
import time

import real_data_guard as guard


def _root(tmp_path):
    (tmp_path / "data/profile").mkdir(parents=True)
    (tmp_path / "data/applications/files").mkdir(parents=True)
    (tmp_path / "data/intelligence").mkdir(parents=True)
    (tmp_path / "data/jobs").mkdir(parents=True)
    (tmp_path / "data/profile/candidate-profile.json").write_text('{"a": 1}')
    (tmp_path / "data/applications/applications.json").write_text("{}")
    (tmp_path / "data/intelligence/candidate-intelligence.json").write_text("{}")
    (tmp_path / "data/jobs/manual_jobs.json").write_text("{}")
    return tmp_path


def test_a_run_that_touches_nothing_reports_no_change(tmp_path):
    root = _root(tmp_path)
    assert guard.changes(guard.fingerprint(root), guard.fingerprint(root)) == []


def test_emptied_rewritten_added_and_removed_files_are_each_reported(tmp_path):
    root = _root(tmp_path)
    before = guard.fingerprint(root)
    time.sleep(0.01)
    (root / "data/profile/candidate-profile.json").write_text("")  # the 2026-11-09 incident
    (root / "data/applications/files/new.pdf").write_text("x")
    (root / "data/intelligence/candidate-intelligence.json").unlink()
    (root / "data/jobs/manual_jobs.json").write_text("{}")  # same size, new mtime: still a write
    moved = guard.changes(before, guard.fingerprint(root))
    assert moved == [
        "added: data/applications/files/new.pdf",
        "changed: data/jobs/manual_jobs.json",
        "changed: data/profile/candidate-profile.json",
        "removed: data/intelligence/candidate-intelligence.json",
    ]


def test_files_the_pipeline_writes_are_not_guarded(tmp_path):
    root = _root(tmp_path)
    before = guard.fingerprint(root)
    (root / "data/jobs/scored_jobs.json").write_text("{}")
    (root / "data/cache").mkdir()
    (root / "data/cache/engine.json").write_text("{}")
    assert guard.changes(before, guard.fingerprint(root)) == []


def test_the_fingerprint_never_opens_a_file(tmp_path):
    root = _root(tmp_path)
    path = root / "data/profile/candidate-profile.json"
    os.chmod(path, 0o000)
    try:
        assert "data/profile/candidate-profile.json" in guard.fingerprint(root)  # stat works where open() would fail
    finally:
        os.chmod(path, 0o600)


def test_a_missing_data_folder_is_an_empty_fingerprint(tmp_path):
    assert guard.fingerprint(tmp_path) == {}
