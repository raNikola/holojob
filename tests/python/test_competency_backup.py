"""Backup, restore and the old-ids snapshot, on a fictional tree in tmp (never the live files)."""

import json
import os
import stat
import subprocess

import pytest

import pipeline_lock

from conftest import fail_replacing
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
            if p.is_file() and ".git" not in p.parts and "backups" not in p.parts and p.name != ".pipeline.lock"}


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


def test_a_failed_restore_keeps_the_live_file_and_the_backup_and_leaves_no_temp_file(tree, monkeypatch):
    target = cb.backup(tree, "t1")
    live = tree / "data/jobs/discovered_jobs.json"
    live.write_text("changed")
    backup_before = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}
    temps = fail_replacing(monkeypatch, live)

    with pytest.raises(OSError, match="disk full"):
        cb.restore(target, tree)

    assert temps and temps[0].endswith(".tmp")
    assert live.read_text() == "changed"
    assert [p.name for p in live.parent.iterdir() if p.name.endswith(".tmp")] == []
    assert {p: p.read_bytes() for p in target.rglob("*") if p.is_file()} == backup_before
    assert cb.verify(target)


def test_restore_gives_back_the_exact_bytes_mode_and_time_of_the_backup(tree):
    live = tree / "data/profile/confirmed-facts.json"  # not the jobs file: backup() parses that one
    raw = b'{"jobs": []}\r\n\xff not utf-8'
    live.write_bytes(raw)
    live.chmod(0o640)
    os.utime(live, (1_000_000_000, 1_000_000_000))
    target = cb.backup(tree, "t1")
    live.write_text("changed")
    live.chmod(0o600)

    cb.restore(target, tree)

    assert live.read_bytes() == raw
    assert stat.S_IMODE(live.stat().st_mode) == 0o640
    assert live.stat().st_mtime == 1_000_000_000


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


def test_restore_refuses_while_a_run_holds_the_pipeline_lock_and_works_after(tree):
    target = cb.backup(tree, "t1")
    live = tree / "data/profile/confirmed-facts.json"
    live.write_text("[1]")
    held = pipeline_lock.acquire(path=tree / "data/jobs/.pipeline.lock")
    assert held is not None
    try:
        with pytest.raises(SystemExit, match="nothing restored"):
            cb.restore(target, tree)
        assert live.read_text() == "[1]"
    finally:
        held.release()
    cb.restore(target, tree)
    assert live.read_text() == "[]"
    again = pipeline_lock.acquire(path=tree / "data/jobs/.pipeline.lock")  # restore let go of the lock
    assert again is not None
    again.release()
