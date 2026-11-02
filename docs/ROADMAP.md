# Holojob - Roadmap

Principles and decisions: [redesign/DECISIONS.md](redesign/DECISIONS.md).
Current-state audit and module decisions: [redesign/PHASE0_AUDIT.md](redesign/PHASE0_AUDIT.md).
Engine contract (draft): [redesign/ENGINE_CONTRACT.md](redesign/ENGINE_CONTRACT.md). Terms: [GLOSSARY.md](GLOSSARY.md). How the system works today: [ARCHITECTURE.md](ARCHITECTURE.md).

This is the only phase list; DECISIONS.md, CLAUDE.md and the README link here.

| Phase | Scope | Status |
|---|---|---|
| 0 | Audit: what exists, per-module Reuse / Adapt / Build / Skip, engine contract | Done |
| 1 | Scoring core: role-family config, requirement extraction with quotes and canonical ids, evidence index, evidence matcher + deterministic Fit, confidence, gates. Shadow mode next to the current score; stability test on fixtures | Steps 1-8c built (role families, requirements, evidence index, matcher, Fit and gates, stability test, shadow mode, privacy test); acceptance criteria pending owner confirmation; stable-id follow-up in progress (below) |
| 2 | Evidence profile: restructured optional questionnaire (story bank, skills with evidence, preferences, gates), AI prefill from the CV through the review screen, ask-user loop that stores confirmed facts | Planned |
| 3 | Application tracker independent of discovery: own store with a posting snapshot, append-only event history, channel, CV version, outcomes, follow-up nudges, import of past applications | In progress. Built: store with event history and configurable stages, migration from job records, Job Details tracker (Mark Applied, CV used, history, void and restore), Board with drag, Statistics, Settings > Applications (tracking switch, columns). Not built: posting snapshot view, Closed panel, "Show voided", removal of the legacy `applicationTracking` field (S4), follow-up nudges and the reminders switch's UI (S5), CSV import of past applications (S6). See [redesign/TRACKER_PLAN.md](redesign/TRACKER_PLAN.md) |
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
| 4 | **Checks pass.** `npm run lint`, `npm test` (vitest and pytest) and `npm run build` pass | Run on the host, no failures | - |

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
   Seed, validator (`python/match_engine/competencies.py`) and report (`npm run competencies:report`, writes
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

## Inherited from Holojob

Discovery across LinkedIn (JobSpy), Infostud, Workable, Greenhouse, Lever and Ashby; job
history ledger; enrichment facts; work-authorization rules; fit judge; CV library and CV
analysis with verification; tailoring; outreach contact scraping. See CHANGELOG.md.
