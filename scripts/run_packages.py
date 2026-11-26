#!/usr/bin/env python3
"""Minimal package runner: the pending packages of docs/redesign/PACKAGES_PLAN.md, one fresh headless session each.

    scripts/run-packages                 all pending packages, in plan order
    scripts/run-packages --through M     pending packages in plan order up to package M
    scripts/run-packages N               package N only
    scripts/run-packages --regate N      run the full tier on the branch tip and record it as package N's pass
    --base REF                           where the branch starts if it does not exist yet (default main)

One feature branch for the whole list (owner decision 2026-11-26): every package is one or more commits on
`list-cleanup`, all in the one worktree /srv/holojob/.claude/worktrees/list-cleanup. The runner keeps its state in
/srv/holojob/.claude/package-runs/state.json (git-ignored, mode 600): per package the recorded tip, the base (the
previous package's recorded tip) and the full-tier pass; the last recorded tip; the package in progress.

Per package the runner:
  1. attaches the worktree (creates the branch from --base when it does not exist); the session reads
     /srv/holojob/data directly. For the must-keep set it writes the application job ids
     (scripts/export-application-job-ids.js; Python does not read the store) to a temp file, ids only, mode 600,
     passed as HOLOJOB_APPLICATION_JOB_IDS and removed after the session;
  2. starts `claude -p "do package N from docs/redesign/PACKAGES_PLAN.md"` there with the owner's normal login, the
     model from the plan table, permission mode acceptEdits (edits in the worktree only), a small Bash allowlist and
     deny rules; in -p a call that would need approval is denied, never waited for (Claude Code docs, permission-modes);
  3. decides from files and git, never from the exit code: the package is done only when the report
     /srv/holojob/.claude/package-runs/reports/NN-slug.md (git-ignored, never committed) starts with `Status: done`,
     the branch has at least one commit since the previous package's recorded tip, the worktree is clean, and the full
     tier (`sh scripts/test-tier.sh full`) passed on the tip. The tip is then recorded in the state.

Reports: Claude Code refuses headless writes under .claude/ ("sensitive file", even with --add-dir and an allow rule;
checked 2026-11-26), so the session writes the report to the git-ignored staging file <worktree>/logs/package-report-
NN-slug.md (path in HOLOJOB_PACKAGE_REPORT, seeded from scripts/package-report-template.md) and the runner moves it to
the reports directory after the session.

No sandbox, no token, no probes: see "What this cannot enforce" in the plan. Works from any cwd (absolute paths only).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(os.environ.get("HOLOJOB_REPO", "/srv/holojob"))
PLAN = "docs/redesign/PACKAGES_PLAN.md"
BRANCH = "list-cleanup"
WORKTREE = REPO / ".claude/worktrees" / BRANCH
RUNS = REPO / ".claude/package-runs"
REPORTS = RUNS / "reports"
STATE = RUNS / "state.json"
TEMPLATE = "scripts/package-report-template.md"
NODE_IMAGE = "docker.io/library/node:20-bookworm"
MAX_TURNS = 400
VENV_PY = REPO / ".venv/bin/python"
# The trusted copy of scripts/node-sandbox, outside every worktree (headless writes under .claude/ are refused).
HELPER = RUNS / "bin/node-sandbox"
HELPER_SOURCE = Path(__file__).resolve().parent / "node-sandbox"

# Bash the headless session may run without approval (everything else is denied in -p).
ALLOWED = (
    "Bash(git status *)", "Bash(git diff *)", "Bash(git log *)", "Bash(git show *)", "Bash(git add *)",
    "Bash(git commit *)", "Bash(git rm *)", "Bash(git mv *)", "Bash(git ls-files *)", "Bash(git grep *)",
    "Bash(git rev-parse *)", "Bash(git branch --show-current)",
    f"Bash({VENV_PY} *)", "Bash(graphify *)", f"Bash({HELPER} *)",
)
# Headless-only denies (owner decision 2026-11-26: podman only here, interactive sessions keep the node test container).
DISALLOWED = (
    "Bash(podman *)", "Bash(podman-compose *)", "Bash(git push *)", "Bash(git remote *)", "Bash(systemctl *)",
    "Bash(sh scripts/test-tier.sh *)", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "EnterWorktree",
    "ExitWorktree", "WebFetch", "WebSearch",
)


@dataclass
class Row:
    n: int
    slug: str
    model: str
    needs: list[int]
    order: int

    @property
    def report_name(self) -> str:
        return f"{self.n:02d}-{self.slug}.md"

    def staging(self, worktree: Path = WORKTREE) -> Path:
        return worktree / "logs" / f"package-report-{self.report_name}"


TABLE = re.compile(r"<!-- packages:start -->\n(.*?)<!-- packages:end -->", re.S)


def parse_table(text: str) -> list[Row]:
    m = TABLE.search(text)
    if not m:
        raise SystemExit(f"run-packages: no package table in {PLAN}")
    rows = []
    for line in m.group(1).splitlines():
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) >= 5 and c[0].isdigit():
            rows.append(Row(int(c[0]), c[1], c[2], [int(x) for x in re.findall(r"\d+", c[3])], int(c[4])))
    return sorted(rows, key=lambda r: r.order)


def git(*args: str, repo: Path = REPO, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {r.stderr.strip()[:300]}")
    return r.stdout.strip() if r.returncode == 0 else ""


def is_ancestor(a: str, b: str, repo: Path = REPO) -> bool:
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b],
                          capture_output=True).returncode == 0


def commits_between(base: str, tip: str, repo: Path = REPO) -> int:
    return int(git("rev-list", "--count", f"{base}..{tip}", repo=repo, check=False) or 0)


def branch_head(repo: Path = REPO) -> str:
    return git("rev-parse", "--verify", "-q", f"refs/heads/{BRANCH}^{{commit}}", repo=repo, check=False)


def load_state(path: Path = STATE) -> dict:
    st = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    st.setdefault("branch", BRANCH)
    st.setdefault("last", "")
    st.setdefault("current", None)
    st.setdefault("packages", {})
    if st["branch"] != BRANCH:
        raise SystemExit(f"run-packages: {path} belongs to branch {st['branch']}, not {BRANCH}")
    return st


def save_state(st: dict, path: Path = STATE) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        os.fchmod(fh.fileno(), 0o600)  # a restrictive or loose umask must not change the mode
        json.dump(st, fh, indent=2)
        fh.write("\n")
    tmp.replace(path)


def record_pass(st: dict, row: Row, tip: str, base: str) -> None:
    """Package N passed the full tier on `tip`; its commits are base..tip. The next package starts from `tip`."""
    st["packages"][str(row.n)] = {"tip": tip, "base": base, "gate": "full tier pass",
                                  "at": dt.datetime.now().isoformat(timespec="seconds")}
    st["last"] = tip
    st["current"] = None


def report_status(text: str) -> str:
    lines = text.splitlines()
    m = re.fullmatch(r"Status:\s*(done|blocked|needs-review)\s*", lines[0].strip()) if lines else None
    return m.group(1) if m else ""


def package_state(row: Row, repo: Path = REPO, reports: Path = REPORTS, worktree: Path = WORKTREE,
                  st: dict | None = None) -> tuple[str, str]:
    """(state, detail): done | blocked | needs-review | unfinished | absent. Done needs all four: the report file says
    `Status: done`; a full-tier pass recorded for a tip that is on the branch; at least one commit from the previous
    package's recorded tip to that tip; a clean worktree while that tip is the branch head."""
    st = st if st is not None else load_state()
    entry = st["packages"].get(str(row.n))
    current = (st.get("current") or {}).get("n") == row.n
    report = reports / row.report_name
    if not report.is_file():
        return ("unfinished" if entry or current else "absent"), f"no report {report}"
    status = report_status(report.read_text(encoding="utf-8", errors="replace"))
    if status != "done":
        return (status or "unfinished"), f"report says {status or 'no valid Status line'}"
    if not entry:
        return "unfinished", "no full-tier pass recorded"
    head = branch_head(repo)
    if not head:
        return "unfinished", f"no branch {BRANCH}"
    tip, base = entry["tip"], entry["base"]
    if not is_ancestor(tip, head, repo):
        return "unfinished", f"recorded tip {tip[:12]} is not on {BRANCH}"
    if commits_between(base, tip, repo) == 0:
        return "unfinished", "no commit since the previous package's tip"
    if tip == head and worktree.exists() and git("status", "--porcelain", repo=worktree, check=False):
        return "unfinished", f"uncommitted changes in {worktree}"
    return "done", tip[:12]


