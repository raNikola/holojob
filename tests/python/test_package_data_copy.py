"""Package data copy: private or secret files must never reach a package worktree, the must-keep file holds ids and
statuses only, and the copy never targets the production checkout. Temp directories only; never data/."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "package_data_copy", Path(__file__).resolve().parents[2] / "scripts/package_data_copy.py")
pdc = importlib.util.module_from_spec(SPEC)
sys.modules["package_data_copy"] = pdc
SPEC.loader.exec_module(pdc)


@pytest.mark.parametrize("rel,secret", [
    ("data/secrets/ai.json", True), ("claude-config/x.json", True), (".env", True), ("data/.env.local", True),
    ("data/config/api_key.json", True), ("data/outreach/linkedin_session.json", True), ("data/x/cert.pem", True),
    ("data/jobs/discovered_jobs.json", False), ("data/ai/settings.json", False), ("../etc/passwd", True),
])
def test_secret_path_port_matches_secret_paths_js(rel, secret):
    assert pdc.is_secret_path(rel) is secret


def _tree(root, files):
    for f in files:
        (root / f).parent.mkdir(parents=True, exist_ok=True)
        (root / f).write_text("{}")


def test_only_allowlisted_ad_data_is_copied(tmp_path):
    data = tmp_path / "data"
    files = ["jobs/discovered_jobs.json", "jobs/job_history.json", "jobs/manual_jobs.json", "jobs/staging/a.json",
             "jobs/staging/session.json", "profile/profile.json", "applications/applications.json", "calibration/l.json",
             "secrets/k.json", "config/sources.json", "config/api_key.json", "cache/engine.json", "cache/fit3.json",
             "intelligence/candidate-intelligence.json", "engine-snapshot.json", "new-folder/unknown.json",
             "profile/.gitkeep"]
    _tree(data, files)
    split = pdc.classify(data, {"profile/.gitkeep"})
    assert set(split.copy) == {"jobs/discovered_jobs.json", "jobs/job_history.json", "jobs/staging/a.json",
                               "config/sources.json", "cache/engine.json"}
    assert split.tracked == ["profile/.gitkeep"]
    assert set(split.copy) | set(split.private) | set(split.tracked) == set(files)
    dst = tmp_path / "dest-data"
    pdc.copy_data(data, dst, split)
    copied = {p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()}
    assert copied == set(split.copy)
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in dst.rglob("*") if p.is_file())


def test_must_keep_holds_ids_and_statuses_only(tmp_path):
    state = tmp_path / "job-state.json"
    state.write_text(json.dumps({"version": 1, "jobs": {
        "a": {"jobId": "aaaa", "status": "saved", "keep": False, "statusAt": "2026-11-01", "note": "private note"},
        "b": {"jobId": "bbbb", "status": "rejected"},
        "c": {"jobId": "cccc", "status": "new", "keep": True},
        "d": {"jobId": "dddd", "status": "saved"}}}))
    out = tmp_path / "derived/must-keep.json"
    doc = pdc.build_must_keep(state, {"dddd", "eeee"}, out)
    assert doc["ads"] == [{"id": "aaaa", "status": "saved"}, {"id": "bbbb", "status": "rejected"},
                          {"id": "dddd", "status": "applied"}, {"id": "eeee", "status": "applied"}]
    assert doc["count"] == 4 and doc["expected"] == 19
    assert "private note" not in out.read_text() and "2026-11-01" not in out.read_text()
    assert out.stat().st_mode & 0o777 == 0o600


def test_export_header_lines_are_not_ids(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("# jobid-less-applications 2\n# ledger-sha256 abc\naaaa\n\nbbbb\n")
    assert pdc.read_id_lines(f) == {"aaaa", "bbbb"}


def test_refuses_the_production_checkout_and_a_used_data_dir(tmp_path):
    source = tmp_path / "holojob"
    (source / "data").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    with pytest.raises(SystemExit):
        pdc.check_dest(source, source, set())
    with pytest.raises(SystemExit):
        pdc.check_dest(source, source / "data" / "x", set())
    wt = tmp_path / "wt"
    (wt / "data").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(wt)], check=True)
    assert pdc.check_dest(source, wt, set()) == wt.resolve()
    (wt / "data" / "left.json").write_text("{}")
    with pytest.raises(SystemExit):
        pdc.check_dest(source, wt, set())
