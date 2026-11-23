# Holojob — Architecture

How the system works today, and why it is built that way. Moved out of `CLAUDE.md`
(which now holds only rules and conventions) without dropping anything. For where it
is going see [ROADMAP.md](ROADMAP.md) and [redesign/DECISIONS.md](redesign/DECISIONS.md);
for terms see [GLOSSARY.md](GLOSSARY.md); for the data files see
[redesign/data-shapes.md](redesign/data-shapes.md).


## Pipeline

    run_discovery.py  ->  enrich_jobs.py  ->  run_scoring.py
    data/jobs/discovered_jobs.json  ->  data/jobs/scored_jobs.json

**Discovery** (`python/job_discovery/`). Six providers in the `serbia`
group: `greenhouse`, `lever` and `ashby` (company boards read from `companies/*.json`) and three
search or board sources: `jobspy` (LinkedIn only — Serbia is unsupported by Indeed and
Glassdoor, and falling back to the USA silently was a real bug), `infostud`
(the domestic board; its free-text search is useless, so whole categories
are pulled and filtered locally), `workable` (remote roles open to Serbia;
its public JSON carries the full description). The other groups (`all`, `ats`, `remote`, `startup`) are in
`source_definitions.py` (`PROVIDER_GROUPS`). HelloWorld and Startuj were
evaluated and rejected: HelloWorld shares Infostud's inventory and ID space,
Startuj is entry-level only.

`joberty` (Serbian and regional IT board, `python/job_discovery/providers/joberty_*.py`) is an **opt-in** source
(`source_definitions.py`, `opt_in=True`): in no group, off by default, and run only while the owner has switched it on
with consent in Settings > Sources > Job boards. The switch, `consentAcceptedAt` (server time) and a history live in
`data/config/sources.json` (`source_settings.py`, the first slice of SOURCES_SPEC.md; the other boards still follow
the groups), and `run_discovery.py` applies them whatever the request names. It reads Joberty's undocumented public
JSON API (product-management domain) with capped, spaced anonymous GETs (3 listing pages, 25 details, 1.5 to 2 s
apart), skips ads the job-history ledger already holds, fails soft, and checks the requested country against the
board's own place facet. Joberty's terms (sections 7 and 8) restrict commercial and unauthorized use; see `python/job_discovery/README.md`.

The standard run is `--providers serbia` (all six providers); it is the
default everywhere: the CLI, `npm run discover:jobs`, the API and every UI
screen. `ats` and the other groups stay available by name.

Dedup is two-pass (`dedupe_jobs.py`): by URL, then by title+company across
every source, keeping the fuller description. The company in that key drops a trailing
country ("Fivetran Serbia" is "Fivetran"), except in "... of <country>". LinkedIn publishes one role as
several ads, one per city, and the same role reaches us from LinkedIn and from
the company's own board.

**Enrichment** (`python/job_scoring/enrich_jobs.py`). An LLM reads each ad
and reports facts: work mode, role track, seniority, years required,
must-haves, listing-quality flags, and the job's country, where a remote hire
may live, and what the ad says about visa sponsorship. It never scores and
never sees the
candidate. It does not read an ad the board already places outside the candidate's
`allowedLocations` (not remote, and a location naming only countries outside them,
`work_authorization.outside_allowed_before_enrichment`; an ad whose own words say remote or open to a region is still read): the location state is already
"outside" from the same fields (a Blocked verdict, 1.5), so a model call would add nothing the verdict reads. `--read-outside-allowed`
turns that off, and an empty `allowedLocations` skips nothing. Results cache on the job under `llmFacts`, keyed by a fingerprint
of the ad, so reruns are free. `llm_client.py` holds a provider table —
OpenAI, DeepSeek, OpenRouter, Groq, Ollama, a `custom` endpoint, and the
Claude Code CLI. Which one runs is the owner's selection in Settings > AI Provider (`data/config/ai-settings.json`,
`python/llm/ai_selection.py`), the same file the browser path reads; no environment key, no `HOLOJOB_LLM_PROVIDER`
and no CLI fallback chooses, and with nothing selected a call refuses (`llm_client.active_provider()`).

**Job history** (`job_scoring/job_history.py`, `data/jobs/job_history.json`).
Discovery rewrites `discovered_jobs.json` every run, so the ledger is what
survives: per `jobId`, `firstSeen`, `lastSeen`, `closedAt`, a snapshot of the
job, and the enrichment facts (`llmFacts`), the only thing enrichment adds to
a job. Facts are reused while the ad's content fingerprint (`job_fingerprint.py`,
the one definition, shared by enrichment and the ledger) is unchanged; a changed
ad is read again. The first run seeds the ledger from the file it replaces, and
the jobs in that file are treated as seen before (not New). A description under
200 characters, which is what LinkedIn returns when it rate-limits the detail
fetch, never replaces a fuller one the ledger holds, so a throttled run cannot
swap good facts for worse.
Records carry `firstSeen`, `lastSeen`, `closedAt`, `isNew` (first seen within 3
days) and `isClosed`; the job list shows New and Closed badges. Closed means
discovery no longer finds the job, and is decided only for Greenhouse, Lever
and Ashby (they list every open posting), only when that provider returned jobs
and the search was the same as when the job was last seen, and never while the
same title and company is still listed under another copy. LinkedIn returns a
rolling 72-hour window, so a LinkedIn job missing from a run is not closed.
Closed jobs stay in `discovered_jobs.json` for 14 days and are never judged;
the ledger drops them after 90. They stay in the main job list with their
badge, but are not candidates for "do something now": bulk tailoring, the
quality-audit sample, the P1 / P2 priority picks, the tier counts and the AI
Copilot's top jobs all skip them. A job picked by id is still tailored.

