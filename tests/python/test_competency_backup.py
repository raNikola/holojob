"""Backup, restore and the old-ids snapshot, on a fictional tree in tmp (never the live files)."""

import json
import subprocess

import pytest

from match_engine import competency_backup as cb
from requirement_frames import frame_key
from requirement_ids import provisional_id

JOB = {"jobId": "j1", "title": "Clown", "company": "Circus", "description": "Plays the kazoo.",
       "llmFacts": {"requirements": [{"id": "kazoo", "text": "Kazoo"}, {"id": provisional_id("Juggling"), "text": "Juggling"}]}}
BARE = {"jobId": "j2", "title": "Cook", "company": "Pot", "description": "Cooks."}


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "tree"
    contents = {
        "data/jobs/discovered_jobs.json": json.dumps({"jobs": [JOB, BARE]}),
        "data/jobs/job_history.json": "{}",
        "data/cache/requirement-frames.json": '{"k": []}',
        "data/cache/llm_fit.json": '{"fit": 1}',
        "data/profile/candidate-profile.json": '{"name": "Fictional"}',
        "data/profile/confirmed-facts.json": "[]",
    }
    for rel, text in contents.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    (root / ".gitignore").write_text("data/backups/\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.parts and "backups" not in p.parts}


def test_old_ids_maps_each_ad_and_text_to_its_id_and_counts_provisional():
    ids = cb.old_ids([JOB, BARE])
    assert ids["jobs"][frame_key(JOB)] == {"jobId": "j1", "requirements": {"Kazoo": "kazoo", "Juggling": provisional_id("Juggling")}}
    assert ids["counts"] == {"ads": 1, "requirements": 2, "provisional": 1}


def test_backup_copies_files_with_checksums_and_notes_the_absent_ones(tree):
    target = cb.backup(tree, "t1")
    assert target == tree / "data/backups/competency-2c3-t1"
    manifest = json.loads((target / "manifest.json").read_text())
    assert set(manifest["files"]) == {
        "data/jobs/discovered_jobs.json", "data/jobs/job_history.json", "data/cache/requirement-frames.json",
        "data/cache/llm_fit.json", "data/profile/candidate-profile.json", "data/profile/confirmed-facts.json"}
    assert "data/requirement-remap.json" in manifest["absent"] and "data/competency-aliases.json" in manifest["absent"]
    for rel, meta in manifest["files"].items():
        assert cb.sha256(target / rel) == cb.sha256(tree / rel) == meta["sha256"]
    assert json.loads((target / "old-ids.json").read_text())["counts"]["provisional"] == 1


def test_backup_refuses_a_target_git_does_not_ignore(tree):
    (tree / ".gitignore").write_text("")
    with pytest.raises(SystemExit, match="does not ignore"):
        cb.backup(tree, "t1")
    assert not (tree / "data/backups").exists()


def test_backup_refuses_to_overwrite(tree):
    cb.backup(tree, "t1")
    with pytest.raises(SystemExit, match="already exists"):
        cb.backup(tree, "t1")


def test_restore_puts_every_file_back_and_removes_what_the_run_created(tree):
    before = snapshot(tree)
    target = cb.backup(tree, "t1")
    (tree / "data/jobs/discovered_jobs.json").write_text("changed")
    (tree / "data/cache/requirement-frames.json").unlink()
    (tree / "data/profile/candidate-profile.json").write_text("{}")
    (tree / "data/requirement-remap.json").write_text('{"prov:1": "x"}')
    (tree / "data/competency-aliases.json").write_text("{}")
    assert snapshot(tree) != before
    restored = cb.restore(target, tree)
    assert "data/jobs/discovered_jobs.json" in restored
    assert snapshot(tree) == before


def test_restore_refuses_a_damaged_backup_and_changes_nothing(tree):
    target = cb.backup(tree, "t1")
    (tree / "data/jobs/discovered_jobs.json").write_text("changed")
    (target / "data/cache/llm_fit.json").write_text("tampered")
    after = snapshot(tree)
    with pytest.raises(SystemExit, match="damaged"):
        cb.restore(target, tree)
    assert snapshot(tree) == after


def test_the_cli_restores_to_the_given_root_only(tree, capsys):
    target = cb.backup(tree, "t1")
    (tree / "data/profile/confirmed-facts.json").write_text("[1]")
    live = cb.ROOT / "data/profile/confirmed-facts.json"
    live_before = live.read_bytes() if live.exists() else None
    assert cb.main(["restore", str(target), "--root", str(tree)]) == 0
    assert (tree / "data/profile/confirmed-facts.json").read_text() == "[]"
    assert (live.read_bytes() if live.exists() else None) == live_before
    assert "restored 6 files" in capsys.readouterr().out
