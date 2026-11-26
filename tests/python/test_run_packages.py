"""Package runner rules that would hurt if broken: a package counted done without its report file saying
`Status: done`, a commit after the base, a clean worktree and a full-tier pass on the branch tip; a run that does not
stop at the first package that is not done. Temp git repos and temp report dirs only."""
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
def env(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@example.invalid")
    (r / "a.txt").write_text("a")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "base")
    base = _git(r, "rev-parse", "HEAD")
    reports = tmp_path / "reports"
    reports.mkdir()
    return r, base, reports


def _package_commit(repo):
    _git(repo, "switch", "-q", "-c", ROW.branch)
    (repo / "feature.txt").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "package")
    return _git(repo, "rev-parse", "HEAD")


def _report(reports, first_line):
    (reports / ROW.report_name).write_text(first_line + "\n\n# report\n")


def _gate_pass(repo, sha, base):
    _git(repo, "notes", f"--ref={rp.NOTES_REF}", "add", "-f", "-m", f"full tier pass base={base} now", sha)


def _state(repo, reports):
    return rp.package_state(ROW, repo, reports, worktree=repo)[0]


def test_done_needs_report_commit_clean_tree_and_gate(env):
    repo, base, reports = env
    assert _state(repo, reports) == "absent"
    sha = _package_commit(repo)
    assert _state(repo, reports) == "unfinished"          # no report file
    _report(reports, "Status: done")
    assert _state(repo, reports) == "unfinished"          # no full-tier pass
    _gate_pass(repo, sha, base)
    assert _state(repo, reports) == "done"
    (repo / "stray.txt").write_text("left over")
    assert _state(repo, reports) == "unfinished"          # worktree not clean


def test_no_commit_after_the_base_is_not_done(env):
    repo, base, reports = env
    _git(repo, "branch", ROW.branch)
    _report(reports, "Status: done")
    _gate_pass(repo, base, base)
    assert _state(repo, reports) == "unfinished"


def test_gate_pass_on_an_older_commit_does_not_count(env):
    repo, base, reports = env
    sha = _package_commit(repo)
    _report(reports, "Status: done")
    _gate_pass(repo, sha, base)
    (repo / "b.txt").write_text("b")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "later change")
    assert _state(repo, reports) == "unfinished"


def test_report_in_git_does_not_count(env):
    repo, base, reports = env
    sha = _package_commit(repo)
    (repo / "docs").mkdir()
    (repo / "docs" / ROW.report_name).write_text("Status: done\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "report committed")
    _gate_pass(repo, _git(repo, "rev-parse", "HEAD"), base)
    assert _state(repo, reports) == "unfinished"          # only the git-ignored report file counts


@pytest.mark.parametrize("line,state", [("Status: blocked", "blocked"), ("Status: needs-review", "needs-review"),
                                        ("Status: in-progress", "unfinished"), ("# no status", "unfinished"),
                                        ("Status: done, mostly", "unfinished")])
def test_report_status_other_than_done_is_not_done(env, line, state):
    repo, base, reports = env
    sha = _package_commit(repo)
    _report(reports, line)
    _gate_pass(repo, sha, base)
    assert _state(repo, reports) == state


def test_template_is_never_done_as_seeded():
    template = Path(__file__).resolve().parents[2] / rp.TEMPLATE
    assert rp.report_status(template.read_text()) != "done"


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
