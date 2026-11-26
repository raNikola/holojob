# Packages plan: archive, measurements, filters, cost, descriptions, reposts

Owner plan of 2026-11-25. Each package runs in its own fresh headless Claude Code session, through `scripts/run-package` (runner: `scripts/run_package.py`). The runner, not the session, decides whether a package is done: see "Runner" below. Reports: `docs/redesign/reports/NN-slug.md` from `reports/TEMPLATE.md`.

## Closed decisions (owner)

- Archive N = the existing `activeWindowDays` (14, Settings).
- Saved ads are never archived. Applications are never archived.
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
- **Tests run in a temp dir, never `data/`.** Run the targeted tests per change. The runner's sandboxed full tier must be green before a package is done.
- **Code and comments in English.**
- **No hot patches.** Build, up, push and deploy are the owner's.
- **No questions.** Trivial matters take the benchmark or standard choice, recorded under "Defaults taken" in the report with its source and how to undo it.

## Stop rules (status `blocked`)

A package stops as blocked on any of these:
- a risk of irreversible data loss;
- any of the 19 labelled ads stops being kept (must-keep set: `data/derived/labelled-ads.json`);
- a limit is reached;
- tests are still red after one fix attempt;
- a real product decision that this plan leaves undefined and that no benchmark, standard practice or earlier owner decision settles.

Blocked means: write the reason in the report, put `Status: blocked` on its first line, commit, and stop.

## Packages

1. **Archive and History.** Implement the rule above. Measure the Active list by days since last seen and by status, before and after (counts only). The 19 labelled ads are unaffected.
2. **Free measurements, no changes:**
   - one scoring pass, profiled offline on a copy (cause of the 12x slowdown);
   - prompt section sizes, and whether the first 1,024 tokens are identical across calls;
   - the share of LinkedIn detail requests in scan time;
   - an audit of negative filters per keyword (unique metric, career-ops filter-audit).
3. **Filter foundation and round 1:**
   - the vocabulary moves out of `role_filter.py` into Settings;
   - a normalized company key, and first/last seen dates, on ledger and filtered rows;
   - filtered sightings do not refresh `lastListedAt`;
   - a must-keep set of the 19 labelled ads;
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

The runner reads this table. `status` is written by the runner only, from its own checks (state file outside the repo + commit + report in that commit + sandboxed gate). A session never edits it. Values: `pending | in-progress | needs-review | blocked | done`. The runner treats a diff that touches this table as needs-review.

<!-- packages:start -->
| N | slug | model | needs | order | maxTurns | status | commit |
|---|---|---|---|---|---|---|---|
| 1 | archive-history | claude-sonnet-5-5 | - | 1 | 400 | pending | - |
| 2 | free-measurements | claude-sonnet-5-5 | - | 2 | 400 | pending | - |
| 3 | filter-foundation | claude-opus-5-5 | - | 3 | 400 | pending | - |
| 5 | cost-scoring-time | claude-opus-5-5 | 2 | 4 | 400 | pending | - |
| 4 | text-rules-round2 | claude-sonnet-5-5 | 3 | 5 | 400 | pending | - |
| 6 | missing-descriptions | claude-sonnet-5-5 | 2 | 6 | 400 | pending | - |
| 7 | reposts | claude-sonnet-5-5 | 3 | 7 | 400 | pending | - |
<!-- packages:end -->

Needs 5→2 and 7→3 are from the plan. 4→3 and 6→2 are inferred from the order (own proposal; undo by editing `needs`). `maxTurns` 400 is an own proposal: a session that reaches it is blocked ("limit reached").

## Runner

### Commands

Usage, in fish from a checkout that has the runner:

```fish
scripts/run-package --probe                    # enforcement probes, PASS/FAIL table
scripts/run-package 1 --base package-runner    # one package; --base only while this branch is not merged
scripts/run-package --through 3                # next pending packages in order, up to package 3
scripts/run-package --status                   # verified status of every package
```

### What one run does

1. **Preflight. The run refuses if any of these holds:**
   - bubblewrap, socat or the token file (`~/.config/holojob-runner/oauth-token`, mode 600) is missing;
   - `/srv/holojob` has a dirty tree;
   - a `pkg/*` branch exists whose package is not verified done;
   - the package is not pending;
   - a needed package is not done;
   - the last probe run is missing or failed.
2. **Branch.** Created at once at the base, so a crash leaves an unfinished branch. The base is the newest done package branch (stacked, owner decision 2026-11-25), or `--base` when none is done.
3. **Clone.** `git clone --no-hardlinks` into `~/holojob-packages/NN/repo`, with the remote removed.
4. **Data split** (owner decision 2026-11-26):
   - ad data and settings are copied by allowlist;
   - private files are not copied at all;
   - the derived `data/derived/labelled-ads.json` (ad ids and verdicts only) replaces the labels.

   The split is listed in `reports/00-package-runner.md`.
5. **Session.** A fresh `claude -p` with the package's model, inside an outer bubblewrap. Inside it, Claude Code's own sandbox runs every Bash command with no network and no token. Settings are injected with `--settings`: the clone's own `.claude/settings*.json` and hooks never load.
6. **Verification.** The runner sets the status from its own checks:
   - the report's `Status:` line;
   - a clean tree;
   - at least one commit;
   - the report is in the HEAD commit;
   - the owner is the only author, with no attribution lines;
   - no protected path is touched;
   - no test is deleted or skipped;
   - the full tier, run in a sandbox (podman `--network none` for node, bubblewrap without network for pytest).
7. **Record.** The status row is committed on the package branch, the branch is fetched into `/srv/holojob`, and `~/holojob-packages/state/NN.json` is written.

### Enforcement and limits

The enforcement layers and their probes are in `reports/00-package-runner.md`.

**Not enforced technically:**
- The session reads the ad-data copy it needs. "Counts only, no private ad content in reports" stays a written rule.
- The `claude` process itself talks to the Anthropic API.