def select(rows: list[Row], only: int | None, through: int | None) -> list[Row]:
    if only is not None:
        picked = [r for r in rows if r.n == only]
        if not picked:
            raise SystemExit(f"run-packages: no package {only}")
        return picked
    if through is not None:
        if through not in {r.n for r in rows}:
            raise SystemExit(f"run-packages: no package {through}")
        idx = next(i for i, r in enumerate(rows) if r.n == through)
        return rows[: idx + 1]
    return rows


def run_all(rows: list[Row], state, run_one) -> int:
    """Skip done packages, run the others in order, stop at the first one that does not end done."""
    for row in rows:
        st, detail = state(row)
        if st == "done":
            print(f"run-packages: {row.n} {row.slug}: done ({detail}), skipped")
            continue
        result = run_one(row)
        if result != "done":
            print(f"run-packages: stopped at package {row.n} {row.slug}: {result}")
            return 1
    return 0


def preflight(all_rows: list[Row], row: Row, st: dict, repo: Path = REPO, worktree: Path = WORKTREE,
              state=None) -> str:
    """'new' or 'resume' for `row`; refuses a dirty main checkout, another package in progress on the branch, a
    blocked or needs-review package (the owner decides those), a needed package that is not done, and for a new
    package: commits since the last recorded tip (they belong to no package) or a dirty worktree."""
    state = state or (lambda r: package_state(r, repo, worktree=worktree, st=st))
    problems = []
    if git("status", "--porcelain", repo=repo):
        problems.append(f"{repo} has a dirty tree")
    by_n = {r.n: r for r in all_rows}
    own = state(row)[0]
    current = (st.get("current") or {}).get("n")
    mode = "new"
    if own in ("blocked", "needs-review"):
        problems.append(f"package {row.n} is {own}: the owner decides first (see its report)")
    elif current == row.n:
        mode = "resume"  # continue in the worktree, uncommitted work kept
    elif current is not None:
        problems.append(f"package {current} is in progress on {BRANCH}: finish or regate it first")
    for need in row.needs:
        if need in by_n and state(by_n[need])[0] != "done":
            problems.append(f"package {row.n} needs {need}, which is not done")
    if mode == "new":
        head = branch_head(repo)
        if head and st["last"] and head != st["last"]:
            problems.append(f"{BRANCH} has commits since the last recorded tip {st['last'][:12]} that belong to no "
                            f"package (regate the package they belong to)")
        if worktree.exists() and git("status", "--porcelain", repo=worktree, check=False):
            problems.append(f"{worktree} has uncommitted changes and no package is in progress")
    if problems:
        raise SystemExit("run-packages: refused:\n  - " + "\n  - ".join(problems))
    return mode


