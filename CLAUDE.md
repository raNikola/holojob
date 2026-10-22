# Holojob — working notes

Personal job-hunt pipeline, single user, running in Podman on a home server
(DS9). Not a product: optimise for this one candidate, a senior/technical
product manager based in Niš, Serbia, who will not relocate to Belgrade and
needs remote or near-remote work.

## Conventions

- All code and comments in English.
- The repo lives at `/srv/holojob`. The container is `holojob`.
- `./data` is bind-mounted to `/app/data`, so data edits need no copying.
  Code does: either `podman cp` for a quick test, or `podman-compose build`
  to make it permanent.
- Changing `.env` requires `podman-compose up -d --force-recreate`; a
  restart does not re-read it.
- The owner runs the commands. Propose them, do not assume they ran.

## Container gotchas

- **Bare `python` in the container is the venv.** `scripts/setup-job-discovery.sh`
  installs the pinned requirements into `/app/.venv`, not the system Python.
  Until the Dockerfile set `ENV PATH="/app/.venv/bin:${PATH}"`, a plain
  `podman exec holojob python ...` hit `/usr/local/bin/python`, which has no
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
repo root does not walk `external/`. The suite includes two `network` tests
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

Dedup is two-pass (`dedupe_jobs.py`): by URL, then by title+company within a
source, because LinkedIn publishes one role as several ads, one per city.

**Enrichment** (`python/job_scoring/enrich_jobs.py`). An LLM reads each ad
and reports facts: work mode, role track, seniority, years required,
must-haves, listing-quality flags. It never scores and never sees the
candidate. Results cache on the job under `llmFacts`, keyed by a fingerprint
of the ad, so reruns are free. `llm_client.py` holds a provider table —
OpenAI, DeepSeek, OpenRouter, Groq, Ollama, a `custom` endpoint, and the
Claude Code CLI as a keyless fallback. `HOLOJOB_LLM_PROVIDER` chooses.

**Scoring** (`python/job_scoring/`). Six weighted dimensions, no AI:

    roleMatch 25, skillMatch 25, locationMatch 20,
    experienceMatch 15, industryMatch 10, cultureMatch 5

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
  is an unusable job. `preferredLocations` must NOT contain "Serbia" —
  matching is substring, so it would hand every Belgrade office 90 points.
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

## Next, in order

1. Fix (1) above, then recalibrate `TARGET_COVERAGE` against a real run.
2. Phase three: an LLM comparison pass through the existing hook in
   `llm_enhancer.py` (`enhance(job, base_result, intelligence)`), which reads
   the ad and the profile and returns a judged fit plus what is missing. Run
   it over the top N only. Hard rules stay in `scorer.py`.
3. Point the existing Greenhouse / Lever / Ashby providers at a real
   `companies/` list. The owner's own application history shows 12 of ~40
   applications went through those three ATS platforms — JetBrains three
   times — and the providers are already written and unused.
4. A nightly cron for `--providers serbia`, then enrich, then score.