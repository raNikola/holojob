"""Package runner rules that would hurt if broken: a package counted done without proof, a --through run that does not
stop, private or secret files copied into a session's clone, a must-keep file carrying more than ids and verdicts.
Temp directories only; never data/."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("run_package", Path(__file__).resolve().parents[2] / "scripts/run_package.py")
rp = importlib.util.module_from_spec(SPEC)
sys.modules["run_package"] = rp
SPEC.loader.exec_module(rp)


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@example.invalid")
    (r / "a.txt").write_text("a")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "base")
    return r


ROW = rp.Row(1, "archive-history", "claude-sonnet-5-5", [], 1, 400, "pending", "-")


def _package_commit(repo, status_line="Status: done"):
    _git(repo, "switch", "-q", "-c", ROW.branch)
    report = repo / ROW.report
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(status_line + "\n\n# report\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "package")
    return _git(repo, "rev-parse", "HEAD")


def _state(sha, gate_sha=None, result="pass", status="done"):
    return {"status": status, "sha": sha, "gate": {"sha": gate_sha or sha, "result": result}}


def test_done_only_with_commit_report_and_gate_on_that_commit(repo):
    sha = _package_commit(repo)
    assert rp.verify_done(repo, ROW, _state(sha)) == (True, "verified")
    assert not rp.verify_done(repo, ROW, _state(sha, result="fail"))[0]
    assert not rp.verify_done(repo, ROW, _state(sha, gate_sha="0" * 40))[0]
    assert not rp.verify_done(repo, ROW, _state(sha, status="needs-review"))[0]
    assert not rp.verify_done(repo, ROW, _state("1" * 40))[0]  # commit does not exist
    assert not rp.verify_done(repo, ROW, {})[0]                 # plan file alone is never trusted


def test_not_done_when_report_missing_or_not_done_in_that_commit(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "branch", ROW.branch, base)
    assert not rp.verify_done(repo, ROW, _state(base))[0]       # commit on the branch, report absent
    _git(repo, "branch", "-D", ROW.branch)
    sha = _package_commit(repo, "Status: blocked")
    assert not rp.verify_done(repo, ROW, _state(sha))[0]


def test_not_done_when_commit_is_off_the_branch(repo):
    _package_commit(repo)
    _git(repo, "switch", "-q", "main")
    (repo / "b.txt").write_text("b")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "elsewhere")
    other = _git(repo, "rev-parse", "HEAD")
    assert not rp.verify_done(repo, ROW, _state(other))[0]


def test_through_stops_at_first_package_not_done_and_skips_done():
    rows = [rp.Row(n, f"p{n}", "m", [], o, 1, "pending", "-") for n, o in ((1, 1), (2, 2), (3, 3), (5, 4))]
    ran = []

    def run_one(row):
        ran.append(row.n)
        return "blocked" if row.n == 3 else "done"

    assert rp.run_through(rows, 5, lambda r: r.n == 1, run_one) == 1
    assert ran == [2, 3]
    ran.clear()
    assert rp.run_through(rows, 2, lambda r: False, run_one) == 0
    assert ran == [1, 2]


@pytest.mark.parametrize("rel,secret", [
    ("data/secrets/ai.json", True), ("claude-config/x.json", True), (".env", True), ("data/.env.local", True),
    ("data/config/api_key.json", True), ("data/outreach/linkedin_session.json", True), ("data/x/cert.pem", True),
    ("data/jobs/discovered_jobs.json", False), ("data/ai/settings.json", False), ("../etc/passwd", True),
])
def test_secret_path_port_matches_secret_paths_js(rel, secret):
    assert rp.is_secret_path(rel) is secret


def test_data_split_copies_only_allowlisted_ad_data(tmp_path):
    data = tmp_path / "data"
    files = ["jobs/discovered_jobs.json", "jobs/job_history.json", "jobs/manual_jobs.json", "jobs/staging/a.json",
             "jobs/staging/session.json", "profile/profile.json", "applications/x.json", "calibration/l.json",
             "secrets/k.json", "config/sources.json", "config/api_key.json", "cache/engine.json", "cache/fit3.json",
             "intelligence/candidate-intelligence.json", "engine-snapshot.json", "new-folder/unknown.json"]
    for f in files:
        (data / f).parent.mkdir(parents=True, exist_ok=True)
        (data / f).write_text("{}")
    split = rp.classify(data)
    assert set(split.copy) == {"jobs/discovered_jobs.json", "jobs/job_history.json", "jobs/staging/a.json",
                               "config/sources.json", "cache/engine.json"}
    assert set(split.copy) | set(split.private) == set(files)
    for root in ("profile", "applications", "calibration", "secrets", "intelligence", "new-folder",
                 "jobs/manual_jobs.json", "cache/fit3.json", "config/api_key.json"):
        assert root in split.private_roots
    for p in split.private:
        assert any(p == r or p.startswith(r + "/") for r in split.private_roots)
    assert not any(c == r or c.startswith(r + "/") for c in split.copy for r in split.private_roots)
    dst = tmp_path / "clone-data"
    rp.copy_data(data, dst, split)
    copied = {p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()}
    assert copied == set(split.copy)


def test_labelled_file_holds_ids_and_verdicts_only(tmp_path):
    md = tmp_path / "ratings.md"
    md.write_text("|rank|verdict|id|company / title|primary driver|reason|\n|---|---|---|---|---|---|\n"
                  "|1|apply|aaaaaaaaaaaaaaaa|Acme / PM|FIT|secret reason|\n"
                  "|2|skip|bbbbbbbbbbbbbbbb|Beta / Eng|ELIG|other reason|\n")
    ledger = tmp_path / "job_history.json"
    ledger.write_text(json.dumps({"jobs": {"aaaaaaaaaaaaaaaa": {"job": {"description": "text", "company": "Acme"}},
                                           "bbbbbbbbbbbbbbbb": {"job": {"description": " "}}}}))
    out = tmp_path / "derived/labelled-ads.json"
    doc = rp.build_labelled(md, ledger, out)
    assert doc["mustKeep"] == ["aaaaaaaaaaaaaaaa"]
    raw = out.read_text()
    for leaked in ("Acme", "PM", "secret reason", "FIT", "text"):
        assert leaked not in raw
    assert {k for a in doc["ads"] for k in a} == {"id", "verdict", "hasText", "inLedger"}
    assert out.stat().st_mode & 0o777 == 0o600


def test_report_status_line_is_strict():
    assert rp.report_status("Status: done\n# x") == "done"
    assert rp.report_status("Status: needs-review\n") == "needs-review"
    assert rp.report_status("# x\nStatus: done") == ""
    assert rp.report_status("Status: done, mostly") == ""