**Scoring** (`python/job_scoring/`). Six weighted dimensions, no AI:

    roleMatch 25, skillMatch 25, locationMatch 20,
    experienceMatch 15, industryMatch 10, cultureMatch 5

Industry points (`dimensions/industry_match.py`, `domain_transfer.py`): the preference match as before, plus a bonus that
keeps proven and assumed experience apart. Proven: a history entry of the candidate (`historyEntries`) is in the ad's
industry, +16. Transferable (assumed): an entry in an adjacent industry (`src/data/domainAdjacency.json`, every edge with
a `why`) states a capability the ad also asks for, +8 per bridge, at most +16. Never for an Unrelated title, never when
an avoided industry matched; every reason names the entry and says "assumed". Skill points use the keyword bank, which
holds keywords only (`keyword_shape.py`) and the skills of the whole history (`historySkills`).

These defaults live in one file, `src/data/scoringWeights.json`, read by the
intelligence generator, the Settings weights panel and `scorer.py`. Weights saved
in Settings are stored on the intelligence (`scoringWeights`) and win over the
defaults; every Regenerate Intelligence action goes through
`regenerateIntelligence()`, which carries the saved weights over, so only a
first-ever generation uses the defaults. A saved set with a missing or malformed
key gets that key from the defaults, in the UI and in the scorer.

**Verdict, ceilings and tiers** (`SCORING_VERSION` 1.7, `scorer.py`). Work authorization, language and place are states beside the score, not caps
(1.5). A confirmed blocker (sponsorship refused, a required language with a quote from the ad, a place outside `allowedLocations`, a required
security clearance or US status; `blocking.py`) sets the verdict to Blocked and never changes the number. `ceilings.py` lowers a score by role class
"other" (54) and, for ads with a current engine answer, by unmet requirements (69); an ad without one says "Ceiling not evaluated". The Fit 3 role
class (target / adjacent / other / not available) is stamped before scoring, and a "target" class is on-track for the engine gate and the
off-track and unrelated-title caps (1.7). The Jobs list shows three coarse tiers from the score (Strong fit 70+, Possible fit 55-69, Weak fit
below 55 or a Skip verdict; `src/modules/jobs/fitTier.js`) and claims no order inside a tier. Rules: `.claude/rules/scoring.md`; history:
[DECISIONS.md](DECISIONS.md).

**Fit judgement** (`llm_enhancer.py`, opt-in: `run_scoring.py --judge`). After
local scoring, an LLM compares the ad with the candidate and returns a fit
category, the requirements it checked, what is missing and any dealbreakers.
It returns no number. The code decides what the answer costs:

    strong +5, good 0, partial -8, poor -15, any dealbreaker -15

Only jobs scoring 65 or more are sent: the largest raise is +5 and Apply
starts at 70 (labels.py `APPLY_MIN_SCORE`), so a job below 65 cannot change decision, and 65 is above both
hard caps (red flag 54, off-track 50, unrelated title 40), so capped jobs are never sent. A job a
hard rule applies to (`hardCapped` on the result) can be lowered by the judge
but never raised. At most 50 jobs are sent per run (`--judge-limit`, 0 for no
limit): the highest local scores at or above the threshold, equal scores in input
order, chosen after every job has been scored locally. A job beyond the cap
still gets a judgement already in the cache, which costs nothing. The run
summary and `meta.judge` in `scored_jobs.json` report jobs scored against jobs
judged, new calls, cache hits and jobs left beyond the cap. Label, recommendation
and priority are recomputed through
`labels.py`. The judge model comes from `llm_client.judge_model()` (sonnet on
the CLI, `gpt-6.1-sol` on OpenAI, `deepseek-v4-pro` on DeepSeek,
`<PROVIDER>_JUDGE_MODEL` overrides). Results
cache in `data/cache/llm_fit.json`; a failed call leaves the local score.
A local run (no `--judge`) re-applies judgements already in that cache and
makes no call: the model function is replaced with one that raises. A cached
judgement matches only while the ad, the digest, the prompt version and the
provider/model are unchanged; the drawer marks it "from cache".

From the UI, a judged run is its own action: the amber "Fit judgement" card in
the Jobs > Pipeline tab opens a confirmation filled by `run_scoring.py
--judge-preview` (provider, model, how many jobs would be sent, the digest
field list `DIGEST_FIELDS` and `NEVER_SENT`), and only its confirm button
calls `POST /api/scoring/judge`, which refuses a body without
`"confirm": true`. `/api/scoring/run`, Re-score and Run Full Pipeline never
judge; `tests/js/judgeBoundary.test.js` pins both routes.

**Apply by** (`job_scoring/deadline.py`). Display metadata like the salary flag: `applyDeadline` is the board's
`expiresAt`, else a date right after a phrase announcing a deadline, only when it cannot be misread; anything else is
unknown. It moves no score and does not close an ad. The Jobs table buckets it in `modules/jobs/jobDeadline.js`.

