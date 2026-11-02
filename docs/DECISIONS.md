# Holojob - Decisions

Short entries for decisions that were not yet written down. Planned work is in [ROADMAP.md](ROADMAP.md). The product
principles and the older owner decisions stay in [redesign/DECISIONS.md](redesign/DECISIONS.md) and are not repeated here.

The date is the day the entry was recorded (2026-11-02), unless the entry names the day of the decision. "Code check" says
what the code did on 2026-11-02. Where it differs from the decision, the entry says so and nothing has been changed yet.

## Activity screen (approved 2026-11-02)

- **New screen:** named Activity, in the nav group System, built in career-os. No Runs screen exists here.
- **Design reference only:** "Runs", "Search funnel", "By source", "Run history" and "Fetching is paused" come from ApplyPack, a
  separate third-party app on the same server. No code is copied. "Fetching is paused" is ApplyPack's text, not career-os's, so
  it is not a career-os task.
- **Not ours:** the legacy "Search history" screen (openai gpt-4o-mini) belongs to the separate jobapply app.
- **Slices, in order:** (1) per-source outcome and run log, including a fix so a failed board cannot close its existing ads;
  (2) `GET /api/runs` read API with 90-day pruning at write time; (3) the Activity screen, one row per run, Details with per-site
  stats plus errors and warnings with their level; (4) ad lifecycle changes, last.
- **Run log:** one record per run, written by `python/job_discovery/run_discovery.py`, so a manual Re-scrape and a pipeline run
  each log once.
- **Storage:** `data/analytics/`, private (0600 files, 0700 folders), atomic through `write_text_atomic`.
- **Trigger field:** allows `manual` and `scheduled`. No scheduler exists yet, so there are no paused rows.
- **No AI.**

**Known gaps, none of this exists yet:**

- A miss counter, a last successful fetch per source, and per-source id snapshots.
- The "read" count: it is lost today, because providers return only the jobs they keep.

**Code check, the bug slice 1 fixes:** the Greenhouse, Lever and Ashby providers catch each board's exception, log it and go on.
`run_discovery.py` counts jobs per provider, not per board, so one failed board among working ones can close that board's ads.

## Ad lifecycle rules (narrowed 2026-11-02)

- **Closed:** the source explicitly says the ad is closed.
- **Missing:** absent in a successful fetch of the same source.
- **Expired:** only Greenhouse, Lever and Ashby can reach it, after two consecutive successful and complete fetches of the same
  board.
- **Search-based sources** (LinkedIn / JobSpy, Infostud, Workable, Joberty) show Missing and never become Expired automatically.
- **What is not a miss:** a failed or partial fetch, and a changed search.
- **0 ads** is a warning and never closes everything.
- **`expiresAt`** (Infostud, Joberty) is a deadline: displayed only, never used as Closed or Expired.

**Code check, differs, built last (slice 4):** `python/job_scoring/job_history.py` has one state, `closedAt` / `isClosed`, and no
Missing or Expired.

- One absence closes a job, not two.
- No provider reads an explicit "closed" from the source.
- A provider that returned 0 jobs closes nothing, which matches the rule, but `run_discovery.py` logs no warning for it.
- The UI's "Closed" badge means "No longer listed since ...", which under these rules would be Missing or Expired.

## AI in scraping - pending, needs separate approval with cost

- AI only as a second stage after the deterministic parser and filter, only on ads that passed the filter, and only for
  missing or uncertain fields and translation.
- First measure how many ads have empty or uncertain fields.
- The Activity screen itself has no AI.

**Code check:** enrichment (`enrich_jobs.py`, `llmFacts`) already sends ads to a model after discovery, and skips ads the board
already places outside `allowedLocations`. This decision does not say how it relates to that step.

## Location cap rule - approved

| Case | Result |
|---|---|
| Outside allowed, no remote signal | Cap 40 |
| Remote with an explicit disallowed geography | Cap 40 |
| Remote, Worldwide or EU with no confirmed restriction | UNKNOWN, no cap, flag "Verify location" |
| Confirmed from Serbia | PASS |

UNKNOWN gets no matching priority. Richer location extraction is later and needs AI cost plus explicit approval. The geo
audit is parked.

**Code check, matches:** `scorer.py` (`OUTSIDE_ALLOWED: 40`), `location_text.py`, and `match_engine/shadow.py` (a passed
location goes before an unknown one). One addition in the code: an ad stating the Balkans, or stating worldwide availability, is also
`pass`. The fix-scoring task in [ROADMAP.md](ROADMAP.md) must not change this rule.

## Matcher (decided 2026-10-28)

- **Cache key:** a hash of the requirement ids and texts.
- **`requirement-remap`:** applied on read.
- **Top 50 tie-break, deterministic:** score, location passed, provisional ratio ascending, newer, fingerprint.
- **Plan:** the matcher plans on the local Layer 1 score, without the judge.
- **Duplicate canonical ids:** not merged.
- **Relocation:** `abroad` stays.