def prompt_for(row: Row, resume: bool) -> str:
    """The package prompt: the owner's one line, then the headless rules the session cannot ask about."""
    lines = [
        f"do package {row.n} from docs/redesign/PACKAGES_PLAN.md",
        "",
        "This is a headless run (scripts/run-packages): no human is available during the session.",
        "- Never ask the owner a question and never end the session with one. Any blocking case or open decision: write it",
        "  in the report, put `Status: blocked` on its first line, commit the work so far, and end the session.",
        f"- Commit on the current branch {BRANCH}, in this worktree. Never create or switch branches.",
        f"- Write the report to {row.staging()} (seeded from the template, git-ignored). The runner moves it to",
        f"  {REPORTS / row.report_name}. Never commit the report.",
        "- podman is denied. Run Vitest, ESLint and node measurement scripts only through the helper:",
        f"  `{HELPER} vitest tests/js/FILE.test.js ...`, `{HELPER} lint [FILE ...]`, `{HELPER} node SCRIPT.js [ARG ...]`",
        "  (no network, this worktree read-write, /srv/holojob/data read-only). Python: "
        f"`{VENV_PY} ...` (pytest: `{VENV_PY} -m pytest tests/python/... -q`).",
        "- Read the real data in /srv/holojob/data; write only to temp dirs. The runner runs the full tier after you finish.",
    ]
    if resume:
        lines += ["- RESUMED RUN: this worktree holds the previous session's uncommitted work and its report. Continue",
                  "  from there: read `git status`, `git diff` and the report first; do not discard or redo finished work."]
    return "\n".join(lines)


