# Holojob — working notes

Personal job-hunt pipeline in Podman on a home server (DS9). Single user (DECISIONS.md principle 15): a senior/technical product manager in Niš, Serbia, no relocation, remote or near-remote work. Read `docs/redesign/DECISIONS.md` before any redesign work. Codebase map: skill `holojob-architecture`.

## Always

- Work only inside /srv/holojob. Do not read other projects under /srv (applypack, jobapply).
- Never print secret values (passwords, keys, tokens) from any file; refer to them by name only. Do not read `data/secrets/`.
- Never `cat`, dump, grep out or print values from the owner's private files under `data/` (profile, intelligence incl. `atsKeywordBank`, CVs, resumes, applications, `data/cache`), not even filtered or truncated: tool output goes to the model provider. Use `.venv/bin/python scripts/inspect-private-data.py FILE` (shape, counts, hashes). Analysis scripts print counts, ids and public ad titles only.
- Personal data never leaves the home server. Push only to `origin` (`git@github.com:raNikola/holojob.git`). `scripts/git-hooks/pre-push` refuses any other remote. Everything under `data/` except tracked examples, `.env`, CVs and keys stays in `.gitignore`.
- **Never push, merge or deploy without the owner's explicit approval.** Never `git push --no-verify`.
- The owner runs commands (builds, deploys, `--apply` scripts). Propose them; do not assume they ran. A `.env` change needs `podman-compose up -d --force-recreate`.
- Never bypass a failing test, or change production data to make one pass.
- **Tests must never touch the real `data/` directory:** no test reads, writes, moves or removes a path under `/srv/holojob/data`, and mocking one `fs` call is not a way to prevent a write. Use a temp directory. Guards that detect a change exist (Vitest `tests/js/setup/realDataGuard.js`, pytest `tests/python/real_data_guard.py`); history and limits: `docs/DECISIONS.md`, "Incident 2026-11-09".
- All code and comments in English.
- After finishing a feature, update `docs/ROADMAP.md` and `docs/DECISIONS.md` (mark what is built, record decisions).
- Never read `docs/DECISIONS.md`, `docs/redesign/data-shapes.md` or `docs/ROADMAP.md` whole: grep for the heading, then read with offset and limit.
- New files in private data folders: mode 600, directories 700, via the helpers (`.claude/rules/private-file-modes.md`).

## Privacy (applies to every task)

- Any new model call goes through the budget gate (`python/llm/ai_gate.py`; Node `scripts/ai-gate.js`), never a provider directly.
- Candidate data sent to a provider needs an explicit confirm and a `redact.py` / `ai-redact.js` pass (name, e-mails, phones, links removed); fail closed. Never send name, email, phone, salary, links, preferred locations, raw resume text, questionnaire answers, recruiter/contact data, notes.
- Add a field to `_candidate_digest` or any outgoing payload only deliberately, and update the inventory in `.claude/rules/privacy-inventory.md` (what each step sends, known gap: the browser AI features have no confirm yet).
- Manual-job `notes`, `extraLinks`, `sourceUrl` are owner-only: in no payload, file, log or AI context.

## Architecture rule

The model marks facts; the code scores and applies caps. Never move a scoring decision into a prompt (`.claude/rules/scoring.md`).

## Workflow sizes (owner decision 2026-11-08)

The owner decides product behavior; Code decides the technical approach.

- **S (columns, UI fixes):** implement, test, commit.
- **M (role scoring, filters, ad statuses):** short self-directed analysis, implement, test, commit. No separate analysis round.
- **L (discovery pipeline, importer, migrations, AI scoring architecture):** Plan Mode, one approval, then autonomous implementation. Stop only for a blocking product decision or significant risk; one final report.
- Skills and plugins must not add ceremony to S and M tasks.

## UI

- `docs/design-system` has priority over any UI plugin guidance (UI UX Pro Max).
- Never use external image-generation or logo / icon services from plugins: they send prompts off the server.

## Testing and commit policy (owner decision 2026-11-04; an explicit testing requirement in a task overrides it)

- **While developing:** only targeted tests for the changed code, plus the relevant lint. Mutation tests only for changed logic, when needed.
- **Before each commit:** those targeted tests and relevant lint pass. Do not run the full suite just to commit.
- **Before a push or merge, once, when the feature is complete:** full pytest, full Vitest, JS lint, production build, mutation checks, required integration tests, `data/` fingerprint check. The pre-push hook runs lint, JS tests, pytest and build; the rest by hand. If the gate fails: fix, rerun the failed checks; rerun everything only if later changes could affect verified areas.

## Test commands

`node` and `npm` are not on the host PATH: lint, vitest and build run in a throwaway node container (always `--security-opt label=disable`, never `:Z`, which relabels the repo). pytest runs on the host `.venv` (Python 3.12), never in the image.

    podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm npm run lint
    podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm npm run test:js
    podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm npm run build
    .venv/bin/python -m pytest tests/python -q            # add -m "not network" to run offline

`npm test` / `npm run test:python` work on neither side. Details (venv setup, pre-push hook, network tests): `docs/ARCHITECTURE.md` "Tests and pre-push hook".

## graphify

Knowledge graph in `graphify-out/` (git-ignored, never committed).

- Use the adapter views in `graphify-out/holojob/`, not the default graph (if missing, build them as in the last rule). Before the first grep, search or source read for a codebase/architecture question: `graphify query "<question>" --graph graphify-out/holojob/architecture.json`; for impact and related tests: `graphify affected "<file>" --graph graphify-out/holojob/test-deps.json`; `graphify path "<A>" "<B>"` and `graphify explain "<concept>"` with the same `--graph`. Original `graphify-out/graph.json` only to verify raw data. Put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read located.
- If `graphify-out/wiki/index.md` exists, use it for broad navigation. Read `GRAPH_REPORT.md` only for broad architecture review or when query/path/explain fall short.
- After modifying code: `graphify update .`, then `.venv/bin/python tools/graphify_adapter/adapter.py build`.

## Where the rest lives

Docs (read on demand): `docs/ARCHITECTURE.md` (pipeline, scoring, container gotchas, tests/hook detail, open problems), `docs/ROADMAP.md` (phases, Phase 1 criteria), `docs/redesign/DECISIONS.md` (principles), `docs/DECISIONS.md` (later decisions), `docs/redesign/ENGINE_CONTRACT.md`, `docs/redesign/data-shapes.md`, `docs/GLOSSARY.md`.

Area rules in `.claude/rules/` load when matching files are touched: `scoring`, `resume` (CV, tailoring, CV analysis), `frontend`, `settings-screen`, `job-details`, `manual-jobs` (incl. Fill from ad), `request-guard` (`/api`, no-login decision, bind), `secret-store`, `ai-gate-and-selection`, `privacy-inventory`, `markets-and-data-source`, `container` (builds, fast deploy, `.env`), `private-file-modes`.
