# Holojob - Roadmap gap analysis (target: 15 modules, finding a job to accepting an offer)

Status: ANALYSIS, 2026-10-29. Read-only. ROADMAP.md, code and `data/` are unchanged. Not committed.

Inputs:
- the docs: CLAUDE.md, [../ROADMAP.md](../ROADMAP.md), [DECISIONS.md](DECISIONS.md), [PHASE0_AUDIT.md](PHASE0_AUDIT.md),
  [TRACKER_PLAN.md](TRACKER_PLAN.md) (committed `7ff5ae0`) and [data-shapes.md](data-shapes.md);
- the code at commit `7ff5ae0` plus the S1 work (committed afterwards as `5e549a4`), read file by file;
- ApplyPack at `5b1edfe9` (the clone used for the tracker plan).

## How to read this

**Status**
- **EXISTS:** working in committed code, with a function, route or test named as evidence.
- **PARTIAL:** some of the capability exists. The evidence says which part.
- **PLANNED:** only in ROADMAP.md, PHASE0_AUDIT.md or TRACKER_PLAN.md.
- **MISSING:** in no code and no plan.
- **S1\*:** implemented in the application tracker S1 commit `5e549a4` (`scripts/application-store.js`,
  `src/modules/applications/`, `tests/js/applicationStore.test.js`, `tests/python/test_application_store_isolation.py`,
  and diffs in `scripts/api-handler.js`, `scripts/backup-handler.js`). It is committed but not counted as EXISTS: no screen uses it yet.

**How each claim was checked**
- **V-code:** read in the source.
- **V-test:** a named test exists for it. The offline Python suite was run for this analysis: `.venv/bin/python -m
  pytest -m "not network"`, **860 passed, 2 deselected**. The JS suite (vitest) was **not run**: the host has no
  Node.js and the image carries no tests. So JS test names below are read, not observed passing. That includes
  every S1\* test.
- **A:** an assumption, not checked. Each one is marked.

**AI column**
- **none:** works offline, no model call.
- **opt:** works without AI, and AI adds to it.
- **req:** cannot work without a model call.