**Salary column.** The table shows the pay as the ad states it (`statedSalary`); `salaryMonthlyEur` appears only as a
second line marked approximate. Lever `salaryRange` and Ashby salary components are written as `N - N yearly EUR` by
`format_pay_range`, which leaves out a figure with no currency.

**Salary flag** (`job_scoring/salary.py`). Display metadata only: it never reaches
`matchScore`, `matchLabel`, `priority`, `applyRecommendation` or the red flags
(`tests/python/test_salary.py` pins that). The profile holds `minSalaryEur` and a
desired range `desiredSalaryMinEur`/`desiredSalaryMaxEur`, all EUR per month,
carried into `jobFitPreferences` by the intelligence generator and never sent to the
judge. Scoring parses the job's free-text `salary` into `salaryMonthlyEur`
(`{min, max, currency, converted}`) only when the text names one currency (EUR, USD
or GBP), a yearly or monthly interval and one amount or range; USD and GBP are
converted at the fixed rates in `salary.py` (`EUR_PER_UNIT`) and shown as "≈". JobSpy's
formatter drops the currency when it is USD, so exactly its own shape
(`92900 - 209500 yearly`) is read as USD; free text with no currency, any other
currency (PLN, CHF, CA$), an hourly rate or an open-ended "up to / from" is unknown. `belowMinSalary` is true
when the top of the range is under the minimum, false when it reaches it, null when
the pay or the minimum is unknown. The job list shows a "Below min salary" badge, and
the Filters panel has Min salary and Desired salary from/to, pre-filled from the
profile until touched; a job with unreadable pay always passes them. The minimum is
read from the intelligence file on every scoring run, so a re-score picks up a changed
minimum without discovery once the intelligence is regenerated and synced.

**My CVs** (`src/utils/cvLibrary.js`, `scripts/cv-store.js`). Every uploaded CV is kept:
the PDF as `data/profile/cvs/<id>.pdf` (server-made id, `%PDF-` and 10 MB checked;
`/api/cvs`), and an entry in `profile.cvLibrary` (`id, label, fileName, uploadedAt,
filePath, rawText, parsedData, importSource, analysis`). `profile.resume` keeps its shape
and is the active CV that the rest of the app reads; `profile.defaultCvId` says which
entry it is. Setting a default copies the entry into `profile.resume`, after writing the
outgoing default's form edits back into its entry (the live copy is `profile.resume`).
The default cannot be deleted. The first load migrates an existing `profile.resume` into
the library (its PDF was never stored, so `filePath` is null). Cancel in Edit Profile
deletes the PDFs of CVs added during that session (`cvFilesToDiscard`).

**CV analysis** (`python/cv_analysis/`, `POST /api/ai/cv-analyze`). On demand, from a My CVs
card. The model reads the CV and returns facts it copied from it: the CV's own competency
and tool groups, roles with bullets, skills, key projects, education, certifications, and a
draft career summary. `analysis.verify` then checks every item against the CV text and
drops (and reports) what is not there; the draft summary is kept only when each number and
proper noun in it is in the CV. The review (`CvAnalysisReview`) compares with the profile
(new / already there / differs) and writes only ticked items, into `parsedData` (skills,
workExperience, education, certifications, plus `experienceDetail`, `competencyGroups`,
`toolGroups`) and Questionnaire answers 4 and 17. Only the default CV can be applied.
Apply then regenerates the intelligence and syncs it to disk (`regenerateAfterApply.js`, the
same steps as the Regenerate Intelligence button, local and rule-based) so scoring sees the
change; the entry remembers which items were applied (`analysis.applied`, `analysis.lastApply`).
Results cache in `data/cache/cv_analysis.json` by a fingerprint of the redacted text,
provider, model and prompt version; the entry keeps its last analysis. The model is
`judge_model(provider)`.

### Fit judge: dealbreakers and languages

A dealbreaker needs the candidate text to *contradict* a hard condition (the ad
requires Russian, the digest lists Serbian and English). Silence is not
failure: a condition the digest cannot settle goes under `missing`. The
digest settles languages from `basicProfile.languages`, a list of
`{ language, proficiency }` entries edited in the profile form
(`src/utils/languages.js` holds the fixed proficiency set; the Python copy is
`python/resume_generator/profile_languages.py`, and a test keeps the two in
step). `generateCandidateIntelligence` derives the `languages` strings the
judge reads (`["Serbian (native)", "English (fluent)"]`), so regenerating the
intelligence file keeps them as long as the profile has them. The same field
prints a Languages section on the CV, not the cover letter. A profile with no
languages is not an error: the digest then says "(none stated)" and the CV has
no such section.

## Re-scrape: the manual intake run

`python/run_rescrape.py` (started by `scripts/run-rescrape.js`; one lock, one Activity record, cancellable) does the whole intake of new
ads in one manual run. It is a manual action: the gate trigger is `manual` on every step, so it does not depend on `automation.enabled`.

    discovery -> classification (ads with no Fit 3 role class, classify_new.py) -> reading (Target / Adjacent ads not yet read,
    enrich_jobs.py, llmFacts) -> free scoring pass into a scratch file (scoring-prepare, never scored_jobs.json) -> engine fill
    (engine_missing.py, only when Settings allow it) -> the real scoring (run_scoring.py)

