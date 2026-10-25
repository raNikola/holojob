# Holojob

**Job matching you can audit: AI cites the evidence, code computes the score.**

Holojob is a self-hosted job search assistant. It finds postings (including Serbian job
boards and remote roles open to Serbia), reads each one into its requirements, ranks them by
evidence of fit from the candidate's own history, and keeps the whole search - applications,
CV versions, notes, interview prep - in one place. Personal identifiers never leave the server.

Author: **Nikola Randjelovic** ([@raNikola](https://github.com/raNikola) · [cv.ranikola.dev](https://cv.ranikola.dev))

---

## Status

Holojob is a fork of [Career OS](https://github.com/Shanupower/career-os), heavily customized and
now being redesigned around evidence-based matching.

- Working today: discovery, enrichment of every ad into facts, six-dimension local scoring with
  hard caps (role track, work authorization, red flags), optional LLM fit judgement, CV library
  with verified CV analysis, CV and cover letter tailoring, outreach contacts.
- In progress: Phase 1 of the redesign - evidence-based Fit, running in shadow mode next to the
  current score. See [docs/ROADMAP.md](docs/ROADMAP.md).

## How scoring works

The rule of the codebase: **the model marks facts, the code scores.**

1. **Enrichment** - an LLM reads each ad (never the candidate) and returns facts with the ad's
   own words: role track, seniority, years, must-haves, work mode, country, visa sponsorship.
2. **Local scoring** - deterministic code scores six dimensions and applies hard caps: an
   off-track role, a red flag or a visa the candidate lacks cannot be argued up by weights.
3. **Fit judgement** (opt-in) - an LLM marks each requirement met / partly met / not met /
   unclear against a redacted digest of the candidate; code decides what that costs.
4. **Evidence-based Fit** (redesign) - each requirement is matched to a quoted piece of the
   candidate's history; code verifies the quote and computes Fit, confidence and gates.
   Unknown is never treated as missing - it becomes a question.

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [CLAUDE.md](CLAUDE.md) (rules), [docs/GLOSSARY.md](docs/GLOSSARY.md) and [docs/redesign/DECISIONS.md](docs/redesign/DECISIONS.md).

## Quick start

Requirements: Node.js 20+, Python 3.11-3.12, Git.

```bash
npm run setup          # Node deps + Python venv + Playwright browsers
cp .env.example .env   # then set an AI provider (see Configuration)
npm run dev            # http://localhost:5173
```

Production build with the full API server:

```bash
npm run start          # builds the SPA and serves it with /api on $PORT (default 5173)
```

Container (the DS9 deployment uses Podman):

```bash
podman-compose up -d --build     # or: docker compose up -d --build
```

`docker-compose.yml` maps host port 3073 to the app's 5173 and bind-mounts `./data`.
Changing `.env` needs `podman-compose up -d --force-recreate`; a restart does not re-read it.

## Data and storage

- The browser's `localStorage` is the master for the profile, the intelligence, the job list and application
  tracking.
- The files under `data/` are mirrors: written when the app syncs, and read by the Python pipeline. Everything
  there except `data/examples/` is git-ignored and private.
- Edit profile data in the profile form, not in the disk file: a correction made only in
  `data/profile/candidate-profile.json` is overwritten at the next sync.
- Shapes of every file: [docs/redesign/data-shapes.md](docs/redesign/data-shapes.md).

## Pipeline

```bash
npm run discover:jobs      # discovery, providers group "serbia"
npm run pipeline           # discovery -> enrichment -> scoring (python/run_pipeline.py)
npm run score:jobs         # re-score only
npm run tailor:resumes     # tailored CVs and cover letters
```

Discovery providers in the `serbia` group: LinkedIn (JobSpy), Infostud, Workable, Greenhouse,
Lever, Ashby. Data flows `data/jobs/discovered_jobs.json` -> `data/jobs/scored_jobs.json`, with
`data/jobs/job_history.json` as the ledger that survives between runs.

## Configuration

| Variable | Purpose |
|---|---|
| `CAREER_OS_LLM_PROVIDER` | Server-side AI provider: `openai`, `deepseek`, `openrouter`, `groq`, `ollama`, `custom` or `claude-code` (keyless fallback) |
| `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `LLM_API_KEY` (custom) | Key for the chosen provider; keys are read from the environment only |
| `<PROVIDER>_MODEL`, `<PROVIDER>_JUDGE_MODEL` | Model overrides for enrichment and judgement |
| `PORT` | Server port inside the container (default 5173) |
| `CLAUDE_AUTO_LOGIN` | Open the Claude Code login on startup (0 to disable) |
| `LINKEDIN_LI_AT` | Optional LinkedIn cookie for deep outreach mode (see Privacy: LinkedIn deep mode) |

Browser AI features (copilot, interview coach) keep their own provider settings in Settings.

## Privacy

- Everything under `data/`, CVs, `.env` and keys are git-ignored and stay on the server.
- Three steps send candidate data to an AI provider:
  - **CV analysis** - behind an explicit confirm; name, phones, e-mails and links are redacted first.
  - **Fit judgement** - behind an explicit confirm; sends a digest that never contains name,
    contacts, links, salary, locations, raw CV text or questionnaire answers.
  - **LLM tailoring** (Claude Code CLI) - sends the parsed CV sections (about, experience, skills,
    education), the intelligence summary and project intelligence; it has no confirm step and no
    redaction pass yet. This is a known gap against [DECISIONS.md](docs/redesign/DECISIONS.md)
    principle 14 and is scheduled with the fact gate in Phase 4.
- **Sensitive files.** Never commit `data/profile/*.json`, `data/resumes/`, `data/cache/repos/`, `.env` or
  `data/outreach/linkedin_session.json`. If one is committed by mistake, rotate the credentials and remove it
  from history before pushing anywhere.
- **API keys** are read from the environment on the server; browser AI features keep their keys in the
  browser's localStorage (Settings) and send them only to the provider you choose.
- **LinkedIn deep mode.** Outreach has an optional deep mode that automates linkedin.com with your `li_at`
  cookie (`LINKEDIN_LI_AT`, or `data/outreach/linkedin_session.json`). This may violate LinkedIn's Terms of
  Service and can get the account suspended or banned. It runs only with explicit consent
  (`acceptTosRisk` in the API and UI, `--i-accept-tos-risk` on the scraper CLI). The default search mode does
  not authenticate to LinkedIn. Never share the cookie.
- **Vulnerabilities:** contact the owner privately ([@raNikola](https://github.com/raNikola)), not in a public issue.
- **License:** AGPL-3.0. A modified version deployed as a network service must offer its source to its users.

## Tests

```bash
npm test                 # vitest, then pytest
npm run test:python      # pytest only (host .venv, Python 3.12)
npm run lint
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `npm run setup` fails on Python | Use Python 3.11 or 3.12 with `python3` on PATH. 3.15 cannot install the pinned pandas 2.3.3 |
| Discovery stops with a message about the country | Set the country in the candidate intelligence (regenerate it from the profile form) or pass `--country`; there is no default country |
| Discovery returns few jobs | Check the network and the slugs in `companies/*.json` (`npm run validate:companies`); LinkedIn rate-limits and Serbia is unsupported by Indeed and Glassdoor |
| Playwright errors | Re-run `npm run setup`, or `.venv/bin/python -m playwright install chromium` |
| Tailoring fails without an AI provider | `python python/resume_generator/run_tailor.py --job-id <id> --no-llm` still produces the rule-based CV and cover letter |
| Port in use | Outside the container set `PORT` in `.env` and restart. In the container the app listens on 5173; change the host port in `docker-compose.yml` (`3073:5173`) |
| `.env` change has no effect in the container | `podman-compose up -d --force-recreate`; a restart does not re-read it |
| `import pandas` fails with `podman exec career-os python` | The image predates the `ENV PATH` line in the Dockerfile; rebuild it (`podman-compose build`) |
| `pytest` not found in the container | The image carries no tests; run `npm run test:python` on the host |
| Jobs not showing in the UI | Run discovery and scoring (`npm run pipeline`); check the Pipeline health card on the Jobs screen |

## Documentation

- [docs/VISION.md](docs/VISION.md) - what Holojob is and is not
- [docs/GOALS.md](docs/GOALS.md) - goals and how they are measured
- [docs/ROADMAP.md](docs/ROADMAP.md) - phases and Phase 1 acceptance criteria
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - how the pipeline, scoring, judge and CV features work today
- [docs/GLOSSARY.md](docs/GLOSSARY.md) - terms used in the docs
- [docs/redesign/SOURCES_SPEC.md](docs/redesign/SOURCES_SPEC.md) - spec of Settings > Sources (job boards and watched companies as user configuration)
- [docs/redesign/ENGINE_CONTRACT.md](docs/redesign/ENGINE_CONTRACT.md) - draft JSON contract of the scoring engine
- [docs/redesign/DECISIONS.md](docs/redesign/DECISIONS.md) - principles and owner decisions
- [docs/redesign/PHASE0_AUDIT.md](docs/redesign/PHASE0_AUDIT.md) - current state and module decisions
- [docs/redesign/data-shapes.md](docs/redesign/data-shapes.md) - data files and their shapes
- [CLAUDE.md](CLAUDE.md) - rules and conventions for the codebase
- [docs/career-os/FLOW_AUDIT.md](docs/career-os/FLOW_AUDIT.md) - Career OS flow audit (historical)

## Credits and license

Holojob is built on [Career OS](https://github.com/Shanupower/career-os) by its original authors and
contributors, licensed under the [GNU Affero General Public License v3.0](LICENSE). Holojob keeps that
license. Ideas, and in some places code, come from MIT-licensed projects listed in
`THIRD_PARTY_NOTICES.md` when code is copied: career-ops, ApplyPack, JobSync, CareerPulse, JobApply.

Copyright (C) 2026 Nikola Randjelovic, for the changes made in Holojob.
