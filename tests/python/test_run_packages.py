"""Package runner rules that would hurt if broken: a package counted done without its report file saying
`Status: done`, a recorded full-tier pass on a tip that is on the one branch, at least one commit since the previous
package's recorded tip and a clean worktree; a regate that records a red tier or the wrong base; a run that does not
stop at the first package that is not done. Temp git repos, temp state and report files only."""
import importlib.util
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("run_packages", Path(__file__).resolve().parents[2] / "scripts/run_packages.py")
rp = importlib.util.module_from_spec(SPEC)
sys.modules["run_packages"] = rp
SPEC.loader.exec_module(rp)

ROW = rp.Row(1, "archive-history", "claude-sonnet-5-5", [], 1)
ROW2 = rp.Row(2, "free-measurements", "m", [], 2)


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def env(tmp_path):
    """A repo on main with the run branch checked out (the repo is its own run worktree), empty reports and state."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@example.invalid")
    (r / "a.txt").write_text("a")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "base")
    base = _git(r, "rev-parse", "HEAD")
    _git(r, "switch", "-q", "-c", rp.BRANCH)
    reports = tmp_path / "reports"
    reports.mkdir()
    return r, base, reports, tmp_path / "state.json"


def _commit(repo, name="feature.txt"):
    (repo / name).write_text(name)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def _report(reports, first_line, row=ROW):
    (reports / row.report_name).write_text(first_line + "\n\n# report\n")


def _state(repo, reports, st, row=ROW):
    return rp.package_state(row, repo, reports, worktree=repo, st=st)[0]


def _recorded(tip, base, row=ROW):
    st = rp.load_state(Path("/nonexistent/state.json"))
    rp.record_pass(st, row, tip, base)
    return st


def _regate(repo, state_path, row=ROW, ok=True, ran=None):
    def fake_gate(sha, log, worktree):
        if ran is not None:
            ran.append(sha)
        return ok
    return rp.regate(row, "main", repo=repo, worktree=repo, state_path=state_path, logdir=state_path.parent,
                     gate_fn=fake_gate)


def test_done_needs_report_pass_commit_and_clean_tree(env):
    repo, base, reports, _ = env
    st = rp.load_state(Path("/nonexistent/state.json"))
    assert _state(repo, reports, st) == "absent"
    tip = _commit(repo)
    _report(reports, "Status: done")
    assert _state(repo, reports, st) == "unfinished"          # no full-tier pass recorded
    st = _recorded(tip, base)
    assert _state(repo, reports, st) == "done"
    (repo / "stray.txt").write_text("left over")
    assert _state(repo, reports, st) == "unfinished"          # worktree not clean while its tip is the head


def test_no_commit_since_the_previous_tip_is_not_done(env):
    repo, base, reports, _ = env
    _report(reports, "Status: done")
    assert _state(repo, reports, _recorded(base, base)) == "unfinished"


def test_recorded_tip_off_the_branch_is_not_done(env):
    repo, base, reports, _ = env
    tip = _commit(repo)
    _report(reports, "Status: done")
    st = _recorded(tip, base)
    _git(repo, "reset", "-q", "--hard", base)                  # branch rewritten: the recorded tip is gone from it
    _commit(repo, "other.txt")
    assert _state(repo, reports, st) == "unfinished"


def test_a_later_package_does_not_undo_an_earlier_one(env):
    repo, base, reports, _ = env
    tip1 = _commit(repo)
    _report(reports, "Status: done")
    st = _recorded(tip1, base)
    _commit(repo, "package2.txt")
    (repo / "wip.txt").write_text("package 2 in progress")
    assert _state(repo, reports, st) == "done"


def test_report_in_git_does_not_count(env):
    repo, base, reports, _ = env
    (repo / "docs").mkdir()
    (repo / "docs" / ROW.report_name).write_text("Status: done\n")
    tip = _commit(repo)
    assert _state(repo, reports, _recorded(tip, base)) == "unfinished"   # only the git-ignored report file counts


@pytest.mark.parametrize("line,state", [("Status: blocked", "blocked"), ("Status: needs-review", "needs-review"),
                                        ("Status: in-progress", "unfinished"), ("# no status", "unfinished"),
                                        ("Status: done, mostly", "unfinished")])
def test_report_status_other_than_done_is_not_done(env, line, state):
    repo, base, reports, _ = env
    tip = _commit(repo)
    _report(reports, line)
    assert _state(repo, reports, _recorded(tip, base)) == state


def test_regate_records_the_tip_and_chains_the_base(env):
    repo, base, reports, state_path = env
    tip1 = _commit(repo)
    assert _regate(repo, state_path).startswith("full tier passed")
    st = rp.load_state(state_path)
    assert st["packages"]["1"]["tip"] == tip1 and st["packages"]["1"]["base"] == base and st["last"] == tip1
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert _regate(repo, state_path, ROW2).startswith("refused")      # package 2 has no commit since 1's tip
    tip2 = _commit(repo, "package2.txt")
    assert _regate(repo, state_path, ROW2).startswith("full tier passed")
    st = rp.load_state(state_path)
    assert st["packages"]["2"] == {**st["packages"]["2"], "tip": tip2, "base": tip1}
    assert _regate(repo, state_path).startswith("refused")            # 1 is no longer the last recorded package


def test_regate_records_nothing_on_red_or_dirty_or_another_package_in_progress(env):
    repo, base, reports, state_path = env
    tip = _commit(repo)
    ran = []
    assert "nothing recorded" in _regate(repo, state_path, ok=False, ran=ran) and ran == [tip]
    assert not state_path.exists()
    (repo / "wip.txt").write_text("x")
    assert _regate(repo, state_path).startswith("refused")
    (repo / "wip.txt").unlink()
    st = rp.load_state(state_path)
    st["current"] = {"n": 2, "base": base}
    rp.save_state(st, state_path)
    assert _regate(repo, state_path).startswith("refused")
    assert rp.load_state(state_path)["packages"] == {}


def test_template_is_never_done_as_seeded():
    template = Path(__file__).resolve().parents[2] / rp.TEMPLATE
    assert rp.report_status(template.read_text()) != "done"


def _rows():
    return [ROW, ROW2]


def test_preflight_resumes_the_package_in_progress_and_refuses_others(env, tmp_path):
    repo, base, reports, _ = env
    main = tmp_path / "main"
    _git(repo, "worktree", "add", "-q", str(main), "main")            # the clean main checkout
    st = rp.load_state(Path("/nonexistent/state.json"))
    st["current"] = {"n": 1, "base": base}
    states = {1: ("unfinished", "")}
    state = lambda r: states.get(r.n, ("absent", ""))  # noqa: E731
    assert rp.preflight(_rows(), ROW, st, main, repo, state) == "resume"
    with pytest.raises(SystemExit):                      # package 2 must not start while 1 is in progress
        rp.preflight(_rows(), ROW2, st, main, repo, state)
    states[1] = ("blocked", "")
    with pytest.raises(SystemExit):                      # blocked: the owner decides, no automatic resume
        rp.preflight(_rows(), ROW, st, main, repo, state)
    st = _recorded(base, base)
    assert rp.preflight(_rows(), ROW2, st, main, repo, lambda r: ("absent", "")) == "new"
    _commit(repo, "unowned.txt")
    with pytest.raises(SystemExit):                      # commits since the last recorded tip belong to no package
        rp.preflight(_rows(), ROW2, st, main, repo, lambda r: ("absent", ""))
    st["last"] = _git(repo, "rev-parse", "HEAD")
    (main / "dirty.txt").write_text("x")
    with pytest.raises(SystemExit):
        rp.preflight(_rows(), ROW2, st, main, repo, lambda r: ("absent", ""))


def test_resume_keeps_the_previous_report_and_work(env, tmp_path):
    repo, base, reports, _ = env
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
    repo, base, reports, _ = env
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


def test_runner_refuses_a_copy_inside_the_run_worktree(tmp_path):
    wt = tmp_path / "list-cleanup"
    (wt / "scripts").mkdir(parents=True)
    with pytest.raises(SystemExit):                      # sessions can edit it, and it installs the node helper
        rp.refuse_inside_worktree(wt / "scripts/run_packages.py", wt)
    rp.refuse_inside_worktree(tmp_path / "runner/scripts/run_packages.py", wt)