The scoring pass before engine fill exists because the engine plans from a scored list; it keeps the three `-pre-rescore` backups of
`scored_jobs.json` unused until the real scoring. The three paid steps run as passes over three priority groups: this run's new ads, then
existing Strong / Possible ads classified before the run, then the older backlog (`run_rescrape.intake`, `run_budget.in_group`).

**Limits live in Settings > AI budget (`data/ai/settings.json`), none in code:** `runLimitUsd` and `runLimitAds` (distinct ads; one ad
classified, read and engine-filled counts once), the daily and monthly limits, the call caps, and `allowEngineFill` (default off; turning it on
is a loosening and needs the confirm). With no run limit set (null or 0) the paid steps send nothing and count what waits ("run limit not set
in Settings"); engine fill is skipped. The orchestrator reads what the run really spent from the AI ledger (features `fit3-classify`,
`enrichment`, `evidence-matcher`) and passes each step the remainder; the AI gate still decides every call
(`python/job_scoring/run_budget.py`, `resolve_limits`; an omitted CLI flag is read from Settings).

**A limit is a stop point, never a silent wait.** A paid step that stops exits 0 and prints one JSON summary line with a fixed stop code
(`run_usd`, `run_ads`, `daily`, `monthly`, `call_cap`, `failures`, `unset`, `gate`, `engine_not_allowed`, `not_sent`, `no_report`); the next steps still
run and scoring always runs. The run status is `waiting`, shown as "Completed, N ads waiting"; `partial` is a failed source or a failed paid
step. Activity shows "Stopped: <limit>, N ads waiting (<step>)" and the `paid` block of the record. Results are cached, so the next run continues
without repeating a paid call.

**Run Full Pipeline** (`python/run_pipeline.py`) runs classification after discovery and enrichment and before scoring, with the Settings limits. It
is an automatic AI task for the gate, so with `automation.enabled` false the gate refuses it (counted, ads stay "not available"). **Re-score**
(`POST /api/scoring/run`) is free and calls no model. Privacy: classification and reading send ad text only; engine fill sends a redacted
evidence index ([`.claude/rules/privacy-inventory.md`](../.claude/rules/privacy-inventory.md)). Decisions and measured numbers:
[DECISIONS.md](DECISIONS.md), packages 12-15.

## Tailoring spec: HOLOJOB_GENERATION_CONTEXT.md

`HOLOJOB_GENERATION_CONTEXT.md` (repo root) is the layout and content spec for the
tailored CV and cover letter. Its visual identity (Parts 1-3) is fixed and measured
from a master PDF: styling is fixed, only the words change. Parts 4-5 are the content
recipes for the cover letter and the CV, Part 6 the implementation notes (HTML
templates rendered by headless Chromium, the validation step, the spec file names
`<Name>_<Company>_<Role>_Resume.pdf` and `..._CoverLetter.pdf`), Part 7 known gotchas.
The code refers to it by name in `llm_tailor.py`, `pdf_renderer.py`, `run_tailor.py`
and the two HTML templates, so keep the file name. The content rules in it sit under
the CV content rule in `CLAUDE.md`: it may not introduce a claim the profile and CV
do not state.

## Why the dimensions look the way they do

- **location_match** reads the board's `workMode` first, then
  `llmFacts.workMode`. JobSpy exposes only `isRemote` and LinkedIn leaves it
  unset, so seven genuinely remote ads were scoring as "not remote". Onsite
  outside Niš scores 15: for this candidate that is not a weaker match, it
  is an unusable job. `preferredLocations` means commute cities only. A
  country there would match every office in it by substring (one did: 12 of
  27 jobs, Belgrade onsite included, scored 90), so countries are now ignored
  as commute places. Onsite or hybrid somewhere the candidate would relocate
  to (`relocation`: none, abroad, anywhere) scores 60; the owner's is
  `abroad`, so Belgrade stays 15 and Berlin is 60.
- **role_match** matches contiguous substrings, not token subsets. Token
  subsets scored "Product Compliance Manager" as a perfect Product Manager
  match, and a single shared word like "lead" passed a 50% overlap test.
- **experience_match** takes seniority from the ad via `llmFacts`. The old
  title ladder mapped "manager" to a lead level, so every "Product Manager"
  came out one step above a senior candidate and the dimension returned 72
  for almost every job.
- **skill_match** weights each keyword by how rare its tokens are across the
  current run's corpus (`corpus.py`, run-local IDF). "Product Management" is
  in every ad and earns nothing; a rare term separates jobs. `TARGET_COVERAGE`
  is the one number to calibrate.
- **scorer.py** caps a job at 50 when `llmFacts.roleTrack` is not one its role family
  accepts (for product: `product_management`, `product_ownership`, `program_management`)
  — delivery work wearing a product title.
- **role_tier.py** sorts a title into target, near or unrelated from the family's
  `titleRules` in `src/data/roleFamilies.json`; only an unrelated title is capped, at 40,
  in `scorer.py` (`hardCapped`, a reason line). Most ads have no `llmFacts`, so this is
  what holds without enrichment. A project or delivery title is near only with
  evidenced product responsibility. No family or no vocabulary means no cap. The vocabulary
  holds Serbian wording too (Latin with and without diacritics, Cyrillic); Serbian project and
  delivery manager titles use the same fact rule as the English ones.
