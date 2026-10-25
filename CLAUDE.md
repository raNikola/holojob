# Holojob (formerly Career OS) — working notes

Read docs/redesign/DECISIONS.md before any redesign work.

Personal job-hunt pipeline running in Podman on a home server (DS9). Single user
for now (DECISIONS.md principle 15): a senior/technical product manager based in
Niš, Serbia, who will not relocate to Belgrade and needs remote or near-remote work.

Docs (read on demand, not loaded automatically):

- `docs/ARCHITECTURE.md` — pipeline, scoring dimensions and why, fit judgement, salary flag, My CVs, CV analysis, open problems.
- `docs/ROADMAP.md` — phases and Phase 1 acceptance criteria (the only phase list).
- `docs/redesign/DECISIONS.md` — principles and owner decisions.
- `docs/redesign/ENGINE_CONTRACT.md` — draft JSON contract of the scoring engine.
- `docs/redesign/data-shapes.md` — data files and their shapes.
- `docs/GLOSSARY.md` — the terms used above (Fit, gate, evidence strength, ledger, ...).

Area rules load only when matching files are touched: `.claude/rules/scoring.md`
(`python/job_scoring/**`), `.claude/rules/resume.md` (`python/resume_generator/**`,
`python/cv_analysis/**`), `.claude/rules/frontend.md` (`src/**`). The skill
`holojob-architecture` maps the codebase.

## Conventions

- All code and comments in English.
- The repo lives at `/srv/career-os`. The container is `career-os`.
- `./data` is bind-mounted to `/app/data`, so data edits need no copying.
  Code does: either `podman cp` for a quick test, or `podman-compose build`
  to make it permanent.
- Changing `.env` requires `podman-compose up -d --force-recreate`; a
  restart does not re-read it.
- The owner runs the commands. Propose them, do not assume they ran.
- Personal data must never leave the home server. The repo is pushed only to the
  owner's private GitHub repo (`origin` = `git@github.com:raNikola/holojob.git`;
  `upstream` = Shanupower/career-os, fetch only, push URL `no-push`).
  `.git/hooks/pre-push` refuses every remote except `origin`. Everything under
  `data/` except the tracked examples, `.env`, CVs and keys stay in `.gitignore`.

## Container gotchas

- Bare `python` in the container is the venv (`/app/.venv`, via `ENV PATH` in the
  Dockerfile); images built before that line need a rebuild.
- The image carries no tests (`tests/` is not copied, no `pytest`). Run the suite on the host.

Detail: `docs/ARCHITECTURE.md` (Container gotchas).

## Tests

Against the host `.venv` (Python 3.12: `uv venv -p 3.12 .venv`, `uv pip install -r requirements.txt`), never inside the image:

    npm run test:python        # or: .venv/bin/python -m pytest
    npm test                   # vitest, then the same pytest run

`pytest.ini` limits collection to `tests/python`. Two `network` tests hit live
Infostud and Workable and skip when unreachable; `-m "not network"` runs offline.
Do not build `.venv` with Python 3.15 (pinned pandas 2.3.3 has no wheel).

## Privacy rules and exceptions

Personal data stays on the server. Two steps send candidate data to the configured
provider, each behind an explicit confirm; a third is a known gap.

- **CV analysis** sends the text of one CV with name, e-mails, phones and links replaced
  by placeholders (`redact.py`), only after the confirm dialog has shown that exact text
  and the provider; `/api/ai/cv-analyze` refuses a body without `"confirm": true`.
- **Fit judge**, only with `--judge`: sends the ad plus a digest of
  `candidate-intelligence.json` (seniority, years, target roles, spoken languages,
  career narrative, skills, domains, project / ownership / leadership / impact examples,
  strengths, known gaps). Never sent: name, email, phone, salary, links, preferred
  locations, raw resume text, questionnaire answers. Add a field to `_candidate_digest`
  only deliberately, and update this list.
- **Known gap:** LLM tailoring (`resume_generator/llm_tailor.py`, Claude Code CLI) also
  sends candidate data (parsed CV sections about_me, experience, skill_categories,
  education, an intelligence summary and project intelligence) with no confirm step and
  no redaction pass. DECISIONS.md principle 14 requires both; it is scheduled with the
  fact gate (Phase 4, `docs/ROADMAP.md`).

## The architectural rule

The model marks facts; the code scores and applies caps. A rule the candidate can lose
a good job to belongs in code, where it is deterministic and testable; the prompt
keeps it only as an explanation. Do not move scoring decisions into prompts. If a
judgement needs the model, have it return a fact, and let `scorer.py` decide what the
fact costs. Scoring specifics: `.claude/rules/scoring.md`.

## Résumé content rule

A CV states only what the profile and the CV text state; no default for anything, a
part that cannot be read stays empty and warns. Specifics: `.claude/rules/resume.md`;
full text in `docs/ARCHITECTURE.md` (Rule details moved from CLAUDE.md).

## No hard-coded markets, no borrowed data

- The country to search comes from `--country`, else the candidate intelligence; with
  neither, discovery stops. No provider, script or UI has a default country.
- Target roles drive search terms only; seniority is read from the current role.
- Europe and the US are search locations only when relocation is `abroad` or `anywhere`;
  a job needing a visa the candidate lacks is capped by scoring, not removed.
- A missing profile, intelligence or scored-jobs file is an empty state; never fill it
  from `data/examples/` outside an explicit demo mode.
- The browser copy of the profile is the master (`localStorage`, mirrored to
  `data/profile/candidate-profile.json` on sync). Fix profile data in the profile form,
  not in the disk file.
