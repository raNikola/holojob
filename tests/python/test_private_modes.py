"""New private files are 600 and new folders 700; an existing file or folder keeps its mode. All on tmp paths."""

import json
import os
import stat
import subprocess

import pytest

import ai_gate
import ai_selection
import confirmed_facts
from atomic_write import make_private_dirs, write_text_atomic
from conftest import fail_replacing
from match_engine import competency_backup as cb

FACT = {"competencyId": "sql", "has": True, "note": ""}


def mode_of(path):
    return stat.S_IMODE(path.stat().st_mode)


# --- the shared helper ---------------------------------------------------------------------------


def test_a_new_file_gets_the_mode_before_any_byte_is_written(tmp_path, monkeypatch):
    seen = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (seen.append(stat.S_IMODE(os.fstat(fd).st_mode)), real_fsync(fd))[1])
    target = tmp_path / "new.json"
    write_text_atomic(target, "x", new_file_mode=0o600)
    assert seen == [0o600]
    assert mode_of(target) == 0o600


@pytest.mark.parametrize("existing", [0o644, 0o640, 0o600, 0o400])
def test_an_existing_file_keeps_its_mode_whatever_is_asked(tmp_path, existing):
    target = tmp_path / "old.json"
    target.write_text("old")
    target.chmod(existing)
    write_text_atomic(target, "new", new_file_mode=0o600)
    assert mode_of(target) == existing
    assert target.read_text() == "new"


def test_without_a_mode_a_new_file_gets_the_process_default(tmp_path):
    write_text_atomic(tmp_path / "default.json", "x")
    (tmp_path / "plain.json").write_text("x")
    assert mode_of(tmp_path / "default.json") == mode_of(tmp_path / "plain.json")


def test_a_failed_rename_leaves_the_target_its_mode_and_no_temp_file(tmp_path, monkeypatch):
    target = tmp_path / "kept.json"
    target.write_text("old")
    target.chmod(0o640)
    temps = fail_replacing(monkeypatch, target)
    with pytest.raises(OSError):
        write_text_atomic(target, "new", new_file_mode=0o600)
    assert temps
    assert target.read_text() == "old"
    assert mode_of(target) == 0o640
    assert [p.name for p in tmp_path.iterdir()] == ["kept.json"]


def test_make_private_dirs_covers_every_new_level_and_leaves_an_existing_one(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    base.chmod(0o755)
    make_private_dirs(base / "a" / "b")
    make_private_dirs(base / "a" / "b")  # again: nothing to do
    assert mode_of(base) == 0o755
    assert mode_of(base / "a") == 0o700
    assert mode_of(base / "a" / "b") == 0o700


# --- ai_gate._atomic_write -----------------------------------------------------------------------


def test_new_budget_settings_are_600():
    assert ai_gate.save_settings({"dailyLimit": 0})["ok"]
    assert mode_of(ai_gate.settings_path()) == 0o600


def test_saving_budget_settings_keeps_the_mode_of_the_file():
    assert ai_gate.save_settings({"dailyLimit": 0})["ok"]
    ai_gate.settings_path().chmod(0o640)
    assert ai_gate.save_settings({"dailyLimit": 0, "currency": "USD"})["ok"]
    assert mode_of(ai_gate.settings_path()) == 0o640


def test_a_new_provider_selection_is_600():
    assert ai_selection.save({"provider": "ollama", "model": "m"})["ok"]
    assert mode_of(ai_selection.selection_path()) == 0o600


def test_saving_a_provider_selection_no_longer_loosens_a_tightened_file():
    assert ai_selection.save({"provider": "ollama", "model": "m"})["ok"]
    path = ai_selection.selection_path()
    path.chmod(0o600)
    assert ai_selection.save({"provider": "ollama", "model": "other"})["ok"]
    assert mode_of(path) == 0o600
    assert json.loads(path.read_text())["model"] == "other"
    path.chmod(0o644)  # an untightened file is not changed by a save either
    assert ai_selection.save({"provider": "ollama", "model": "third"})["ok"]
    assert mode_of(path) == 0o644


# --- confirmed facts -----------------------------------------------------------------------------


def test_new_confirmed_facts_are_600_in_new_700_folders(tmp_path):
    path = tmp_path / "data" / "profile" / "confirmed-facts.json"
    confirmed_facts.save([FACT], path)
    assert mode_of(path) == 0o600
    assert mode_of(path.parent) == 0o700
    assert mode_of(path.parent.parent) == 0o700
    assert confirmed_facts.load(path) == [FACT]


def test_saving_confirmed_facts_keeps_the_existing_file_and_folder_modes(tmp_path):
    folder = tmp_path / "profile"
    folder.mkdir()
    folder.chmod(0o755)
    path = folder / "confirmed-facts.json"
    path.write_text('{"version": 1, "facts": []}')
    path.chmod(0o644)
    confirmed_facts.save([FACT], path)
    assert mode_of(path) == 0o644
    assert mode_of(folder) == 0o755
    assert confirmed_facts.load(path) == [FACT]
    assert [p.name for p in folder.iterdir()] == ["confirmed-facts.json"]


# --- competency backup ---------------------------------------------------------------------------


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "tree"
    for rel, text in {"data/jobs/discovered_jobs.json": '{"jobs": []}', "data/profile/candidate-profile.json": "{}"}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
        (root / rel).chmod(0o644)
    (root / ".gitignore").write_text("data/backups/\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_everything_in_a_backup_is_private_whatever_the_source_modes(tree):
    target = cb.backup(tree, "t1")
    assert mode_of(tree / "data/backups") == 0o700
    entries = [target, *target.rglob("*")]
    assert any(p.name == "candidate-profile.json" for p in entries)
    for entry in entries:
        assert mode_of(entry) == (0o700 if entry.is_dir() else 0o600), entry
    assert mode_of(tree / "data/profile/candidate-profile.json") == 0o644  # the live file is not touched


def test_a_backup_leaves_an_existing_backups_folder_as_it_is(tree):
    (tree / "data/backups").mkdir()
    (tree / "data/backups").chmod(0o755)
    cb.backup(tree, "t1")
    assert mode_of(tree / "data/backups") == 0o755


def test_restore_gives_back_the_mode_recorded_at_backup_time(tree):
    live = tree / "data/profile/candidate-profile.json"
    live.chmod(0o640)
    target = cb.backup(tree, "t1")
    assert mode_of(target / "data/profile/candidate-profile.json") == 0o600
    live.chmod(0o644)
    cb.restore(target, tree)
    assert mode_of(live) == 0o640


def test_restore_of_a_backup_without_recorded_modes_uses_the_copy_mode(tree):
    target = cb.backup(tree, "t1")
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for meta in manifest["files"].values():
        del meta["mode"]
    manifest_path.write_text(json.dumps(manifest))
    cb.restore(target, tree)
    assert mode_of(tree / "data/profile/candidate-profile.json") == 0o600
