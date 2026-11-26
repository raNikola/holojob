# Packages plan: archive, measurements, filters, cost, descriptions, reposts

Owner plan of 2026-11-25. The owner runs each package in a normal interactive Claude Code session, one package per session: see "How to run a package" below. Reports: `docs/redesign/reports/NN-slug.md` from `reports/TEMPLATE.md`.

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
- **Tests run in a temp dir, never `data/`.** Run the targeted tests per change, and the full tier (CLAUDE.md, "Testing and commit policy") before a package is set to done.
- **Code and comments in English.**
- **No hot patches.** Build, up, push and deploy are the owner's.
- **No questions.** Trivial matters take the benchmark or standard choice, recorded under "Defaults taken" in the report with its source and how to undo it.

## Stop rules (status `blocked`)

A package stops as blocked on any of these:
- a risk of irreversible data loss;
- any of the 19 labelled ads (the owner's Applied, Saved and Rejected ads) stops being kept (must-keep set: `data/derived/must-keep.json`, see "Data copy");
- a limit is reached;
- tests are still red after one fix attempt;
- a real product decision that this plan leaves undefined and that no benchmark, standard practice or earlier owner decision settles.

Blocked means: write the reason in the report, put `Status: blocked` on its first line, commit, and stop.

## Packages

1. **Archive and History.** Implement the rule above. Measure the Active list by days since last seen and by status, before and after (counts only). The 19 labelled ads (Applied/Saved/Rejected) are unaffected.
2. **Free measurements, no changes:**
   - one scoring pass, profiled offline on a copy (cause of the 12x slowdown);
   - prompt section sizes, and whether the first 1,024 tokens are identical across calls;
   - the share of LinkedIn detail requests in scan time;
   - an audit of negative filters per keyword (unique metric, career-ops filter-audit).
3. **Filter foundation and round 1:**
   - the vocabulary moves out of `role_filter.py` into Settings;
   - a normalized company key, and first/last seen dates, on ledger and filtered rows;
   - filtered sightings do not refresh `lastListedAt`;
   - a must-keep set of the 19 labelled ads (Applied/Saved/Rejected);
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
| 1 | archive-history | claude-sonnet-5-5 | - | 1 | pending | - |
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
2. **Data copy.** It makes the package's copy (below) and works only on that copy, never on `/srv/holojob/data`.
3. **Work and tests.** It implements only package N and runs the targeted tests while it works, then the full tier.
4. **Report.** It writes `docs/redesign/reports/NN-slug.md` from the template. The first line is `Status: done | blocked | needs-review`.
5. **Commit and stop.** It sets the package's row in the table, commits with the owner as the only author, and stops at the commit with a short report. No push, no build, no deploy: the report ends with the owner's commands.

A stop rule means: `Status: blocked`, the reason in the report, commit, stop. There are no questions for trivial matters: the session takes the benchmark or standard choice and records it under "Defaults taken".

## Data copy

Owner decision 2026-11-26: ad data and settings are copied, private files are not copied at all. Make the copy into the package's worktree:

```fish
# Owner or session, once per worktree. The application ids come from the node export (TRACKER_PLAN 6a: Python does not read the application store).
podman run --rm --security-opt label=disable -v /srv/holojob:/work:ro -v /tmp:/out -w /work docker.io/library/node:20-bookworm node scripts/export-application-job-ids.js /out/holojob-app-ids.txt
/srv/holojob/.venv/bin/python scripts/package_data_copy.py --dest WORKTREE --application-job-ids /tmp/holojob-app-ids.txt
rm /tmp/holojob-app-ids.txt
```

`scripts/package_data_copy.py` behaves as follows:
- **Destination.** It refuses `/srv/holojob` itself, and any `data/` that already holds more than the tracked files.
- **Contents.** Files are written with mode 600 and directories with mode 700. It prints counts only.

**Copied (allowlist `AD_DATA_ALLOW`):**
- `jobs/`: `discovered_jobs.json`, `job_history.json`, `filtered_ads.json`, `normalized_jobs.json`, `raw_jobs.csv`, `scored_jobs.json`, `rescored_kept.json`, `pipeline_last_run.json`, `job-state.json` and `staging/`.
- `ai/settings.json` and `ai/usage-ledger.jsonl`.
- `config/sources.json` and `config/ai-settings.json`.
- `analytics/runs/`.
- `cache/engine.json` and `cache/requirement-frames.json`.

Any path that looks like a secret (the `scripts/secret-paths.js` rules) is never copied.

**Not copied:** everything else. That includes:
- **Candidate data:** profile (and its `.bak`), applications, resumes, intelligence, interviews, outreach, chat.
- **Labels and calibration.**
- **Keys and backups:** secrets, backups.
- **Profile-derived:** audits, AI findings, `analytics/skill_gap.json`, `engine-snapshot.json`, `profile-enrichment.json`, `requirement-remap.json`, `competency-*`.
- **Fit and CV caches:** `cache/llm_fit.json`, `cache/fit3.json`, `cache/cv_analysis.json`, `cache/competency-evidence.json`, `cache/engine-calibration.json`, `cache/engine-stability.json`, `cache/repos`.
- **Owner-only:** `jobs/manual_jobs.json` (notes, links, source URL).
- **Not needed:** `.bak` copies and lock files.

To move a file to private, delete its line in `AD_DATA_ALLOW`.

**For owner review:**
- `jobs/scored_jobs.json`: its match reasons are derived from the profile.
- `jobs/job-state.json`: your Saved/Rejected statuses.

Package 1 needs both.

**Must-keep set** (`data/derived/must-keep.json`): ad ids and statuses only.
- A status is `applied`, `saved` or `rejected`; `applied` wins when an ad has two.
- Saved and Rejected come from `data/jobs/job-state.json`.
- Applied comes from the application-id export.
- The file records `expected: 19` and the count found. The helper warns when they differ.

**Open (owner):** on 2026-11-26 the server knows **16** of the 19: 5 Saved, 2 Rejected, 12 applications, with an overlap of 3. The other 3 are probably statuses held only in the browser. `export-protect-ids.js` notes that those reach the server only through Settings > import browser state. Until they do, the stop rule covers the 16.
