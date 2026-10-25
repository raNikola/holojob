> Dated snapshot as of commit a3b6ce8; not updated afterwards. Sections of CLAUDE.md cited below now live in [../ARCHITECTURE.md](../ARCHITECTURE.md); the current phase list is [../ROADMAP.md](../ROADMAP.md).

# Phase 0 audit - code side

Scope: the Holojob code on `main` (commit 897c09f) measured against `DECISIONS.md`,
plus the ported-from sources. DS9 runtime facts (job volume, AI setup, data shapes)
come from the DS9 report and `data-shapes.md`; they are quoted, not re-measured.

## 1. Headline

Holojob is much further along than the public Holojob it was forked from. The
core rule of `DECISIONS.md` - the model marks facts, code computes - is already the
rule of this repo (CLAUDE.md, "The architectural rule"), and three of its pieces
exist:

- **Requirement facts per ad** - `enrich_jobs.py` reads every ad, never sees the
  candidate, and stores `llmFacts` (role track, seniority, years, up to 8
  must-haves, up to 6 nice-to-haves, domain, visa, remote eligibility) cached by an
  ad fingerprint.
- **Requirement-level statuses** - the opt-in judge in `llm_enhancer.py` already
  returns `requirements[] {requirement, status: met | partly_met | not_met | unclear,
  evidence}`, with "silence is unclear, not not_met" in its rules.
- **Hard rules in code** - `scorer.py` caps off-track roles (50), red flags (54) and
  work authorization (25 / 40 / 45); `work_authorization.py` resolves the status.

What is missing is the step that turns the requirement statuses into the number.
Today the score is six weighted dimensions where `skillMatch` is keyword coverage
weighted by run-local IDF, and the judge's per-requirement statuses are discarded:
only its holistic `fit` category is used, as a +5 / 0 / -8 / -15 adjustment, and
only for jobs already at 65+ (max 50 per run). CLAUDE.md "Open problems" 1 states
the effect: role, culture and location give every surviving job about 70 points,
so scores bunch between 68 and 78.

So Phase 1 is an **adaptation of existing modules**, not a new engine from zero.

## 2. Current state by area

