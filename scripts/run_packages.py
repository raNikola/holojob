#!/usr/bin/env python3
"""Minimal package runner: the pending packages of docs/redesign/PACKAGES_PLAN.md, one fresh headless session each.

    scripts/run-packages                 all pending packages, in plan order
    scripts/run-packages --through M     pending packages in plan order up to package M
    scripts/run-packages N               package N only
    --base REF                           base while no package is done (default main; the plan must exist there)

Per package the runner:
  1. creates the worktree /srv/holojob/.claude/worktrees/pkg-NN-slug on branch pkg/NN-slug, stacked on the last done
     package's branch (else --base); the session reads /srv/holojob/data directly. For the must-keep set it writes the
     application job ids (scripts/export-application-job-ids.js; Python does not read the store) to a temp file, ids
     only, mode 600, passed as HOLOJOB_APPLICATION_JOB_IDS and removed after the session;
  2. starts `claude -p "do package N from docs/redesign/PACKAGES_PLAN.md"` there with the owner's normal login, the
     model from the plan table, permission mode acceptEdits (edits in the worktree only), a small Bash allowlist and
     deny rules; in -p a call that would need approval is denied, never waited for (Claude Code docs, permission-modes);
  3. decides from files and git, never from the exit code: the package is done only when the report
     /srv/holojob/.claude/package-runs/reports/NN-slug.md (git-ignored, never committed) starts with `Status: done`,
     pkg/NN-slug has a commit after the base, the worktree is clean, and the full tier (`sh scripts/test-tier.sh full`)
     passed on the branch tip. The pass is recorded as a local git note (refs/notes/package-gate, with the base sha)
     on the tip, so a resumed run can verify it.

Reports: Claude Code refuses headless writes under .claude/ ("sensitive file", even with --add-dir and an allow rule;
checked 2026-11-26), so the session writes the report to the git-ignored staging file <worktree>/logs/package-report-
NN-slug.md (path in HOLOJOB_PACKAGE_REPORT, seeded from scripts/package-report-template.md) and the runner moves it to
the reports directory after the session.

No sandbox, no token, no probes: see "What this cannot enforce" in the plan.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(os.environ.get("HOLOJOB_REPO", "/srv/holojob"))
PLAN = "docs/redesign/PACKAGES_PLAN.md"
REPORTS = REPO / ".claude/package-runs/reports"
TEMPLATE = "scripts/package-report-template.md"
NOTES_REF = "refs/notes/package-gate"
NODE_IMAGE = "docker.io/library/node:20-bookworm"
MAX_TURNS = 400
VENV_PY = REPO / ".venv/bin/python"
# The trusted copy of scripts/node-sandbox, outside every worktree (headless writes under .claude/ are refused).
HELPER = REPO / ".claude/package-runs/bin/node-sandbox"
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
    def branch(self) -> str:
        return f"pkg/{self.n:02d}-{self.slug}"

    @property
    def report_name(self) -> str:
        return f"{self.n:02d}-{self.slug}.md"

    @property
    def staging(self) -> Path:
        return self.worktree / "logs" / f"package-report-{self.report_name}"

    @property
    def worktree(self) -> Path:
        return REPO / ".claude/worktrees" / f"pkg-{self.n:02d}-{self.slug}"


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


def report_status(text: str) -> str:
    lines = text.splitlines()
    m = re.fullmatch(r"Status:\s*(done|blocked|needs-review)\s*", lines[0].strip()) if lines else None
    return m.group(1) if m else ""


def package_state(row: Row, repo: Path = REPO, reports: Path = REPORTS, worktree: Path | None = None) -> tuple[str, str]:
    """(state, detail): done | blocked | needs-review | unfinished | absent. Done needs all four: the report file says
    `Status: done`, a commit after the base on the branch, a clean worktree, a full-tier pass on the branch tip."""
    tip = git("rev-parse", "--verify", "-q", f"refs/heads/{row.branch}^{{commit}}", repo=repo, check=False)
    if not tip:
        return "absent", "no branch"
    report = reports / row.report_name
    if not report.is_file():
        return "unfinished", f"no report {report}"
    status = report_status(report.read_text(encoding="utf-8", errors="replace"))
    if status != "done":
        return (status or "unfinished"), f"report says {status or 'no valid Status line'}"
    wt = worktree if worktree is not None else row.worktree
    if wt.exists() and git("status", "--porcelain", repo=wt, check=False):
        return "unfinished", f"uncommitted changes in {wt}"
    note = git("notes", f"--ref={NOTES_REF}", "show", tip, repo=repo, check=False)
    m = re.match(r"full tier pass base=([0-9a-f]{40})\b", note)
    if not m:
        return "unfinished", "no full-tier pass recorded for the branch tip"
    if git("rev-list", "--count", f"{m.group(1)}..{tip}", repo=repo, check=False) in ("", "0"):
        return "unfinished", "no commit after the base"
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


def preflight(all_rows: list[Row], row: Row, repo: Path = REPO, state=None) -> str:
    """'new' or 'resume' for `row`; refuses a dirty main checkout, another package's unfinished branch, a needed
    package that is not done, and a blocked or needs-review package (the owner decides those)."""
    state = state or package_state
    problems = []
    if git("status", "--porcelain", repo=repo):
        problems.append(f"{repo} has a dirty tree")
    by_n = {r.n: r for r in all_rows}
    mode = "new"
    for ref in git("for-each-ref", "--format=%(refname:short)", "refs/heads/pkg/", repo=repo).split():
        m = re.match(r"pkg/(\d+)-", ref)
        other = by_n.get(int(m.group(1))) if m else None
        st = state(other)[0] if other else "unknown"
        if other == row and st == "unfinished":
            mode = "resume"  # continue on its branch and worktree, uncommitted work kept
        elif other == row and st in ("blocked", "needs-review"):
            problems.append(f"package {row.n} is {st}: the owner decides first (see its report)")
        elif st != "done":
            problems.append(f"unfinished package branch {ref} ({st})")
    for need in row.needs:
        if need in by_n and state(by_n[need])[0] != "done":
            problems.append(f"package {row.n} needs {need}, which is not done")
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
        f"- Write the report to {row.staging} (seeded from the template, git-ignored). The runner moves it to",
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


def base_for(rows: list[Row], default: str) -> str:
    done = [r for r in rows if package_state(r)[0] == "done"]
    return done[-1].branch if done else default


def gate(row: Row, sha: str, base_sha: str, log: Path) -> bool:
    env = {**os.environ, "HOLOJOB_NODE_MODULES": str(REPO / "node_modules"), "HOLOJOB_PYTHON": str(VENV_PY)}
    with open(log, "w") as fh:
        r = subprocess.run(["sh", "scripts/test-tier.sh", "full", sha], cwd=row.worktree, stdout=fh,
                           stderr=subprocess.STDOUT, env=env)
    if r.returncode == 0:
        git("notes", f"--ref={NOTES_REF}", "add", "-f", "-m",
            f"full tier pass base={base_sha} {dt.datetime.now().isoformat(timespec='seconds')}", sha)
    return r.returncode == 0


def export_application_ids(tmp: str) -> Path:
    """Application job ids, read-only on the store, ids only (the repo's sanctioned exporter)."""
    out = Path(tmp) / "application-job-ids.txt"
    subprocess.run(["podman", "run", "--rm", "--security-opt", "label=disable", "-v", f"{REPO}:/work:ro",
                    "-v", f"{tmp}:/out", "-w", "/work", NODE_IMAGE, "node", "scripts/export-application-job-ids.js",
                    f"/out/{out.name}"], check=True, capture_output=True)
    out.chmod(0o600)
    return out


def prepare_report(row: Row, resume: bool, reports: Path = REPORTS, worktree: Path | None = None) -> Path:
    """Seed the staging report and return its path. On resume the previous report continues (moved back into the
    worktree); otherwise a fresh copy of the template, and a stray old report is kept aside, never trusted."""
    wt = worktree if worktree is not None else row.worktree
    staging = wt / "logs" / f"package-report-{row.report_name}"
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
        staging.write_text((wt / TEMPLATE).read_text(encoding="utf-8"), encoding="utf-8")
    staging.chmod(0o600)
    return staging


def run_one(row: Row, all_rows: list[Row], base_default: str) -> str:
    mode = preflight(all_rows, row)
    base = base_for(all_rows, base_default)
    if mode == "resume":
        # The base is where the package branch left the stack, not where the stack is now.
        base_sha = git("merge-base", f"{base}^{{commit}}", row.branch)
        if not row.worktree.exists():
            git("worktree", "add", "-q", str(row.worktree), row.branch)
        print(f"run-packages: package {row.n} {row.slug}: resuming on {row.branch} (uncommitted work kept), "
              f"model {row.model}")
    else:
        base_sha = git("rev-parse", "--verify", f"{base}^{{commit}}")
        print(f"run-packages: package {row.n} {row.slug} on {row.branch} from {base}, model {row.model}")
        git("worktree", "add", "-q", "-b", row.branch, str(row.worktree), base_sha)
    prepare_report(row, mode == "resume")
    install_helper()
    logdir = REPO / ".claude/package-runs"
    logdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log = logdir / f"{row.n:02d}-{stamp}.json"
    argv = ["claude", "-p", prompt_for(row, mode == "resume"), "--model", row.model, "--permission-mode", "acceptEdits",
            "--allowedTools", *ALLOWED, "--disallowedTools", *DISALLOWED, "--max-turns", str(MAX_TURNS),
            "--output-format", "json"]
    with tempfile.TemporaryDirectory(prefix="holojob-app-ids-") as tmp, open(log, "w") as fh:
        os.chmod(tmp, 0o700)
        os.chmod(log, 0o600)
        env = {**os.environ, "HOLOJOB_APPLICATION_JOB_IDS": str(export_application_ids(tmp)),
               "HOLOJOB_PACKAGE_REPORT": str(row.staging)}
        subprocess.run(argv, cwd=row.worktree, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, env=env)
    # Move the report out of the worktree to its git-ignored home; the verdict never comes from the exit code.
    final = REPORTS / row.report_name
    if row.staging.is_file():
        row.staging.replace(final)
        final.chmod(0o600)
    tip = git("rev-parse", "HEAD", repo=row.worktree)
    if tip == base_sha:
        return f"no commit on {row.branch} (session log {log})"
    if git("status", "--porcelain", repo=row.worktree):
        return f"uncommitted changes left in {row.worktree} (session log {log})"
    if not final.is_file():
        return f"no report written (session log {log})"
    status = report_status(final.read_text(encoding="utf-8", errors="replace"))
    if status in ("blocked", "needs-review"):
        return f"{status}: see {final}"
    if status != "done":
        return f"not done: report {final} has no Status: done line (session log {log})"
    gate_log = logdir / f"{row.n:02d}-{stamp}-gate.log"
    if not gate(row, tip, base_sha, gate_log):
        return f"not done: full tier red on {tip[:12]} (log {gate_log})"
    st, detail = package_state(row)
    print(f"run-packages: package {row.n} {row.slug}: {st} ({detail})")
    return st


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run-packages", description=__doc__.split("\n\n")[0])
    ap.add_argument("package", nargs="?", type=int)
    ap.add_argument("--through", type=int)
    ap.add_argument("--base", default="main")
    a = ap.parse_args(argv)
    if a.package is not None and a.through is not None:
        raise SystemExit("run-packages: give N or --through M, not both")
    text = git("show", f"{a.base}:{PLAN}", check=False)
    if not text:
        raise SystemExit(f"run-packages: {PLAN} not found at {a.base} (use --base package-runner until it is merged)")
    rows = parse_table(text)
    return run_all(select(rows, a.package, a.through), package_state, lambda r: run_one(r, rows, a.base))


if __name__ == "__main__":
    sys.exit(main())