- **eligibility.py** (scoringVersion 1.5) is the work-authorization state beside the score, never inside it: `authorized` (the profile lists
  the ad's country), `sponsorship_offered`, `sponsorship_refused` and `unknown` ("Unconfirmed"). An ad statement counts only with a quote that
  is found in the ad's own text; a refusing quote refuses, a quote that only requires a right to work blocks only when the ad's country is
  outside the authorized countries, silence and unread ads are unknown, and B2B / employer-of-record / contractor wording in the ad (found by
  code) keeps an ad from being blocked when the profile says B2B is available. No authorized country in the profile means the check is
  dormant (`eligibility: null`). The 25 / 40 / 45 visa caps and the language cap (25) were removed from `matchScore` in 1.5.
- **work_authorization.py** still resolves where the work is done (`resolve_places`) and the location status the shadow engine's gates read
  (`needs_visa_*` statuses there are display and gate input only; nothing caps on them).
  When `allowedLocations` is set, `location_text.py` also reads the board's remote flag and
  the stored description (no model): no remote signal and a place outside the list is
  `outside_allowed` as before; a remote signal with a geography the ad states and the
  candidate does not allow ("UK only", "must be based in the UK") is `outside_allowed` too;
  a remote, worldwide or EU / Europe signal with no confirmed restriction is `unknown`
  location, not capped, flagged "Verify location" (`workAuthorization.location`), and lowers
  confidence only; "Serbia", "Balkans" or "worldwide" stated is `pass`. "Remote" alone never
  means available from Serbia. Benefit lines ("fully remote workers") and a hybrid mention
  are not a remote signal. An unknown location gets no ranking boost.
  `outside_allowed` is shown as "Outside your places" and is not capped (1.5); nothing is ever
  hidden. The candidate's side is `jobFitPreferences.workAuthorization`
  (where they may work without sponsorship, and whether they are open to a
  sponsored role) and `allowedLocations`, all edited in the profile form.
  None has a default: no work rights means the visa is not checked, and an
  empty `allowedLocations` gates nothing, which is the owner's setting: the
  US and the EU are live options, and authorization affects the score only.
  An ad that lists several offices is judged on all of them: one in a country
  the candidate may work in makes it `authorized`. `geography.py` resolves places through `src/data/geography.json`, shared
  with the UI; a place it does not know is unknown, and unknown never caps.
- **text_utils.py** folds diacritics, so "Niš" and "Nis" compare equal.
  Serbian boards spell both ways and a failed match is silent.

## Open problems

1. ~~`skill_match` saturates~~ — no longer: on the 2026-10-24 run (430 jobs) it is
   the one dimension that discriminates (mean 47, 44 distinct values; `TARGET_COVERAGE`
   was recalibrated). The flat ones are `roleMatch` (95 for 273 of 288 uncapped jobs,
   since every ad was found by a target-role search), `cultureMatch` (58 for 266) and
   `locationMatch` (60 for 226). They give every job about 70 points before skills
   count, so scores bunch between 68 and 78 and the median uncapped job is 70. The
   real remaining work is giving those three dimensions something to separate on.
2. **Seven ads still have `workMode: unclear`.** The model is right — those
   ads do not say. But "Serbia" alone and "Belgrade, Serbia" are treated the
   same, and a country without a city is weaker evidence of an office.
3. ~~`priority()` dead branch~~ — P1 is now a separate line, `P1_MIN_SCORE = 76` in
   labels.py (Apply stays at 70). At 70 it held 175 of 430 jobs (41%); at 76 it holds
   37 (9%), and Apply-level jobs below it are P2. It is one number calibrated by hand
   against a run: recheck it after any weights or dimension change.
4. **No regression tests.** The Infostud and Workable clients parse other
   people's page structures and will break silently when those change. A
   test asserting a non-empty result would catch it.
5. **The résumé parser cannot split a flat skills row from its neighbour.** PDF
   text arrives as one line, so in "Languages: Python, Scala Data Tools: Airflow"
   "Scala Data Tools" reads as one label. A period, a bracket, a dotted name
   or any line break between rows settles it. A CV whose competencies are
   "Label Item, Item, Item." groups with no colon gets no rows from them; the
   profile's skills list covers them in one "Skills" row.

Carried over from the former "Next, in order" list (nothing else from it is still open):

6. **Recalibrate `TARGET_COVERAGE`** against a real run once problem 1 is fixed.
7. **Judge a real run** and check the adjustments against the owner's own sense of
   the jobs (the fit judgement itself is built).
8. **Companies not covered by Greenhouse / Lever / Ashby:** `companies/` holds only
   companies from the owner's application history whose board slug resolved against
   the live API. Not covered: Revolut (Workable,
   already reached by the `workable` search), Nutanix (Jobvite), Openprovider
   (Recruitee), Proxify, Cleverbridge, DataWalk (no supported ATS found). Lever's EU
   instance (`api.eu.lever.co`, Everseen) is tried as a fallback; Fundraise Up's board
   is `fundraiseup-serbia`, not `fundraiseup`. These providers match search terms
   against the whole ad, not the title, so engineering ads that mention "product
   manager" come through (scoring caps them at off-track); `role_filter.py` would
   tighten that.
9. **Nightly run** of `--providers serbia`, then enrich, then score: listed under
   "Later" in [ROADMAP.md](ROADMAP.md).


## Automatic backups and the save guard (2026-11-23)

**Backups.** Before any write that changes one of `data/intelligence/candidate-intelligence.json`, `data/profile/candidate-profile.json` or
`data/profile-enrichment.json`, the file as it is now is copied to `data/backups/auto/<file name>/<YYYYMMDD-HHMMSS>.json` (UTC, files 600, folders 700,
read back and hash-checked). The last 10 versions per file are kept; the same code removes the older ones. Identical new content makes no backup (the
profile is compared without its `meta.updatedAt`, which every save refreshes). If the backup cannot be written the write is refused with an error and
nothing changes. Writers: `scripts/save-profile.js`, `scripts/save-intelligence.js` (so the two save routes, the pipeline run and the re-scrape push),
the zip restore in `scripts/backup-handler.js`, `python/job_scoring/profile_enrichment.py`.
**`data/jobs/scored_jobs.json` is different (owner decision 2026-11-23): it is backed up only immediately before a re-score** (`run_scoring.py`, the one
writer that rebuilds it), as `data/backups/auto/scored_jobs.json/<YYYYMMDD-HHMMSS>-pre-rescore.json`, the last 3 of those. The other writers of that file (a
manual job add, edit or delete in `import_job_url.py`, and the zip restore) make no backup and never use up the 3. That loses nothing: a manual job is
saved in `manual_jobs.json` first and every re-score rebuilds the scored file from the discovered jobs plus that file. A re-score whose backup cannot
be written is refused (the old file stays). Code: `scripts/auto-backup.js`, `python/job_scoring/auto_backup.py` (`event="rescore"`).
A file outside the data folder (a scratch or test file) is never backed up.

**Restore is manual, one copy.** List the versions, pick one, copy it over the file (the next write backs the current one up in turn):

    ls /srv/holojob/data/backups/auto/candidate-intelligence.json/
    cp -p /srv/holojob/data/backups/auto/candidate-intelligence.json/<YYYYMMDD-HHMMSS>.json /srv/holojob/data/intelligence/candidate-intelligence.json

(profile: `.../auto/candidate-profile.json/` to `data/profile/candidate-profile.json`; enrichment: `.../auto/profile-enrichment.json/` to `data/profile-enrichment.json`;
scores: `.../auto/scored_jobs.json/` to `data/jobs/scored_jobs.json`.) The browser is still the master of the profile and the intelligence until Step 5:
the next push from a browser overwrites a restored file, so restore the browser's copy as well, or do not save from a browser that holds an older one.

**Save guard** (`scripts/save-guard.js`, inside `writeProfileFile` / `writeIntelligenceFile`): a save is refused (409, `would_lose_data`, nothing written)
when it would empty, or cut by more than half (lists of 3 or more), at least 3 of the owner-set preference fields listed in that file (target roles,
locations, languages, remote preference, role family, salary fields, work-authorization holds, role and search lists, preferred industries, questionnaire
answers, GitHub links, CV library) that are filled in on the server. A first save, a server file with nothing filled in, and a normal edit (one or two fields) pass.
The refusal is logged with field names only and shown in the app (`SaveRefusedNotice`). Limits: it stops emptying, not replacing with an older but filled copy;
there is no override (save in smaller steps); scripts that write the files directly (restore, import, re-score) do not go through it.


## Role class before scoring (scoring 1.7, 2026-11-23)

`role_class.label(rows)` stamps `roleClass` / `roleName` from `data/cache/fit3.json` before `score_jobs`; `role_class.ceiling(scored)` applies the 1.6 role ceiling after it. The scorer reads the class through `scorer.role_on_track` (engine gate `role_family`, off-track cap 50) and `scorer.role_class_is_target` (unrelated-title cap 40 is skipped for a target class). The class exists only for an ad that has a stored Fit 3 classification; an ad without one is "not available" and takes the old track test. `python/job_scoring/classify_new.py` gives new ads their class: ads with text and no `fit3.json` entry at all (an entry whose role did not anchor is counted, never called again), one gated call each, limits from Settings, never from code; unset means nothing is sent. A limit, the AI gate or 3 failed calls in a row stops it; the rest stay "not available" and the stop is counted in the run record shown in Activity. Who runs it and under which budget: [Re-scrape](#re-scrape-the-manual-intake-run). Plain Re-score never calls a model. `tests/python/test_entry_scripts_clean_interpreter.py` loads every script Node or an orchestrator starts by path in `python -I`.

## Container gotchas (detail)

- **Bare `python` in the container is the venv.** `scripts/setup-job-discovery.sh`
  installs the pinned requirements into `/app/.venv`, not the system Python.
  Until the Dockerfile set `ENV PATH="/app/.venv/bin:${PATH}"`, a plain
  `podman exec holojob python ...` hit `/usr/local/bin/python`, which has no
  pandas, and `import pandas` failed although the image was built from the
  current `requirements.txt`. The app itself was never affected: it spawns
  `.venv/bin/python` directly. Images built before that ENV line need a rebuild.
- **The image carries no tests.** The Dockerfile does not copy `tests/`, and a
  bare `pytest` is not on the runtime PATH. Run the checks outside it, as in Tests (full text).
- **Build layers and the build context.** Dependencies come before code: `npm ci`, the global Claude Code
  install and `scripts/setup-job-discovery.sh` (pip plus the Playwright browsers, about 75 s and a 1.5 GB layer)
  rerun only when `package*.json`, `requirements.txt` or that script changes. A change to `python/`, `scripts/` or
  `src/` rebuilds only the `COPY` layers and, for `src/` or `scripts/`, the frontend stage (measured 2026-10-29:
  about 10 s, against about 90 s before). The frontend stage copies only what `vite build` reads (`index.html`,
  `vite.config.js`, `public`, `scripts`, `data/examples`, `src`). `.dockerignore` is an allow-list for `data/`
  (`data/*` except `data/examples`) and also drops `.env*`, `.claude`, `claude-config`, `docs`, `tests`, `fixtures`,
  so no private path enters any layer. Old intermediate frontend layers from earlier builds still hold
  `data/applications`, `data/ai` and so on; `podman image prune` removes them.
- **Deploy = image rebuild from a tagged, pushed commit. No hot patches** (owner decision 2026-11-18). Never `podman cp` / `tar | podman cp`
  into the running container, never edit files inside it: such a change is not in any image, is lost on the next recreate and leaves the running code
  different from the commit the source link points at. Every deploy is:

      # 1. the commit is pushed to origin and the tree it is built from is clean (a `git archive <commit>` export is the safest context:
      #    the build context otherwise includes untracked files)
      # 2. keep the running image as rollback
      podman tag localhost/holojob:latest localhost/holojob:rollback-<date>
      # 3. normal compose build, commit baked in (never an exported or copied filesystem)
      env HOLOJOB_COMMIT=<full commit sha> podman-compose build
      # 4. tag the new image like the git tag, back up the data file the release rewrites, recreate from /srv/holojob
      podman tag localhost/holojob:latest localhost/holojob:<release-tag>
      podman-compose -f /srv/holojob/docker-compose.yml up -d --force-recreate --no-build
      # 5. checks: health 200 (use an allowed Host header: -H "Host: localhost:3073" http://127.0.0.1:3073/api/pipeline/health),
      #    row and Blocked counts, band counts equal to the release report, no new line in data/ai/usage-ledger.jsonl.
      #    Roll back on any failure: podman tag localhost/holojob:rollback-<date> localhost/holojob:latest, then the same recreate.

  A re-score after a deploy runs inside the container (`podman exec holojob ...`) or through the app's own route, never by copying code in.
  The image holds no tests and no private data (`.dockerignore`); the data stays in the `./data` bind mount, so a rebuild changes no data.
  A frontend or Python change is a rebuild too (about 10 s with a warm layer cache, see above), so there is no reason to skip it.

### Tests (full text)

`node` and `npm` are not on the host's PATH, so lint, vitest and build run in a
throwaway node container (always `--security-opt label=disable`, never `:Z`,
which would relabel the repo). pytest runs directly against the host `.venv`
(Python 3.12, from `uv venv -p 3.12 .venv` and
`uv pip install -r requirements.txt`), never inside the image. In fish or bash:

    podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm npm run lint
    podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm npm run test:js
    podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm npm run build
    .venv/bin/python -m pytest tests/python -q

`npm test` and `npm run test:python` work on neither side: the host has no npm,
and `.venv/bin/python` does not resolve in the container (it links to a Python
outside the repo).

`pytest.ini` limits collection to `tests/python`, so a bare `pytest` from the
repo root does not walk `node_modules` or other third-party trees. The suite includes two `network` tests
that hit the live Infostud and Workable sites; they skip, rather than fail,
when a site is unreachable. Use `-m "not network"` to run offline.

Host Python 3.15 cannot install the pinned pandas 2.3.3 (no wheel; the source
build fails), so do not build `.venv` with it.

## Rule details moved from CLAUDE.md

### The architectural rule

The model marks facts; the code scores and applies caps. This is deliberate,
and borrowed from mature tools in this space (ApplyPack's ADR 0012, which
they arrived at after three attempts): a rule the candidate can lose a good
job to belongs in code, where it is deterministic and testable, and the
prompt keeps it only as an explanation.

So: do not move scoring decisions into prompts. If a judgement needs the

### Résumé content rule

A CV states only what the profile and the CV text state. There is no default for
anything: a part that cannot be read stays empty, `run_tailor.py` warns, and it
records the warning under the job's `tailoredAssets.warnings`.

- **Education** comes from `resume.parsedData.education`, the list the profile
  form edits, written as `Degree — School | Year`; the first readable entry is
  used. With none, the section is left out. An earlier hard-coded fallback put a
  stranger's degree on every CV; `tests/python/test_resume_education.py` pins
  its absence.
- **Summary and tagline** are the candidate's own: the CV's summary section,
  else the questionnaire narrative, and the CV header's headline, else the
  profile's current role. Rule-based tailoring writes no sentence of its own.
- **The parser reads structure, not one person's CV** (`resume_parser.py`):
  headings by the words they contain, entries by their date ranges, the header
  by the patterns contact details follow, the name through the profile's name.
  Titles and companies come from the profile's work-experience list when the
  start dates match. Nothing in it names an employer, a title, a city or a
  heading from any one CV, and `tests/python/test_resume_parser.py` keeps it so
  with invented CVs in several layouts.

### No hard-coded markets, no borrowed data

The country to search comes from `--country`, else the candidate intelligence;
with neither, discovery stops. No provider, script or UI has a default country.
Target roles drive search terms only. Seniority and candidate type are read
from the current role (`candidateNarrativeBuilder.js`), so listing "Head of
Product" as a target does not relabel the candidate. Europe and the United
States are added as search locations only when the profile's relocation is
`abroad` or `anywhere`; a role there that needs a visa the candidate lacks is
marked Blocked when the ad's own quote settles it (a verdict beside the score), not removed from the search.
The same holds after the search: the board providers' country filter lets a job
through when it lies in a searched place (`in_searched_place`, using
`geography.py`), so an onsite Berlin or Austin ad reaches scoring, gets its location state there and is never hidden. A candidate who would not relocate has only their home places in the
search locations, so nothing changes for them.
A missing profile, intelligence or scored-jobs file is an empty state: the app
never fills it from `data/examples/` outside an explicit demo mode. Keep it
that way: a default is a decision made for the candidate without asking.

The server as master is decided (DECISIONS.md principle 15) but not built.
Until step 5 ([redesign/STEP5_SERVER_MASTER_PLAN.md](redesign/STEP5_SERVER_MASTER_PLAN.md))
ships, the profile, intelligence and job list live in the browser's
`localStorage`. The profile is mirrored to
`data/profile/candidate-profile.json` on sync, so a correction made only in
the disk file is overwritten at the next sync. Fix profile data in the
profile form. Applications (tracker) are already on the server:
`data/applications/` is the master and the browser keeps a read cache.


## Tests and pre-push hook (moved from CLAUDE.md)

The commands stay in CLAUDE.md. Detail, moved verbatim:

- pytest runs directly against the host `.venv` (Python 3.12: `uv venv -p 3.12 .venv`, `uv pip install -r requirements.txt`), never inside the image. The container's `python` is its own venv; `.venv/bin/python` does not resolve in the container (it links to a Python outside the repo).

`npm test` and `npm run test:python` work on neither side: the host has no npm, and `.venv/bin/python` does not resolve
in the container (it links to a Python outside the repo).

`pytest.ini` limits collection to `tests/python`. Two `network` tests hit live
Infostud and Workable and skip when unreachable; `-m "not network"` runs offline.
Do not build `.venv` with Python 3.15 (pinned pandas 2.3.3 has no wheel).

Commit attribution: `scripts/git-hooks/commit-msg` refuses a message with an attribution line (`Co-Authored-By:`, `Claude-Session:`, `Generated with Claude Code`), and `pre-push` refuses a push of any commit with one that the remote does not have yet. History already pushed is not rewritten and does not block a push.

Pre-push hook: `sh scripts/install-git-hooks.sh` (once; sets `core.hooksPath`) enables `scripts/git-hooks/pre-push`. After the remote and attribution guards it runs a test tier from `scripts/test-tier.sh`, stopping at the first failure. It checks an export of the pushed commit, not the working tree, using the repo's
`node_modules` and `.venv` (`HOLOJOB_NODE_MODULES` / `HOLOJOB_PYTHON` override them).

- **Fast tier (default, every push):** lint of the changed `src/` and `scripts/` files (the whole tree if `eslint.config.js` / `package.json` changed or the base is unknown; every rule is per-file), `vitest related` over the changed files, pytest over the tests that import a changed module or name a changed file (`scripts/select-tests.py`: import graph of `python/`, transitive; file-name mentions for fixtures, runners and configs), and always the meta tests (source-scanning guards, lists in `select-tests.py`: Vitest `browserStorageAllowlist`, `dataPermissions`, `requestGuard`, `composePorts`, `gitHooks`, `realDataGuard`, `importWizardSource`; pytest `test_real_data_guard`, `test_application_store_isolation`, `test_import_privacy`). No build, no `slow` tests. A change it cannot map (a file no test refers to, shared test setup such as `conftest.py` or `vitest.config.js`, an unknown base) runs the meta tests only and prints a `NOTE` line saying so.
- **Full tier (on demand):** `sh scripts/test-tier.sh full [SHA]`, or `HOLOJOB_PUSH_TIER=full git push ...`: all lint, all Vitest, all pytest including `slow`, the build.
- **Parallelism:** Vitest `maxWorkers: 4` (`vitest.config.js`), pytest `-n 4` (pytest-xdist, `pytest.ini`; `-n 0` for one process). Tests keep all state in `tmp_path` / temp dirs (the autouse fixtures in `tests/python/conftest.py`), use port 0, and the parametrized ids of generated zips are fixed (a time-dependent id makes xdist workers disagree on collection). `@pytest.mark.slow` marks tests of about a second or more (real kills, parallel processes). It skips branch deletions and tag-only pushes. It first refuses every remote except `origin` at its pinned URL, deletions and tags included (`core.hooksPath` turns off `.git/hooks/pre-push`, which is no longer used).
`git push --no-verify` bypasses all of it, the remote refusal included (only upstream's `no-push` push URL still holds then).