| Area | What exists | Gap against DECISIONS.md |
|---|---|---|
| Job sources | 6 providers in the `serbia` group: jobspy (LinkedIn only), infostud, workable, greenhouse, lever, ashby. Two-pass dedup. Ledger `job_history.json`. One day of data on DS9 (552 jobs, 2 runs). | No scheduler yet (CLAUDE.md "Next" 4). Not a redesign item. |
| AI layer (server) | `python/job_scoring/llm_client.py`: provider table (OpenAI, DeepSeek, OpenRouter, Groq, Ollama, custom, Claude Code CLI), JSON-schema output, `judge_model()`. DS9: OpenAI. | Reusable as is for the engine. |
| AI layer (browser) | `src/modules/ai/*`: provider registry, features (jobAnalysis, coverLetter, interviewPrep, skillGap, ...), settings in localStorage. | A second AI stack the server cannot see. Engine stays server-side; browser features later read engine output. |
| Requirement extraction | `enrich_jobs.py` `FACT_SCHEMA` v-current. | Must-haves are bare strings: no kind, no per-requirement quote, no canonical id, cap of 8/6. |
| Evidence source | `profile.resume.parsedData.experienceDetail` (title, company, start, end, bullets), `competencyGroups`, `toolGroups`, skills; intelligence maps (`experienceMap.projectHighlights`, ownership, leadership, impact examples); questionnaire answers. CV analysis already verifies every extracted item against the CV text (`cv_analysis/analysis.py`). | No evidence index with ids; the judge sees a digest of summary lists, not dated roles; nothing checks the judge's `evidence` text against a source. No confirmed/denied candidate facts store. |
| Scoring | `scorer.py` + six dimensions, weights in `src/data/scoringWeights.json`, caps, `labels.py` (Apply 70, P1 76). | Fit from evidence coverage does not exist; UNKNOWN handling, confidence and the "Incomplete" label do not exist. |
| Gates | `work_authorization.py` statuses; caps in `scorer.py`; language dealbreakers via the judge. | Implemented as caps, not as Apply / Check first / Blocked buckets. Close enough to adapt (label on top of the cap). |
| Role families | `ROLE_TRACKS` enum in `enrich_jobs.py`; `ACCEPTABLE_TRACKS = {product_management, product_ownership}` hard-coded in `scorer.py`; `src/data/jobRoles.json` is a flat list of 633 titles; target roles in `roleStrategy`. | Product is hard-coded as the only acceptable track. No family -> title synonyms config. |
| Old dictionary | `src/data/skillsDictionary.js`, `src/modules/intelligence/skillsClassifier.js`, feeding `skillsMap` and `atsKeywordBank`. | Keep as Engineering/QA alias list; stop using it as a score source once Fit exists. |
| Questionnaire | 17 questions, `src/data/questions.js`. Enforced only in the onboarding wizard (`OnboardingWizard.jsx` via `src/utils/validators.js` `validateQuestion` / `validateQuestionnaireSection` / `validateStep`). Edit Profile does not enforce. CV analysis already writes answers 4 and 17. | Restructure and make optional (Phase 2). |
| CV library + review | `src/utils/cvLibrary.js`, `scripts/cv-store.js`, `CvAnalysisReview`, `regenerateAfterApply.js`. | Reuse for AI prefill of the profile (Phase 2). |
| Tracker | `applicationTracking` on the job record (`src/modules/jobs/applicationTracking.js`): applied, date, URL, recruiter, notes, follow-up date, one `interviewStage` from a fixed list; `followUps.js`; `ApplicationTrackerPanel.jsx`. | No event log, no channel, no CV version, no outcome enum. **Risk:** tracking lives on the job and `mergeStatusOnImport` (`src/modules/jobs/jobStorage.js`) keeps only incoming jobs, so an applied job that leaves the discovered list loses its tracking. |
| Interview prep | Browser AI feature `interviewPrep` (`aiPromptLibrary.js`: technical, behavioral, system design, STAR answers, company questions). | Not tied to the job's requirement statuses or to a story bank. |
| Fact gate | `python/resume_generator/provenance_checker.py` (54 lines: substring and metric regex against profile facts); CV analysis `verify`. | Weak compared to ApplyPack's `fact-check.ts`. |
| Privacy of tailoring | `python/resume_generator/llm_tailor.py` sends parsed CV sections (about_me, experience, skill_categories, education), an intelligence summary and project intelligence to the Claude Code CLI. | Not listed under "Privacy exceptions" in CLAUDE.md; no confirm step and no redaction pass. Against principle 14; fix with H in Phase 4 (redact with `redact.py`, add the confirm, list it in CLAUDE.md). |
| Market report | None. `llmFacts.mustHaves` for every ledger job already exist. | Build. A raw version is cheap now; the real one needs canonical ids. |

## 3. Module decisions

Effort: S under a day, M a few days, L about a week of focused work.

