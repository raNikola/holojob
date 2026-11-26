# Packages plan: archive, measurements, filters, cost, descriptions, reposts

Owner plan of 2026-11-25. The owner runs each package in a normal interactive Claude Code session, one package per session: see "How to run a package" below. Reports are temporary and never committed: `/srv/holojob/.claude/package-runs/reports/NN-slug.md` (git-ignored), from `scripts/package-report-template.md`. The permanent description of each feature goes into the repo's own docs in the package commit.

## Closed decisions (owner)

- Archive N = the existing `activeWindowDays` (14, Settings).
- Saved ads are never archived. Applications are never archived. Kept ads are never archived (owner 2026-11-26).
- Archived (unseen for N days) and Expired (deadline passed, or confirmed closed) are two separate reasons.
- An archived ad that reappears and passes the current filters returns to Jobs, unless the user rejected it.
- History replaces All ads as a second view of the same data. It is searchable by company, title and reason.
- Nothing is deleted.
- A drop by rule never pins dedup.
- Rules come in three classes: hard, soft and unknown. Years, seniority and domain are labels only. Unknown continues.
- "project manager" is not a hard negative.
- A title that misses the list goes to a free-text check. An empty description does not drop the ad.
- Easy Apply is out.
- Cost accounting and scoring are unchanged.
- `estimatedOutputTokens` = p90 from the ledger, in Settings.
- A prompt layout change only comes with two separate versions (layout, and validity of the extracted facts) and a Stage A calibration check. No forced re-reading.
- Retry of empty descriptions:
  - per ledger ad, not per search result;
  - 1 retry in the next scan, max 2 in total;
  - the counts live in Settings;
  - an empty detail reply never means expiry.
- Repost counter by rule. All of these must hold:
  - same company key;
  - same title word set;
  - different URL;
  - at least 2 dates;
  - same source host;
  - within 90 days.

  The crosspost loser URL is kept. SimHash is a note only (min 400 chars, Hamming <= 7).
- Data file modes 600 is the owner's command.

## Rules for every package

- **Benchmark first.** Open the repo files in `/home/ranikola/holojob-eval/benchmarks/` directly (read-only).
- **Name the source of each design element:** benchmark file, owner decision, or own proposal. Flag every deviation from the benchmark.
- **Limits and thresholds the owner decides live in Settings.**
- **Real data, read-only.** Measurements read `/srv/holojob/data` directly. Measurements and tests write only to temp dirs, never under `data/`. Reports carry counts, ids and public ad titles only, never private content.
- **Tests run in a temp dir, never `data/`.** Run the targeted tests per change, and the full tier (CLAUDE.md, "Testing and commit policy") before a package is set to done.
- **Code and comments in English.**
- **No hot patches.** Build, up, push and deploy are the owner's.
- **No questions.** Trivial matters take the benchmark or standard choice, recorded under "Defaults taken" in the report with its source and how to undo it.

## Stop rules (status `blocked`)

A package stops as blocked on any of these:
- a risk of irreversible data loss;
- any ad of the must-keep set (below) stops being kept;
- a limit is reached;
- tests are still red after one fix attempt;
- a real product decision that this plan leaves undefined and that no benchmark, standard practice or earlier owner decision settles.

**Must-keep set.** The owner's Applied, Saved and Rejected ads, with an ad that has two of these counted once. It is computed from the real data when needed and not stored:
- **Saved and Rejected:** `status` in `/srv/holojob/data/jobs/job-state.json`.
- **Applied:** the job ids from `scripts/export-application-job-ids.js`, because Python does not read the application store (TRACKER_PLAN 6a).

  In an interactive session, run the export into a temp file. In a headless run, the runner writes it before the session and passes the path in `HOLOJOB_APPLICATION_JOB_IDS`.

Blocked means: write the reason in the report, put `Status: blocked` on its first line, commit the work so far, and stop.

## Packages

1. **Archive and History.** Implement the rule above. Measure the Active list by days since last seen and by status, before and after (counts only). Saved, applied and kept ads are never archived; Rejected ads are archived after N days like any other (owner decisions 2026-11-26). An ad past its deadline leaves Active unless it is Saved, applied or kept; those stay with the Expired badge.
2. **Free measurements, no changes:**
   - one scoring pass, profiled offline on a copy (cause of the 12x slowdown);
   - prompt section sizes, and whether the first 1,024 tokens are identical across calls;
   - the share of LinkedIn detail requests in scan time;
   - an audit of negative filters per keyword (unique metric, career-ops filter-audit).
3. **Filter foundation and round 1:**
   - the vocabulary moves out of `role_filter.py` into Settings;
   - a normalized company key, and first/last seen dates, on ledger and filtered rows;
   - filtered sightings do not refresh `lastListedAt`;
   - the must-keep set (Applied/Saved/Rejected) as a check the round-1 rules are measured on;
   - the round-1 rule changes are measured on that set.
