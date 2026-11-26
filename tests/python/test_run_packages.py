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


def _rows():
    return [ROW, rp.Row(2, "free-measurements", "m", [], 2)]


def test_preflight_resumes_own_unfinished_branch_and_refuses_others(env):
    repo, base, reports = env
    _git(repo, "branch", ROW.branch)
    states = {1: ("unfinished", "")}
    state = lambda r: states.get(r.n, ("absent", ""))  # noqa: E731
    assert rp.preflight(_rows(), ROW, repo, state) == "resume"
    with pytest.raises(SystemExit):                      # package 2 must not start while 1 is unfinished
        rp.preflight(_rows(), _rows()[1], repo, state)
    states[1] = ("blocked", "")
    with pytest.raises(SystemExit):                      # blocked: the owner decides, no automatic resume
        rp.preflight(_rows(), ROW, repo, state)
    _git(repo, "branch", "-D", ROW.branch)
    assert rp.preflight(_rows(), ROW, repo, lambda r: ("absent", "")) == "new"
    (repo / "dirty.txt").write_text("x")
    with pytest.raises(SystemExit):
        rp.preflight(_rows(), ROW, repo, lambda r: ("absent", ""))


def test_resume_keeps_the_previous_report_and_work(env, tmp_path):
    repo, base, reports = env
    wt = tmp_path / "wt"
    (wt / "scripts").mkdir(parents=True)
    (wt / rp.TEMPLATE).write_text("Status: in-progress\n# template\n")
    (wt / "work.txt").write_text("uncommitted work")
    (reports / ROW.report_name).write_text("Status: in-progress\n# half written by the last session\n")
    staging = rp.prepare_report(ROW, True, reports, worktree=wt)
    assert "half written" in staging.read_text()
    assert not (reports / ROW.report_name).exists()      # moved back, continued, not duplicated
    assert (wt / "work.txt").read_text() == "uncommitted work"
    assert rp.prepare_report(ROW, True, reports, worktree=wt).read_text() == staging.read_text()  # interrupted twice


def test_new_run_starts_from_template_and_sets_an_old_report_aside(env, tmp_path):
    repo, base, reports = env
    wt = tmp_path / "wt"
    (wt / "scripts").mkdir(parents=True)
    (wt / rp.TEMPLATE).write_text("Status: in-progress\n# template\n")
    (reports / ROW.report_name).write_text("Status: done\n# stale\n")
    staging = rp.prepare_report(ROW, False, reports, worktree=wt)
    assert staging.read_text().startswith("Status: in-progress")
    assert not (reports / ROW.report_name).exists()
    assert len(list(reports.glob(ROW.report_name + ".old-*"))) == 1


def test_prompt_forbids_questions_and_names_the_helper():
    for resume in (False, True):
        text = rp.prompt_for(ROW, resume)
        assert text.startswith("do package 1 from docs/redesign/PACKAGES_PLAN.md")
        assert "Never ask the owner a question" in text and "Status: blocked" in text
        assert str(rp.HELPER) in text
        assert ("RESUMED RUN" in text) is resume
    assert f"Bash({rp.HELPER} *)" in rp.ALLOWED
    assert "Bash(podman *)" in rp.DISALLOWED


def test_installed_helper_is_the_runner_copy(tmp_path):
    src = tmp_path / "src"
    src.write_text("trusted")
    dest = rp.install_helper(src, tmp_path / "bin/node-sandbox")
    assert dest.read_text() == "trusted" and dest.stat().st_mode & 0o777 == 0o700


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
