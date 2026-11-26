"""Package runner rules that would hurt if broken: a package counted done without its report, Status line, commit
and full-tier pass; a run that does not stop at the first package that is not done. Temp git repos only."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("run_packages", Path(__file__).resolve().parents[2] / "scripts/run_packages.py")
rp = importlib.util.module_from_spec(SPEC)
sys.modules["run_packages"] = rp
SPEC.loader.exec_module(rp)

ROW = rp.Row(1, "archive-history", "claude-sonnet-5-5", [], 1)


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


def _commit_report(repo, first_line):
    _git(repo, "switch", "-q", "-c", ROW.branch)
    report = repo / ROW.report
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(first_line + "\n\n# report\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "package")
    return _git(repo, "rev-parse", "HEAD")


def _gate_pass(repo, sha):
    _git(repo, "notes", f"--ref={rp.NOTES_REF}", "add", "-m", "full tier pass now", sha)


def test_done_needs_report_status_commit_and_gate(repo):
    assert rp.package_state(ROW, repo)[0] == "absent"
    sha = _commit_report(repo, "Status: done")
    assert rp.package_state(ROW, repo)[0] == "unfinished"      # no full-tier pass recorded
    _gate_pass(repo, sha)
    assert rp.package_state(ROW, repo)[0] == "done"


def test_gate_pass_on_an_older_commit_does_not_count(repo):
    sha = _commit_report(repo, "Status: done")
    _gate_pass(repo, sha)
    (repo / "b.txt").write_text("b")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "later change")
    assert rp.package_state(ROW, repo)[0] == "unfinished"


@pytest.mark.parametrize("line,state", [("Status: blocked", "blocked"), ("Status: needs-review", "needs-review"),
                                        ("# no status", "unfinished"), ("Status: done, mostly", "unfinished")])
def test_report_status_other_than_done_is_not_done(repo, line, state):
    sha = _commit_report(repo, line)
    _gate_pass(repo, sha)
    assert rp.package_state(ROW, repo)[0] == state


def test_branch_without_report_is_unfinished(repo):
    _git(repo, "branch", ROW.branch)
    assert rp.package_state(ROW, repo) == ("unfinished", f"{ROW.report} not in the branch tip")


def test_run_stops_at_first_not_done_and_skips_done():
    rows = [rp.Row(n, f"p{n}", "m", [], o) for n, o in ((1, 1), (2, 2), (3, 3), (5, 4))]
    ran = []

    def run_one(row):
        ran.append(row.n)
        return "blocked: x" if row.n == 3 else "done"

    assert rp.run_all(rows, lambda r: ("done", "") if r.n == 1 else ("absent", ""), run_one) == 1
    assert ran == [2, 3]


def test_through_and_single_selection_follow_plan_order():
    rows = [rp.Row(n, f"p{n}", "m", [], o) for n, o in ((1, 1), (2, 2), (3, 3), (5, 4), (4, 5))]
    assert [r.n for r in rp.select(rows, None, 5)] == [1, 2, 3, 5]
    assert [r.n for r in rp.select(rows, 4, None)] == [4]
    assert [r.n for r in rp.select(rows, None, None)] == [1, 2, 3, 5, 4]
