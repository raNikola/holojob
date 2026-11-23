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

The job list still lives in the browser (`localStorage`) and the screens save the whole list; `job-state.json` v1 (Saved, Rejected, Keep) is built. Not built: the server as master of the list. Plan: [redesign/STEP5_SERVER_MASTER_PLAN.md](redesign/STEP5_SERVER_MASTER_PLAN.md). `offList` rows migrate as orphans.

### 4. Owner actions

- Review the 11 of 17 CV documents that carry stale unverified-degree findings before they are used for applications.
- Rotate the OpenAI key and `li_at` (not verifiable from the repo).
- Label ads while applying: this is the path to a holdout and to a proof of the order inside a tier (the Jobs list makes no order claim inside a tier).
- Run the first real Re-scrape: set the run limit (USD and ads) and the engine fill switch in Settings > AI budget first (until then a Re-scrape spends nothing and says so), then review the result in Activity.

### 5. Open, cause unknown

- The warning "36 ads could not be loaded with their text" (text in `src/modules/jobs/storageNoticeText.js`, raised from `JobTextGate`). The cause is not known; do not assume it.

### 6. Carried over from the earlier roadmap (open when last recorded; not re-verified on 2026-11-23)

- **Scoring and engine:** stable ids phase 4 (gate quotes into extraction, so an ad whose requirements all resolve locally makes zero matcher calls); competency memory M6 (audit of `auto` links) and the prior in production Fit; the Stage B bucket hold and unconfirmed flag in production; domain transferability uses a fixed table of adjacent industries, so a structural match outside it (carrier / shipper vs host / guest) is not covered; the owner fills Profile > Work authorization (countries, B2B) and re-scores.
- **Ads without owner data can still leave `scored_jobs.json` while the ledger keeps them open** (All Jobs still shows them); decide whether the view keeps `notFoundThisRun` rows (`row_state.py`).
- **Discovery:** Infostud snapshot switch (`SNAPSHOT_AFTER_PROOF` in `job_history.py`) stays off until several complete runs are seen in Activity; Infostud stays unclassified (not snapshot-based) until its fetch coverage is measured; run record lacks scored, closed, missing and expired counts; the Infostud description repair (`scripts/repair-infostud-descriptions.py`) dry run, `--apply` decision and a Re-score; a run with every source skipped is still held by a caller that does not pass `require_usable`; `scoringBehind` is false after a cancel; `lastImport.meta` is stale after a partial import; the pre-S6 backfill double count.
- **Browser storage:** no bulk restore of kept-ad text from the ledger beyond the start-up reload.
- **Import (Wave 7):** real-file check with one resume PDF and one LinkedIn PDF; the Continue / Save wizard flow fix; the score 60/58 neutral defaults fix.
- **Hand-entered jobs:** Delete exists in Job Details only, not in the list row actions.
- **Tests:** no test for a bulk tailoring run that aborts outside the draft, nor for `claude_code._call` with empty stdout and a non-zero exit.
- **Settings and owner steps:** Settings > Usage & cost (what is missing is not recorded); move the OpenAI key to the secret store and remove it from `.env`; run one real backup through `scripts/backup-check.js` (Wave 0); judge a real run against the owner's own sense of the jobs.
- **Fill from ad (AI step):** was refused because `job-import` is not in `claudeCodeSubscription.features` (checked 2026-11-02, not re-checked).
- **Graphify adapter:** the build exited non-zero in Wave 4, cause not investigated.

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
- **Later:** multi-device access with server-side storage as master; scheduled discovery; more role families and prompt variants; sources consent modal; Job Details tabs and AI spend per job; Step 6, a confirm dialog for the browser AI features ([redesign/BROWSER_STORAGE_POLICY.md](redesign/BROWSER_STORAGE_POLICY.md)); the "Urgent only" filter and Greenhouse per-job pay and deadline; source order and per-source timeout policy.
- **Ledger growth:** `job_history.json` grows about 550 MB a year (about 10 KB per entry, about 150 new ads a day) and every import rewrites it. Deferred; likely fix: descriptions out of the main file.
- **Jobs list and storage gaps (deferred):** "Keep this ad" does not guarantee document generation for a kept ad outside the scored list (the kept-ads sync now registers kept and applied ads, but document generation end to end is not verified); text search covers only rows with text in the browser; the 5,242,880-character `localStorage` limit is an assumption, not measured per browser; hand-entered jobs have no flag saying whether the server has them; direct `setItem` writers bypass the storage budget.
- **Discovery edge cases (deferred):** a throttled source can count as proven; about 1,934 `older_key` rows stay until the owner runs the prune report and `--apply`; the hand-edited `appliedRuns` double count; no `init` in compose; a truncated ledger with a matching generation; `jobspy_adapter` can report a blocked LinkedIn search as a successful read of 0 ads.
- **Test and tooling debt:** a flaky run-lock test in `tests/js/rescrape.test.js` ("a dead running record becomes interrupted ...", still present); test isolation is by fingerprint guards that detect, not prevent, a change to the real `data/` (history: [DECISIONS.md](DECISIONS.md), "Incident 2026-11-09"); no tests for `scripts/run-tailor.js` and the `/api/tailor/*` routes; Graphify adapter: run the zero-token cycle on the real repo and file the upstream issue (owner).
- **Tailoring audit debt:** `provenance_auditor.py` matches a company name with `cl in k or k in cl`, so a short known name can vouch for a longer one; a failure outside the draft (disk full, render crash) stops `run_tailor.main()` before `scored_jobs.json` is saved, on purpose.
- **Manual owner step:** `chmod 600` the top-level files of `data/` (`find data -maxdepth 1 -type f -perm /077 -exec chmod 600 {} +`); not verified whether done.
- **Ideas, not scheduled:** prompt templates for application answers (any run is an AI call: gate, redaction and confirm apply).
- **Inherited features:** discovery (LinkedIn via JobSpy, Infostud, Workable, Greenhouse, Lever, Ashby), job history ledger, enrichment facts, work-authorization rules, CV library and analysis, tailoring, outreach contact scraping. See [CHANGELOG.md](../CHANGELOG.md).