def install_helper(source: Path = HELPER_SOURCE, dest: Path = HELPER) -> Path:
    """Copy the runner's own node-sandbox (not a worktree's) to the trusted path the sessions may call."""
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(source.read_bytes())
    tmp.chmod(0o700)
    tmp.replace(dest)
    return dest


def ensure_worktree(base_ref: str, repo: Path = REPO, worktree: Path = WORKTREE) -> None:
    """The one run worktree on BRANCH: reused, re-attached, or created with the branch from base_ref."""
    if worktree.exists():
        on = git("branch", "--show-current", repo=worktree, check=False)
        if on != BRANCH:
            raise SystemExit(f"run-packages: {worktree} is on {on or 'a detached HEAD'}, not {BRANCH}")
    elif branch_head(repo):
        git("worktree", "add", "-q", str(worktree), BRANCH, repo=repo)
    else:
        base = git("rev-parse", "--verify", f"{base_ref}^{{commit}}", repo=repo)
        git("worktree", "add", "-q", "-b", BRANCH, str(worktree), base, repo=repo)


def gate(sha: str, log: Path, worktree: Path = WORKTREE) -> bool:
    """The full tier on `sha`, with the branch's own scripts/test-tier.sh."""
    env = {**os.environ, "HOLOJOB_NODE_MODULES": str(REPO / "node_modules"), "HOLOJOB_PYTHON": str(VENV_PY)}
    log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        r = subprocess.run(["sh", str(worktree / "scripts/test-tier.sh"), "full", sha], cwd=worktree, stdout=fh,
                           stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env)
    return r.returncode == 0


def regate(row: Row, base_ref: str, repo: Path = REPO, worktree: Path = WORKTREE, state_path: Path = STATE,
           logdir: Path = RUNS, gate_fn=gate) -> str:
    """Run the full tier on the branch tip and record it as package N's pass. N must be the package in progress, the
    last recorded one, or (nothing in progress) the next one; its commits are from its base to the tip."""
    st = load_state(state_path)
    current = st.get("current") or {}
    if current and current.get("n") != row.n:
        return f"refused: package {current['n']} is in progress on {BRANCH}"
    ensure_worktree(base_ref, repo, worktree)
    if git("status", "--porcelain", repo=worktree, check=False):
        return f"refused: uncommitted changes in {worktree}"
    tip = git("rev-parse", "HEAD", repo=worktree)
    entry = st["packages"].get(str(row.n))
    if entry and st["last"] and entry["tip"] != st["last"]:
        return f"refused: package {row.n} is not the last recorded package (last tip {st['last'][:12]})"
    if current:
        base = current["base"]
    elif entry:
        base = entry["base"]
    else:
        base = st["last"] or git("merge-base", f"{base_ref}^{{commit}}", BRANCH, repo=repo)
    if commits_between(base, tip, repo) == 0:
        return f"refused: no commit since {base[:12]} for package {row.n}"
    log = logdir / f"{row.n:02d}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-regate.log"
    if not gate_fn(tip, log, worktree):
        return f"full tier red on {tip[:12]} (log {log}); nothing recorded"
    record_pass(st, row, tip, base)
    save_state(st, state_path)
    return f"full tier passed on {tip[:12]}, recorded for package {row.n} (base {base[:12]}, log {log})"


def export_application_ids(tmp: str) -> Path:
    """Application job ids, read-only on the store, ids only (the repo's sanctioned exporter)."""
    out = Path(tmp) / "application-job-ids.txt"
    subprocess.run(["podman", "run", "--rm", "--security-opt", "label=disable", "-v", f"{REPO}:/work:ro",
                    "-v", f"{tmp}:/out", "-w", "/work", NODE_IMAGE, "node", "scripts/export-application-job-ids.js",
                    f"/out/{out.name}"], check=True, capture_output=True)
    out.chmod(0o600)
    return out


def prepare_report(row: Row, resume: bool, reports: Path = REPORTS, worktree: Path = WORKTREE) -> Path:
    """Seed the staging report and return its path. On resume the previous report continues (moved back into the
    worktree); otherwise a fresh copy of the template, and a stray old report is kept aside, never trusted."""
    staging = row.staging(worktree)
    reports.mkdir(mode=0o700, parents=True, exist_ok=True)
    final = reports / row.report_name
    staging.parent.mkdir(mode=0o700, exist_ok=True)
    if resume and staging.is_file():
        pass  # left by an interrupted run: newer than anything in reports/
    elif resume and final.is_file():
        final.replace(staging)
    else:
        if final.exists():
            final.rename(final.with_name(f"{final.name}.old-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"))
        staging.write_text((worktree / TEMPLATE).read_text(encoding="utf-8"), encoding="utf-8")
    staging.chmod(0o600)
    return staging


