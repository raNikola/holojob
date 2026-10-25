# Holojob — Architecture

How the system works today, and why it is built that way. Moved out of `CLAUDE.md`
(which now holds only rules and conventions) without dropping anything. For where it
is going see [ROADMAP.md](ROADMAP.md) and [redesign/DECISIONS.md](redesign/DECISIONS.md);
for terms see [GLOSSARY.md](GLOSSARY.md); for the data files see
[redesign/data-shapes.md](redesign/data-shapes.md).


## Pipeline

    run_discovery.py  ->  enrich_jobs.py  ->  run_scoring.py
    data/jobs/discovered_jobs.json  ->  data/jobs/scored_jobs.json

**Discovery** (`python/job_discovery/`). Three providers in the `serbia`
group: `jobspy` (LinkedIn only — Serbia is unsupported by Indeed and
Glassdoor, and falling back to the USA silently was a real bug), `infostud`
(the domestic board; its free-text search is useless, so whole categories
are pulled and filtered locally), `workable` (remote roles open to Serbia;
its public JSON carries the full description). HelloWorld and Startuj were
evaluated and rejected: HelloWorld shares Infostud's inventory and ID space,
Startuj is entry-level only.

The standard run is `--providers serbia` (all six providers); it is the
default everywhere: the CLI, `npm run discover:jobs`, the API and every UI
screen. `ats` and the other groups stay available by name.

Dedup is two-pass (`dedupe_jobs.py`): by URL, then by title+company across
every source, keeping the fuller description. LinkedIn publishes one role as
several ads, one per city, and the same role reaches us from LinkedIn and from
the company's own board.

**Enrichment** (`python/job_scoring/enrich_jobs.py`). An LLM reads each ad
and reports facts: work mode, role track, seniority, years required,
must-haves, listing-quality flags, and the job's country, where a remote hire
may live, and what the ad says about visa sponsorship. It never scores and
never sees the
candidate. It does not read an ad the board already places outside the candidate's
`allowedLocations` (not remote, and a location naming only countries outside them,
`work_authorization.outside_allowed_before_enrichment`): scoring caps it at 40 from the
same fields, so a model call would only be discarded. `--read-outside-allowed`
turns that off, and an empty `allowedLocations` skips nothing. Results cache on the job under `llmFacts`, keyed by a fingerprint
of the ad, so reruns are free. `llm_client.py` holds a provider table —
OpenAI, DeepSeek, OpenRouter, Groq, Ollama, a `custom` endpoint, and the
Claude Code CLI as a keyless fallback. `CAREER_OS_LLM_PROVIDER` chooses.

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
quality-audit sample, the P1/P2 view, the Apply/P1/P2 counts and the AI
Copilot's top jobs all skip them. A job picked by id is still tailored.

**Scoring** (`python/job_scoring/`). Six weighted dimensions, no AI:

    roleMatch 25, skillMatch 25, locationMatch 20,
    experienceMatch 15, industryMatch 10, cultureMatch 5

These defaults live in one file, `src/data/scoringWeights.json`, read by the
intelligence generator, the Settings weights panel and `scorer.py`. Weights saved
in Settings are stored on the intelligence (`scoringWeights`) and win over the
defaults; every Regenerate Intelligence action goes through
`regenerateIntelligence()`, which carries the saved weights over, so only a
first-ever generation uses the defaults. A saved set with a missing or malformed
key gets that key from the defaults, in the UI and in the scorer.

**Fit judgement** (`llm_enhancer.py`, opt-in: `run_scoring.py --judge`). After
local scoring, an LLM compares the ad with the candidate and returns a fit
category, the requirements it checked, what is missing and any dealbreakers.
It returns no number. The code decides what the answer costs:

    strong +5, good 0, partial -8, poor -15, any dealbreaker -15

Only jobs scoring 65 or more are sent: the largest raise is +5 and Apply
starts at 70 (labels.py `APPLY_MIN_SCORE`), so a job below 65 cannot change decision, and 65 is above both
hard caps (red flag 54, off-track 50), so capped jobs are never sent. A job a
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

## Tailoring spec: CAREER_OS_GENERATION_CONTEXT.md

`CAREER_OS_GENERATION_CONTEXT.md` (repo root) is the layout and content spec for the
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
- **scorer.py** caps a job at 50 when `llmFacts.roleTrack` is neither
  `product_management` nor `product_ownership` — delivery or programme work
  wearing a product title.
- **work_authorization.py** gives each job one status, and scorer.py caps it
  the same way: `needs_visa_refused` 25 (the ad will not sponsor),
  `outside_allowed` 40 (a location the candidate excluded), `needs_visa_silent`
  45 (the ad does not mention sponsorship; Weak, still reviewable).
  `authorized`, `sponsored` and `unknown` are not capped, and nothing is ever
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
   the live API (Stripe, Coinbase and Anthropic were added from the old upstream list
   because their Greenhouse boards still resolve). Not covered: Revolut (Workable,
   already reached by the `workable` search), Nutanix (Jobvite), Openprovider
   (Recruitee), Proxify, Cleverbridge, DataWalk (no supported ATS found). Lever's EU
   instance (`api.eu.lever.co`, Everseen) is tried as a fallback; Fundraise Up's board
   is `fundraiseup-serbia`, not `fundraiseup`. These providers match search terms
   against the whole ad, not the title, so engineering ads that mention "product
   manager" come through (scoring caps them at off-track); `role_filter.py` would
   tighten that.
9. **Nightly run** of `--providers serbia`, then enrich, then score: listed under
   "Later" in [ROADMAP.md](ROADMAP.md).


## Container gotchas (detail)

- **Bare `python` in the container is the venv.** `scripts/setup-job-discovery.sh`
  installs the pinned requirements into `/app/.venv`, not the system Python.
  Until the Dockerfile set `ENV PATH="/app/.venv/bin:${PATH}"`, a plain
  `podman exec career-os python ...` hit `/usr/local/bin/python`, which has no
  pandas, and `import pandas` failed although the image was built from the
  current `requirements.txt`. The app itself was never affected: it spawns
  `.venv/bin/python` directly. Images built before that ENV line need a rebuild.
- **The image carries no tests.** The Dockerfile does not copy `tests/`, and a
  bare `pytest` is not on the runtime PATH. Run the suite on the host instead.

### Tests (full text)

Tests run against the host `.venv` (Python 3.12, from `uv venv -p 3.12 .venv`
and `uv pip install -r requirements.txt`), never inside the image:

    npm run test:python        # or: .venv/bin/python -m pytest
    npm test                   # vitest, then the same pytest run

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
capped by scoring, not removed from the search.
The same holds after the search: the board providers' country filter lets a job
through when it lies in a searched place (`in_searched_place`, using
`geography.py`), so an onsite Berlin or Austin ad reaches scoring and is capped
there. A candidate who would not relocate has only their home places in the
search locations, so nothing changes for them.
A missing profile, intelligence or scored-jobs file is an empty state: the app
never fills it from `data/examples/` outside an explicit demo mode. Keep it
that way: a default is a decision made for the candidate without asking.

The browser copy of the profile is the master (`localStorage`, mirrored to
`data/profile/candidate-profile.json` on sync), so a correction made only in
the disk file is overwritten at the next sync. Fix profile data in the
profile form.