| Module | Decision | Base in Holojob | Port from | What changes | Effort | Risks |
|---|---|---|---|---|---|---|
| Engine contract | BUILD | - | ApplyPack `src/resume/score.ts` (structure of a pure scorer with versioned constants) | New package `python/match_engine/` with pure functions and a JSON in/out contract (section 4). CLI wrapper for the pipeline and tests. No UI imports. | M | Scope creep into a framework. Keep it to functions + one CLI. |
| A Prefilter | ADAPT | `work_authorization.outside_allowed_before_enrichment`, location rules, `roleStrategy` | career-ops `title-keywords.mjs`, `role-matcher.mjs` (ideas) | Add role-family title synonyms and avoid-roles before any model call; report how many jobs each rule drops. | S | Over-filtering hides good jobs: log, never silently drop. |
| B Requirement extraction | ADAPT | `enrich_jobs.py` | ApplyPack ADR 0044 (either/or groups read once), career-ops `skill-extract.mjs` (canonical vocabulary for tech terms) | Schema adds `requirements[] {text, kind, importance: must/preferred/nice, quote}`; keep existing fields. Code maps each requirement to a canonical id or a deterministic provisional id. Bump `PROMPT_VERSION`. | M | Version bump re-reads every cached ad (cost). Decomposition instability (measure, section 5). |
| C Evidence profile | ADAPT | `parsedData.experienceDetail`, competency/tool groups, intelligence example lists, questionnaire answers | ApplyPack `src/resume/evidence.ts` (strength grading), `src/resume/usage.ts` (recency from dated roles), `src/resume/facts.ts` (confirmed/denied facts) | Build an evidence index without AI: one item per bullet/example with id, text, role, dates; grade strength 1-4 in code (listed, in a role, described as work, with a number). New store for confirmed/denied facts. | M | Profiles with flat skills and no bullets give low strength everywhere: show it as confidence, not as a low score. |
| D Match + score | ADAPT | `llm_enhancer.py` (prompt, schema, cache, privacy boundary), `scorer.py` caps, `labels.py` | ApplyPack `src/resume/keyword-anchor.ts`, `src/screening/anchor.ts` (quote checks), `src/screening/score.ts` (caps, confidence, unknown out of the denominator) | Judge becomes the matcher: per requirement `status` + `evidence_id` + quote. Code checks the quote exists in that evidence item (else downgrade), computes Fit (importance weight x status credit x strength credit), confidence, Incomplete label, gate bucket. Fit replaces `skillMatch` first; whether role/culture/location stay as points is decided from shadow-mode data. | L | Cost per run (matching sees the candidate, so it is per job and profile version). Privacy: needs more candidate text than today's digest. |
| E Role families | BUILD | `ROLE_TRACKS`, `ACCEPTABLE_TRACKS`, `jobRoles.json`, `roleStrategy` | CareerPulse `app/matcher.py` role taxonomy (idea) | `src/data/roleFamilies.json`: family -> title synonyms, accepted role tracks, later prompt variant. `scorer.py` reads the candidate's family instead of the hard-coded set. Seed Product, Engineering, Design, QA, Data. | S-M | Enum in the enrichment prompt must stay in step with the config (test). |
| F Tracker | ADAPT | `applicationTracking.js`, `followUps.js`, `ApplicationTrackerPanel.jsx` | ApplyPack ADR 0024 / 0025 (append-only stage ledger, custom stages), JobSync `prisma/schema.prisma` (JobStage, Question, JobStagePrepQuestion), career-ops `funnel-stages.mjs`, `outcome.mjs` (outcome set) | Move applications to their own store keyed by job, so they outlive the job list; append-only events with dates; channel, CV id sent, outcome; CSV import of past applications. | M | Migration of existing tracking (small; one user). |
| G Interview prep | ADAPT | browser `interviewPrep` feature | career-ops `match-star.mjs` (zero-LLM story matching), `modes/interview-prep.md`; CareerPulse `app/routers/tailoring.py` interview-prep; JobSync question bank with asked flag | Feed prep with the job's requirement statuses and the story bank; track which questions were asked. | M | Depends on C (story bank). |
| H Fact gate | ADAPT | `provenance_checker.py`, CV analysis `verify` | ApplyPack `src/resume/fact-check.ts` (pure, 456 lines), ADR 0020 | Port the fact gate to Python and use it for tailored CVs and cover letters. career-ops `verify-cv-facts.mjs` (3015 lines): SKIP, too large for the gain. | M | Over-blocking truthful text; follow ApplyPack's "block fabrication, not imprecision". |
| I Market report | BUILD | `job_history.json` `llmFacts` | career-ops `analyze-patterns.mjs` (ideas) | Aggregate requirements by canonical id per role family; mark which the candidate has evidence for. A raw (text) version can ship early. | S-M | Needs B's canonical ids for anything beyond a word count. |
| Calibration (Phase 5) | ADAPT | - | career-ops `calibrate.mjs` (score bands x outcomes, n floors, separating / flat / inverted / insufficient verdict) | Port the pure logic once F records outcomes. Report only, never auto-tunes. | S | Needs outcome volume. |

JobOps (Commons Clause) contributed ideas only (stage list, job brief); no code.

## 4. Engine contract (draft)

Input:

