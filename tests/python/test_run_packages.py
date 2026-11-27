"""Package runner rules that would hurt if broken: a package counted done without its report file saying
`Status: done`, a recorded full-tier pass on a tip that is on the one branch, at least one commit since the previous
package's recorded tip and a clean worktree; a regate that records a red tier or the wrong base; a run that does not
stop at the first package that is not done. Temp git repos, temp state and report files only."""
import importlib.util
import json
import os
import stat
import subprocess
import sys
import time
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


def test_prompt_names_the_exact_paths_and_the_mark(tmp_path):
    ids = tmp_path / rp.IDS_FILE
    text = rp.prompt_for(ROW, True, ids, after="a" * 40, worktree=tmp_path / "wt")
    assert str(ROW.staging(tmp_path / "wt")) in text and str(ids) in text and str(rp.BENCHMARKS) in text
    assert "a" * 12 in text                               # the session learns it needs a commit after the mark
    assert "a" * 12 not in rp.prompt_for(ROW, True)


def test_session_reads_benchmarks_but_never_edits_them():
    argv = rp.session_argv(ROW, "p", extra_allowed=("Read(//tmp/x/ids.txt)",))
    allowed = argv[argv.index("--allowedTools") + 1:argv.index("--disallowedTools")]
    denied = argv[argv.index("--disallowedTools") + 1:argv.index("--max-turns")]
    bench = f"/{rp.BENCHMARKS}/**"
    assert f"Read({bench})" in allowed and "Read(//tmp/x/ids.txt)" in allowed
    assert f"Edit({bench})" in denied and f"Write({bench})" in denied
    assert not any(a.startswith(("Edit(", "Write(")) for a in allowed)
    # The benchmarks are an added dir (Bash grep/ls there), which acceptEdits covers: only the denies keep it read-only.
    assert argv[argv.index("--add-dir") + 1] == str(rp.BENCHMARKS)


def test_mark_needs_a_commit_of_the_package_after_it(env):
    repo, base, reports, state_path = env
    _commit(repo, "package1-part1.txt")
    st = rp.load_state(state_path)
    st["current"] = {"n": 1, "base": base}
    rp.save_state(st, state_path)
    runner_tip = _commit(repo, "runner-fix.txt")          # runner commits land mid-package
    assert rp.mark_tip(ROW, repo, state_path).startswith("package 1 needs a commit after")
    assert rp.load_state(state_path)["current"] == {"n": 1, "base": base, "after": runner_tip}
    assert "mark" in _regate(repo, state_path) and rp.load_state(state_path)["packages"] == {}
    tip = _commit(repo, "package1-part2.txt")
    assert _regate(repo, state_path).startswith("full tier passed")
    entry = rp.load_state(state_path)["packages"]["1"]
    assert entry["base"] == base and entry["after"] == runner_tip and entry["tip"] == tip
    _report(reports, "Status: done")
    st = rp.load_state(state_path)
    assert _state(repo, reports, st) == "done"
    st["packages"]["1"]["tip"] = runner_tip               # a pass on the mark itself is never done
    assert _state(repo, reports, st) == "unfinished"


def test_mark_tip_refuses_without_that_package_in_progress(env):
    repo, base, reports, state_path = env
    _commit(repo)
    assert rp.mark_tip(ROW, repo, state_path).startswith("refused")
    st = rp.load_state(state_path)
    st["current"] = {"n": 2, "base": base}
    rp.save_state(st, state_path)
    assert rp.mark_tip(ROW, repo, state_path).startswith("refused")
    assert "after" not in rp.load_state(state_path)["current"]


def test_plan_table_is_a_valid_chain():
    """The real plan: unique numbers and orders, every `needs` an existing package that runs earlier, so a package is
    never started before what it needs; the packages already recorded keep their numbers."""
    plan = Path(__file__).resolve().parents[2] / rp.PLAN
    rows = rp.parse_table(plan.read_text(encoding="utf-8"))
    by_n = {r.n: r for r in rows}
    assert len(by_n) == len(rows) and len({r.order for r in rows}) == len(rows)
    assert {1, 2, 3} <= set(by_n) and [by_n[n].order for n in (1, 2, 3)] == [1, 2, 3]
    for r in rows:
        for need in r.needs:
            assert need in by_n and by_n[need].order < r.order, f"package {r.n} needs {need}"
    assert [r.n for r in rp.select(rows, None, 3)] == [1, 2, 3]


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


