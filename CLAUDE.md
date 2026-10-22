# Career OS — working notes

Personal job-hunt pipeline, single user, running in Podman on a home server
(DS9). Not a product: optimise for this one candidate, a senior/technical
product manager based in Niš, Serbia, who will not relocate to Belgrade and
needs remote or near-remote work.

## Conventions

- All code and comments in English.
- The repo lives at `/srv/career-os`. The container is `career-os`.
- `./data` is bind-mounted to `/app/data`, so data edits need no copying.
  Code does: either `podman cp` for a quick test, or `podman-compose build`
  to make it permanent.
- Changing `.env` requires `podman-compose up -d --force-recreate`; a
  restart does not re-read it.
- The owner runs the commands. Propose them, do not assume they ran.
- This repo is local-only and is never pushed: personal data must never leave
  the home server. The push URL of `origin` is `no-push` and `.git/hooks/pre-push`
  always refuses, on purpose. Do not "fix" either as if it were broken.

## Container gotchas

- **Bare `python` in the container is the venv.** `scripts/setup-job-discovery.sh`
  installs the pinned requirements into `/app/.venv`, not the system Python.
  Until the Dockerfile set `ENV PATH="/app/.venv/bin:${PATH}"`, a plain
  `podman exec career-os python ...` hit `/usr/local/bin/python`, which has no
  pandas, and `import pandas` failed although the image was built from the
  current `requirements.txt`. The app itself was never affected: it spawns
  `.venv/bin/python` directly. Images built before that ENV line need a rebuild.
- **The image carries no tests.** The Dockerfile does not copy `tests/`, and a
  bare `pytest` is not on the runtime PATH. Run the suite on the host instead.

## Tests

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

Dedup is two-pass (`dedupe_jobs.py`): by URL, then by title+company within a
source, because LinkedIn publishes one role as several ads, one per city.

**Enrichment** (`python/job_scoring/enrich_jobs.py`). An LLM reads each ad
and reports facts: work mode, role track, seniority, years required,
must-haves, listing-quality flags, and the job's country, where a remote hire
may live, and what the ad says about visa sponsorship. It never scores and
never sees the
candidate. Results cache on the job under `llmFacts`, keyed by a fingerprint
of the ad, so reruns are free. `llm_client.py` holds a provider table —
OpenAI, DeepSeek, OpenRouter, Groq, Ollama, a `custom` endpoint, and the
Claude Code CLI as a keyless fallback. `CAREER_OS_LLM_PROVIDER` chooses.

**Scoring** (`python/job_scoring/`). Six weighted dimensions, no AI:

    roleMatch 25, skillMatch 25, locationMatch 20,
    experienceMatch 15, industryMatch 10, cultureMatch 5

**Fit judgement** (`llm_enhancer.py`, opt-in: `run_scoring.py --judge`). After
local scoring, an LLM compares the ad with the candidate and returns a fit
category, the requirements it checked, what is missing and any dealbreakers.
It returns no number. The code decides what the answer costs:

    strong +5, good 0, partial -8, poor -15, any dealbreaker -15

Only jobs scoring 65 or more are sent: the largest raise is +5 and Apply
starts at 70, so a job below 65 cannot change decision, and 65 is above both
hard caps (red flag 54, off-track 50), so capped jobs are never sent. A job a
hard rule applies to (`hardCapped` on the result) can be lowered by the judge
but never raised. Label, recommendation and priority are recomputed through
`labels.py`. The judge model comes from `llm_client.judge_model()` (sonnet on
the CLI, `gpt-6.1-sol` on OpenAI, `deepseek-v4-pro` on DeepSeek,
`<PROVIDER>_JUDGE_MODEL` overrides). Results
cache in `data/cache/llm_fit.json`; a failed call leaves the local score.