4. **Round 2 text rules.** Language, years, on-site only, visa and employment type, as hard/soft/unknown labels.
5. **Cost and scoring time** (needs 2):
   - stop after 3 consecutive failures in reading and in engine fill;
   - the p90 setting;
   - the prompt layout with two versions;
   - scoring-prepare limited per the findings of package 2.
6. **Missing descriptions:**
   - the retry as above, with per-run stats;
   - a paste box for discovered ads;
   - refresh from the employer page, shown as a diff with the original kept;
   - deferred fetch only if package 2 shows a gain;
   - pin the JobSpy version and test the private `_fetch_details` call.
7. **Reposts** (needs 3): as above.

**Order:** 1 and 2 first, then 3 and 5 (independent), then 4, 6, 7.

## Package table

`status` values: `pending | in-progress | needs-review | blocked | done`. The session sets its package's row in the package's own commit, from the report's first line, and only after the full tier is green.

<!-- packages:start -->
| N | slug | model | needs | order | status | commit |
|---|---|---|---|---|---|---|
| 1 | archive-history | claude-sonnet-5-5 | - | 1 | done | pkg/01-archive-history |
| 2 | free-measurements | claude-sonnet-5-5 | - | 2 | pending | - |
| 3 | filter-foundation | claude-opus-5-5 | - | 3 | pending | - |
| 5 | cost-scoring-time | claude-opus-5-5 | 2 | 4 | pending | - |
| 4 | text-rules-round2 | claude-sonnet-5-5 | 3 | 5 | pending | - |
| 6 | missing-descriptions | claude-sonnet-5-5 | 2 | 6 | pending | - |
| 7 | reposts | claude-sonnet-5-5 | 3 | 7 | pending | - |
<!-- packages:end -->

Needs 5→2 and 7→3 are from the plan. 4→3 and 6→2 are inferred from the order (own proposal; undo by editing `needs`). `model` is the owner's choice per session (`/model`).

## How to run a package

The owner runs each package by hand:

1. Start a new Claude Code session in `/srv/holojob` and type `/clear`.
2. Set the model from the table (`/model`).
3. Type: `do package N from the plan`.

What the session does:

1. **Start.** It reads this plan, CLAUDE.md and the rules. It works in a worktree on its own branch `pkg/NN-slug`, stacked on the last done package's branch (owner decision 2026-11-25), or on `main` when none is done.
2. **Data.** It reads `/srv/holojob/data` directly. The worktree's own `data/` holds only tracked files. It writes nothing under `data/`.
3. **Work and tests.** It implements only package N and runs the targeted tests while it works, then the full tier.
4. **Permanent docs.** In the package commit, it describes the feature in the repo's own docs: DECISIONS.md, ROADMAP.md and the feature md (for example the area's plan or spec under `docs/redesign/`).
5. **Report (temporary, never committed).** It writes `/srv/holojob/.claude/package-runs/reports/NN-slug.md` from `scripts/package-report-template.md`. In a headless run it writes to the path in `HOLOJOB_PACKAGE_REPORT` instead, a git-ignored file in the worktree that the runner moves there. The first line is `Status: done | blocked | needs-review`. Three people review it (the owner and two reviewers), so it is detailed:
   - for each change: what and why, with its source (benchmark file, owner decision or own proposal), the files and functions changed, and the behaviour before and after;
   - defaults taken, with how to undo each;
   - deviations from the benchmark;
   - measurements, counts only;
   - tests and their results;
   - risks, and what was not done;
   - "How the owner tests this": exact fish commands with the expected result of each;
   - the owner's merge, build, up and rollback commands.
6. **Commit and stop.** It sets the package's row in the table and commits with the owner as the only author. The commit holds code, tests and permanent docs, never the report. It stops at the commit and points to the report. No push, no build, no deploy.

A stop rule means: `Status: blocked`, the reason in the report, commit, stop. There are no questions for trivial matters: the session takes the benchmark or standard choice and records it under "Defaults taken".

### Headless: `scripts/run-packages`

Optional. It runs the pending packages in table order, one fresh `claude -p` session each, on the owner's normal login, with the model from the table. The prompt is `do package N from docs/redesign/PACKAGES_PLAN.md`.

```fish
cd /srv/holojob
scripts/run-packages --base package-runner              # all pending (--base only until this plan is on main)
scripts/run-packages --through 3 --base package-runner  # pending packages in table order up to package 3
scripts/run-packages 2 --base package-runner            # package 2 only
```

**Refusals.** It refuses to start when:
- `/srv/holojob` has a dirty tree;
- another package's `pkg/*` branch is not done;
- the package itself is `blocked` or `needs-review` (the owner decides first);
- a needed package is not done.

**Resume.** If the package's own branch exists and the package is unfinished (no report, or a report without `Status: done|blocked|needs-review`), the runner resumes it. That covers a stopped session or a missing commit:
- it reuses `pkg/NN-slug` and its worktree, with the uncommitted changes kept, never discarded or reset (the worktree is re-attached if it was removed);
- it moves the previous report back into the worktree, so the session continues it;
- the prompt tells the session it is a resumed run;
- the base stays where the branch left the stack.

