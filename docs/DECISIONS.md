# Holojob - Decisions

Short entries for decisions that were not yet written down. Planned work is in [ROADMAP.md](ROADMAP.md). The product
principles and the older owner decisions stay in [redesign/DECISIONS.md](redesign/DECISIONS.md) and are not repeated here.

The date is the day the entry was recorded (2026-11-02), unless the entry names the day of the decision. "Code check" says
what the code did on 2026-11-02. Where it differs from the decision, the entry says so and nothing has been changed yet.

## Activity screen (approved 2026-11-02)

- **New screen:** named Activity, in the nav group System, built in holojob. No Runs screen exists here.
- **Design reference only:** "Runs", "Search funnel", "By source", "Run history" and "Fetching is paused" come from ApplyPack, a
  separate third-party app on the same server. No code is copied. "Fetching is paused" is ApplyPack's text, not holojob's, so
  it is not a holojob task.
- **Not ours:** the legacy "Search history" screen (openai gpt-4o-mini) belongs to the separate jobapply app.
- **Slices, in order:** (1) per-source outcome and run log, including a fix so a failed board cannot close its existing ads;
  (2) `GET /api/runs` read API (the 90-day pruning at write time was built in slice 1); (3) the Activity screen, one row per run, Details with per-site
  stats plus errors and warnings with their level; (4) ad lifecycle changes, last.
- **Run log:** one record per run, written by `python/job_discovery/run_discovery.py`, so a manual Re-scrape and a pipeline run
  each log once.
- **Storage:** `data/analytics/`, private (0600 files, 0700 folders), atomic through `write_text_atomic`.
- **Trigger field:** allows `manual`, `pipeline` and `scheduled` (`pipeline` added in slice 1). No scheduler exists yet, so there are
  no paused rows, and nothing writes `scheduled`.
- **No AI.**

**Known gaps, none of this exists yet:**

- A miss counter, a last successful fetch per source, and per-source id snapshots.

**The bug slice 1 fixed:** the Greenhouse, Lever and Ashby providers caught each board's exception, logged it and went on, and
`run_discovery.py` counted jobs per provider, not per board, so one failed board among working ones could close that board's ads.

## Activity slice 1, as built (2026-11-02)

**Where:** `python/job_discovery/run_log.py`, called once from `run_discovery.py` `main()`. One file per run:
`data/analytics/runs/<startedAt, UTC, YYYYMMDDTHHMMSSZ>-<runId>.json`, 0600 in 0700 folders, atomic through `write_text_atomic`.
`HOLOJOB_ANALYTICS_DIR` moves the folder (tests set it). Records that started more than 90 days ago are removed when a record is
written. One file per run, not one shared file, because a Re-scrape takes no pipeline lock, so two runs can overlap and a rewrite
of a shared file could lose a record.

**Record, version 1:**

```json
{
  "version": 1,
  "runId": "<discovered_jobs.json meta.sourceRunId>",
  "trigger": "manual | pipeline | scheduled",
  "startedAt": "<ISO>",
  "finishedAt": "<ISO>",
  "status": "ok | partial | failed | skipped",
  "sources": [
    {
      "name": "greenhouse",
      "status": "ok | partial | failed | skipped",
      "read": 120,
      "kept": 8,
      "new": 1,
      "error": "<string or null>",
      "boardsFailed": ["<board or feed>"],
      "skipReason": "<string or null>"
    }
  ],
  "issues": [
    { "level": "error | warning", "source": "<name or null>", "message": "<string>" }
  ]
}
```

- **read:** ads parsed before the search, role and location filters. **kept:** past them, before dedupe. **new:** ads no earlier run
  recorded, counted after dedupe under the provider of the copy that won, so `new` is not a share of `kept`. Summed, it equals
  `meta.history.new`.
- **Extensible:** scored, closed, missing and expired are left out, because discovery does not know them yet. A later slice adds
  fields; a reader ignores what it does not know and treats a missing field as unknown. A breaking change raises `version`.
- **Run status:** `failed` when the exit code is not 0, no source ran, or every source that searched failed. `partial` when some
  searching source is not `ok`. A `skipped` source does not count, and warnings alone leave it `ok`. **`skipped` (owner correction,
  done):** every source was skipped, so nothing was searched; the record carries one run-level issue saying so. A non-zero exit
  still makes it `failed`.
