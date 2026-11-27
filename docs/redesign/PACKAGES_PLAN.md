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

   Status 2026-11-27: all five points are committed (`9eb3ccf`, `1c07e0d`, `8f49e74`; 0 of 16 must-keep ads lost (first written as 19: three comment lines of the ids file were counted)). What remains is the benchmark-first check, which the headless sessions could not do because benchmark reads were denied: open the career-ops files the report cites (`company_key.py` sources, `filter-audit.mjs`, `classify-tier.mjs`, `title-keywords.mjs`, `role-matcher.mjs`), confirm or correct the sources and deviations in the docs and the report, and end with a commit of its own (the runner's mark). It is small, so it is not split.
4. **Round 2 text rules.** Language, years, on-site only, visa and employment type, as hard/soft/unknown labels. Acceptance, measured like package 3 (`scripts/measure_package3.py` is the pattern; no model call, real data read-only, counts and public titles only):
   - every rule has its class (hard, soft or unknown) and its stated text in Settings or the docs; unknown continues, years, seniority and domain stay labels, and a drop by rule never pins dedup;
   - **the 16 must-keep ads** (Saved, Rejected and Applied, one count per ad): the report lists, before and after the new rules, how many are kept and their ids. All 16 must be kept after, otherwise the package is `blocked` (stop rule);
   - **the effect on real data**, counts only, per rule and in total: of the ledger rows and the filtered rows, how many ads change decision (kept to dropped, dropped to kept, kept with a new label only), and how many ads each rule touches alone. A rule that changes more than the report can explain by examples (public titles) is reported, not tuned;
   - the measurement script is committed, so the numbers can be repeated.

**Cost and scoring time** (the former package 5, split on 2026-11-27 into one package per point; content unchanged, every part needs 2). Each part has its own commit and report, and its acceptance below:

5. **Failure stop.** Reading and engine fill stop after 3 consecutive failures. Acceptance: tests show that the 3rd consecutive failure stops the step, a success resets the count, and nothing else in the step changes.
8. **p90 setting.** `estimatedOutputTokens` = p90 from the ledger, in Settings. Acceptance: the value comes from Settings and its default is the measured p90 (count and value in the report); cost accounting is unchanged.
9. **Scoring pass speed.** This applies the package 2 finding (FREE_MEASUREMENTS §1): fold each ad once in `location_text._restrictions`, and compute `resolve_places` once per row. Acceptance: the output is identical row for row before and after on the real ledger (a copy in a temp dir), and the pass time is reported before and after.
10. **scoring-prepare limit.** `scoring-prepare` is limited per the findings of package 2: today a Re-scrape runs up to three `scoring-prepare` passes plus the final `scoring` (FREE_MEASUREMENTS §1). Needs 9, so that the limit is measured on the faster pass (own proposal for the order). Acceptance: the number of passes and the time per Re-scrape are reported before and after, and the final scores are unchanged. Unchanged also means the same ads are selected for the paid steps (reading, engine fill, Fit 3 classify) before and after: the report compares the selected id sets of each paid step on a copy of the real ledger in a temp dir (equal sets, or every difference listed by id and explained), not only the final scores. A selection that differs without an explanation is a stop rule.

    **Closed 2026-11-27 (owner): accept three scoring-prepare passes.** No limit is built. Reason: both real runs spent about 99.5% of the USD budget, so a skip rule would never fire; package 9 already cut the pass time by 39%. The finding that no cap keeps the selection and the scores is in `docs/DECISIONS.md` ("scoring-prepare limit, package 10"). The acceptance above is void.
11. **Prompt layout, two versions.** The Fit 3 lists go before the title and the ad (FREE_MEASUREMENTS §2), released as two separate versions: the layout, and the validity of the extracted facts. Acceptance: two parts.
    - **Quality:** the Stage A calibration check passes for both versions, and nothing is re-read by force.
    - **Proof that caching works:** the usage record of a Fit 3 call shows cached input tokens above zero from the second call on (`cache_read_input_tokens` or the gate's own cached-token field, whichever the ledger records; the report names the field). This needs a few paid calls, and only the owner runs paid calls: the package makes none. It writes the exact fish commands for the owner (an estimate first, `--confirm`, `--max-usd`, 3 to 5 calls, with the cost cap), the expected numbers (first call: cached tokens 0 and the prefix about 4.2k tokens written; later calls: cached tokens at or near the shared prefix, from FREE_MEASUREMENTS §2), and what a failure looks like (zeros on every call: the prefix is below the provider's minimum, or it differs between calls). The package is `done` with the commands written; the owner's result is recorded in DECISIONS afterwards.

**Missing descriptions** (the former package 6, split on 2026-11-27, own proposal). It was clearly too large for one session: five independent changes, two of them new UI (a paste box, and a diff view). Content unchanged:

6. **Retry of empty descriptions.** The retry as above, with per-run stats.
12. **Paste box** for discovered ads (needs 6).
13. **Refresh from the employer page**, shown as a diff with the original kept (needs 6).
14. **Deferred fetch and the JobSpy pin** (needs 6). Pin the JobSpy version and test the private `_fetch_details` call. Then the deferred fetch: package 2 shows a gain (up to about 75% of LinkedIn detail requests, FREE_MEASUREMENTS §3); whether JobSpy allows a per-ad fetch is open. **Before building anything, re-measure the estimated saving** on the filter as it will be after packages 3 and 4: the share of kept ads that are new to the ledger and the share of detail requests that the filters and the ledger make unnecessary (counts only, the method of FREE_MEASUREMENTS §3, which was measured before the round-1 and round-2 rules). If the saving after the filter changes is below the cost of the change, the package reports that and builds nothing (`Status: needs-review` with the numbers; the deferred fetch is the owner's decision then). Package 14 needs 4 for this reason.

7. **Reposts** (needs 3): as above.

15. **Private file modes for the job and cache writers** (own proposal, 2026-11-27; needs nothing). Route every writer of `data/jobs/*.json`, `data/cache/*.json` and the competency-audit scratch files (`python/match_engine/competency_audit.py` and whatever it writes) through the private-mode helper (`atomic_write`: files 600, directories 700; `.claude/rules/private-file-modes.md`). Behaviour otherwise identical: same content, same paths, same atomicity. Acceptance: a test that a rewritten file in each of those families stays 600 (and its directory 700) after a second write, including when it was 644 before the first write; a one-off fix of the modes already on disk, written as an owner command in the report (a `find ... -exec chmod` for `data/jobs`, `data/cache` and the audit scratch directory, with a dry-run listing first), never run by the package; the full tier unchanged.

**Order:** 1 and 2 first. Then 3, then the cost parts 5, 8, 9, 10 and 11. Then 4, the missing-description parts 6, 12, 13 and 14, and 7. Package 15 is independent and last. Package 14 comes after 4 because its saving is measured on the final filters.

Packages 4 and 7 are each one mechanism with closed rules, so they stay whole.

## Package table

`status` values: `pending | in-progress | needs-review | blocked | done`. The session sets its package's row in the package's own commit, from the report's first line (`done` when its own work is complete; the full tier is the runner's job). The table is informational: the runner's state (`.claude/package-runs/state.json`) decides what is done. Status as of 2026-11-27 against `state.json`: 1, 2, 3, 5, 8 and 9 have a recorded full-tier tip. Package 10 is closed by owner decision (below) and has no recorded tip yet: `--regate 10` records it once the branch tip passes the full tier.

<!-- packages:start -->
| N | slug | model | needs | order | status | commit |
|---|---|---|---|---|---|---|
| 1 | archive-history | claude-sonnet-5-5 | - | 1 | done | list-cleanup |
| 2 | free-measurements | claude-sonnet-5-5 | - | 2 | done | list-cleanup |
| 3 | filter-foundation | claude-sonnet-5-5 | - | 3 | done | list-cleanup |
| 5 | failure-stop | claude-sonnet-5-5 | 2 | 4 | done | list-cleanup |
| 8 | p90-setting | claude-sonnet-5-5 | 2 | 5 | done | list-cleanup |
| 9 | scoring-pass-speed | claude-sonnet-5-5 | 2 | 6 | done | list-cleanup |
| 10 | scoring-prepare-limit | claude-sonnet-5-5 | 2, 9 | 7 | done | list-cleanup |
| 11 | prompt-layout | claude-sonnet-5-5 | 2 | 8 | done | list-cleanup |
| 4 | text-rules-round2 | claude-sonnet-5-5 | 3 | 9 | done | list-cleanup |
| 6 | description-retry | claude-sonnet-5-5 | 2 | 10 | done | list-cleanup |
| 12 | paste-box | claude-sonnet-5-5 | 6 | 11 | done | list-cleanup |
| 13 | employer-refresh | claude-sonnet-5-5 | 6 | 12 | done | list-cleanup |
| 14 | deferred-fetch | claude-sonnet-5-5 | 2, 4, 6 | 13 | done | list-cleanup |
| 7 | reposts | claude-sonnet-5-5 | 3 | 14 | done | list-cleanup |
| 15 | private-mode-writers | claude-sonnet-5-5 | - | 15 | done | list-cleanup |
<!-- packages:end -->

Needs 14→4 comes from the 2026-11-27 re-measure rule (the saving is re-measured after the filter changes). Needs 5→2 and 7→3 are from the plan, and so are 8, 9 and 11→2: every former package 5 point inherits the "needs 2". 4→3 and 6→2 are inferred from the order. 10→9, 12→6, 13→6 and 14→6 come from the 2026-11-27 split. These are own proposals; undo one by editing `needs`. Package numbers stay stable (the runner state and the report names use them), so the new parts take numbers 8 to 14 and the `order` column sets the sequence. `model` is the owner's choice per session (`/model`).

## How to run a package

The owner runs each package by hand:

1. Start a new Claude Code session in `/srv/holojob` and type `/clear`.
2. Set the model from the table (`/model`).
3. Type: `do package N from the plan`.

What the session does:

1. **Start.** It reads this plan, CLAUDE.md and the rules. Every package works on the one feature branch `list-cleanup` (owner decision 2026-11-26; it replaces the per-package branches stacked on each other of 2026-11-25): its work is one or more commits on that branch, after the previous package's commits.
2. **Data.** It reads `/srv/holojob/data` directly. The worktree's own `data/` holds only tracked files. It writes nothing under `data/`.
3. **Work and tests.** It implements only package N and runs the targeted tests while it works, then the full tier.
4. **Permanent docs.** In the package commit, it describes the feature in the repo's own docs: DECISIONS.md, ROADMAP.md and the feature md (for example the area's plan or spec under `docs/redesign/`).
5. **Report (temporary, never committed).** It writes `/srv/holojob/.claude/package-runs/reports/NN-slug.md` from `scripts/package-report-template.md`. In a headless run it writes to the path in `HOLOJOB_PACKAGE_REPORT` instead, a git-ignored file in the worktree that the runner moves there. The first line is `Status: done | blocked | needs-review`: `done` when its own work is complete (the full tier is the runner's job, not a condition), `blocked` or `needs-review` only with the reason stated in "Blocked or needs owner" (a report with None there does not stop the chain). Three people review it (the owner and two reviewers), so it is detailed:
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
scripts/run-packages               # all pending, in table order (any cwd: /srv/holojob/scripts/run-packages)
scripts/run-packages --through 3   # pending packages in table order up to package 3
scripts/run-packages 2             # package 2 only
scripts/run-packages --regate 1    # full tier on the branch tip, recorded as package 1's pass
scripts/run-packages --mark-tip 3  # package 3 (in progress) must add a commit after the current branch tip
```

**Where the runner lives.** Run it from a checkout outside the run worktree (it refuses a copy inside it: sessions can edit every file there, and it installs the node helper from its own directory), for example a detached checkout `.claude/worktrees/package-runner-bin` of the reviewed runner commit.

**One branch, one worktree.** All packages are commits on `list-cleanup`, in the one worktree `.claude/worktrees/list-cleanup` (re-attached if removed; the branch is created from `--base`, default `main`, only if it does not exist). The plan is read from `list-cleanup`. The runner state `.claude/package-runs/state.json` (git-ignored, mode 600) records per package the tip that passed the full tier, its base (the previous package's recorded tip) and the time, plus the last recorded tip and the package in progress with its base.

**Regate.** `--regate N` runs `sh scripts/test-tier.sh full` (the branch's copy) on the branch tip and, when it passes, records the tip for package N with the base above; a red tier records nothing (log `.claude/package-runs/NN-<time>-regate.log`). It refuses a dirty worktree, another package in progress, a package N that is recorded but no longer the last one, and a tip with no commit since the base. Use it after fixing a red gate by hand. With nothing recorded yet, the base is where the branch left `--base`.

**Mark.** When runner or plan commits land on `list-cleanup` while a package is in progress, `--mark-tip N` records the branch head as package N's `after` mark in the state (the base stays). Package N is then done, in the run, in `--regate` and in the done check, only with at least one commit after the mark, so the runner's own commits never count as the package's work; the resume prompt says so. It refuses when N is not the package in progress or the head does not descend from N's base. (2026-11-27: the runner fixes landed during package 3.)

**Live progress.** The session runs with `--output-format stream-json --verbose` (Claude Code docs, "Run Claude Code programmatically", Stream responses: the examples all use both flags; `--include-partial-messages` is not used). Per tool call the runner prints one line and appends it to `.claude/package-runs/progress.log` (mode 600): time, `package N (position of total) slug`, elapsed time, the session's turn count and the last tool or file, for example `01:52:07  package 9 (6 of 14) scoring-pass-speed  +12m03s  turn 41  Edit python/job_scoring/location_text.py`. Start and end lines (session start, ended with N turns, full tier running, paused or done) go to the same file. The event shapes (`assistant` blocks with `tool_use`, `rate_limit_event`, `result`) are not in the CLI docs, so they were probed live on Claude Code 2.1.331 on 2026-11-27 and are covered by tests. The raw stream of each session is kept in `NN-<time>.stream.jsonl`, stderr in `NN-<time>.stderr`, and the final `result` event, the object `--output-format json` printed before, stays in `NN-<time>.json`.

```fish
tail -f /srv/holojob/.claude/package-runs/progress.log
```

**Refusals.** It refuses to start when:
- `/srv/holojob` has a dirty tree;
- another package is in progress on the branch;
- for a new package: the branch has commits since the last recorded tip (they belong to no package), or the worktree has uncommitted changes;
- the package itself is `blocked` or `needs-review` with a stated reason (the owner decides first);
- a needed package is not done.

**Resume.** If the state names the package as in progress and it is unfinished (no report, a report without a valid status, a paused usage limit, or a red gate), the runner resumes it. That covers a stopped session, a missing commit or a red gate:
- it reuses the worktree, with the uncommitted changes kept, never discarded or reset;
- it moves the previous report back into the worktree, so the session continues it;
- the prompt tells the session it is a resumed run;
- the base stays the one recorded when the package started.

**Per package**, the runner:
1. **Prepares.** It attaches the worktree and, for a new package, records it as in progress with the last recorded tip as its base. It installs the runner's own copy of `scripts/node-sandbox` at `.claude/package-runs/bin/node-sandbox`. It also writes the application-id export to a temp file (ids only, mode 600, removed after the session) for the must-keep set.
2. **Runs the session** in that worktree. The prompt is `do package N from docs/redesign/PACKAGES_PLAN.md`, followed by the headless rules below (and the resume note when resuming). The session commits on `list-cleanup`, never creates or switches branches, and reads `/srv/holojob/data` directly.
3. **Moves the report** from the worktree's git-ignored `logs/package-report-NN-slug.md` to `.claude/package-runs/reports/NN-slug.md`. Claude Code refuses headless writes under `.claude/` as a "sensitive file", even with `--add-dir` and an allow rule (checked 2026-11-26). The staging file is seeded from the template, whose first line `Status: in-progress` never counts as done.
4. **Decides from files and git, never from the exit code or the session's word** (owner decision 2026-11-27: done is the runner's decision). The package is done only when all of these hold:
   - `.claude/package-runs/reports/NN-slug.md` exists with a valid first line. `Status: done` counts. `blocked` and `needs-review` count as done too when "Blocked or needs owner" says None (or n/a, nothing); with a stated reason, or no such section, they stop the chain for the owner. An untouched template (`Status: in-progress`) or a missing Status line is not done;
   - there is at least one commit on `list-cleanup` since the previous package's recorded tip;
   - the worktree is clean;
   - `sh scripts/test-tier.sh full` passed on the tip; the runner then records the tip in the state (done stays done while that tip is on the branch, after later packages too).
5. **Pauses on a usage limit.** When the session's last event is the account's limit ("You've hit your 5-hour limit · resets 12:50am (Europe/Belgrade)", `is_error` with `api_error: usage_limit_reached`) and the package is not otherwise done, the run prints `paused: usage limit, resets 00:50 (Europe/Belgrade)` and exits with code 75. This is not a failure and not a stop: the package stays in progress and the same command resumes it. The runner never waits for the reset and never changes a limit (standing rule 1).
6. **Stops** at the first package that is not done, blocked or needs-review. Packages already done are skipped, after the same four checks. A report left by an abandoned run is renamed `.old-<time>` and never trusted.

**In headless sessions:**
- **No questions, ever.** The session never asks the owner a question and never ends with one. Any blocking case or open decision goes into the report as `Status: blocked`; the session commits the work so far and ends. The prompt says so.
- **No approvals.** A call that needs approval is denied, never waited for (Claude Code docs: permission modes, headless).
- **Permission mode** `acceptEdits`: file edits inside the worktree only.
- **Allowed Bash:** `git status`, `git diff`, `git log`, `git show`, `git add`, `git commit`, `git rm`, `git mv`, `git ls-files`, `git grep`, `git rev-parse`; the venv python; `graphify`; the node helper `/srv/holojob/.claude/package-runs/bin/node-sandbox`. Read-only commands such as `grep`, `ls` and `cat` work inside the working directories (the worktree and the benchmarks). Everything else is denied.
- **Benchmarks, read-only.** `/home/ranikola/holojob-eval/benchmarks` is an `--add-dir`, with `Edit` and `Write` denied there. Claude Code 2.1.331 has no Grep or Glob tool, so searching is Bash `grep`, which is auto-allowed only in working directories. A live `-p` probe on 2026-11-27 with the runner's own argv:
  - Read, `grep` and `ls` there work;
  - Write, Edit, `touch`, `mkdir`, `cp`, `sed -i` and a redirect there are all denied (under `acceptEdits` the Edit deny also covers Bash writes in an added dir);
  - `git` there needs approval, so it is denied: the clones are untrusted.
  The files are also read-only on disk.
- **Paths in the prompt.** The prompt names the exact paths so that a session does not spend calls looking for them (package 3 tried `printenv`, `ls` of the reports directory and earlier reports):
  - the staging report (also `$HOLOJOB_PACKAGE_REPORT`);
  - the application-ids file (also `$HOLOJOB_APPLICATION_JOB_IDS`; a Read allow covers exactly that file);
  - the scratch dir, the worktree's git-ignored `logs/` (`/tmp` is outside the working directories);
  - the data and the benchmarks.
  It also says that everything else under `.claude/` is denied, and that a Bash call is one command: a compound `cd X; …` or `…; echo` is denied as a whole.
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

  Every file must lie inside the worktree: no absolute path, `..`, symlink out or option-like name, and no other flags. Script arguments are limited to plain characters. It runs only from the `list-cleanup` worktree.
- **Tests:** the session runs pytest, plus Vitest and lint through the helper. The runner runs the full tier, the build included, on the branch tip.

**Project deny rules (`.claude/settings.json`, every session):** `git push`, `podman-compose`, `systemctl`; edits and writes under `/srv/holojob/data` (Edit and Write tools); reads of `.env`, `claude-config` and `data/secrets`. Project deny rules apply in `-p` without the trust dialog.

**What this cannot enforce (no sandbox):**
- **The rules only see the command as typed.** Any allowed command can run something else: the venv python can call `subprocess` and run `git push`, podman or a provider call, write under `data/`, or read a secret. So can a test the session writes, which the runner's full tier then runs with the owner's rights.
- **Bash rules miss variants.** `Bash(git push *)` does not stop `git -C dir push` (Claude Code docs, permissions). `Read` denies do not stop `cat` through an allowed command, and they apply to Grep and Glob only "best-effort".
- **The owner's keys stay reachable.** The login, ssh key, gh token and provider keys are readable by any process the session starts. Nothing technical stops a paid call or a push. The plan's rules, the denies and the owner's review of the branch before merging are the only guard.
