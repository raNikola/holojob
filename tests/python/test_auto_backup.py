"""Automatic backup of the four owner files before a write that changes them (owner decision 2026-11-23): the Python twin of
scripts/auto-backup.js. Synthetic data, temp folders only (a file outside the data folder is never backed up)."""

import hashlib
import json
import os
import stat
import sys
from datetime import datetime, timezone

import pytest

import auto_backup
import profile_enrichment
import run_scoring
from match_engine import shadow


@pytest.fixture
def data(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(auto_backup, "DATA_ROOT", root)
    return root


def put(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def versions(root, name):
    directory = root / "backups" / "auto" / name
    return sorted(os.listdir(directory)) if directory.exists() else []


def at(second):
    return datetime(2026, 11, 23, 10, 0, second, tzinfo=timezone.utc)


def test_the_old_content_is_kept_before_a_changing_write_with_private_modes(data):
    path = put(data, "jobs/scored_jobs.json", '{"v":1}')
    backup = auto_backup.backup_before_write(path, '{"v":2}', now=at(1))
    assert backup.name == "20261123-100001.json"
    assert backup.read_text() == '{"v":1}'
    assert hashlib.sha256(backup.read_bytes()).digest() == hashlib.sha256(b'{"v":1}').digest()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE((data / "backups" / "auto").stat().st_mode) == 0o700


def test_nothing_for_identical_content_a_new_file_another_name_or_a_file_outside_the_data_folder(data, tmp_path):
    path = put(data, "profile-enrichment.json", "same")
    assert auto_backup.backup_before_write(path, "same") is None
    assert auto_backup.backup_before_write(data / "jobs" / "scored_jobs.json", "first write") is None
    other = put(data, "jobs/discovered_jobs.json", "{}")
    assert auto_backup.backup_before_write(other, "changed") is None
    outside = tmp_path / "scratch" / "scored_jobs.json"
    outside.parent.mkdir()
    outside.write_text("{}")
    assert auto_backup.backup_before_write(outside, "changed") is None
    assert not (data / "backups").exists()


def test_the_profile_is_unchanged_when_only_its_save_stamp_differs(data):
    old = json.dumps({"basicProfile": {"a": 1}, "meta": {"updatedAt": "2026-11-22T10:00:00Z"}}, indent=2)
    path = put(data, "profile/candidate-profile.json", old)
    same = json.dumps({"basicProfile": {"a": 1}, "meta": {"updatedAt": "2026-11-23T10:00:00Z"}}, indent=2)
    changed = json.dumps({"basicProfile": {"a": 2}, "meta": {"updatedAt": "2026-11-23T10:00:00Z"}}, indent=2)
    assert auto_backup.backup_before_write(path, same) is None
    assert auto_backup.backup_before_write(path, changed, now=at(2)) is not None


@pytest.mark.parametrize("name, rel, rewrites, kept", [
    ("candidate-intelligence.json", "intelligence/candidate-intelligence.json", 14, 10),
    ("scored_jobs.json", "jobs/scored_jobs.json", 6, 3),
])
def test_only_the_newest_versions_are_kept(data, name, rel, rewrites, kept):
    path = put(data, rel, "v0")
    for i in range(1, rewrites + 1):
        auto_backup.backup_before_write(path, f"v{i}", now=at(i))
        path.write_text(f"v{i}")
    names = versions(data, name)
    assert len(names) == kept
    newest = data / "backups" / "auto" / name / names[-1]
    assert newest.read_text() == f"v{rewrites - 1}"


def test_a_backup_that_cannot_be_written_stops_the_write_and_keeps_the_file(data):
    path = put(data, "jobs/scored_jobs.json", "old")
    (data / "backups").write_text("a file where the folder should be")
    with pytest.raises(auto_backup.BackupError, match="nothing was changed"):
        auto_backup.write_text_with_backup(path, "new")
    assert path.read_text() == "old"


def test_the_enrichment_save_backs_up_the_previous_file(data):
    path = data / "profile-enrichment.json"
    profile_enrichment.save({"domains": [{"id": "d1", "source": "CV", "title": "t", "text": "one"}]}, path)
    assert versions(data, "profile-enrichment.json") == []  # a first write has nothing to keep
    profile_enrichment.save({"domains": [{"id": "d1", "source": "CV", "title": "t", "text": "two"}]}, path)
    (kept,) = versions(data, "profile-enrichment.json")
    assert "one" in (data / "backups" / "auto" / "profile-enrichment.json" / kept).read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_rescore_keeps_the_previous_scored_file(tmp_path, data, monkeypatch):
    (tmp_path / "intel.json").write_text(json.dumps({"jobFitPreferences": {}, "roleFamily": "product"}))
    (tmp_path / "jobs.json").write_text(json.dumps({"jobs": [{
        "jobId": "a", "title": "Product Manager", "company": "Acme", "location": "Niš, Serbia",
        "description": "Own the roadmap.", "jobUrl": "https://jobs.example/a", "provider": "jobspy", "status": "new",
    }]}))
    (tmp_path / "profile.json").write_text(json.dumps({}))
    out = put(data, "jobs/scored_jobs.json", '{"previous": true}')
    monkeypatch.setattr(run_scoring, "PROFILE_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "llm_fit.json")
    monkeypatch.setattr(shadow, "CACHE_PATH", tmp_path / "engine.json")
    monkeypatch.setattr("confirmed_facts.load", lambda *a, **k: [])
    monkeypatch.setattr(shadow, "load_remap", lambda: {})
    monkeypatch.setattr(sys, "argv", ["run_scoring.py", "--intelligence", str(tmp_path / "intel.json"), "--jobs", str(tmp_path / "jobs.json"),
                                      "--manual", str(tmp_path / "manual.json"), "--output", str(out)])
    assert run_scoring.main() == 0
    assert [j["jobId"] for j in json.loads(out.read_text())["jobs"]] == ["a"]
    (kept,) = versions(data, "scored_jobs.json")
    assert (data / "backups" / "auto" / "scored_jobs.json" / kept).read_text() == '{"previous": true}'