- **Providers:** `fetch_jobs` still returns a list. The outcome is `provider.last_outcome` (`ProviderOutcome`, `base_provider.py`).

**Decisions made while building, beyond the brief:**

- **A failed board's open ads stay in `discovered_jobs.json`,** unchanged and open (`meta.history.keptFailedBoard` counts them), under
  the same conditions closing has: same search, role not listed under another copy. Not closing them alone would have dropped them
  out of the scored list. A board that fails every run therefore keeps its ads open until it is fixed or removed from
  `companies/*.json`; its error shows on every record.
- **What counts as a failed board:** an exception, an error status, an answer with no jobs list, and Lever's 404 on both hosts (that
  last one used to count as empty).
- **A provider that raises** is one failed source; the others still run and its board ads are held. Before, it stopped the whole run
  with nothing written.
- **A run that cannot start or that crashes** also writes a record, `failed`, with the reason as an error issue. `run_pipeline.py
  --skip-discovery` and a pipeline refused by its lock or setup write none: discovery did not run.
- **`--trigger` is passed by the caller:** `run_pipeline.py` passes `pipeline`, everything else defaults to `manual`. Cron goes through
  `run_pipeline.py`, so cron runs log as `pipeline` until a scheduler passes `scheduled`.
- **Status `skipped` (owner correction, done):** a source that did not search because it does not apply (Infostud or Joberty on an
  unsupported country, Wellfound not built) is `skipped`, not `ok`, with `skipReason` saying why and no warning. `skipReason` is an
  addition to the requested shape, so the reason is not lost. A failed Joberty `fetch_cities` can be told apart, because the board
  always lists places: an empty list is `failed`, not `skipped`.
- **An empty board holds (owner correction, done):** a Greenhouse, Lever or Ashby board that answers 200 with no jobs does not close
  its ads, even when other boards return jobs. They stay open in `discovered_jobs.json`, counted in `meta.history.keptEmptyBoard`, and
  the record gets a warning naming the board. A board that lists at least one posting closes its absent ads as before, even if the
  filters kept none of them. A board that really has emptied therefore keeps its ads open, with the warning, on every run.
- **A source that did not run keeps its ads (owner correction, done):** the open ads of a source with status `skipped` or `failed`
  stay in `discovered_jobs.json`, with no change to the ledger entry: no `closedAt`, no new `lastSeen`. `meta.history.keptSourceNotRun`
  counts them. This covers search-based sources too, and it ignores the "same search" condition: a source skipped for an unsupported
  country is by definition on a different search from the one that found its ads. A role now listed under another copy is still not
  carried. So after a permanent country change, Infostud's Serbian ads stay active until slice 4 decides otherwise.