**Privacy exception.** Everything else in this repo keeps personal data on the
server. The judge is the one deliberate exception, and only when `--judge` is
passed: it sends the ad plus a digest of `candidate-intelligence.json` (seniority,
years, target roles, spoken languages, career narrative, skills, domains,
project / ownership / leadership / impact examples, strengths, known gaps) to
the configured provider. Never sent: name, email, phone, salary, links,
preferred locations, raw resume text, questionnaire answers. Add a field to
`_candidate_digest` only deliberately, and update this list.

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

## The architectural rule

The model marks facts; the code scores and applies caps. This is deliberate,
and borrowed from mature tools in this space (ApplyPack's ADR 0012, which
they arrived at after three attempts): a rule the candidate can lose a good
job to belongs in code, where it is deterministic and testable, and the
prompt keeps it only as an explanation.

So: do not move scoring decisions into prompts. If a judgement needs the
model, have it return a fact, and let `scorer.py` decide what the fact costs.

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
  `geography.py` resolves places through `src/data/geography.json`, shared
  with the UI; a place it does not know is unknown, and unknown never caps.
- **text_utils.py** folds diacritics, so "Niš" and "Nis" compare equal.
  Serbian boards spell both ways and a failed match is silent.

## Open problems

1. **`skill_match` saturates.** Eleven of 23 jobs score exactly 100, which
   is not a result, it is a bug. Suspect the `achievable` accumulator in
   `_credit` or the must-have blend. The intent: must-haves are *reported*
   (they populate `missingSkills`, which feeds resume tailoring) and do NOT
   move the score, because judging whether a sentence like "experience
   shipping LLM-powered features" is met by counting shared tokens blurs the
   whole dimension. Verify what the file actually does before changing it.
2. **Seven ads still have `workMode: unclear`.** The model is right — those
   ads do not say. But "Serbia" alone and "Belgrade, Serbia" are treated the
   same, and a country without a city is weaker evidence of an office.
3. **`priority()` in labels.py** has a dead branch: `>= 85` and `>= 70` both
   return P1.
4. **No regression tests.** The Infostud and Workable clients parse other
   people's page structures and will break silently when those change. A
   test asserting a non-empty result would catch it.
5. **The résumé parser cannot split a flat skills row from its neighbour.** PDF
   text arrives as one line, so in "Languages: Python, Scala Data Tools: Airflow"
   "Scala Data Tools" reads as one label. A period, a bracket, a dotted name
   or any line break between rows settles it. A CV whose competencies are
   "Label Item, Item, Item." groups with no colon gets no rows from them; the
   profile's skills list covers them in one "Skills" row.

## Résumé content rule

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

## No hard-coded markets, no borrowed data

The country to search comes from `--country`, else the candidate intelligence;
with neither, discovery stops. No provider, script or UI has a default country.
A missing profile, intelligence or scored-jobs file is an empty state: the app
never fills it from `data/examples/` outside an explicit demo mode. Keep it
that way: a default is a decision made for the candidate without asking.

The browser copy of the profile is the master (`localStorage`, mirrored to
`data/profile/candidate-profile.json` on sync), so a correction made only in
the disk file is overwritten at the next sync. Fix profile data in the
profile form.

## Next, in order

1. Fix (1) above, then recalibrate `TARGET_COVERAGE` against a real run.
2. ~~Phase three: fit judgement~~ — built, see "Fit judgement" above. Still
   to do: judge a real run and check the adjustments against your own sense
   of the jobs.
3. ~~Greenhouse / Lever / Ashby~~ — built: `companies/` holds only companies
   from the owner's application history whose board slug resolved against the
   live API, and the three providers are in the `serbia` group. Not covered:
   Revolut (Workable, already reached by the `workable` search), Nutanix
   (Jobvite), Openprovider (Recruitee), Proxify, Cleverbridge, DataWalk (no
   supported ATS found). Lever's EU instance (`api.eu.lever.co`, Everseen) is
   tried as a fallback; Fundraise Up's board is `fundraiseup-serbia`, not
   `fundraiseup`. These providers match search terms against the whole ad, not
   the title, so engineering ads that mention "product manager" come through
   (scoring caps them at off-track); `role_filter.py` would tighten that.
4. A nightly cron for `--providers serbia`, then enrich, then score.