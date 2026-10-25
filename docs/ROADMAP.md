# Holojob - Roadmap

Principles and decisions: [redesign/DECISIONS.md](redesign/DECISIONS.md).
Current-state audit and module decisions: [redesign/PHASE0_AUDIT.md](redesign/PHASE0_AUDIT.md).
Engine contract (draft): [redesign/ENGINE_CONTRACT.md](redesign/ENGINE_CONTRACT.md). Terms: [GLOSSARY.md](GLOSSARY.md). How the system works today: [ARCHITECTURE.md](ARCHITECTURE.md).

This is the only phase list; DECISIONS.md, CLAUDE.md and the README link here.

| Phase | Scope | Status |
|---|---|---|
| 0 | Audit: what exists, per-module Reuse / Adapt / Build / Skip, engine contract | Done |
| 1 | Scoring core: role-family config, requirement extraction with quotes and canonical ids, evidence index, evidence matcher + deterministic Fit, confidence, gates. Shadow mode next to the current score; stability test on fixtures | Next |
| 2 | Evidence profile: restructured optional questionnaire (story bank, skills with evidence, preferences, gates), AI prefill from the CV through the review screen, ask-user loop that stores confirmed facts | Planned |
| 3 | Application tracker independent of discovery: own store with a posting snapshot, append-only event history, channel, CV version, outcomes, follow-up nudges, import of past applications | Planned |
| 4 | Interview prep from requirement statuses and the story bank; CV and cover letter tailoring behind a fact gate; market report of requirements per role family | Planned |
| 5 | Feedback loop: conversion by channel and Fit band, calibration of Fit against real outcomes (report only, never auto-tuning) | Planned |

## Phase 1 acceptance criteria - PROPOSED, owner to confirm

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

## Later

- Multi-device access with server-side storage as the master.
- Scheduled discovery (nightly run: discover, enrich, score).
- More role families and their prompt variants for CVs and cover letters.
- Recalibrate `TARGET_COVERAGE` and fix the flat scoring dimensions (open problems in [ARCHITECTURE.md](ARCHITECTURE.md)).
- Judge a real run and compare the adjustments with the owner's own sense of the jobs.
- Redaction and a confirm step for LLM tailoring (privacy gap in [CLAUDE.md](../CLAUDE.md)), with the Phase 4 fact gate.

## Inherited from Holojob

Discovery across LinkedIn (JobSpy), Infostud, Workable, Greenhouse, Lever and Ashby; job
history ledger; enrichment facts; work-authorization rules; fit judge; CV library and CV
analysis with verification; tailoring; outreach contact scraping. See CHANGELOG.md.
