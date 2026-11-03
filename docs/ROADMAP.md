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
   Seed, validator (`python/match_engine/competencies.py`) and report (`podman exec career-os npm run competencies:report`, writes
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

- [ ] **Skill extraction covers the whole work history.** JavaScript, React, PHP, HTML, CSS, Git, Figma and REST APIs
  were flagged missing although they are explicit in an earlier role (Senior Web Programmer, 2014-2021). Today only
  recent roles are read.
- [ ] **Hard vs. nice-to-have requirements.** A "plus if you have X" line was weighted like a must-have. The model
  tags each requirement hard or soft as a fact; `scorer.py` decides the weight (architectural rule in CLAUDE.md).
- [ ] **Domain transferability.** "No clear industry match" was emitted for B2B two-sided dynamics (carrier / shipper)
  that are structurally similar to the posting's marketplace (host / guest). Judge structural similarity, not a flat
  mismatch.
- [ ] **Low-confidence reasons only when the signal is absent.** "seniority not stated" and "no strong culture
  signals" fired on a posting that lists salary bands per seniority tier and 3-month / 6-month onboarding milestones.
  Guard each string with a check of the source text.
- **Must NOT change: location mismatch detection.** It worked correctly in this test; the location cap rules, the
  "Verify location" flag and the location gate stay untouched, and their tests must keep passing.

Each item gets a fixture-based regression test; the Phase 1 stability test must keep passing. Related: "Recalibrate
`TARGET_COVERAGE` and fix the flat scoring dimensions" under Later.

## Activity screen - planned

A new screen named Activity, in the nav group System, built in this repo. Decisions and known gaps:
[DECISIONS.md](DECISIONS.md#activity-screen-approved-2026-11-02).

Two numberings meet here. **A1 and A2a** are the slices built earlier (run log; background Re-scrape). **S1 to S7** are the SCRAPE -> IMPORT -> SCORING
slices approved 2026-11-03: a scrape writes staging only, an import (idempotent, its own step) commits, scoring follows and never undoes the import.
Plan, approved decisions and rollback per slice: [DECISIONS.md](DECISIONS.md#scrape-import-scoring-approved-2026-11-03). Each S slice is small and shippable alone.

| Slice | Content | Status on 2026-11-03 |
|---|---|---|
| A1 | Per-source outcome and run log, including a fix so a failed board cannot close its existing ads | **Built.** `python/job_discovery/run_log.py`, records in `data/analytics/runs/`. [Shape and deviations](DECISIONS.md#activity-slice-1-as-built-2026-11-02) |
| A2a | Background Re-scrape: one job with a lock over discovery and scoring, an event log, the interrupted state, a commit marker | **Built, not deployed.** `python/run_rescrape.py`, `python/job_scoring/pipeline_lock.py`, `scripts/run-rescrape.js`. Tailoring merges at write time and backup export refuses during a run or after an unfinished commit. [Mechanism and limits](DECISIONS.md#activity-slice-2a-background-re-scrape-2026-11-03) |
| S1 | Staging store and ad records, then streaming. **1a:** `data/jobs/staging/<runId>/<source>.jsonl` (header, batches, footer), reader and validator, a hard link of the ledger as the run found it, last 3 runs kept, excluded from backup and restore, Joberty reads the ledger read-only. **1b:** providers append while they collect. No behaviour change: the old commit path is untouched and nothing reads staging yet | **1a built, not deployed.** `python/job_discovery/staging.py`. [What is staged and what is not](DECISIONS.md#scrape-import-scoring-approved-2026-11-03) |
| S2 | Per-ad discard reasons plus `externalId`: source-stage reasons in the staging data | Not built |
| S3 | `import --dry-run` (writes nothing) and the import report with import-stage discard reasons; compared with the current commit on real runs before the switch | Not built |
| S4a | The switch: scrape -> import -> scoring, ledger as single source of truth with a derived `discovered_jobs.json`, generation check before any reader, automatic recovery, commit marker removed, closures stop, 90-day ledger prune off. Manual backup first | Not built |
| S4b | Demote then remove the debug mirrors `raw_jobs.csv` and `normalized_jobs.json` (no reader exists; confirmed 2026-11-03) | Not built |
| S5 | Lifecycle by source class (snapshot or search-based), Stale as a flag only; after a dry-run comparison on real data | Not built |
| S6 | Cancel a running Re-scrape (was 2b): stop the scrape, import what is written, skip scoring; its own outcome, not a failed run | Not built |
| S7 | `GET /api/runs` read API and the Activity screen (was 3) | Not built |
| later | Source order and per-source timeout policy (was 2c) | Not built |

Backlog: Infostud completeness measurement (end of this work). Infostud is **not** classified snapshot-based until it is done.

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

## Import redesign - in progress

Sources and design: [DECISIONS.md](DECISIONS.md#import-redesign).

| Slice | Content | Status on 2026-11-02 |
|---|---|---|
| 1a | Wizard, paste step, review screen | Done |
| 1b | TXT / MD and DOCX | Not built ("Other file types are coming"). `python-docx` is already pinned |
| 3 | PDF and LinkedIn PDF | Listed after 1b, but both are already in the code (`PdfStep`, `4f2cd7e`). Real-file test below still open |
| 2 | LinkedIn data ZIP. Needs real export file names and headers | Not built |
| 4 | JSON Resume | Not built |
| 5 | Structured experience editors | Not verified |

Also later: the Continue / Save wizard flow fix, the score 60/58 fix, and a LinkedIn PDF test on a real file.

## Tech debt leftovers

Known and left open on purpose. Checked against the code on 2026-11-02.

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
- Jobs table: Applied button to the tracker, and the shadow badge off the table ([open direction](DECISIONS.md#jobs-table---open-discussion-not-final)).
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

## Inherited from Career OS

Discovery across LinkedIn (JobSpy), Infostud, Workable, Greenhouse, Lever and Ashby; job
history ledger; enrichment facts; work-authorization rules; fit judge; CV library and CV
analysis with verification; tailoring; outreach contact scraping. See CHANGELOG.md.