- **Unchanged on purpose:** a source that ran successfully and did not return an ad. A search-based ad then leaves
  `discovered_jobs.json`, `scored_jobs.json` and the browser list with no badge, while the ledger keeps it open; a Greenhouse, Lever or
  Ashby ad closes and shows the badge for 14 days. A source that was not asked to run at all (not in `--providers`, or an opt-in source
  switched off) has no status, so its ads leave the file too. **For slice 4.** A row that left no longer loses the owner's data in
  the browser: see [offList](#offlist-rows-keep-the-owners-data-2026-11-03).
- **Scoring:** `scored_jobs.json` meta gains `discoveryRunId`; `sourceRunId` stays scoring's own. No scored counts are attached: a
  Re-score runs on its own, several times per discovery run, so it would overwrite an older record's counts.
- **Backups:** `data/analytics/` is not in `DATA_DIRS` in `scripts/backup-handler.js`, so run history is not backed up (nor is
  `skill_gap.json`, already there), though `PRIVATE_RESTORE` accepts the folder. Left as it is: a 90-day report is not clearly worth
  backing up.

**Known limitations (none of these closes an ad):**

- **`jobspy_adapter` can report a blocked LinkedIn search as a successful fetch with 0 ads,** because `jobspy_adapter.fetch_jobs` never
  raises. The source then shows `ok` with the 0-ads warning, so run statistics for `jobspy` are unreliable. It never closes ads
  automatically.
- `joberty_client.fetch_listing` keeps the pages it read and drops the rest, so a listing cut short still shows `ok`.

## offList rows keep the owner's data (2026-11-03)

**Rule:** discovery finds ads and never deletes what the owner did. Re-running discovery must not remove a status, AI insights,
tailored assets, outreach or legacy `applicationTracking`.

- **What is kept:** `importJobsFromFile` keeps a stored row the imported file lacks if it holds any of those: a status other than
  `new` (`rejected` included, so a rediscovered ad does not come back as new), or a non-empty `aiInsights`, `tailoredAssets`, `outreach`
  or `applicationTracking`. It is marked `offList: true`. A row with none of them is dropped as before, so old ads do not pile up.
  Timestamps alone, `applied: false` and an outreach with status `none` and empty lists do not count as data.
- **When it returns:** matched on `jobId`, then lowercased URL, as before. It loses the mark and keeps all its data.
- **Where it is hidden:** the Jobs list (`filterJobs`), its totals, filter options and exports, `computeJobStats`, `computeOutreachMetrics`,
  the Dashboard's tailored count, the pipeline counts, and the AI features that read the whole list (`topJobs`, skill gap). The "Show
  jobs absent from current results" filter lists them.
- **Where it stays visible, on purpose:** Job Details and the drawer by id, Resume Library, the tracker table, and the Outreach contact
  list and exports, because each of those is the owner's own record. The backup, the tracker migration and the AI redaction hints still read
  these rows.
- **Scoring and discovery never see it:** the browser sends only hand-entered jobs to the server, and `run_scoring.py` reads only the
  discovered and manual files (`tests/python/test_scoring_input.py`). The file contents did not change.

**Terms, two different states:**

- **offList** = absent from current results. A browser mark on a row. It says nothing about whether the ad closed.
- **orphan** (Step 5) = a user record with no matching active discovery record.

**Temporary:** `offList` is a protection until the Step 5 job-state overlay (`data/jobs/job-state.json`). The Step 5 migration must treat
`offList` rows as orphans, not as active records. Its plan turns a browser-only job into a `record` entry, which is an active job, so this
is an exception to that rule ([plan, section 2.3](redesign/STEP5_SERVER_MASTER_PLAN.md)).

**Limits of this step:**

- Data lost before this change is not restored; only rows still in the browser are protected.
- A row kept under another browser or profile is not shared: the data still lives in one browser's `localStorage`.
- When the list does not fit `localStorage`, `saveJobs` stores it without `description`, `llmFacts` and `engineShadow` (`slimJob`). A
  scored row gets them back from the file; an `offList` row does not, so its Job Details can show no ad text. The ledger still has it.
- Carry-over still matches on `jobId` or URL only. A status on one copy of a role is not moved to another copy with a different URL; the
  old copy is kept `offList` instead.
- Job Details does not yet say a job is absent from current results, and an ad whose row was dropped still cannot be opened.
- Stat cards count only rows in current results, so an application whose ad is `offList` is not in the "Applied" card; Application
  Statistics reads the application store and still counts it.

## Ad lifecycle rules (narrowed 2026-11-02)

- **Closed:** the source explicitly says the ad is closed.
- **Missing:** absent in a successful fetch of the same source.
- **Expired:** only Greenhouse, Lever and Ashby can reach it, after two consecutive successful and complete fetches of the same
  board.
- **Search-based sources** (LinkedIn / JobSpy, Infostud, Workable, Joberty) show Missing and never become Expired automatically.
- **What is not a miss:** a failed or partial fetch, and a changed search.
- **0 ads** is a warning and never closes everything.
- **A source that did not run** (`skipped` or `failed`) keeps its ads as they were (slice 1 correction).
- **`expiresAt`** (Infostud, Joberty) is a deadline: displayed only, never used as Closed or Expired.

**Code check, differs, built last (slice 4):** `python/job_scoring/job_history.py` has one state, `closedAt` / `isClosed`, and no
Missing or Expired.

- One absence closes a job, not two.
- No provider reads an explicit "closed" from the source.
- A provider that returned 0 jobs closes nothing, and neither does a Greenhouse, Lever or Ashby board that answered with no jobs,
  which matches the rule. The run log gives each a warning (slice 1).
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