# --- owner decision 2026-11-27: done is the runner's decision; a usage limit pauses; progress is live ------------------

BLOCKED_NONE = "Status: needs-review\n\n# r\n\n## Blocked or needs owner\n\nNone.\n\n## Permanent docs updated\n\nx\n"
BLOCKED_REASON = "Status: blocked\n\n# r\n\n## Blocked or needs owner\n\nA real decision: keep or drop X?\n\n## Next\n"


@pytest.mark.parametrize("text,status", [
    (BLOCKED_NONE, "done"),                                                   # None: the session's work is complete
    (BLOCKED_NONE.replace("None.", "**n/a**"), "done"),
    (BLOCKED_REASON, "blocked"),                                              # a stated reason stops the chain
    (BLOCKED_NONE.replace("None.", "None. Decide X first."), "needs-review"),  # more than None is a reason
    ("Status: blocked\n\n# r\n", "blocked"),                                  # no section: the owner looks
    ("Status: needs-review\n\n## Blocked or needs owner\n\n<!-- hint -->\n", "needs-review"),  # empty is not None
    ("Status: done\n\n## Blocked or needs owner\n\nSomething.\n", "done"),
    ("Status: in-progress\n\n## Blocked or needs owner\n\nNone.\n", ""),      # the untouched template never counts
])
def test_effective_status(text, status):
    assert rp.effective_status(text) == status


def test_needs_review_with_none_can_be_done_but_a_reason_stops(env):
    repo, base, reports, _ = env
    tip = _commit(repo)
    st = _recorded(tip, base)
    (reports / ROW.report_name).write_text(BLOCKED_NONE)
    assert _state(repo, reports, st) == "done"            # with the commit, the clean tree and the recorded pass
    (reports / ROW.report_name).write_text(BLOCKED_REASON)
    assert _state(repo, reports, st) == "blocked"


def test_verdict_before_gate_follows_the_new_rule(env, tmp_path):
    repo, base, reports, _ = env
    final, log = reports / ROW.report_name, tmp_path / "s.json"

    def check():
        return rp.verdict_before_gate(base, "", _git(repo, "rev-parse", "HEAD"), final, log, repo, repo)[0]

    assert check() == "fail"                                # no commit of its own yet
    _commit(repo)
    assert check() == "fail"                                # no report
    final.write_text(BLOCKED_NONE)
    assert check() == "ok"                                  # the full tier decides next
    final.write_text(BLOCKED_REASON)
    assert check() == "blocked"
    final.write_text("Status: in-progress\n")
    assert check() == "fail"
    final.write_text("Status: done\n")
    (repo / "dirty.txt").write_text("x")
    assert check() == "fail"                                # uncommitted work is never done


LIMIT = {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429,
         "api_error": "usage_limit_reached", "result": "You've hit your 5-hour limit · resets 12:50am (Europe/Belgrade)"}


@pytest.mark.parametrize("result,expected", [
    (LIMIT, "00:50 (Europe/Belgrade)"),
    ({**LIMIT, "result": "You've hit your 5-hour limit · resets 3pm"}, "15:00"),
    ({**LIMIT, "result": "You've hit your 5-hour limit · resets 12:05pm"}, "12:05"),
    ({"is_error": True, "result": "You've hit your weekly limit · resets Dec 1"}, "Dec 1"),   # no api_error code: the text
    ({**LIMIT, "result": "limit"}, "at an unknown time"),
    ({**LIMIT, "is_error": False}, None),
    ({"is_error": True, "api_error_status": 429, "api_error": "rate_limit_error", "result": "Overloaded"}, None),
    ({"is_error": True, "subtype": "error_during_execution", "result": "boom"}, None),
    (None, None),
])
def test_usage_limit_reset(result, expected):
    assert rp.usage_limit_reset(result) == expected


def test_usage_limit_reset_falls_back_to_the_event_time():
    assert rp.usage_limit_reset({**LIMIT, "result": "You've hit your limit"}, 1795755000) == \
        time.strftime("%H:%M", time.localtime(1795755000))


def test_a_usage_limit_pauses_the_run_without_failing_it(capsys):
    rows = [rp.Row(n, f"p{n}", "m", [], n) for n in (1, 2, 3)]
    ran = []

    def run_one(row):
        ran.append(row.n)
        return "paused: usage limit, resets 00:50" if row.n == 2 else "done"

    assert rp.run_all(rows, lambda r: ("absent", ""), run_one) == rp.PAUSED_EXIT == 75
    assert ran == [1, 2]                                    # it does not wait, and does not go on to package 3
    out = capsys.readouterr().out
    assert "paused: usage limit, resets 00:50" in out and "stopped at" not in out and "resumes" in out