```json
{
  "posting": {
    "id": "<string>", "title": "<string>", "company": "<string>",
    "location": "<string>", "description": "<string>",
    "facts": "<llmFacts incl. requirements[] from B>"
  },
  "candidate": {
    "profileVersion": "<hash>",
    "roleFamily": "<string>",
    "evidence": [{ "id": "<string>", "text": "<string>", "source": "role|project|example|questionnaire|fact",
                   "role": "<string|null>", "start": "<YYYY-MM|null>", "end": "<YYYY-MM|null>", "strength": 1 }],
    "confirmedFacts": [{ "competencyId": "<string>", "has": true, "note": "<string>" }],
    "gates": { "workAuthorization": "<object>", "allowedLocations": ["<string>"], "languages": ["<string>"], "minSalaryEur": "<number|null>" }
  }
}
```

Output:

```json
{
  "engineVersion": "<string>",
  "requirements": [{
    "id": "<canonical or provisional id>", "provisional": true, "text": "<string>",
    "kind": "<string>", "importance": "must|preferred|nice", "postingQuote": "<string>",
    "status": "MET|PARTIAL|MISSING|UNKNOWN", "evidenceId": "<string|null>",
    "evidenceQuote": "<string|null>", "quoteVerified": true, "strength": 0
  }],
  "gates": [{ "gate": "<string>", "result": "pass|unknown|fail", "quote": "<string|null>" }],
  "bucket": "apply|check_first|blocked",
  "fit": 0, "cvCoverage": 0, "confidence": 0,
  "label": "Strong|Good|Partial|Weak|Incomplete",
  "counts": { "mustMet": 0, "mustTotal": 0, "preferredMet": 0, "preferredTotal": 0, "unknown": 0, "blockers": 0 },
  "caps": ["<string>"],
  "questions": [{ "competencyId": "<string>", "question": "<string>" }]
}
```

`cvCoverage` is computed in Phase 4 (CV tailoring); Phase 1 returns null.

## 5. Phase 1 proposal

1. **E** role families config; `scorer.py` and enrichment read it instead of the hard-coded product tracks.
2. **B** enrichment schema with requirements, quotes, kinds, importance; canonical / provisional ids in code.
3. **C (minimal)** evidence index built from data that already exists; no questionnaire changes yet.
4. **D** matcher + deterministic Fit, confidence, Incomplete label, gate bucket, in `python/match_engine/`.
5. **Shadow mode**: compute Fit next to the current `matchScore`, show both in the job drawer, change no ranking. Switch only after comparing on the fixtures and one real run.
6. **Stability test** (acceptance criterion): the 10 fixtures in `tests/fixtures/postings/`, 3 runs each, report requirement-id overlap, status flips and Fit spread; stabilizers: deterministic settings where the provider allows, cache by (ad fingerprint, profile version, prompt version), previous requirement frame fed back for the same ad.
7. Tests: pure-function tests for the scorer, anchor and id mapping; a parity test that the role-family enum and the prompt stay in step.

## 6. Decisions needed from the owner

**Resolved 2026-10-25** (recorded in DECISIONS.md, principles 13-15 and the decisions log):
1. Privacy: yes, with full name, phones, e-mails and personal links (CV site, LinkedIn, GitHub, any profile URL) redacted.
2. Budget: top 50 per run, as the judge does today.
3. Single user stays for now; multi-device access later. CLAUDE.md is not changed for this yet.
4. Shadow mode first: yes.
5. No applications are tracked yet, so nothing to migrate. Application tracking becomes independent of discovery (principle 13), built in Phase 3.

The original questions, for reference:

1. **Privacy.** Evidence matching needs candidate text with roles, dates and bullets, more than today's digest. Proposal: send the evidence index built from `experienceDetail` and the example lists, redacted with `redact.py` (no name, contacts, links), behind the same explicit confirm as `--judge`. Yes / no?
2. **Budget.** Matching runs per job and profile version. Today the judge is capped at 50 jobs per run above 65. Proposal for shadow mode: prefilter + the top 50 by current score, cache everything. Rough size per job: ad up to `MAX_DESCRIPTION_CHARS` plus evidence index plus about 1k tokens out. Confirm the cap.
3. **CLAUDE.md says "Not a product: optimise for this one candidate"**, while DECISIONS.md plans role families for colleagues. Proposal: keep single-user for now, but remove product-only hard-coding in Phase 1 so another role family works by config. Update CLAUDE.md accordingly?
4. **Shadow mode first** (recommended) or replace `skillMatch` directly?
5. **Tracker risk** in section 2 (tracking lost when an applied job leaves the list): fix it as a small task before Phase 3?