**Per package**, the runner:
1. **Prepares.** For a new package, it creates the worktree `.claude/worktrees/pkg-NN-slug` on `pkg/NN-slug`, stacked on the last done package; on resume, it reuses both. It installs the runner's own copy of `scripts/node-sandbox` at `.claude/package-runs/bin/node-sandbox`. It also writes the application-id export to a temp file (ids only, mode 600, removed after the session) for the must-keep set.
2. **Runs the session** in that worktree. The prompt is `do package N from docs/redesign/PACKAGES_PLAN.md`, followed by the headless rules below (and the resume note when resuming). The session finds its branch ready, works there and reads `/srv/holojob/data` directly.
3. **Moves the report** from the worktree's git-ignored `logs/package-report-NN-slug.md` to `.claude/package-runs/reports/NN-slug.md`. Claude Code refuses headless writes under `.claude/` as a "sensitive file", even with `--add-dir` and an allow rule (checked 2026-11-26). The staging file is seeded from the template, whose first line `Status: in-progress` never counts as done.
4. **Decides from files and git, never from the exit code.** The package is done only when all of these hold:
   - `.claude/package-runs/reports/NN-slug.md` exists and its first line is `Status: done`;
   - there is a commit on `pkg/NN-slug` after the base;
   - the worktree is clean;
   - `sh scripts/test-tier.sh full` passed on the branch tip, recorded with the base sha as a local git note in `refs/notes/package-gate`.
5. **Stops** at the first package that is not done, blocked or needs-review. Packages already done are skipped, after the same four checks. A report left by an abandoned run is renamed `.old-<time>` and never trusted.

**In headless sessions:**
- **No questions, ever.** The session never asks the owner a question and never ends with one. Any blocking case or open decision goes into the report as `Status: blocked`; the session commits the work so far and ends. The prompt says so.
- **No approvals.** A call that needs approval is denied, never waited for (Claude Code docs: permission modes, headless).
- **Permission mode** `acceptEdits`: file edits inside the worktree only.
- **Allowed Bash:** `git status`, `git diff`, `git log`, `git show`, `git add`, `git commit`, `git rm`, `git mv`, `git ls-files`, `git grep`, `git rev-parse`; the venv python; `graphify`; the node helper `/srv/holojob/.claude/package-runs/bin/node-sandbox`. Everything else is denied.
- **Denied for these sessions only:** podman, `scripts/test-tier.sh`, `git remote`, `AskUserQuestion`, plan mode, worktree switching, web tools. This is owner decision 2026-11-26: interactive sessions keep the node test container.
- **Node helper** (`scripts/node-sandbox`; only the runner's installed copy is allowed, so a session cannot widen it by editing the worktree's file). The session runs Vitest, ESLint and node measurement scripts through it:
  - `node-sandbox vitest tests/js/FILE.test.js ... [--reporter=dot|default|verbose]`
  - `node-sandbox lint [FILE ...]`
  - `node-sandbox node SCRIPT.js [ARG ...]`

  It runs one fixed container:
  - `node:20-bookworm`, `--network none`, `--security-opt label=disable`;
  - the package worktree read-write;
  - `/srv/holojob/data` read-only, at its own path, with `data/secrets` masked by an empty tmpfs (`notmpcopyup`, checked: 0 files visible);
  - the shared `node_modules` as a podman overlay: Vitest writes its temp config there, the writes are discarded and the host copy never changes.

  Every file must lie inside the worktree: no absolute path, `..`, symlink out or option-like name, and no other flags. Script arguments are limited to plain characters. It runs only from a `pkg-NN-*` worktree.
- **Tests:** the session runs pytest, plus Vitest and lint through the helper. The runner runs the full tier, the build included, on the branch tip.

**Project deny rules (`.claude/settings.json`, every session):** `git push`, `podman-compose`, `systemctl`; edits and writes under `/srv/holojob/data` (Edit and Write tools); reads of `.env`, `claude-config` and `data/secrets`. Project deny rules apply in `-p` without the trust dialog.

**What this cannot enforce (no sandbox):**
- **The rules only see the command as typed.** Any allowed command can run something else: the venv python can call `subprocess` and run `git push`, podman or a provider call, write under `data/`, or read a secret. So can a test the session writes, which the runner's full tier then runs with the owner's rights.
- **Bash rules miss variants.** `Bash(git push *)` does not stop `git -C dir push` (Claude Code docs, permissions). `Read` denies do not stop `cat` through an allowed command, and they apply to Grep and Glob only "best-effort".
- **The owner's keys stay reachable.** The login, ssh key, gh token and provider keys are readable by any process the session starts. Nothing technical stops a paid call or a push. The plan's rules, the denies and the owner's review of each branch before merging are the only guard.