def run_one(row: Row, all_rows: list[Row], base_ref: str) -> str:
    st = load_state()
    mode = preflight(all_rows, row, st)
    ensure_worktree(base_ref)
    if mode == "resume":
        base_sha = st["current"]["base"]
        print(f"run-packages: package {row.n} {row.slug}: resuming on {BRANCH} (uncommitted work kept), "
              f"model {row.model}")
    else:
        base_sha = st["last"] or git("rev-parse", "HEAD", repo=WORKTREE)
        st["current"] = {"n": row.n, "base": base_sha}
        save_state(st)
        print(f"run-packages: package {row.n} {row.slug} on {BRANCH} from {base_sha[:12]}, model {row.model}")
    staging = prepare_report(row, mode == "resume")
    install_helper()
    RUNS.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log = RUNS / f"{row.n:02d}-{stamp}.json"
    argv = ["claude", "-p", prompt_for(row, mode == "resume"), "--model", row.model, "--permission-mode", "acceptEdits",
            "--allowedTools", *ALLOWED, "--disallowedTools", *DISALLOWED, "--max-turns", str(MAX_TURNS),
            "--output-format", "json"]
    with tempfile.TemporaryDirectory(prefix="holojob-app-ids-") as tmp, open(log, "w") as fh:
        os.chmod(tmp, 0o700)
        os.chmod(log, 0o600)
        env = {**os.environ, "HOLOJOB_APPLICATION_JOB_IDS": str(export_application_ids(tmp)),
               "HOLOJOB_PACKAGE_REPORT": str(staging)}
        subprocess.run(argv, cwd=WORKTREE, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, env=env)
    # Move the report out of the worktree to its git-ignored home; the verdict never comes from the exit code.
    final = REPORTS / row.report_name
    if staging.is_file():
        staging.replace(final)
        final.chmod(0o600)
    tip = git("rev-parse", "HEAD", repo=WORKTREE)
    if commits_between(base_sha, tip) == 0:
        return f"no commit on {BRANCH} since {base_sha[:12]} (session log {log})"
    if git("status", "--porcelain", repo=WORKTREE):
        return f"uncommitted changes left in {WORKTREE} (session log {log})"
    if not final.is_file():
        return f"no report written (session log {log})"
    status = report_status(final.read_text(encoding="utf-8", errors="replace"))
    if status in ("blocked", "needs-review"):
        return f"{status}: see {final}"
    if status != "done":
        return f"not done: report {final} has no Status: done line (session log {log})"
    gate_log = RUNS / f"{row.n:02d}-{stamp}-gate.log"
    if not gate(tip, gate_log):
        return f"not done: full tier red on {tip[:12]} (log {gate_log}; after a fix: scripts/run-packages --regate {row.n})"
    st = load_state()
    record_pass(st, row, tip, base_sha)
    save_state(st)
    state_now, detail = package_state(row)
    print(f"run-packages: package {row.n} {row.slug}: {state_now} ({detail})")
    return state_now


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run-packages", description=__doc__.split("\n\n")[0])
    ap.add_argument("package", nargs="?", type=int)
    ap.add_argument("--through", type=int)
    ap.add_argument("--regate", type=int, metavar="N")
    ap.add_argument("--base", default="main")
    a = ap.parse_args(argv)
    if sum(x is not None for x in (a.package, a.through, a.regate)) > 1:
        raise SystemExit("run-packages: give one of N, --through M, --regate N")
    ref = BRANCH if branch_head() else a.base
    text = git("show", f"{ref}:{PLAN}", check=False)
    if not text:
        raise SystemExit(f"run-packages: {PLAN} not found at {ref}")
    rows = parse_table(text)
    if a.regate is not None:
        result = regate(select(rows, a.regate, None)[0], a.base)
        print(f"run-packages: --regate {a.regate}: {result}")
        return 0 if result.startswith("full tier passed") else 1
    return run_all(select(rows, a.package, a.through), package_state, lambda r: run_one(r, rows, a.base))


if __name__ == "__main__":
    sys.exit(main())
