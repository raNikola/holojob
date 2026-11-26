# Holojob - Roadmap

Principles: [redesign/DECISIONS.md](redesign/DECISIONS.md). Later decisions and the history of what was built: [DECISIONS.md](DECISIONS.md) (the roadmap keeps no history). Current-state audit: [redesign/PHASE0_AUDIT.md](redesign/PHASE0_AUDIT.md). Engine contract: [redesign/ENGINE_CONTRACT.md](redesign/ENGINE_CONTRACT.md). Terms: [GLOSSARY.md](GLOSSARY.md). How the system works today: [ARCHITECTURE.md](ARCHITECTURE.md).

This is the only phase list; DECISIONS.md, CLAUDE.md and the README link here.

## Status at a glance

As of 2026-11-23. The deployed image is built from `4a64657` (tag `release-20261123-rescrape-intake`), the tip of `main` that day; the owner deployed it on 2026-11-23. Everything merged before it is in that image (an inference from the commit history; the owner named the 2026-11-23 items).

| State | Items |
|---|---|
| **Built and deployed** (in `main`) | Phase 0 audit; Phase 1 steps 1-8c (engine in shadow); scoring 1.7 (a Fit 3 target role class is on-track); the owner's kept and applied ads stay in every scoring run; automatic backups with the save guard; display labels; role classification of new ads; Re-scrape does the whole intake of new ads in one manual run under one budget set in Settings; three fit tiers in the Jobs list; Activity screen; per-source switches; application tracker (store, Board, Statistics); profile import (S0-S4, S6, S7); Phase 4 protections (fact gate, identifier redaction, confirm); delete for hand-entered jobs |
| **Built, not merged** | Nothing. One unmerged branch exists: `scoring-16-held` (a scoring 1.6 package that failed its pre-registered guard: held, not deployed, kept as a record) |
| **Next** | Not decided by the owner. The open items below are the candidates |
| **Later** | Wave 7 S5 LinkedIn data ZIP (waits for the owner's real file); application tracker: Closed panel, follow-up nudges, CSV import of past applications; watched companies from a pasted URL; Phase 2 questionnaire and ask-user loop; Phase 4 interview prep from requirement statuses and market report; Phase 5 feedback loop; list under "Later, deferred and ideas" |

| Phase | Scope | Status |
|---|---|---|
| 0 | Audit and engine contract | Done |
| 1 | Scoring core: requirements with quotes, evidence index, matcher, Fit and gates, shadow mode | Steps 1-8c built; acceptance criteria below not confirmed by the owner. Stable requirement ids: seed, report, audit tool and mapping in extraction built; version split (`evidenceVersion`, `answersVersion`) built with competency memory M1; the verdict cache per competency and local embeddings are not built |
| 2 | Evidence profile: questionnaire, AI prefill, ask-user loop | Partly built: confirmed-facts store v2 with `record_answer` and `revoke` (`python/job_scoring/confirmed_facts.py`); no caller outside the module, no route or UI (verified by grep), so nothing writes it yet. The cross-ad question queue (M9, M10) is parked (owner, 2026-11-14) |
| 3 | Application tracker | Built: store with event history, Job Details tracker, Board, Statistics, All records, Settings > Applications. Not built: Closed panel (`stageRegistry.js` names it, no component renders it), removal of the legacy `applicationTracking` field, nudges, CSV import, several contacts. Plan: [redesign/TRACKER_PLAN.md](redesign/TRACKER_PLAN.md) |
| 3b | Sources as user configuration | Built: `data/config/sources.json`, on/off per source, one-run "Skip LinkedIn". Not built: watched companies from a pasted URL (providers still read `companies/*.json`); the `serbia` provider group is still the default (`run-discovery.js`, `run-rescrape.js`, `api-handler.js`). Spec: [redesign/SOURCES_SPEC.md](redesign/SOURCES_SPEC.md) |
| 4 | Interview prep, tailoring behind a fact gate, market report | Protections built (fact gate, redaction, confirm, draft-then-accept cover letter, verdicts checked on attach). A browser "Generate Interview Prep" tool exists (`JobAIToolsPanel.jsx`); interview prep from requirement statuses and the market report are not built (not verified beyond a code search) |
| 5 | Feedback loop: conversion by channel and band | Planned |

## Open items

### 1. Hard-rule gaps

- **Item 12, non-English ads.** A required-language demand is read only from a readable English text (`gates.language_text_readable`: enough words, English stop-word ratio, not cut off). An ad written in another language (a German ad, `5aaeb781`; 33 non-English rows when it was measured on 2026-11-14) has no confirmed language block. Separate owner decision, not started.
- **B2B lower priority.** Not built. `eligibility.b2b_wording` only keeps a sponsorship refusal "unknown" when the profile says B2B is available; nothing lowers the tier or order of a B2B-only ad (code search).
- **Unknown location.** A bare "Remote" or an unreadable place gives location state `unknown`: shown as a flag, never blocked, never lowers the score (`blocking.location_state`). Whether that is right for remote ads with only a region is an owner decision, not made.

### 2. Evaluation quality

- **Hard vs nice-to-have requirements.** The engine splits `must` and `preferred` and weights them (`match_engine/fit.py`); the keyword score reads only `mustHaves`. What is left: the extraction can still tag a "plus if you have X" line as a must. Not measured since 2026-11-10 (not verified); the 1.x skill score still has an unused constant `MUST_HAVE_SHARE` (`dimensions/skill_match.py`), to remove or explain.
- **Low-confidence reasons only when the signal is absent.** Still needed. "Seniority not stated" comes from the model's `seniority` fact or the title (`experience_match.py`, `data_sufficiency.py`), "No strong culture signals" from a keyword match (`culture_match.py`); neither checks the source text, and there is no test for the salary-band example. Guarded by a computed signal already: "Requirements not extracted", "Short description", "Location not stated", "No keyword bank".
- Related: recalibrate `TARGET_COVERAGE` and the flat scoring dimensions ([ARCHITECTURE.md](ARCHITECTURE.md), open problems).

### 3. Step 5, server master of the job list (not blocking)

The job list still lives in the browser (`localStorage`) and the screens save the whole list; `job-state.json` v1 (Saved, Rejected, Keep) is built. Not built: the server as master of the list. Plan: [redesign/STEP5_SERVER_MASTER_PLAN.md](redesign/STEP5_SERVER_MASTER_PLAN.md). The list itself (server-side filter, sort and paging; the browser keeps only shown and worked ads), in progress on branch `jobs-list-server`: [redesign/JOBS_LIST_SERVER_PLAN.md](redesign/JOBS_LIST_SERVER_PLAN.md) (phases P0-P5, status, open items; updated at the end of every prompt of that work). `offList` rows migrate as orphans.

### 3b. Packages 1-7 (archive, measurements, filters, cost, descriptions, reposts)

Plan and status: [redesign/PACKAGES_PLAN.md](redesign/PACKAGES_PLAN.md) (the package table there is the only status record). The owner runs each package in an interactive session ("do package N from the plan"). Built (branch `package-runner`, not merged): the plan, the report template and the optional headless runner `scripts/run-packages` (no sandbox: what it cannot enforce is in the plan). Package sessions read `/srv/holojob/data` directly and write nothing there. No package has run.

### 4. Owner actions

- Review the 11 of 17 CV documents that carry stale unverified-degree findings before they are used for applications.
- Rotate the OpenAI key and `li_at` (not verifiable from the repo).
- Label ads while applying: this is the path to a holdout and to a proof of the order inside a tier (the Jobs list makes no order claim inside a tier).
- Run the first real Re-scrape: set the run limit (USD and ads) and the engine fill switch in Settings > AI budget first (until then a Re-scrape spends nothing and says so), then review the result in Activity.

### 5. Open, cause unknown

- The warning "36 ads could not be loaded with their text" (text in `src/modules/jobs/storageNoticeText.js`, raised from `JobTextGate`). The cause is not known; do not assume it.

### 6. Carried over from the earlier roadmap, checked 2026-11-23

One status each: **open** (seen in the code or tests today), **not verified** (cannot be told from the repo, or needs private data), or **done** (listed last, removed from the open list).

**Scoring and engine**

- Gate quotes into extraction, so an ad whose requirements all resolve locally makes no matcher call: open (gate quotes are still read in the matcher call, `match_engine/matcher.py`).
- Competency memory M6, audit of `auto` links: open (no code, no commit).
- The Fit prior in production scoring: open (no prior in `scorer.py` or `fit.py`; prior 0 is a calibration setting only).
- Stage B bucket hold and unconfirmed flag in production: not verified.
- Local embeddings as a mapping step (only if the mapping proves noisy): open (`competency_mapping.py` has none; `embed()` is used by the experiment only).
- Domain transferability for a structural match outside the fixed table (carrier / shipper vs host / guest): open (`src/data/domainAdjacency.json` has no such edge).
- The neutral defaults of 58 / 60 in `culture_match.py` and `industry_match.py`: open (58 present in `culture_match.py`; the 60 not re-checked).
- `MUST_HAVE_SHARE` in `dimensions/skill_match.py`: open (the constant is defined and read nowhere).
- Ads without owner data can leave `scored_jobs.json` while the ledger keeps them open: partly built 2026-11-24. An open ad of a search source that the latest search did not return (class `absent`) is scored every run (`job_history.open_search_rows`, marked `notFoundThisRun`, free). The rest (about 3,900 on 2026-11-24: `older_key`, `unclassified`) stays unscored: open, see DECISIONS 2026-11-24 "Search-source ads the latest search did not return".
- Active period (days an absent ad stays in Active): built, Settings > AI budget > "Jobs: Active list ..." (`activeWindowDays`, default 14, whole days 1 to 365).
- The owner fills Profile > Work authorization (countries, B2B) and re-scores: not verified (private data).

**Discovery and Infostud**

- Infostud snapshot switch (`SNAPSHOT_AFTER_PROOF` in `job_history.py`): open (False, so Infostud stays "unclassified"; the same fact covers "stays unclassified until its fetch coverage is measured").
- Run record lacks scored, closed, missing and expired counts: open (`run_log.py` docstring).
- Infostud description repair: dry run, `--apply` decision, Re-score: not verified (private data).
- A run with every source skipped is held by a caller that does not pass `require_usable`: open (the default is False in `importer.py`).
- Hand-edited `appliedRuns` double count: open (strict xfail in `tests/python/test_filtered_ads.py`).
- Pre-S6 `--backfill-filtered` double count: not verified.
- Truncated ledger with a matching generation: not verified.
- No `init` in compose: open (`docker-compose.yml` has none).
- About 1,934 `older_key` rows stay until the owner runs the prune report and `--apply`: not verified (private data).
- A throttled `jobspy` source can count as proven; `jobspy_adapter` can report a blocked LinkedIn search as a read of 0 ads: not verified.
- Ledger growth, about 550 MB a year: open (the description is still stored in each ledger entry, `job_history.py`).
- Source order and per-source timeout policy: not verified.

**Tracker, jobs list, import**

- Closed panel: open (`stageRegistry.js` names it, no component renders it).
- Removal of the legacy `applicationTracking` field (tracker S4): open (still read in `ApplicationHome.jsx`, `JobTable.jsx`).
- Follow-up nudges and the reminders switch UI: open (enums and controller only, no component).
- CSV import of past applications: open (only a "CSV" origin label exists).
- Several contacts per application: not verified.
- Delete in the list row actions (Details only today): not verified.
- Wave 7: real-file check with one resume PDF and one LinkedIn PDF; the Continue / Save wizard fix: not verified.
- "Keep this ad" and document generation for a kept ad outside the scored list: not verified end to end (`NOT_IN_SCORED_LIST` still exists; the kept-ads sync now registers kept ads).
- Text search covers only rows with text in the browser; no bulk restore of kept-ad text; hand-entered jobs have no flag saying whether the server has them: not verified.
- The 5 MiB `localStorage` limit is an assumption: open (`STORAGE_QUOTA_CHARS = 5 * 1024 * 1024`).
- The demo loader writes `localStorage` directly: open (`loadDemoData.js`).

**Settings and security**

- Move the OpenAI key to the secret store and remove it from `.env`: not verified (`.env` is private).
- Settings > Usage & cost: not verified (a section "AI budget, provider and usage" exists; what is missing is not recorded).
- Sources consent as a modal: open (the inline checkbox is still in `JobBoardsPanel.jsx`).
- One real backup through `scripts/backup-check.js` (Wave 0): not verified.
- Fill from ad, AI step: not verified (the default allowlist lacks `job-import`; the owner's setting is private).
- `chmod 600` of the top-level files in `data/`: not verified.

**Tests and tooling**

- Flaky run-lock test in `tests/js/rescrape.test.js`: open (the test is still there).
- Bulk tailoring run that aborts outside the draft: open (only the malformed-draft case is tested, `test_llm_tailor.py`).
- `claude_code._call` with empty stdout and a non-zero exit: open (no such test found).
- `provenance_auditor.py` company match `cl in k or k in cl`: open (`python/quality_audit/provenance_auditor.py`).
- Test isolation by per-test data directory: open (the guards detect a change, they do not prevent it).
- Graphify build exits non-zero (Wave 4): not verified. Run the zero-token cycle on the real repo and file the upstream issue: not verified.

**Verified done, removed from the open list:** `scoringBehind` after a cancel (`scoringIsBehind` in `scripts/run-rescrape.js`); `lastImport.meta` after a partial import (`lastPartial`, `import_meta.py`); backup includes `analytics` (`DATA_DIRS` in `scripts/backup-handler.js`); tests for `run-tailor.js` and `/api/tailor/*` (`tests/js/tailorRoutes.test.js`).

## Phase 1 acceptance criteria - PROPOSED, owner to confirm

Measured on the ten postings in `tests/fixtures/postings/`; they implement the "Stable results", "Private by default" and "Every score is explainable" measures in [GOALS.md](GOALS.md). Status: criteria 3 and 4 hold at the close-out check (2026-11) and 2 is covered by tests on synthetic jobs; 1 has not been measured on the current code (needs live model calls). No owner confirmation is recorded (not verified).

| # | Criterion | Measured by |
|---|---|---|
| 1 | **Stability.** 3 runs per fixture with the same profile: requirement-id overlap >= 90%, status flips <= 5%, Fit spread <= 5 points | A script reports the three numbers per fixture and overall |
| 2 | **Shadow mode changes nothing.** Ranking, label and priority are identical with and without Fit stored | A test scores a fixture set both ways |
| 3 | **No personal identifiers leave.** No name, phone, e-mail or personal link in any payload sent to a provider | A test builds every payload from a profile with such strings |
| 4 | **Checks pass.** Lint, Vitest, pytest and the build | Commands in [CLAUDE.md](../CLAUDE.md) (Test commands) |

## Later, deferred and ideas

- **Deferred (owner):** UI redesign epic and design system, planning only, nothing built ([design-system/](design-system/README.md)); Company information standardization (planned, nothing built; the canonical job carries only a `company` string); shared job database for several users (goal only, [redesign/SHARED_JOB_DB_PLAN.md](redesign/SHARED_JOB_DB_PLAN.md); principle 15, single user, stands). Notes only (P1/P2): family subscriptions, new-ad notifications, canonical company dedupe, source coverage analytics.
- **Dev tool:** the Graphify adapter (`tools/graphify_adapter/`, slices S0-S6) is built; it is not part of the app.
- **Idea, parked:** HolyJobs browser extension for LinkedIn job and profile import (no tasks, no plan; notes in [DECISIONS.md](DECISIONS.md#idea-browser-extension-parked-notes-2026-11-09)).
- **Later:** multi-device access with server-side storage as master; scheduled discovery; more role families and prompt variants; Job Details tabs and AI spend per job; Step 6, a confirm dialog for the browser AI features ([redesign/BROWSER_STORAGE_POLICY.md](redesign/BROWSER_STORAGE_POLICY.md)); the "Urgent only" filter and Greenhouse per-job pay and deadline.
- **Ideas, not scheduled:** prompt templates for application answers (any run is an AI call: gate, redaction and confirm apply).
- **Inherited features:** discovery (LinkedIn via JobSpy, Infostud, Workable, Greenhouse, Lever, Ashby), job history ledger, enrichment facts, work-authorization rules, CV library and analysis, tailoring, outreach contact scraping. See [CHANGELOG.md](../CHANGELOG.md).
