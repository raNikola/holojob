---
name: holojob-architecture
description: Map of the Holojob codebase (directories, pipeline, data flow, key files per concern). Use before exploring the codebase or planning a change, to find where something lives without searching.
---

# Holojob codebase map

Depth: `docs/ARCHITECTURE.md`. Terms: `docs/GLOSSARY.md`. Phases: `docs/ROADMAP.md`. Data shapes: `docs/redesign/data-shapes.md`. Engine contract (draft): `docs/redesign/ENGINE_CONTRACT.md`.

## Data flow

    browser localStorage (profile, intelligence, job list; server master decided, NOT built until step 5)
        --sync--> data/profile, data/intelligence (mirrors)
    applications: already on the server, data/applications/ is the master (browser: read cache)
    run_discovery.py -> data/jobs/discovered_jobs.json (+ job_history.json ledger)
    enrich_jobs.py   -> llmFacts on each job
    run_scoring.py   -> data/jobs/scored_jobs.json   (--judge is opt-in, confirmed)
    run_tailor.py    -> data/resumes/<jobId>/
    python/run_pipeline.py chains discovery -> enrich -> classify -> score (podman exec holojob npm run pipeline)
    python/run_rescrape.py (manual, one lock): discovery -> classify_new.py -> enrich_jobs.py (reading) -> scoring-prepare ->
        engine_missing.py (only if Settings allow) -> run_scoring.py; one run budget from Settings, spend read from the AI ledger
    stores: data/cache/fit3.json (role class per ad), data/ai/settings.json (limits, gate), data/backups/auto/ (previous versions)

## Where things live

| Concern | Location |
|---|---|
| React UI | `src/components/<area>/`, state and logic in `src/modules/<area>/`, helpers `src/utils/`, shared JSON `src/data/` |
| Node API + runners | `scripts/api-handler.js` (routes), `local-server.js`, `run-*.js` (spawn Python), `cv-store.js`, `save-*.js` |
| Discovery | `python/job_discovery/` (`run_discovery.py`, `providers/`, `dedupe_jobs.py`); company boards in `companies/*.json` |
| Enrichment, scoring, judge | `python/job_scoring/` (`enrich_jobs.py`, `scorer.py`, `dimensions/`, `eligibility.py`, `blocking.py`, `ceilings.py`, `role_class.py`, `work_authorization.py`, `geography.py`, `labels.py`, `llm_enhancer.py`, `llm_client.py`, `job_history.py`, `salary.py`) |
| Re-scrape and paid steps | `python/run_rescrape.py` (orchestrator), `python/job_scoring/run_budget.py` (limits, stop codes), `classify_new.py`, `engine_missing.py`, `kept_ads.py`, `auto_backup.py` |
| Evidence engine (shadow, plus role class and ceiling) | `python/match_engine/` (`fit.py`, `fit3.py`, `matcher.py`, `gates.py`, `verify.py`, `constants.py`), `python/llm/` (AI gate, selection) |
| Calibration and measurement (owner-run, no production path) | `python/calibration/`, `scripts/measure_*.py`, `scripts/check_fit3_bars.py` |
| Jobs list tiers | `src/modules/jobs/fitTier.js` |
| CV analysis | `python/cv_analysis/` (`analysis.py`, `redact.py`), UI in `src/components/cvs/`, `src/utils/cvLibrary.js` |
| Tailoring, CV and cover letter | `python/resume_generator/` (`run_tailor.py`, `resume_parser.py`, `llm_tailor.py`, `templates/`); spec `HOLOJOB_GENERATION_CONTEXT.md` |
| Other modules | `python/quality_audit/`, `python/outreach_scraper/`, `python/profile_import/`, `python/job_import/`, `python/project_intelligence/`, `python/llm/claude_code.py` |
| Tests | `tests/python/` (pytest), `tests/js/` (vitest), `tests/fixtures/postings/`, root `fixtures/` |
| Deploy | `Dockerfile`, `docker-compose.yml` (Podman; host 3073 -> 5173) |

## Commands

`node` and `npm` are not on the host's PATH. Lint, JS tests and build run in a throwaway node container (always `--security-opt label=disable`, never `:Z`); pytest runs on the host against `.venv` (Python 3.12). `npm test` and `npm run test:python` work on neither side. In fish or bash:

    podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm npm run lint
    podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm npm run test:js
    podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm npm run build
    .venv/bin/python -m pytest tests/python -q

The pipeline scripts run inside the app container:

    podman exec holojob npm run pipeline
    podman exec holojob npm run discover:jobs
    podman exec holojob npm run score:jobs

## Rules

Always-on rules are in `CLAUDE.md` and in `.claude/rules/working-rules.md` and `standing-rules.md` (no path filter); path-scoped ones in `.claude/rules/` (scoring, resume, frontend, settings-screen, job-details, manual-jobs, request-guard, secret-store, ai-gate-and-selection, privacy-inventory, markets-and-data-source, container, private-file-modes). Status of what is built or open: `docs/ROADMAP.md` only.
