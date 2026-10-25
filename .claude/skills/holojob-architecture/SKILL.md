---
name: holojob-architecture
description: Map of the Holojob codebase (directories, pipeline, data flow, key files per concern). Use before exploring the codebase or planning a change, to find where something lives without searching.
---

# Holojob codebase map

Depth: `docs/ARCHITECTURE.md`. Terms: `docs/GLOSSARY.md`. Phases: `docs/ROADMAP.md`. Data shapes: `docs/redesign/data-shapes.md`. Engine contract (draft): `docs/redesign/ENGINE_CONTRACT.md`.

## Data flow

    browser (localStorage = master) --sync--> data/profile, data/intelligence (mirrors)
    run_discovery.py -> data/jobs/discovered_jobs.json (+ job_history.json ledger)
    enrich_jobs.py   -> llmFacts on each job
    run_scoring.py   -> data/jobs/scored_jobs.json   (--judge is opt-in, confirmed)
    run_tailor.py    -> data/resumes/<jobId>/
    python/run_pipeline.py chains discovery -> enrich -> score (npm run pipeline)

## Where things live

| Concern | Location |
|---|---|
| React UI | `src/components/<area>/`, state and logic in `src/modules/<area>/`, helpers `src/utils/`, shared JSON `src/data/` |
| Node API + runners | `scripts/api-handler.js` (routes), `local-server.js`, `run-*.js` (spawn Python), `cv-store.js`, `save-*.js` |
| Discovery | `python/job_discovery/` (`run_discovery.py`, `providers/`, `dedupe_jobs.py`); company boards in `companies/*.json` |
| Enrichment, scoring, judge | `python/job_scoring/` (`enrich_jobs.py`, `scorer.py`, `dimensions/`, `work_authorization.py`, `geography.py`, `labels.py`, `llm_enhancer.py`, `llm_client.py`, `job_history.py`, `salary.py`) |
| CV analysis | `python/cv_analysis/` (`analysis.py`, `redact.py`), UI in `src/components/cvs/`, `src/utils/cvLibrary.js` |
| Tailoring, CV and cover letter | `python/resume_generator/` (`run_tailor.py`, `resume_parser.py`, `llm_tailor.py`, `templates/`); spec `CAREER_OS_GENERATION_CONTEXT.md` |
| Other modules | `python/quality_audit/`, `python/outreach_scraper/`, `python/profile_import/`, `python/job_import/`, `python/project_intelligence/`, `python/llm/claude_code.py` |
| Tests | `tests/python/` (pytest), `tests/js/` (vitest), `tests/fixtures/postings/`, root `fixtures/` |
| Deploy | `Dockerfile`, `docker-compose.yml` (Podman; host 3073 -> 5173) |

## Commands

`npm run lint`, `npm run test:js`, `npm run test:python` (host `.venv`, Python 3.12), `npm test`, `npm run build`, `npm run pipeline`, `npm run discover:jobs`, `npm run score:jobs`.

## Rules

Always-on rules are in `CLAUDE.md`; path-scoped ones in `.claude/rules/` (scoring, resume, frontend).