**Code check:**

- Tie-break, plan and remap match (`match_engine/shadow.py` `plan`, `matcher.py` `posting_from_job`).
- `requirements_hash` also covers each requirement's kind, importance and quote, and it is one part of a key with the ad
  fingerprint, profile version and prompt version. That is wider than this entry.
- `abroad` is still a relocation option (`dimensions/location_match.py`).
- Not verified: "duplicate canonical ids". `competencies.py` refuses a repeated id within a list, but nothing states this
  decision in the code.

Earlier related decision: top 50 per run ([redesign/DECISIONS.md](redesign/DECISIONS.md), 2026-10-25).

## AI budget and the subscription exception

- Paid steps need separate approval.
- The owner set `dailyLimit` 10 and `monthlyLimit` 25.
- `claude-code` under the owner's flat subscription is class `subscription`: cost 0, default off, allowlist `jobAnalysis`
  only, daily cap 5, with ledger rows. Rules: AI budget gate in [../CLAUDE.md](../CLAUDE.md).
- Ollama is not installed.

**Code check:**

- `data/ai/settings.json` holds those limits, and the subscription switch is on there with `jobAnalysis` only. Off is the
  code's default, not the current state. The same file also caps calls at `maxCallsDaily` 5 and `maxCallsMonthly` 25.
- Ollama: no binary on the host or in the container, and no running service. It remains a provider in the code and the price table.

## Import redesign

**Approved sources:** PDF, DOCX, TXT / MD, pasted text, LinkedIn data ZIP, JSON Resume, LinkedIn PDF, manual form.
**Rejected:** PDF URL, LinkedIn profile URL.

**Design:**

- A transient `ImportDraft`, from a stateless `POST /api/profile/import/parse`, in `python/profile_import`.
- No new dependencies and no new AI call.
- A review-and-correct screen before saving.
- Import creates a new "My CVs" entry that is not automatically active.
- Unplaced text goes only into `rawText`.
- A DOCX original is not stored.

Slice order and status: [ROADMAP.md](ROADMAP.md). Draft shape: [redesign/data-shapes.md](redesign/data-shapes.md).

**Code check, differs in one place:** the first CV imported becomes the active one (`willBeActive` in `importDraft.js`); any
later import does not. The rest of what is built matches.

## Product principles

- **Other users:** Holojob will be used by other users, so no personal data is hard-coded.
- **English only:** no Serbian, Cyrillic or multilingual parsing. AI translates non-English ads and CVs. English
  section-header synonyms live in one data file.
- **Access:** no login and no basic auth; home LAN plus Tailscale. Already recorded:
  [redesign/DECISIONS.md](redesign/DECISIONS.md), 2026-10-29.

**Code check, differs:**

- **Single user:** principle 15 in [redesign/DECISIONS.md](redesign/DECISIONS.md) and [../CLAUDE.md](../CLAUDE.md) still say
  "single user for now".
- **Hard-coded market:** the `serbia` provider group ([ROADMAP.md](ROADMAP.md), Tech debt leftovers) and Serbian place names in
  `location_text.py`, which is also how "Confirmed from Serbia" above is read.
- **Serbian parsing exists:** `src/data/sectionHeadings.json` has `en` and `sr` blocks and a Cyrillic transliteration, used by
  `python/profile_import/vocabulary.py` and `src/utils/headingVocabulary.js` (commit `10bf5d3`, 2026-11-01). Its removal is
  not scheduled.
- **Serbian sites:** [redesign/DECISIONS.md](redesign/DECISIONS.md) keeps "job sources incl. Serbian sites" in scope. This
  entry is about parsing, and does not say whether those sources change.
- **No AI translation exists:** the prompts in `job_import/ad_ai.py` and `cv_analysis/analysis.py` tell the model not to translate.
- **One data file:** `sectionHeadings.json` is that file for the import parser and the PDF extractor, but
  `resume_generator/resume_parser.py` has its own English list (`SECTION_STEMS`).

## Jobs table - open discussion, not final

Meaning today, confirmed in the code: the New badge is `job.isNew` (3 days or less, `NEW_WINDOW_DAYS`), and Status is
`job.status`.

| Agreed direction | Status on 2026-11-02 |
|---|---|
| Display names "Just found" and "Unreviewed", data unchanged | Done (`jobHistory.js`, `jobStatusLabel`) |
| Warnings in the Location cell | Done (`AuthorizationBadge`, `33e5a18`) |
| Icon actions with tooltips | Done (`JobActions`, `63f216c`) |
| Compact rows | Done (`63f216c`) |
| Remove the shadow badge from the table, keep it on Details | Not done: `EngineShadowBadge` is still in `JobTable.jsx` (table and cards), and is on Details |
| Applied button goes to the tracker (a separate task) | Not done: the table button only sets `job.status` to `applied_manually` through `updateJobStatus` and writes no application |