def _stream(*events):
    return "".join(json.dumps(e) + "\n" for e in events)


def _assistant(mid, *blocks, parent=None):
    return {"type": "assistant", "parent_tool_use_id": parent, "message": {"id": mid, "content": list(blocks)}}


def _tool(name, **inp):
    return {"type": "tool_use", "id": "t", "name": name, "input": inp}


def _progress(tmp_path, lines):
    return rp.Progress(ROW, 1, 14, path=tmp_path / "progress.log", out=lines.append, worktree=Path("/wt"))


def test_progress_writes_one_line_per_tool_call_with_turns_and_last_tool(tmp_path):
    lines = []
    pr = _progress(tmp_path, lines)
    for ev in (
        {"type": "system", "subtype": "init", "model": "claude-x"},
        _assistant("m1", {"type": "text", "text": "hi"}, _tool("Edit", file_path="/wt/python/a.py")),   # one turn, two blocks
        {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
        _assistant("m2", _tool("Bash", command="git   status  --short")),
        _assistant("m2b", _tool("Read", file_path="/x/y"), parent="toolu_1"),                          # a subagent: no turn
        {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed_warning", "resetsAt": 1}},
        {"type": "result", "subtype": "success", "num_turns": 3, "is_error": False},
    ):
        pr.feed(json.dumps(ev))
    pr.feed("not json")
    steps = [ln for ln in lines if "turn " in ln and "session ended" not in ln]
    assert len(steps) == 3 and "package 1 (1 of 14) archive-history" in steps[0]
    assert steps[0].endswith("turn 1  Edit python/a.py") and steps[1].endswith("turn 2  Bash git status --short")
    assert steps[2].endswith("turn 2  subagent Read /x/y")
    assert "session started, model claude-x" in lines[0] and "3 turns" in lines[-1] and "last: subagent Read" in lines[-1]
    assert not any("usage limit" in ln for ln in lines)     # a warning is not a stop
    log = tmp_path / "progress.log"
    assert log.read_text().splitlines() == lines and stat.S_IMODE(log.stat().st_mode) == 0o600
    assert pr.result["num_turns"] == 3


def test_run_session_tees_the_stream_and_keeps_the_result(tmp_path):
    lines = []
    pr = _progress(tmp_path, lines)
    script = tmp_path / "fake_claude.py"
    script.write_text("import sys\nsys.stdout.write(%r)\nsys.stdout.flush()\nsys.stderr.write('warn')\nsys.exit(1)\n" % _stream(
        {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": 1795755000}},
        _assistant("m1", _tool("Edit", file_path="/wt/a.py")), LIMIT))
    stream, err, log = tmp_path / "s.jsonl", tmp_path / "s.stderr", tmp_path / "s.json"
    code = rp.run_session([sys.executable, str(script)], tmp_path, dict(os.environ), stream, err, pr)
    rp.write_result_log(log, pr, code)
    assert code == 1 and err.read_text() == "warn"
    assert [json.loads(x)["type"] for x in stream.read_text().splitlines()] == ["rate_limit_event", "assistant", "result"]
    assert json.loads(log.read_text()) == LIMIT             # the final result log stays the result object
    assert rp.usage_limit_reset(pr.result, pr.limit_event) == "00:50 (Europe/Belgrade)"
    assert all(stat.S_IMODE(x.stat().st_mode) == 0o600 for x in (stream, err, log))
    assert any("usage limit reached" in ln for ln in lines) and any("Edit a.py" in ln for ln in lines)


def test_a_session_without_a_result_event_is_logged_as_an_error(tmp_path):
    pr = _progress(tmp_path, [])
    log = tmp_path / "s.json"
    rp.write_result_log(log, pr, 7)
    body = json.loads(log.read_text())
    assert body["is_error"] is True and "exit code 7" in body["result"]
    assert rp.usage_limit_reset(body) is None               # a crash is a failure, never a pause


def test_session_streams_events_and_the_prompt_states_the_status_rule():
    argv = rp.session_argv(ROW, "p")
    assert argv[argv.index("--output-format") + 1] == "stream-json" and "--verbose" in argv   # stream-json needs it
    text = rp.prompt_for(ROW, False)
    assert "Status: done" in text and "None there does not stop the chain" in text