"Paid" means a call billed per token. Career OS also has keyless providers, `ollama` (local) and `claude-code` (the
CLI on the owner's subscription), in `llm_client.py` `KEYLESS`. Whether they count as "AI budget 0" is decision D1.

**Principle column:** a conflict with DECISIONS.md principles 8 (fact gate), 14 (privacy, redaction, confirm), 13
and 15 (own stores, server master), or the CLAUDE.md architectural rule "the model marks facts, code computes
numbers". A dash means no conflict found.

**Size:** S is up to about 2 days, M up to about a week, L is more.

## 0. Findings that change the order

1. **No AI hard limit exists anywhere, and one automation spends without a confirm.**
   - **Enrichment runs unconfirmed** (V-code). `python/run_pipeline.py` `execute()` runs `enrich_jobs.py` on every
     "Run Full Pipeline", `npm run pipeline` and cron run. It has no confirm and no spend ceiling. `llm_client.py`
     `active_provider()` picks the first provider whose key is set, else falls back to `claude-code`.
   - **Only per-run caps exist** on the other paths:
     - the judge: top 50 at or above 65, `llm_enhancer.py` `select()`, `DEFAULT_THRESHOLD = 65`;
     - the shadow matcher: `match_engine/shadow.py` `DEFAULT_LIMIT = 50`;
     - tailoring: `--tailor-limit 10`.
   - **Browser usage tracking estimates only.** `src/modules/ai/aiUsageTracker.js` `trackAiUsage()` counts estimated
     tokens (`aiCostEstimator.js` `estimateTokens`) in `localStorage`, for browser AI features only. The Python calls
     (enrichment, judge, matcher, CV analysis, tailoring) are counted nowhere.
   - **With an AI budget of 0, this is the first thing to fix.** It is free work.
2. **Layer 1 ranking depends on AI enrichment** (V-code, V-test).
   - The pipeline stops when fewer than 80% of jobs are enriched: `DEFAULT_MIN_ENRICHED = 0.8`, tests
     `test_too_few_enriched_jobs_stops_before_scoring`, `test_min_enriched_can_be_relaxed`.
   - `--skip-enrich` exists and is labelled "not recommended".
   - So with no AI at all, discovery and scoring run degraded: no `llmFacts` (role track, seniority, work mode).
     Local `ollama` would keep it free (D1).
3. **An unlisted privacy gap** (V-code). The browser AI features send the candidate's **full name and e-mail**, plus
   recruiter contacts, to the provider:
   - **Which features:** the `/api/ai/*` routes in `scripts/api-handler.js` `AI_ROUTES`: job analysis, cover
     letter, interview prep, outreach, company intelligence, career strategy, skill gap and application strategy.
   - **How the data gets there:** `aiContextBuilder.js` `summarizeProfile()` puts `name: bp.fullName` and
     `email: bp.email` into the context. `aiClient.js:19` builds that context, and `aiPromptLibrary.js` `buildMessages()` serializes it into the prompt
     (line 15).
   - **Missing safeguards:** there is no `redact.py` pass and no confirm step.
   - **Mitigation:** the default provider is `mock` (`scripts/run-ai.js:76`).
   - **Not listed:** CLAUDE.md lists only CV analysis, the judge, the matcher and the known `llm_tailor.py` gap. This
     violates principle 14 whenever a real provider is selected (D3).
4. **S1 is committed (`5e549a4`), with the revised stages.** S1\* provides the store, events, fold, duplicate rules,
   frozen CV copies and backup merge, and also the parts of TRACKER_PLAN 1.6-1.9 that this point once listed as missing:
   - the stage registry and `settings.json`;
   - the `/move` route;
   - the competing-attempt rule;
   - the tracking switch.

   What is still open is the migration (S2) and every screen (S3-S5). Nothing in the browser reads the store yet.
5. **ApplyPack has no interviews, calendar, offers or salary calculator** (V-code at `5b1edfe9`).
   - **Interviews:** "interview" appears only in employer-mode screening (`src/web/routes/screen.tsx`).
   - **Offers:** `offer` is only a default board column.
   - **Calendar and pay types:** no calendar or `.ics` code, and no W-2 / 1099 / C2C calculation was found.
   - So module group (c) has no functional reference and is designed from scratch.

## 1. Module by module

### Group (a) Discovery & Evaluation

#### 1. Job Discovery

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| Search by role and country | EXISTS | `python/job_discovery/run_discovery.py`. Country from `--country` or intelligence, never a default (CLAUDE.md rule); search terms from target roles. Tests `searchCountry.test.js`, `searchStrategy.test.js` (JS, not run) | none | — | — |
| Sources | PARTIAL | `providers/`: greenhouse, lever, ashby, workable, infostud, jobspy (LinkedIn/Indeed), remoteok, wwr, wellfound, yc. `provider_registry.py` `PROVIDER_GROUPS`; `run_pipeline.py --providers` defaults to `serbia`. Company boards in `companies/*.json` (3 files). Test `test_provider_registry.py` (V-test). Sources are not user configuration yet | none | Principle 16 not yet met | PLANNED Phase 3b (M) |
| Scraping | EXISTS | Board APIs plus JobSpy; `playwright_provider_base.py`; tests `test_discovery_clients.py` (2 network tests skipped offline) | none | — | — |
| Dedupe | EXISTS | `dedupe_jobs.py`; tests `test_role_cross_posted_to_three_cities_collapses_to_one`, `test_same_url_collapses` (V-test) | none | — | — |
| Filtering | EXISTS | Pipeline: `test_discovery_filters.py` (location, relocation, V-test). UI: `JobFilters.jsx` (search, location, site, provider, status); salary filter `jobSalary.js` (`jobSalary.test.js`, not run) | none | — | — |
| Ranking (Layer 1) | EXISTS, degraded without AI | `scorer.py` (`test_score_job_returns_expected_fields`, `test_weighted_total_custom_weights`), weights UI `ScoringWeightsPanel.jsx`. Needs `llmFacts` from `enrich_jobs.py` (finding 2) | opt (enrichment is an AI call) | Rule respected: enrichment returns facts, `scorer.py` computes | — |
| Ledger: new and closed | EXISTS | `python/job_scoring/job_history.py`; tests `test_a_known_job_keeps_first`, `test_facts_are_dropped_when_the_ad_changed` (V-test); UI badges `jobHistory.js` `historyBadges()` | none | — | — |
| Import a job by URL | EXISTS | `POST /api/jobs/import-url` (`api-handler.js:409`), `JobUrlImport.jsx` | none (A: not read in depth) | — | — |
| Job details | see module 2 | | | | |

#### 2. Job Details (central page)

The screen is `src/components/jobs/JobDetailDrawer.jsx`, a drawer and not a page.

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| Description | EXISTS | `JobDescription.jsx`; `descriptionFormat.js` (`descriptionFormat.test.js`, not run) | none | — | — |
| Fit | PARTIAL | Old score and labels (`JobScoreBadge`, matched/missing skills from `matchScore.js`). `FitJudgementSection` shows `job.llmFit` (judge); `EngineShadowSection` shows the Phase 1 engine in shadow. The deterministic engine Fit is built (`test_fit.py`, `test_gates.py`, V-test) but in shadow only, acceptance pending | judge and matcher req; old score none | — | Phase 1 acceptance |
| Location | EXISTS | Drawer "Location" field; gates `work_authorization.py`, `geography.py` (`test_work_authorization.py`, `test_location_match.py`, V-test) | none | — | — |
| Salary | PARTIAL | `salary.py`: monthly EUR from free text, conservative (`test_unknown_currency_or_interval_is_unknown_never_a_guess`, V-test). Drawer shows `salaryMonthlyEur` with badges. Display only by design; no RSD, and no gross/net | none | — | ties to module 12 |
| `datePosted` | PARTIAL | Kept on the job (`data-shapes.md`; used in `jobExport.js`, `shadow.py` `_posted`). **Not shown** in `JobDetailDrawer` (V-code: no `datePosted` in the drawer) | none | — | S |
| `dateAdded` (first seen) | EXISTS | Ledger `firstSeen`; drawer "Seen first – last" (`JobDetailDrawer.jsx:104-108`) | none | — | — |
| Last-checked date | PARTIAL | `lastSeen` is "last listed in a discovery run", not a liveness check. It is shown as part of the "Seen" range, not under its own name | none | — | S |
| `jobEndDate` only when it exists | PARTIAL | Only Infostud returns it, as `expiresAt` (`infostud_client.py:186`, `infostud_provider.py:85`). Nothing downstream reads or shows it (V-code grep). Never invented today | none | — | S |
| Status open / closed / expired / unknown | PARTIAL | Only `isClosed` / `closedAt` = "no longer listed" (`historyBadges()`). There is no `expired` (past `expiresAt`) and no `unknown` | none | — | S |
| Legitimacy check | MISSING | No code. ApplyPack has a deterministic HTTP liveness ladder (ADR 0016) and an AI web-search verification (ADR 0009). Neither phase covers it | liveness none; web verification req | Web verification sends the ad only (no candidate data): no conflict if it stays so | liveness M, verification M |
| Apply (open the posting) | EXISTS | External link in the drawer header (`ExternalLink` import, A: not traced to the click handler) | none | — | — |
| Resume Match | PARTIAL | see module 6 | | | |
| Cover Letter | PARTIAL | see module 7 (`JobTailorActions.jsx`, the `JobAIToolsPanel` "Cover Letter" tab) | | | |
| Application Pack | PARTIAL | see module 8 | | | |
| Tracking and current stage | PARTIAL | `ApplicationTrackerPanel.jsx` on `job.applicationTracking` (fixed `INTERVIEW_STAGES`, no history). S1\* store underneath. Revised design: TRACKER_PLAN 3.2 (S3) | none | Principle 13 met only after S2-S4 | PLANNED Phase 3 |

#### 3. Companies

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| Company profile | MISSING (AI text only) | No Companies screen in the navigation (`appNavigation.js:112-123`). Only `/api/ai/company-intelligence` (AI text per job, `JobAIToolsPanel` "Company" tab). `companies/*.json` are board lists, not profiles | profile none; intelligence req | The AI route has the finding 3 gap | M |
| Its postings | MISSING | Possible through a filter on `company`, but there is no company view | none | — | S once the module exists |
| Application history | MISSING | S1\* holds `posting.company`, but no grouping. A company key needs the revised `norm()` (TRACKER_PLAN 4) | none | — | S |
| Contacts | PARTIAL | Outreach contacts (`src/modules/outreach/outreachStorage.js`, `localStorage` key `job-dashboard-outreach-index`); `RelatedContactsPanel` per job. They are browser-only, against principle 15 for a new store | none | Principle 15 (browser master) | M (move server-side) |
| Notes | MISSING | — | none | — | S |

No roadmap phase covers Companies. PHASE0_AUDIT does not list it as a module.

#### Scoring, Fit, posting verification

These are covered above and in Phase 1. The engine is built and in shadow
(`test_engine_shadow.py`, `test_engine_stability.py`, `test_engine_privacy.py`, V-test).

**Blocked at AI budget 0 (paid):**
- Phase 1 acceptance criterion 1 needs live calls (ROADMAP "Phase 1 acceptance criteria");
- every new requirement extraction;
- the matcher.

### Group (b) Application Preparation & Tracking

#### 4. Applications

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| Independent store, snapshot, frozen CV | S1\* | `application-store.js` `createApplication()`, `buildPosting()` (snapshot with sha256), `freezeFile()`; tests `creates an application with a frozen snapshot, attempt and first event`, `the frozen copy is unchanged after the library CV changes or is deleted`, `the application survives deleted job files, résumés and library CV` (not run) | none | Meets 13 and 15 | built, committed (S1) |
| Append-only history | S1\* | `assertAppendOnly()`, `appendEvent()`; tests `appends keep the old log as a prefix and seq runs 1..n`, `assertAppendOnly rejects any rewrite` (not run) | none | — | built |
| Duplicates, attempts, void and restore | S1\* | `findConflict()`, `requestId` replay; tests `a duplicate open attempt is refused`, `a voided application does not block a new one, and its restore cannot duplicate` (not run). Follows TRACKER_PLAN 1.9 (competing-attempt rule, `/move` reopen) | none | — | S |
| Backup merge | S1\* | `mergeFromBackup()`; `backup-handler.js` diff; tests `a restore adds history and never removes or rewrites it` (not run). The diff also carries the unrelated archiver import fix | none | — | built |
| Kanban, drag and drop | PLANNED | TRACKER_PLAN 3.2 / S4. Today `ApplicationHome.jsx` is a sortable table (`TRACKER_COLUMNS`) | none | — | M |
| Configurable columns, stable stage ids | S1\* | TRACKER_PLAN 1.6, 1.6.1, decision 13. `stageRegistry.js`, `settings.json`, `POST /api/applications/settings/stages`; the Settings UI is S5 | none | — | M (S5 UI) |
| Follow-up | PARTIAL | `src/modules/jobs/followUps.js` `isFollowUpDue()` on one `followUpDate`; `FollowUpPanel.jsx`. Nudges N0-N5: TRACKER_PLAN 5 / S5 | none | — | M |
| Migration and CSV import | PLANNED | TRACKER_PLAN 2, 4 (S2, S6) | none | — | M each |

#### 5. Resume Manager

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| Library | EXISTS | `src/utils/cvLibrary.js` `addCv()`, `setDefaultCv()`, `renameCv()`, `removeCv()`; files via `scripts/cv-store.js` `saveCvFile()`. Tests `cvLibrary.test.js`, `cvStore.test.js` (not run). The library list lives in the profile (`localStorage` master, mirrored on sync) | none | — | — |
| Versions v1, v2 ... | MISSING | Each library entry is an independent CV with its own id. There is no lineage and no version number. ApplyPack has versions per resume (`appliedResumeVersion`, 0a) | none | — | M |
| Original file and download | EXISTS | `GET /api/cvs/:id/file` (`api-handler.js`, `cvMatch` route) with `?name=` | none | — | — |
| Resume Strength with per-category explanation | PARTIAL | `python/quality_audit/ats_scorer.py` `score_ats()` gives a breakdown (contactInfo, structure, keywordMatch, ...). It scores **tailored** résumés per job (`data/resumes/<jobId>/tailored_resume.md`), not library CVs; UI `QualityDashboard` / `AtsScorePanel`. ApplyPack ADR 0030: the AI grades six dimensions with quotes, and code turns grades into 0-100 | deterministic part none; graded review req | ApplyPack's pattern fits the rule (the model grades, code scores) | M |
| ATS view (what a parser recognizes) | PARTIAL | `resume_parser.py` (`test_resume_parser.py`, V-test) parses sections deterministically. No "what a parser recognized" view per field | none | — | S-M |
| Prioritized recommendations with concrete rephrasings | PLANNED (part) | Phase 4 "CV and cover letter tailoring behind a fact gate". There is no recommendation list for a library CV. `/api/ai/resume-enhance` exists (AI, finding 3 gap) | req | Principle 8: a rephrasing must pass the fact gate; `provenance_checker` exists (`test_verified_metric_passes`, `test_unverified_metric_fails`, V-test) | M |
| Questions only the user can answer, stored for good | PARTIAL / PLANNED | The 17-question questionnaire (`QuestionnaireForm.jsx`, answers in the profile). Phase 2 "ask-user loop that stores confirmed facts"; principle 2 (UNKNOWN becomes a question) | prefill opt | Answers must never reach the matcher cache key (DECISIONS 2026-10-25) | M (Phase 2) |
| Compare two versions | MISSING | — | none (text diff) | — | S-M |
| Link a CV to applications and jobs | S1\* | `attempt.cv` `{kind, cvLibraryId, fileName, sha256}`; tailored CV from `data/resumes/<jobId>/` (`cvSource()`, `tailoredSource()`) | none | — | built |
| Keep the exact version sent | S1\* | Frozen copy in `data/applications/files/<appId>/` (decision 7) | none | — | built |

#### 6. Resume Match

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| A specific CV against a posting | PARTIAL | The engine matches the **profile and intelligence** evidence index (`match_engine/`, `evidence_index` tests), not a chosen library CV. `matchScore.js` compares profile skills | matcher req | — | M (choose the CV as the evidence source) |
| Requirements | EXISTS (shadow) | Requirement extraction with quotes, canonical ids (`test_requirements.py`, `test_requirement_frames.py`, V-test). Shown in `EngineShadowSection` | extraction req (cached) | — | — |
| Gaps | PARTIAL | Missing skills (old score); MISSING / UNKNOWN statuses in the engine (`test_fit.py`) | matcher req | — | — |
| Recommendations | MISSING | Gaps become questions (principle 2, Phase 2). There is no "how to close the gap" list | opt | Principle 8 | M |

#### 7. Cover Letter

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| Generation | EXISTS (deterministic) | `python/resume_generator/cover_letter_generator.py` `build_cover_letter_context()`, `lint_cover_letter()`; tests `test_every_sentence_is_the_candidates_own_or_a_fixed_connective`, `test_a_sentence_with_a_banned_phrase_is_skipped_not_edited` (V-test). `run_tailor.py --no-llm` writes `cover_letter.md` | none; LLM paragraphs opt | The LLM path is the CLAUDE.md known gap (no confirm, no redaction) | — |
| Tone | MISSING | — | opt | — | S |
| Tailoring to the posting | PARTIAL | `cl_ctx` takes the job; LLM paragraphs via `llm_tailor.py` (Claude Code CLI) | opt | Known gap | — |
| Versions | MISSING | `cover_letter.md` is overwritten per job (`run_tailor.py:199-205`) | none | — | S |
| Saving | PARTIAL | Saved per job under `data/resumes/<jobId>/`, plus a PDF; the frozen copy on apply is in S1\* (`attempt.coverLetter`) | none | — | — |

#### 8. Application Pack

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| Prepare the full package | PARTIAL | `run_tailor.py tailor_job()` writes the CV (md, html, PDF) and the cover letter (md, PDF) per job; `JobTailorActions.jsx`; `POST /api/tailor/run`. There is no pack record, state or checklist. ApplyPack ADR 0063: a pack row with status, step, files and `sentAt` | none with `--no-llm` | — | M |
| Store the documents used | S1\* | Frozen copy of the CV and cover letter at apply time | none | — | built |
| Preparing never marks applied | EXISTS (V-code) | `run_tailor.py` never writes job status or tracking (no `applied` in the file). Requirement stated in TRACKER_PLAN 8 | none | — | — |

### Group (c) Interview & Offer Management

#### 9. Interviews

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| Scheduling, type and stage | MISSING | No model, no route. TRACKER_PLAN O2: the interview stage mark creates nothing; scheduling belongs to this module | none | — | M |
| Prep questions | PARTIAL / PLANNED | `/api/ai/interview-prep` (AI, finding 3 gap), stored by `scripts/run-ai.js` in `data/interviews/<jobId>/interview_prep.json`, read by `GET /api/interviews/:id/interview_prep.json`. Phase 4 "interview prep from requirement statuses and the story bank" | req today; from requirements + story bank mostly none | Gap until redacted | M |
| Questions asked | MISSING | PHASE0_AUDIT G mentions "track which questions were asked" (idea, not a phase line) | none | — | S |
| STAR answers from history | PLANNED | Phase 2 story bank and Phase 4 | opt | Principle 8 | M |
| Notes and feedback, next steps | MISSING | — | none | — | S |
| Linked to an application | MISSING | Needs the S1 store (`appId`) | none | — | S |

#### 10. Calendar

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| Month and week view | MISSING | — | none | — | M |
| Interviews, follow-ups, deadlines on it | MISSING | Sources exist or are planned: follow-up dates, `assignment_due` and `offer_deadline` events (TRACKER_PLAN 1.4), `expiresAt` | none | — | S once both exist |
| Google Calendar integration | MISSING | — | none | Sends interview data to Google, an external service: principle 14 applies (D6) | M |
| Reminders | MISSING (in-app nudges planned) | TRACKER_PLAN 5 (in-app only); no notification channel exists | none | — | S-M |

#### 11. Job Offers

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| Offer record: company, position, amount, currency, period, gross/net, employment type, benefits, received date, deadline | MISSING | Only `stage offer`, the outcomes `offer_accepted` / `offer_declined` and the `offer_deadline` event (TRACKER_PLAN 1.4) | none | Code computes every number (D10) | M |
| Status received / negotiating / accepted / declined / withdrawn | MISSING | It overlaps the tracker outcomes (D10) | none | — | S |
| Comparison of offers | MISSING | Needs module 12 for net amounts | none | — | M |

#### 12. Salary Calculator (Serbia)

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| Serbian taxes and contributions | MISSING | `salary.py` reads ad figures only. ApplyPack has no calculator (finding 5) | none | Must be code with rule tables, never a model | M |
| Engagement forms | MISSING | Which forms is decision D5 | none | — | M |
| Rules versioned by year | MISSING | Proposal: one data file per year, with source and date | none | Rules must come from an owner-checked source (D5) | S per year |

### Group (d) Analytics & Administration

#### 13. Statistics

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| Applications, interviews, offers, rejections | PARTIAL | `src/modules/jobs/jobStats.js` `crmApplied`, `crmInterviewing`, `crmOffers`, `crmRejected`, `crmFollowUpsDue` from `applicationTracking.interviewStage`; `ApplicationDashboard.jsx` / `ApplicationHome.jsx` stat cards. Moves onto the fold in TRACKER_PLAN S4 | none | — | — |
| Conversion rates | PLANNED | Phase 5 "conversion by channel and Fit band" | none | Report only, never auto-tuning (Phase 5) | M |
| Response times | MISSING | Computable from events (`applied` → first `reply_received` / `stage_changed`) once S1 ships. No phase names it | none | — | S |
| Outreach metrics | EXISTS | `outreachMetrics.js` `computeOutreachMetrics()` (A: not read in depth) | none | — | — |

#### 14. AI Usage & Costs

| Capability | Status | Evidence | AI | Principle | Size |
|---|---|---|---|---|---|
| Calls, tokens, cost per model / module / job | PARTIAL | Browser only: `trackAiUsage()` (estimated tokens), `getUsageRollups()` day / week / month, `AIUsageDashboard.jsx`. Python calls are not recorded (finding 1). ApplyPack ADR 0055: every AI attempt is a server-side ledger row | none | — | M |
| History | PARTIAL | The last 400-500 browser entries (`aiUsageTracker.js`, trims at 500) | none | — | — |
| Daily and monthly budget | MISSING | — (ApplyPack: a monthly budget that **warns at 80% and 100% and never stops a call**, `prisma/schema.prisma` `aiBudgetCents`) | none | — | S |
| Hard limit on calls and spend | MISSING | No limit in `llm_client.py` or `run-ai.js`. The target is stricter than ApplyPack | none | Required by the target: "no automation may bypass the hard limit" | M (one server-side gate in front of `llm_client.complete`, `run-ai.js` and `llm_tailor.py`) |
| Cache overview | PARTIAL | Caches exist: browser `aiResponseCache.js` (`clearAiCache()`); `llmFacts` fingerprints (`enrich_jobs.py`); the fit cache (`FIT_CACHE_PATH`); the matcher cache (commit `287887b`). No overview screen | none | — | S |
| Free vs paid split | PARTIAL | `KEYLESS = {"ollama", "claude-code"}` (`llm_client.py:130`); `mock` provider in the browser. Not shown to the user | none | — | S |
| Control over auto-run AI tasks | PARTIAL | The judge and matcher are confirm-only (`judgeBoundary.test.js`, not run; `test_below_threshold_makes_no_call`, V-test). **Enrichment in the pipeline is not** (finding 1). Browser feature toggles: `aiFeatureRegistry.js` `settings.features[...] !== false` | none | Conflicts with the target rule | S |

#### 15. Settings

| Section | Status | Evidence | Size |
|---|---|---|---|
| Job Search | PARTIAL | Search preferences live in the Profile and Intelligence screens (target roles, locations, salary floor), not in Settings (A: not read field by field) | S |
| Sources | PLANNED | Phase 3b, SOURCES_SPEC.md (`data/config/sources.json`). Note: `data/config/` is not in `backup-handler.js` `DATA_DIRS` (V-code), so 3b must add it | M |
| Applications | PLANNED | TRACKER_PLAN 3.2 / S5 | M |
| Notifications | MISSING | No channel exists; the tracker plan keeps nudges in-app | S-M |
| Calendar | MISSING | — | S |
| AI | PARTIAL | `AISettingsPanel.jsx`: provider, provider health, feature toggles, usage and cost (browser) | — |
| Budgets and limits | MISSING | see module 14 | S |
| Other existing | EXISTS | `SettingsHome.jsx`: data paths, demo data, pipeline API status, backup / restore (`/api/backup/export`, `/api/backup/import`), clear local data | — |

## 2. Overlaps and dependencies

- **The S1 store underlies modules 4, 5, 8, 9, 10, 11 and 13:**
  - frozen CV and cover letter copies;
  - an `appId` for interviews and offers;
  - events for the calendar and statistics.

  Committing and revising S1 (TRACKER_PLAN 1.8) unblocks the most.
- **One company key** (the revised `norm()`, TRACKER_PLAN 4) is shared by Companies (3), the tracker's soft warning
  and CSV import (4), and outreach contacts.
- **Offers (11) depend on the Salary Calculator (12)** for gross / net and comparison. Both are pure code.
- **The Calendar (10) only displays** what Interviews (9), the tracker (4) and Offers (11) record. Build it after
  them.
- **Interview prep (9) and Resume Match recommendations (6)** both need requirement statuses (Phase 1) and the story
  bank (Phase 2).
- **The fact gate** (`provenance_checker`, principle 8) gates modules 5 (rephrasings), 7 (LLM paragraphs) and 9
  (STAR answers).
- **The AI hard limit (14)** must sit in front of every model call before any module that uses AI is expanded:
  enrichment, judge, matcher, CV analysis, tailoring and the browser features.
- **Overlap with existing screens:** the Quality Audit (`QualityDashboard`, ATS score of tailored résumés) overlaps
  Resume Strength (5). AI Copilot and Career Strategy overlap nothing in the target list (D4).
- **Statistics (13) "interviews"** needs the interview `interview` stage flag (TRACKER_PLAN O2) or interview records
  (9). Pick one definition (D9).
- **Job status (2) and liveness** feed Discovery's "closed" badge, the Calendar's deadlines (`expiresAt`), and Phase
  5 reporting.

## 3. Results

### 3.1 MISSING items that no roadmap phase covers

ROADMAP phases checked: 0, 1, 2, 3, 3b, 4, 5. Items covered by TRACKER_PLAN count as Phase 3.

1. **Job Details:**
   - posting legitimacy: a deterministic liveness check, and web verification;
   - a separate last-checked date;
   - `jobEndDate` carried through and shown (Infostud `expiresAt` is captured and then dropped);
   - an `expired` / `unknown` job status;
   - `datePosted` shown in the drawer.
2. **Companies:** the whole module (profile, postings, application history, notes), and contacts moved server-side.
3. **Resume Manager:**
   - versions with lineage;
   - comparing two versions;
   - Resume Strength for library CVs (today only tailored résumés);
   - an ATS "what the parser recognized" view.
4. **Resume Match:** choosing a specific CV as the match input; gap-closing recommendations.
5. **Cover Letter:** tone, and versions.
6. **Application Pack:** a pack record (state, files, "sent" marker).
7. **Interviews:** scheduling, type, questions asked, notes and feedback, next steps, the link to an application.
   (Phase 4 covers only prep.)
8. **Calendar:** month and week views, Google Calendar, reminders.
9. **Job Offers:** the whole module.
10. **Salary Calculator (Serbia):** the whole module.
11. **Statistics:** response times. (Conversion is Phase 5.)
12. **AI Usage & Costs:**
    - a server-side ledger of all calls;
    - daily and monthly budget;
    - a hard limit;
    - a cache overview;
    - the free / paid split shown to the user;
    - confirm or limit control for pipeline enrichment.
13. **Settings:** Notifications, Calendar, Budgets and limits, and Job Search gathered in Settings.
14. **Privacy:** redaction and confirm for the browser AI features (finding 3). CLAUDE.md does not list this gap.

### 3.2 Proposed phase order (AI budget 0, not topped up)

Each step uses free or offline work only. A step marked **blocked** waits for AI to be allowed (D1).

| Order | Group | Step | AI | Why here |
|---|---|---|---|---|
| 1 | (d) | **AI guardrail:** server-side ledger of every call (Python and Node); one gate with a hard limit (default 0 = every paid call refused); a pipeline that runs with enrichment skipped or keyless; enrichment under the same confirm and limit as the judge; the free / paid split shown | none | Finding 1. With budget 0, nothing paid may run by accident. Everything after this is safe |
| 2 | (d) | **Privacy fix for the browser AI features:** turn them off or redact (D3) | none | Finding 3; cheap |
| 3 | (b) | **Tracker S1-S2:** S1\* is committed (TRACKER_PLAN 1.8 was the revision list); the S2 migration core is committed, the panel rewiring is open (TRACKER_PLAN 2.4) | none | Already designed and mostly built; unblocks 4, 5, 8, 9, 10, 11, 13 |
| 4 | (a) | **Job Details facts:** show `datePosted`; carry `expiresAt` → `jobEndDate`; status open / closed / expired / unknown; last-checked; deterministic liveness check (HTTP status, board API presence) | none (liveness makes network requests to job boards, no AI) | Small, free, improves every list |
| 5 | (b) | **Tracker S3-S6:** Job Details section, Kanban, Settings → Applications with nudges, CSV import | none | Planned in TRACKER_PLAN |
| 6 | (b) | **Resume Manager, free part:** versions with lineage, compare versions, ATS parser view, deterministic strength checks on library CVs (`ats_scorer` categories that need no job), the pack record over `run_tailor --no-llm`, cover letter versions | none | Free; builds on the S1 frozen copies |
| 7 | (a) | **Sources (Phase 3b)** and **Companies** (profile, postings, history, notes, contacts server-side) | none | Free; uses the shared `norm()` |
| 8 | (c) | **Salary Calculator (Serbia)**, then **Job Offers** with comparison | none | Pure code; needs D5 |
| 9 | (c) | **Interviews (records)** linked to `appId` (schedule, type, questions asked, notes, feedback, next steps), then the **Calendar** (in-app month / week, ICS export), then **Google Calendar** if D6 allows | none (Google is an external call, not AI) | Free; Google behind its own decision |
| 10 | (d) | **Statistics:** counts from the fold, response times, then Phase 5 conversion (report only) | none | Needs real events, so it comes later |
| 11 | (d) | **Settings consolidation:** Job Search, Notifications (in-app), Calendar, Budgets | none | Gathers the earlier steps |
| — | (a) | **Blocked until AI is allowed:** Phase 1 acceptance (live calls); new requirement extraction and the matcher; the Fit judge; AI web verification of postings; company intelligence | req | |
| — | (b) | **Blocked until AI is allowed:** CV analysis; Resume Strength graded review (ApplyPack ADR 0030 pattern); rephrasing recommendations (Phase 4, behind the fact gate); LLM cover-letter paragraphs (and their known privacy gap) | req | |
| — | (c) | **Blocked until AI is allowed:** AI interview-prep questions; STAR drafting from the story bank (the Phase 2 story bank itself can be filled by hand, free) | req | |
| — | (a) | **Partly blocked:** Layer 1 enrichment quality (finding 2), unless D1 allows local `ollama` | req, or keyless | |

### 3.3 Decisions for the owner

| # | Decision | Why it matters |
|---|---|---|
| D1 | **What "AI budget 0" covers.** Paid API only, or also the `claude-code` CLI (subscription) and local `ollama`? | Decides whether enrichment, tailoring paragraphs and CV analysis are blocked or free. `active_provider()` falls back to `claude-code` today |
| D2 | **Hard-limit semantics.** A server-side ledger plus a gate that *refuses* (stricter than ApplyPack, which only warns). Scope: calls, money or both; per day and month; what a refused pipeline step does (skip enrichment, or stop) | Step 1 cannot be built without it |
| D3 | **Browser AI features (finding 3).** Disable them until they are redacted and confirmed, or redact now. Add the gap to the CLAUDE.md privacy list either way? | Principle 14 |
| D4 | **Existing screens outside the 15 modules.** AI Copilot, Career Strategy, Intelligence, Quality Audit, Outreach: keep, fold into modules (Quality → Resume Strength, Outreach → Companies contacts), or retire | Avoids two versions of one feature |
| D5 | **Salary calculator scope and rule source.** Which engagement forms: employment contract, entrepreneur flat-rate (paušal), entrepreneur bookkeeping, service contract (ugovor o delu), copyright contract, foreign-employer payment. Who supplies and checks each year's rates | Rules must be correct; code computes, the owner verifies |
| D6 | **Google Calendar.** Two-way sync, one-way push, or ICS export only. Pushing sends interview data (company, time, notes?) to Google | External service; principle 14 |
| D7 | **Notifications.** In-app only, or a channel (e-mail, Telegram)? None exists today | Settings → Notifications scope |
| D8 | **Companies identity and contacts.** The company key from `norm()` (exact, never fuzzy). Move outreach contacts from `localStorage` to a server store under principle 15 | Data model |
| D9 | **Interviews: own store or application events.** Recommended: own records keyed by `appId`, consistent with TRACKER_PLAN O2. And the definition of "interviews" in Statistics: stage flag or interview records | Data model, Statistics |
| D10 | **Offers vs tracker outcomes.** One offer record per application, with its own status, which drives `outcome_set offer_accepted` / `offer_declined` when decided; or a status only in the offer | Avoids two sources of truth |
| D11 | **Job status vocabulary and liveness frequency.** `expired` = past `jobEndDate`; `closed` = not listed / liveness failed; `unknown` = never checked. How often liveness requests may hit boards | Network load, honesty of dates |
| D12 | **Resume versions.** A new upload "as a new version of CV X" (lineage) vs a new CV. Does the frozen copy record the version number | Data model for module 5 |
| D13 | **The S1 work.** Done: committed as `5e549a4`, revised per TRACKER_PLAN 1.8; the archiver fix is its own commit `549d42f` | Unblocked step 3 |
