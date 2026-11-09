# Holojob - Roadmap

Principles and decisions: [redesign/DECISIONS.md](redesign/DECISIONS.md) and [DECISIONS.md](DECISIONS.md).
Current-state audit and module decisions: [redesign/PHASE0_AUDIT.md](redesign/PHASE0_AUDIT.md).
Engine contract (draft): [redesign/ENGINE_CONTRACT.md](redesign/ENGINE_CONTRACT.md). Terms: [GLOSSARY.md](GLOSSARY.md). How the system works today: [ARCHITECTURE.md](ARCHITECTURE.md).

This is the only phase list; DECISIONS.md, CLAUDE.md and the README link here.

| Phase | Scope | Status |
|---|---|---|
| 0 | Audit: what exists, per-module Reuse / Adapt / Build / Skip, engine contract | Done |
| 1 | Scoring core: role-family config, requirement extraction with quotes and canonical ids, evidence index, evidence matcher + deterministic Fit, confidence, gates. Shadow mode next to the current score; stability test on fixtures | Steps 1-8c built (role families, requirements, evidence index, matcher, Fit and gates, stability test, shadow mode, privacy test); acceptance criteria pending owner confirmation; stable-id follow-up in progress (below) |
| 2 | Evidence profile: restructured optional questionnaire (story bank, skills with evidence, preferences, gates), AI prefill from the CV through the review screen, ask-user loop that stores confirmed facts | Planned |
| 3 | Application tracker independent of discovery: own store with a posting snapshot, append-only event history, channel, CV version, outcomes, follow-up nudges, import of past applications | In progress. Built: store with event history and configurable stages, migration from job records, Job Details tracker (Mark Applied, CV used, history, void and restore), Board with drag, Statistics, Settings > Applications (tracking switch, columns), applications that open and count without their ad ([decision](DECISIONS.md#applications-open-without-the-ad-history-read-path-2026-11-03)). Not built: Closed panel, "Show voided", removal of the legacy `applicationTracking` field (S4), follow-up nudges and the reminders switch's UI (S5), CSV import of past applications (S6), several contacts. See [redesign/TRACKER_PLAN.md](redesign/TRACKER_PLAN.md) |
| 3b | Sources as user configuration: Settings > Sources with an on/off switch per job board, watched companies added from a pasted careers or board URL and probed live, stored server-side in `data/config/sources.json`; replaces the hard-coded `serbia` group and the repo's `companies/*.json` as runtime config (principle 16). Spec: [redesign/SOURCES_SPEC.md](redesign/SOURCES_SPEC.md). Independent of Phases 1-2; built next to Phase 3 because both are user-owned data that must persist | First slice built: `data/config/sources.json` and Settings > Sources > Job boards, with the Joberty opt-in only. Not built: a switch for the other boards (they still follow the provider groups, `serbia` is still the default), watched companies from a pasted URL with a live probe (providers still read `companies/*.json`) |
| 4 | Interview prep from requirement statuses and the story bank; CV and cover letter tailoring behind a fact gate; market report of requirements per role family | Planned |
| 5 | Feedback loop: conversion by channel and Fit band, calibration of Fit against real outcomes (report only, never auto-tuning) | Planned |

## Phase 1 acceptance criteria - PROPOSED, owner to confirm

Status at the close-out check: criteria 3 and 4 hold; criterion 2 is covered by tests on synthetic jobs; criterion 1 has not been
measured on the current code (it needs live model calls) - pending owner confirmation.

Phase 1 is done when all of these hold. They are measured on the ten postings in `tests/fixtures/postings/`
(3 Greenhouse, 1 Ashby, 2 each of Infostud, LinkedIn and Workable) and the candidate profile used for the shadow
run, and they implement the "Stable results", "Private by default" and "Every score is explainable" measures in
[GOALS.md](GOALS.md).

| # | Criterion | How it is measured | Goal |
|---|---|---|---|
| 1 | **Stability.** For each fixture, 3 runs with the same profile: requirement-id overlap >= 90%, status flips <= 5%, Fit spread <= 5 points | A test or script reports all three numbers per fixture and overall; overlap is the share of requirement ids present in all 3 runs, flips the share of shared requirements whose status differs between runs, spread the max minus min Fit | Stable results |
| 2 | **Shadow mode changes nothing.** With Fit computed and stored, ranking, label and priority of every job are identical to a run without it | A test scores a fixture set both ways and asserts equal `matchScore`, `matchLabel`, `priority` and sort order | Rank by evidence of fit |
| 3 | **No personal identifiers leave.** No name, phone, e-mail or personal link in any payload sent to a provider | A test builds every payload the engine sends from a profile that contains such strings and asserts none is present | Private by default |
| 4 | **Checks pass.** Lint, vitest, pytest and the build pass | `npm run lint`, `npm run test:js` and `npm run build` in the throwaway `node:20-bookworm` container (`--security-opt label=disable`, never `:Z`), pytest against the host `.venv`, no failures; commands in [CLAUDE.md](../CLAUDE.md) (Tests) | - |

Related GOALS.md measures that these criteria cover only in part, and the later phase that finishes them: "Every
score is explainable" is shown in the job drawer in Phase 1 but its per-requirement quotes are verified by the
engine invariants in [ENGINE_CONTRACT.md](redesign/ENGINE_CONTRACT.md) section 5.2; "Rank postings by evidence of
fit" is judged by the owner on real runs after shadow mode; "Honest documents" and "Nothing is lost" belong to
Phases 4 and 3.

## Phase 1 follow-up: stable requirement ids - PLANNED

Decided 2026-10-26 ([DECISIONS.md](redesign/DECISIONS.md)). Today 92% of requirement ids are provisional (a hash of
the ad's own wording), so a requirement worded differently in another ad gets another id and the owner's answers
could never be reused. Built in four phases, each measured by the share of provisional ids before moving on:

1. **Seed, report and audit tool.** The curated competency list for the product family
   (`src/data/competencies/product.json`), a local report (no model call) that groups frequent provisional texts and
   proposes new competencies or aliases, and the audit tool for the accuracy gate (a sample of about 100 real
   requirements: correct, wrong, legitimately provisional). The owner sets the acceptable wrong-merge rate after
   the first measurement.
   Seed, validator (`python/match_engine/competencies.py`) and report (`podman exec holojob npm run competencies:report`, writes
   `data/competency-report.json`) exist; the audit tool does not yet.
2. **Mapping in extraction.** The model picks a `competencyId` from the list or NONE; code accepts only listed ids;
   precedence previous frame > alias > dictionary > model suggestion > provisional; pending aliases and the
   `prov:` -> canonical remap table under `data/`; one re-extraction of the stored ads.
3. **Version split.** `evidenceVersion` and `answersVersion`; answers applied in code on top of cached verdicts
   ([ENGINE_CONTRACT.md](redesign/ENGINE_CONTRACT.md) 6.1).
4. **Gate quotes into extraction,** so an ad whose requirements all resolve locally makes zero matcher calls.

Deferred (TODO, not scheduled):

- A per-competency verdict cache keyed by (competency id, qualifier, evidence version), so a verdict is reused across
  ads without a call.
- Local embeddings as an extra mapping step, only if the mapping proves noisy in the audit.

## Fix scoring: skill extraction scope, requirement weighting, domain transferability - TODO

Found 2026-11-02 on a real posting (a PM role at a B2B-adjacent consumer marketplace): the tool gave 45 / Weak / P3 /
"Maybe"; the owner's manual review put the real fit near 6/10, with the mismatch mainly on remote / location, not on
skills or domain. GitHub Issues are disabled on this repo, so the work is tracked here. Not started.

- [x] **Skill extraction covers the whole work history** (Wave 3). JavaScript, React, PHP, HTML, CSS, Git, Figma and REST APIs
  were flagged missing although they are explicit in an earlier role (Senior Web Programmer, 2014-2021). Today only
  recent roles are read.
- [ ] **Hard vs. nice-to-have requirements.** A "plus if you have X" line was weighted like a must-have. The model
  tags each requirement hard or soft as a fact; `scorer.py` decides the weight (architectural rule in CLAUDE.md).
- [x] **Domain transferability** (Wave 3; a fixed table of adjacent industries, so the marketplace example below is not covered). "No clear industry match" was emitted for B2B two-sided dynamics (carrier / shipper)
  that are structurally similar to the posting's marketplace (host / guest). Judge structural similarity, not a flat
  mismatch.
- [ ] **Low-confidence reasons only when the signal is absent.** "seniority not stated" and "no strong culture
  signals" fired on a posting that lists salary bands per seniority tier and 3-month / 6-month onboarding milestones.
  Guard each string with a check of the source text.
- **Must NOT change: location mismatch detection.** It worked correctly in this test; the location cap rules, the
  "Verify location" flag and the location gate stay untouched, and their tests must keep passing.

Each item gets a fixture-based regression test; the Phase 1 stability test must keep passing. Related: "Recalibrate
`TARGET_COVERAGE` and fix the flat scoring dimensions" under Later.

## Roadmap v2 (recorded 2026-11-04)

Goal: **Scoring -> Matching -> Application Tracking.** Execution order approved by the owner and reviewed by GPT. Priorities P0 to P3. Nothing below is built unless the S table above says so. Decisions: [DECISIONS.md](DECISIONS.md#roadmap-v2-and-the-single-discovery-safety-rule-2026-11-04).

State at this point: S1 to S8b are built, deployed from a clean build and merged to main at `d44d9cd`.

| Wave | Priority | Content |
|---|---|---|
| Before 0 | Planning complete; implementation deferred | **UI redesign and Design System planning** (shadcn/ui preset `b1a1cZcRs`, which superseded `b7CScIWmG` on 2026-11-04, plus a semantic extension). Documents only, in [design-system/](design-system/README.md); nothing is built. Implementation is postponed and needs separate PO approval: see [the Epic](#epic-ui-redesign--design-system---deferred--to-do). |
| 0 | P0, minimal | **Built on branch `wave0-backup`, not merged or deployed** ([as built](DECISIONS.md#wave-0-verified-backup-and-restore-check-2026-11-08); owner still rotates the keys and runs one real backup through `scripts/backup-check.js`). Verified backup plus restore check covering server data and browser state (Keep, statuses, applications), with integrity hashes and a tested restore; include `data/analytics` if it cannot be reconstructed. Rotate the OpenAI key and `li_at` (the owner does this). Align the rules in ROADMAP.md and DECISIONS.md. |
| 1 | P0 | **(k) + (q) discovery safety**, one rule (below): a throttled source never proves an ad disappeared; "ok with 0 read" is not automatically proof of closure; a confirmed-empty source is told apart from an incomplete or failed read; successful sources import independently (a partial source must not block the import); failed sources never affect closing. |
| 2 | P0 | **Built on branch `wave2-scoring-correctness` (local, not merged)** ([as built](DECISIONS.md#wave-2-scoring-correctness-built-2026-11-08)). **(a1) scoring correctness:** junk baseline of at most about 5 plus a distinct Insufficient Data state, hard/soft requirement handling, low-confidence reasons. **(e)** manual Re-score and tailoring for kept ads. **(g)** exclude closed ads from the IDF corpus (approved; measured effect at most 1 point). **(i)** `scoringBehind` after a cancel. |
| 3 | P0 | **Built on branch `wave3-scoring-quality` (local, not merged)** ([as built](DECISIONS.md#wave-3-scoring-quality-and-the-three-level-role-filter-built-2026-11-08)). **(a2)** skills from the whole history, domain transferability (proven vs assumed), the keyword bank holds keywords only, `TARGET_COVERAGE` recalibrated. **(b)** the three-level role filter (Target / Near / Excluded). Owner steps: regenerate the intelligence, then Re-score. |
| 4 | P1 | **Built on branch `wave4-coverage-retention` (local, not merged)** ([as built](DECISIONS.md#wave-4-coverage-retention-and-import-meta-built-2026-11-09)). **(h)** `older_key` retention rule and guarded prune script (window 180 days chosen; the owner runs the report and `--apply`, nothing is automatic); **(c)** Infostud: why it returns irrelevant ads explained, per-category probe, complete-read proof recorded report-only (`SNAPSHOT_AFTER_PROOF` off until several complete runs are seen); **(n)** `lastImport.meta` v2, `lastPartial`, held counts in Activity. |
| 5 | P1 | **Built on branch `wave6-application-tracking` (local, not merged)** ([as built](DECISIONS.md#wave-5--goal-j-application-tracking-built-2026-11-09)). **(j) Application Tracking:** all records including history-only and voided (Applications > All records), snapshots (existing, shown with their honesty), applied sync (Applied derived from the store, `job-state.json` v1 for Saved, Rejected and Keep with an owner-run export and import), the Applied button opens a confirm form, history-only rows no longer read "Unreviewed", shadow badge off the table, prune `--apply` checks the live store hash. Follow-up built: a failed status write (API unreachable included) changes nothing, and prune `--apply` also refuses unless applications without a job id are covered by URL / posting-key protection (`export-application-job-ids.js --check`). Owner steps listed in the decision. |
| 6 | P2, release blockers | Profile import slices. Phase 4 protections (fact gate, identifier redaction, confirm) are release blockers for AI and application workflows. Review the 11 of 17 resume docs with stale unverified-degree findings before they are used for applications. |
| 7 | P2 | UX, Settings, **(d)**. (d) is probably not a bug: the toggle exists only for Joberty and the other boards follow group `serbia`. Treat it as a missing feature and confirm the UX first. |
| 8 | P3 | Step 5 server master ([TRACKER_PLAN.md](redesign/TRACKER_PLAN.md)). A verified backup (Wave 0) is mandatory before bigger changes. |
| 9 | P3 | **(f)** ledger growth; **(m)** hand-edited `appliedRuns` double-count; **(o)** truncated ledger with an unchanged generation; **(p)** never run the old `import_run --backfill-filtered` below S6; Step 6; tech debt. |

**The single discovery safety rule (Wave 1).** A throttled source never proves an ad disappeared. A source that is `ok` with zero ads read is not automatically proof of closure: a confirmed-empty source is distinguished from an incomplete or failed read. Successful sources import independently, so a `partial` source does not block the import of the ads it did read. A failed source never affects closing. Status: **built on branch `wave1-discovery-safety` (local, not merged)**: read classes, JobSpy error signalling and the partial-source gate (DECISIONS.md, "Wave 1 discovery safety built").

**Added to the backlog (2026-11-04):**

- [ ] Rotate the OpenAI key and `li_at` (owner action, Wave 0).
- [ ] Resume findings: 11 of 17 resume docs carry stale unverified-degree findings; review before use for applications (Wave 6).

**Open decisions:**

1. Whether the four items under [Fix scoring](#fix-scoring-skill-extraction-scope-requirement-weighting-domain-transferability---todo) split as proposed: hard/soft requirements and low-confidence reasons to a1 (Wave 2); whole-history skills and domain transferability to a2 (Wave 3).
2. ~~The `older_key` retention window~~ decided: 180 days (Wave 4, h); the owner still runs the report and `--apply`.
3. The Infostud snapshot switch (Wave 4, c): off until several consecutive complete runs are seen in Activity; then set `SNAPSHOT_AFTER_PROOF` in `job_history.py`. Any category change waits for several probes.

## Wave 5 Infostud incomplete description - built (2026-11-09), owner steps pending

- [x] Full ad text read from the detail page (`__NEXT_DATA__ job.textAd`), chosen by a real-content check, not length (`infostud_description.py`).
- [x] `descriptionStatus` per ad: complete / teaser / failed / source_truncated; ledger keeps a complete text over a later teaser.
- [x] Scoring: incomplete description = low-confidence reason; one-line switch to Insufficient Data (`data_sufficiency.py`).
- [x] Repair script, dry run by default, throttled, counts only (`scripts/repair-infostud-descriptions.py`). Dry run: 9 of 9 stored Infostud ads are candidates.
- [ ] Owner: run the dry run, decide `--apply`, then Re-score; check the next discovery run.
- [ ] Follow-up: the Graphify adapter build exited non-zero in Wave 4 (cause not investigated).
- [ ] Not started on purpose: Infostud snapshot switch (Wave 4) stays off.

## Discovery improvement: Company information standardization - Planned / To Do

**Status: PLANNED, P1. Part of Discovery, not of the browser extension.** Nothing is built. Recorded 2026-11-09.

**Goal:** the normal discovery pipeline extracts and standardises company data across providers, so the company-level facts exist once and every job and every later source (including the extension) can use them.

**Audit already done (code read, 2026-11-09):** the canonical job carries only a `company` string. Infostud's list API client keeps `companyName` and drops everything else it may return; Joberty has `companyUrlName` and `companyName`; no field for company website, industry, size or headquarters exists in the canonical job, the ledger or `data-shapes.md`. The claim that Infostud already provides a useful reference could not be confirmed from the code: the first Task step is to look at what its list and detail payloads actually carry.

| Step | Content |
|---|---|
| 1 | Provider audit: per provider, which company fields are present in the raw payload (counts and field names only, no private data); decide the field list |
| 2 | One company record shape, keyed by a normalised company key, kept **apart from the job** (no duplicate profile per job); fields: normalised name, website, industry, size, location / headquarters, provider company-page URL, description, source and observed-at per field |
| 3 | Missing data is distinguished from unverified: each value is `known`, `unverified` or `missing` with its source and time; unchanged data is not re-fetched (a freshness window, as the AI findings store does) |
| 4 | Providers fill the record from data they already read; no extra page fetch by default, no scraping of private or personal contacts |

Acceptance: a fixture per provider shows which fields it fills; a job and its company are two records joined by the key; re-running discovery on unchanged data changes nothing; the shape is written so a future shared Company entity can take it over (no per-user field in it). Dependencies: Wave 4 import meta (built; merged into `main`). Open: the company key (name only is weak; domain when known), and where the record lives (a `data/companies` file beside the ledger).

## Delete job for hand-entered jobs - built on branch `delete-manual-jobs` (2026-11-09), owner check pending

Details Delete for manual jobs only; the server re-checks the application store (voided records included) and removes the job from `manual_jobs.json`, `scored_jobs.json`, `job-state.json` and the browser. Decisions: `docs/DECISIONS.md` "Delete job for hand-entered jobs". Not built: Delete in the list row actions.

## Per-source switches and one-off Re-scrape skip - built (2026-11-09), owner check pending

Settings > Sources: every source can be switched off and on (server-side, `data/config/sources.json`); discovery and Re-scrape skip a
switched-off source without closing or counting anything; Re-scrape has "Skip LinkedIn this time" (one run, nothing saved).
Decisions: `docs/DECISIONS.md` "Per-source switches". Owner steps: rebuild/restart the API, then check in Settings > Sources and Activity.

## Job relevance, lifecycle, salary, deadline - built (2026-11-08), owner visual check pending

- [x] Three title tiers, cap 40 for an unrelated title, program work accepted for the product family.
- [x] Fragment role variants no longer match; `stretchRoles` and "product management" are read.
- [x] A closed ad leaves Active and stays in All Jobs and the Application Tracker ("Ad closed").
- [x] Open before closed on the default sort only.
- [x] Salary column (stated pay; EUR monthly only as an approximate second line); Lever and Ashby structured pay.
- [x] Apply by column with warnings and sort.
- [ ] Not started on purpose: "Urgent only" filter, Greenhouse per-job pay and deadline. (Keyword-bank recalibration: done in Wave 3.)

Decisions: [DECISIONS.md](DECISIONS.md#job-relevance-lifecycle-salary-and-deadline-2026-11-08).

## Epic: UI Redesign & Design System - deferred / To Do

**Status: POSTPONED. The Epic and all its work are To Do.** Nothing is built or authorized. All colours are provisional. This Epic does not reorder scoring, matching, discovery or application tracking; the wave order above stands. Backlog with Sub-tasks, dependencies and acceptance criteria: [REDESIGN_BACKLOG.md](design-system/REDESIGN_BACKLOG.md). Decisions: [DECISIONS.md](DECISIONS.md#design-system-final-planning-decisions-epic-postponed-2026-11-04).

| Task | Status | Aligned with |
|---|---|---|
| 1. Design System Integration & Foundations | To Do | |
| 2. Application Layout & Navigation | To Do | |
| 3. Jobs Listing & Filtering | To Do | Wave 3 role filter built (discovery side) |
| 4. Job Details & Scoring UI | To Do | Wave 2 UI |
| 5. Application Tracker | To Do | Wave 5 |
| 6. Profile & Resume Management | To Do | Wave 6 profile import |
| 7. Tailoring & Application Preparation | To Do | Wave 6 Phase 4 protections |
| 8. Settings & Sources | To Do | Wave 7 |
| 9. Responsive, Accessibility & Visual Consistency | To Do | |

**Implementation prerequisites (future gates, not authorization to execute):**

1. Complete and verify the minimal Wave 0 backup.
2. Finalize and approve the colour palette.
3. Recalculate contrast ratios against the final colours.
4. Verify the semantic-token mappings.
5. Recheck framework and dependency compatibility.
6. Obtain separate PO implementation approval.

## Idea: HolyJobs browser extension (LinkedIn job and profile import) - Idea / Not planned for implementation

**Status: parked.** This is a product idea, not a plan. It has no tasks, no phases, no priorities and no dependencies on waves, and nothing is built. It becomes planning work only when the owner decides to plan it. Notes: [DECISIONS.md](DECISIONS.md#idea-browser-extension-parked-notes-2026-11-09).

**Goal:** a browser extension that, on a LinkedIn page the user opened, sends what the page shows into HolyJobs, so the owner does not copy a posting or a profile by hand.

**Value to the owner:** a job seen on LinkedIn lands in HolyJobs without retyping and without a duplicate of a job already known (open, closed, kept, rejected or applied); an existing job can gain missing details; the owner's own profile could be brought in without downloading a PDF.

**Core principles:**
- Only when the user acts; no background work.
- No LinkedIn credentials or cookies stored or sent to HolyJobs.
- No crawling, automatic navigation or continuous scraping.
- No new AI call for extraction.
- Preview and confirmation before any change; nothing is created or overwritten silently, and the owner's own job states are never touched.
- Reuse the Wave 7 `ImportDraft` pipeline and the manual-job model; no second writer.

**Candidate capabilities (loose, none committed):**
- **Job import:** "find in HolyJobs" on an opened posting (match by LinkedIn id or URL, show candidates when unsure), or preview and create a new job through the Add job form.
- **Enrichment:** offer missing details for a job already known (description, how to apply, external apply link, who posted it), shown as a difference to accept or refuse.
- **Profile import:** the owner's own opened profile as an `ImportDraft` into the existing review, confirm and apply. The riskiest idea; the LinkedIn PDF and data ZIP imports stay the supported way.

**Questions for later** (no answers decided):
1. If it is ever planned: where it fits among the other work.
2. How the extension would identify itself to HolyJobs, given there is no login today.
3. How its data would reach the app screen (and whether anything may be held on the server meanwhile).
4. Which browser: Chrome first.
5. How the true source (LinkedIn) is kept apart from the import route for a job it creates.
6. Where per-user and job-level data would live (see the notes).
7. How a job poster would be kept, if at all.
8. What the LinkedIn terms and account-risk assessment finds.

---
## Graph tooling (Graphify adapter) - in progress

A minimal, removable, stdlib-only adapter over the local Graphify graph (no services, databases, network or LLM extraction). Primary success measure: the graph reliably answers "if we change this Python module, which other parts of the system may be affected?". Decisions: [DECISIONS.md](DECISIONS.md#graph-tooling-graphify-output-update-cycle-and-backup-2026-11-08).

**Milestone 1** (separate checkpoints, each approved by the owner):

| Checkpoint | Status |
|---|---|
| B0. Restorable backup of `graphify-out/` and the Graphify config outside the repo | Done (2026-11-06) |
| S0. `graphify-out/` git- and docker-ignored; CLAUDE.md Graphify section committed without the committed-graph line | Done |
| S1. Adapter skeleton: identity pass, invariants, `report.md` with separate code, doc-link and semantic freshness | Done |
| S2. Python import resolution, only where every run context proves the same file without executing project modules | Done |

**Then (authorized 2026-11-08):**

| Slice | Status |
|---|---|
| S3. Remove inferred call edges proven wrong at the call site | Done |
| S4. `architecture.json` and `test-deps.json` views | Done |
| S5. Doc-to-code links from exact backticked paths | Done |
| S6. Zero-token cycle check in a throwaway copy (`zero_token_check.sh`) | Done |

As built: [DECISIONS.md](DECISIONS.md#graph-tooling-the-graphify-adapter-as-built-2026-11-08). Open: run the cycle on the real repo; file the upstream Graphify issue (owner).

## Activity screen - planned

A new screen named Activity, in the nav group System, built in this repo. Decisions and known gaps:
[DECISIONS.md](DECISIONS.md#activity-screen-approved-2026-11-02).

Two numberings meet here. **A1 and A2a** are the slices built earlier (run log; background Re-scrape). **S1 to S7** are the SCRAPE -> IMPORT -> SCORING
slices approved 2026-11-03: a scrape writes staging only, an import (idempotent, its own step) commits, scoring follows and never undoes the import.
Plan, approved decisions and rollback per slice: [DECISIONS.md](DECISIONS.md#scrape-import-scoring-approved-2026-11-03). Each S slice is small and shippable alone.

| Slice | Content | Status (updated 2026-11-04) |
|---|---|---|
| A1 | Per-source outcome and run log, including a fix so a failed board cannot close its existing ads | **Built.** `python/job_discovery/run_log.py`, records in `data/analytics/runs/`. [Shape and deviations](DECISIONS.md#activity-slice-1-as-built-2026-11-02) |
| A2a | Background Re-scrape: one job with a lock over discovery and scoring, an event log, the interrupted state, a commit marker | **Built and deployed.** `python/run_rescrape.py`, `python/job_scoring/pipeline_lock.py`, `scripts/run-rescrape.js`. Tailoring merges at write time and backup export refuses during a run or after an unfinished commit. [Mechanism and limits](DECISIONS.md#activity-slice-2a-background-re-scrape-2026-11-03) |
| S1 | Staging store and ad records, then streaming. **1a:** `data/jobs/staging/<runId>/<source>.jsonl` (header, batches, footer), reader and validator, hard links of the ledger and the discovered file as the run found them, no automatic deletion (S4a deletes by status), excluded from backup and restore, Joberty reads the ledger read-only. **1b:** providers append while they collect. No behaviour change: the old commit path is untouched and nothing reads staging yet | **1a and 1b built and deployed.** `python/job_discovery/staging.py`; streaming in the providers. [What is staged, when, and what is not](DECISIONS.md#s1-as-built-1a-store-1b-streaming) |
| S2 | Per-ad discard reasons plus `externalId`: every ad a provider drops is a line in `staging/<runId>/discards.jsonl` with a stable reason; kept ads carry the source's own id beside the canonical job; `read == kept + discarded` is checked per source. No filter rule changed | **Built and deployed.** `python/job_discovery/staging.py`, `providers/role_filter.py`, `providers/base_provider.py`. [Reasons, invariant, limits](DECISIONS.md#s2-as-built-discard-reasons-and-externalid) |
| S3 | The importer (`apply_run` as it is, no new rule, full validation), `import_run.py --dry-run` (writes nothing) and the import report; replay compared with what the old commit wrote, `derive_view` rebuilt from the ledger alone. Staging failure marked in the run record. No staging run is deleted (disk use printed) | **Built and deployed.** `python/job_discovery/importer.py`, `import_run.py`. Run it on real runs before S4a. [Decisions, order behaviour, exit codes](DECISIONS.md#s3-as-built-the-importer-import---dry-run-and-the-import-report) |
| S4a | The switch: scrape (staging) -> importer -> ledger as the single source of truth -> `discovered_jobs.json` derived from it, with a generation check before every reader (Python and Node), automatic rebuild or an explicit error, commit marker removed, ledger first then view (also in enrichment), import final and independent of scoring, order guard, status-based staging retention, 90-day ledger prune off, debug files best effort | **Built and deployed** (2026-11-03). `python/job_scoring/view_guard.py`, `scripts/view-guard.js`, `python/job_discovery/importer.py`, `run_discovery.py`. Owner gate: 3 real dry-runs with zero differences (none contained a closed or reopened ad). [Decisions, lock rules, tests](DECISIONS.md#s4a-as-built-the-switch-2026-11-03) |
| S4a follow-up | `--allow-older` needs `--confirm-overwrite-newer` or a typed `OVERWRITE`, and is never reachable from automatic paths; `scripts/check-view-recovery.js` proves the Node view recovery in the real container on a copy of the data | **Built and deployed** (2026-11-03). [Decisions](DECISIONS.md#s4a-follow-up-2026-11-03-the-older-run-override-is-confirmed-by-a-human-node-view-recovery-has-a-safe-live-check) |
| S4a follow-up 2 | The Node view-recovery check sends the Host the request guard allows; a guard 403 is an environment failure (exit 2), not a recovery failure | **Built and deployed** (2026-11-03). [Fix](DECISIONS.md#fix-to-the-node-view-recovery-check-the-host-guard-2026-11-03) |
| S4b | Stop writing the debug mirrors `raw_jobs.csv` and `normalized_jobs.json` (no reader exists; re-confirmed 2026-11-03); old files are left on disk | **Built and deployed** (2026-11-03). [Decision](DECISIONS.md#s4b-as-built-the-debug-mirror-files-are-no-longer-written-2026-11-03) |
| S5a | Lifecycle report: what the S5 rules would do, from the ledger and staged runs (`import_run.py --lifecycle-report`, read-only). No behaviour change | **Built and deployed** (2026-11-03). `python/job_discovery/lifecycle_report.py`. [Decisions](DECISIONS.md#s5-owner-decisions-so-far-and-s5a-as-built-the-lifecycle-report-2026-11-03) |
| S5b | Board completeness evidence in the staging footer (`boardsRead`): Greenhouse `meta.total`, Lever end-of-list request, Ashby never complete. Nothing reads it yet | **Built and deployed** (2026-11-03). [Decisions](DECISIONS.md#s5b-as-built-board-completeness-evidence-2026-11-03) |
| S5c | Two-fetch closing for snapshot sources: a board proven complete twice in a row, not listing the ad. Ashby never closes. A removed board closes nothing. Search-based sources unchanged | **Built and deployed** (2026-11-03). `job_history.apply_run`, `importer.board_evidence`. [Decisions](DECISIONS.md#s5c-as-built-two-fetch-closing-for-snapshot-sources-2026-11-03) |
| S5d | Readers ready for rows a run did not find: out of the scoring corpus, no enrichment, judge or shadow call, own summary lines. No visible change | **Built and deployed** (2026-11-03). `python/job_scoring/row_state.py`. [Decisions](DECISIONS.md#s5d-as-built-readers-ready-for-rows-a-run-did-not-find-2026-11-03) |
| S5d2 | A durable `notFoundThisRun` mark from the ledger's `heldRunId`, replacing the date test; closed rows in the corpus measured only | **Built and deployed** (2026-11-03). [Decisions](DECISIONS.md#s5d2-as-built-a-durable-not-found-this-run-mark-2026-11-03) |
| S5e1 | `data/jobs/filtered_ads.json`: every dropped ad, one record per `jobId`, written at import before pruning; a run not yet counted is never pruned; `import_run.py --backfill-filtered`. No UI, no route | **Built and deployed** (2026-11-03). [Decisions](DECISIONS.md#s5e1-as-built-dropped-ads-kept-in-filtered_adsjson-2026-11-03) |
| S5e2 | `GET /api/jobs/all`: every ad known as slim rows with a class and a reason, from the ledger and `filtered_ads.json`. Read-only, no UI, no scores | **Built and deployed** (2026-11-03). [Decisions](DECISIONS.md#s5e2-as-built-get-apijobsall-the-read-only-list-of-all-ads-2026-11-03) |
| S5e2b | `all_ads.py`: a row whose source was not part of the latest run is `unclassified`, not absent. `filtered_ads.json`: `appliedRuns` only grows, the trim step is gone | **Built and deployed** (2026-11-03). [Decisions](DECISIONS.md#s5e2b-as-built-two-fixes-after-s5e2-2026-11-03) |
| S5e3a | Active/All logic: `copyGroup` on the route, `allAds.js` (per-field merge, `composeJobList`, copy choice, labels), `useAllAds.js` (in-memory fetch). Wired to nothing, no visible change | **Built and deployed** (2026-11-03). [Decisions](DECISIONS.md#s5e3a-as-built-the-merge-and-the-two-lists-wired-to-nothing-2026-11-03) |
| S5e3b | `JobTable`: one layout mounted, the whole list sorted then shown in batches of 100, selection as a Set, select all states what it covers; `FitScore` `emptyLabel`. No storage change | **Built and deployed** (2026-11-03). [Decisions](DECISIONS.md#s5e3b-as-built-the-jobs-table-on-a-long-list-2026-11-03) |
| S5e3c | The visible Active/All view: toggle, class and 14-day filters, badges and reasons, "Not scored", notices, read-only filtered rows with an "Add job" prefill. Server-only rows stay in memory; actions on them wait for S5e3d | **Built and deployed** (2026-11-03). [Decisions](DECISIONS.md#s5e3c-as-built-the-visible-activeall-view-2026-11-03) |
| S5e3d (1) | `jsdom` as a dev dependency; real clicks on the Jobs screen become permanent tests. No production change | **Built and deployed** (2026-11-03). [Decisions](DECISIONS.md#s5e3d-commit-1-jsdom-and-permanent-click-tests-2026-11-03) |
| S5e3d (2) | "Keep this ad": the only way a server-only row becomes a stored row, marked `keptByUser` so it lasts; Mark Applied the same in the drawer and Job Details, with no promotion; the reason line hidden on found rows | **Built and deployed** (2026-11-03). [Decisions](DECISIONS.md#s5e3d-commit-2-keep-this-ad-and-promotion-2026-11-03) |
| S5f | Stale flag: 30 days and 3 proven runs of the same source and search, from a new additive ledger record. Class, reason with the counts, badge, filter; not actionable; out of Active unless worked | **Built and deployed** (2026-11-04). [Decisions](DECISIONS.md#s5f-as-built-the-stale-flag-2026-11-04) |
| S5 | Lifecycle by source class (snapshot or search-based), Stale as a flag only | **Built in slices S5a to S5f; deployed** (2026-11-04) |
| S6 | Cancel a running Re-scrape (was 2b): stop the scrape, **save only the ads it validly collected** (the list is not rebuilt; nothing held, absent, closed or Stale; no proven run; `appliedRuns` untouched; dropped ads saved once under `partialRuns`), skip scoring; its own outcome, not a failed run. `POST /api/rescrape/cancel`, run status `cancelled`; the button is S7 | **Built and deployed** (2026-11-04). [Decisions](DECISIONS.md#s6-as-built-cancel-a-running-re-scrape-2026-11-04) |
| S7a | Run evidence in new records (`import` block: saved, new, refreshed, ledger effect, per-source proof with reason codes, per-board reasons, filter-reason counts; per-source times) and `GET /api/runs`: read-only, bounded, allow-listed, no lock, no process, no ledger or staging read | **Built and deployed** (2026-11-04). [Decisions](DECISIONS.md#s7a-as-built-run-evidence-in-the-record-and-get-apiruns-2026-11-04) |
| S7b | The Activity screen, read-only: nav item first in System, history (30 a page, Show more), per-source Details with the proof reasons, Not recorded for old records, loading, empty and error states. Asks on open, Refresh and Show more only; no polling, nothing stored in the browser | **Built and deployed** (2026-11-04). [Decisions](DECISIONS.md#s7b-as-built-the-activity-screen-read-only-2026-11-04) |
| S7c | Live view and Cancel: `GET /api/runs/<id>?after=N` (Node only, read-only), a 3 s poll only while Activity and the tab are visible and the run is active (back-off 3, 6, 12, 30 s), source rows and events as they arrive, Cancel with confirm on Activity and on the Jobs progress line ("Cancel requested" is not "Cancelled"), a Details link from Jobs, the list read once when the run ends | **Built and deployed** (2026-11-04). [Decisions](DECISIONS.md#s7c-as-built-the-live-view-and-cancel-on-activity-2026-11-04) |
| S8a | The job list never silently loses data to the browser's storage limit: tiers full / lean / minimal / error, a visible notice that names what is kept and what is reloaded, ad text of dropped rows reloaded from the ledger before any screen (`POST /api/jobs/texts`, `jobTexts.js`, `JobTextGate`), error keeps the last saved copy and says the change is not saved. Tailoring a kept or no-longer-listed ad says it cannot be done. | **Built and deployed** (`b498308`) |
| S8b | A run in which no source gave a usable result (all skipped, failed, partial or unfinished, or held as not run) imports nothing: ledger, view, corpus, lifecycle, `lastImport`, `sourceRuns`, `appliedRuns` and generation are the same bytes. `require_usable` is opt-in (the live path and `import_run.py --import` turn it on). All skipped: exit 0, Activity status stays Skipped, scoring is not run. Attempted and unusable: exit 1, a failed run with the reason. The Jobs screen says the list was not changed. | **Built and deployed** |
| later | Source order and per-source timeout policy (was 2c) | Not built |
| deferred | Ledger growth: `job_history.json` grows about 550 MB a year (about 10 KB per entry, about 150 new ads a day), and every import reads and rewrites it. Likely fix: descriptions out of the main file | **Deferred** (recorded 2026-11-03). [Decisions](DECISIONS.md#s5e1-as-built-dropped-ads-kept-in-filtered_adsjson-2026-11-03) |

**Review requirements for S3 / S4a (recorded 2026-11-03, not built):**

1. **A staging write failure must not pass as a saved run.** Today a failed staging write is only a warning in the run record. Before anything imports staging, a failed
   write (a source writer, the discards log or the run folder) must be marked in the run status, must stop the run from being treated as fully saved, and must stop
   the import from taking incomplete staging as if it were a complete scrape. **Done in S3:** the run record gets a `staging` field and an `error` issue (status `partial`), the folder gets `status.json`, and the importer refuses such a run.
2. **Retention must never delete a run that waits.** **Done in S4a (`staging.prune`):** staging is deleted by status, never a run still waiting for import or for recovery (S3 deleted nothing in between);
   the disk use is logged and printed.
3. **S3 import validates in full before it changes the ledger.** Staging validation (`staging.problems`) only requires `jobId`, `provider` and `title`; the import must
   check everything the commit path relies on (types, URL, dates, sizes, duplicates) on every ad. **Done in S3 (`importer.validate_ad`):** an ad that fails is left out and reported with a code, and its source is held
   like a source that did not run, so nothing is closed on the strength of an ad that went missing.

Backlog: Infostud completeness measurement (end of this work). Infostud is **not** classified snapshot-based until it is done. The six checks are postponed to the end of this work (owner, 2026-11-03).

**Backlog from owner decisions, 2026-11-03** (reasons in [DECISIONS.md](DECISIONS.md#owner-decisions-baseline-score-role-filter-infostud-testing-2026-11-03)). None is started:

- [ ] **Scoring baseline for junk or empty ads.** A made-up manual job with a junk description scored 44 (Weak, P3, Maybe; Role 45, Skill 20, Industry 55, Experience 65, Location 50, Culture 58). The owner expects at most about 5 and an "insufficient data" label. Deferred to the end of the current Activity work and solved with [Fix scoring](#fix-scoring-skill-extraction-scope-requirement-weighting-domain-transferability---todo).
- [ ] **Role filter too strict across platforms.** `role_filter.py` checks `TITLE_EXCLUDE` ("project manager", ...) first, and an ad with no include term is dropped silently (Infostud: 392 of 409 dropped with no reason; for example ad 765172 "Medior Dev Project Manager Niš", position "IT Project Manager"). Idea: three tiers (clear no / clear yes / borderline kept with a "for review" flag; AI only on a borderline title plus a short description). Depends on the scoring fix and on the discard-reason data from S2. Deferred.
- [ ] **Infostud stays unclassified** (not snapshot-based) until its fetch coverage is confirmed; the six checks are postponed to the end.
- **Testing rule:** the owner tests everything at the end. No merge and no production before the real-container integration check.

Owner corrections to slice A1, all done: an empty board holds its ads; a source that does not apply is `skipped`; a run where every
source was skipped is `skipped`; a source that skipped or failed keeps its ads in `discovered_jobs.json`.

**Built 2026-11-03, browser only, ahead of the lifecycle slice (S5):** an ad that leaves the file no longer takes the owner's data with it. The import keeps a row
holding a status other than `new`, AI insights, tailored assets, outreach or legacy tracking, marked `offList` and hidden from default views. This is a
temporary protection until the Step 5 overlay. [Rule, terms and limits](DECISIONS.md#offlist-rows-keep-the-owners-data-2026-11-03).

**Built 2026-11-03, read-only:** every known ad and every non-voided application opens when its ad has left the list. `GET /api/jobs/history/<jobId>` serves one ledger snapshot, Job Details
falls back from row to file to ledger to the application's frozen posting and says "Not in the latest run", and the tracker stat cards and AI application context count from the application store.
No data migration; `localStorage` stays the job list until Step 5. [Rule and limits](DECISIONS.md#applications-open-without-the-ad-history-read-path-2026-11-03).

**For slice 4, unchanged so far:** a search-based ad that a successful run did not return leaves the file, the scored list and the
browser's default list with no badge, while the ledger keeps it open. A row with none of the owner's data is dropped from the browser. A skipped source's
ads, on the other hand, stay active with no time limit. [Details](DECISIONS.md#activity-slice-1-as-built-2026-11-02).

Left for a later slice from slice 1: scored, closed, missing and expired counts on the record.

**Known limitation:** `jobspy_adapter` can report a blocked LinkedIn search as a successful fetch with 0 ads, so run statistics for that
source are unreliable. It never closes ads automatically. `joberty_client.py` also drops listing pages it could not read
([details](DECISIONS.md#activity-slice-1-as-built-2026-11-02)).

## Import redesign (Wave 7) - in progress

Sources and design: [DECISIONS.md](DECISIONS.md#import-redesign).

| Slice | Content | Status |
|---|---|---|
| S0 | Atomic profile mirror write; import backup route (last 10, profile JSON only) | Built on `wave7-profile-import` (2026-11-09) |
| S1 | One source list + draft version; guarded apply (backup, one write, retry never re-applies, Undo); confirm step with cache impact | Built on `wave7-profile-import` (2026-11-09) |
| S2 | TXT / MD | Built on `wave7-profile-import` (2026-11-09) |
| S3 | JSON Resume | Built on `wave7-profile-import` (2026-11-09) |
| S4 | DOCX | Built on `wave7-profile-import` (2026-11-09) |
| S6 | PDF failure hardening (password, scanned, page cap, empty MIME type) | Built on `wave7-profile-import` (2026-11-09). Real-file check with one resume PDF and one LinkedIn PDF is still the owner's |
| S7 | Manual "Start blank" through the same review, confirm and apply | Built on `wave7-profile-import` (2026-11-09) |
| S5 | LinkedIn data ZIP | Last: waits for the owner's real file names and header rows |
| Gate | Full gate for S0-S4, S6, S7 on the real tree (2026-11-09): pytest 3040 passed, Vitest 2320 passed (the listed flaky `rescrape.test.js` failed once, passed on rerun), lint and build clean, mutation checks on the new logic, private files unchanged. Rerun the changed areas when S5 lands | Done |
| 1a | Wizard, paste step, review screen | Done |
| 1b | TXT / MD and DOCX | Not built ("Other file types are coming"). `python-docx` is already pinned |
| 3 | PDF and LinkedIn PDF | Listed after 1b, but both are already in the code (`PdfStep`, `4f2cd7e`). Real-file test below still open |
| 2 | LinkedIn data ZIP. Needs real export file names and headers | Not built |
| 4 | JSON Resume | Not built |
| 5 | Structured experience editors | Not verified |

A browser-extension profile import is only an idea (parked), not a Wave 7 source: see [the idea](#idea-holyjobs-browser-extension-linkedin-job-and-profile-import---idea--not-planned-for-implementation). LinkedIn PDF and the data ZIP stay the supported LinkedIn sources.

Also later: the Continue / Save wizard flow fix, the score 60/58 fix, and a LinkedIn PDF test on a real file.

## Tech debt leftovers

Known and left open on purpose. Checked against the code on 2026-11-02.

**Tests:**

- Flaky run-lock test in `tests/js/rescrape.test.js` ("a dead running record becomes interrupted at the first status; a live one does not"): `withRunLock` sometimes answers busy (seen 1 of 3 runs alone, and once in a full run). Deferred, not fixed.

**Step 5 (server master), [STEP5_SERVER_MASTER_PLAN.md](redesign/STEP5_SERVER_MASTER_PLAN.md):**

- `applied_manually` vs the tracker: "Mark as applied" still sets the old job status beside the application store's record.
- `offList` rows migrate as orphans, not active `record` entries ([decision](DECISIONS.md#offlist-rows-keep-the-owners-data-2026-11-03)).
- Whole-list save: the Jobs, Applications and Outreach screens still save their whole list from memory (`saveJobs`).
- Hard-coded `serbia` provider group: `scripts/run-discovery.js`, `run-pipeline.js`, `api-handler.js`, `PipelineOrchestrator.jsx`, `JobDiscoveryScreen.jsx` and `npm run discover:jobs`.

**Phase 4, strict xfails in `tests/python/test_llm_tailor.py`:**

- The fact gate only sees metric-shaped numbers, so "47 engineers" passes.
- Refusal and rejection reasons are stored in `tailoredAssets.llmIssues` but not shown to the owner.
- Identifiers inside the sections LLM tailoring sends are not redacted.
- LLM tailoring has no confirm step.

**Untested:**

- `scripts/run-tailor.js` and the `/api/tailor/*` routes.
- A bulk tailoring run that aborts. A malformed draft in a bulk run is covered; a failure outside the draft is not (below).
- Empty stdout with a non-zero exit from the Claude Code CLI: `claude_code._call` does not read the exit code, and the tests only use exit 0.
- "dynamic": the tailoring prompt bans it, but it is not in `BANNED_PHRASES` (`candidate_text.py`), so code does not enforce it and no test covers it.
- Project intelligence metrics are not a fact source: `build_canonical_facts` does not read that file, so a draft that uses a metric from it is rejected. Nothing tests this.

**Tailoring and audit behaviour:**

- `provenance_auditor.py`: the metric, degree and certification checks match whole tokens, but the company check still uses `cl in k or k in cl`, so a short known name can vouch for a longer company name. A severe finding comes from it, so changing it can move jobs to `needs_review`.
- A failure outside the draft (disk full, render crash) still stops `run_tailor.main()` before `scored_jobs.json` is saved. There is deliberately no catch-all, because it would hide real errors.

**Manual owner steps:**

- `chmod 600` the top-level files of `data/` (`competency-*`, `competencies-review.md`, `discovery-test.log`, `engine-snapshot.json`, `requirement-remap.json`). `scripts/tighten-data-permissions.sh` covers folders only, not these. Command: `find data -maxdepth 1 -type f -perm /077 -exec chmod 600 {} +`.
- `chmod 700` the `audits`, `chat` and `data` folders. Already 700 on DS9 on 2026-11-02, with nothing inside `audits` or `chat` open to group or other; nothing is left to run.

## Later

- Multi-device access with server-side storage as the master.
- Scheduled discovery (nightly run: discover, enrich, score).
- More role families and their prompt variants for CVs and cover letters.
- Recalibrate `TARGET_COVERAGE` and fix the flat scoring dimensions (open problems in [ARCHITECTURE.md](ARCHITECTURE.md)).
- Judge a real run and compare the adjustments with the owner's own sense of the jobs.
- Redaction and a confirm step for LLM tailoring (privacy gap in [CLAUDE.md](../CLAUDE.md)), with the Phase 4 fact gate.
- Sources consent UI: replace the inline "I have read the terms" checkbox in Settings > Sources > Job boards with a
  modal. The user opens it from the Job boards section, selects which opt-in sources to enable, reads the terms for
  each, and confirms with one explicit action. Server behaviour stays as is: opt-in default off, the server stores its
  own `consentAcceptedAt`, switching off keeps history, switching on again asks for consent again. UI-only change.
  Reason: the inline checkbox under the chips looks bad and does not scale to more opt-in sources.
- ~~Jobs table: Applied button to the tracker, and the shadow badge off the table~~ built in Wave 5 (j), branch `wave6-application-tracking`, not merged.
- Settings follow-ups:
  - Usage & cost. Code check 2026-11-02: a section "AI budget, provider and usage" exists; what is still missing is not recorded.
  - Clear cache. Code check: `AISettingsPanel.jsx` has a button for the browser AI cache.
  - Remove the OpenAI key from `.env` after moving it to the store. Code check: `.env` still has `OPENAI_API_KEY`, and
    `data/secrets/` has no `ai.json` yet, so the move comes first.
  - Rotate the OpenAI key and `li_at`. Not verifiable from the repo.
- Job Details: tabs and AI spend per job.
- Step 6: browser AI confirm dialog ([redesign/BROWSER_STORAGE_POLICY.md](redesign/BROWSER_STORAGE_POLICY.md)).
- Next big scoring task: [Fix scoring](#fix-scoring-skill-extraction-scope-requirement-weighting-domain-transferability---todo).

## Ideas (not scheduled)

- **Prompt templates (business idea).** When AI writes answers to application questions, offer a template picker. Starter
  "humanizer" family, each wrapping a pasted text: Professional AI Humanizer; Natural Human Tone Converter; AI-Detection Safe
  Rewrite; Conversational Human Rewrite; Emotion & Flow Humanizer; Human Language Converter; Human Rhythm & Style Fixer; Final
  Humanized Master Edit. Any template run is an AI call, so the gate, redaction and confirm rules apply. Nothing is built.
- **"Fill from ad" (AI field extraction).** Needs the allowlist plus owner confirmation. Code check 2026-11-02: both steps are
  already built (Manual jobs in [CLAUDE.md](../CLAUDE.md)), and the AI step stays refused because `job-import` is not in
  `claudeCodeSubscription.features`.

## Inherited from Holojob

Discovery across LinkedIn (JobSpy), Infostud, Workable, Greenhouse, Lever and Ashby; job
history ledger; enrichment facts; work-authorization rules; fit judge; CV library and CV
analysis with verification; tailoring; outreach contact scraping. See CHANGELOG.md.

## DEFERRED after S8 (recorded 2026-11-04)

Functional gap (must be fixed, not just noted):
- [ ] **"Keep this ad" stores an ad but does not guarantee every action on it.** Tailoring a kept ad is impossible, because the server reads only the scored file; the button now says so (`NOT_IN_SCORED_LIST`). The fix is to let the tailor read a kept ad from the ledger or send its text, with the fact gate (Phase 4).

Deferred items (known, not scheduled):
- [ ] Runs with every source skipped used to hold rows of any search key (design 2026-11-02); with `require_usable` they no longer import. A caller that does not pass it (the plain importer) still holds them.
- [x] **Discovery safety rule (Wave 1, replaces the two items previously here; built, local branch):** see [Roadmap v2](#roadmap-v2-recorded-2026-11-04). A source that is `ok` with zero reads is not automatically usable and is not proof of closure, and a `partial` source's real ads are imported without waiting for another source.
- [ ] Text search covers only the rows that have text in the browser; ads whose text could not be reloaded are not found by it (the notice names how many).
- [ ] No bulk restore of kept-ad text from the ledger beyond the start-up reload of the rows stored without it.
- [ ] The 5,242,880-character localStorage limit is an assumption, not measured per browser.
- [ ] Hand-entered jobs have no flag saying whether the server has them.
- [ ] Direct `setItem` writers (the demo loader) bypass the storage budget in `saveJobs`.
- [ ] **Lead to verify (recorded 2026-11-09, no code change):** `MUST_HAVE_SHARE = 0.5` in `python/job_scoring/dimensions/skill_match.py` appears unused, since must-haves are reported in `missingSkills` and no longer scored (`score = bank_score`). Confirm with a grep and the tests, then remove the constant or document why it stays.
- [ ] A throttled source (`jobspy` read 4) can count as proven (Wave 1 now flags a search whose sites all raised as failed; a partly read search keeps its ads); about 1,934 `older_key` rows never go away (rule and prune script built in Wave 4; the owner runs it); `scoringBehind` is false after a cancel; the hand-edited `appliedRuns` xfail; no `init` in compose; pre-S6 backfill double-count; `lastImport.meta` is stale after a partial import (Wave 4: `lastPartial` records the attempt; `lastImport` stays the last complete import); a truncated ledger with a matching generation.

- **Test isolation (recorded 2026-11-09, after the profile-mirror incident):** the pytest and Vitest fingerprint guards only detect a change to `data/profile`, `data/intelligence`, `data/applications`, `manual_jobs.json` and `job-state.json`; they do not prevent it, and no other `data/` folder is checked. Long term every test uses an isolated data directory and never resolves the real `data/` ([DECISIONS.md](DECISIONS.md), "Incident 2026-11-09").
