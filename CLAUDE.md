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
- **Builds:** dependencies are layered before code, so a code-only `podman-compose build` takes about 10 s; pip and the
  Playwright browsers rerun only when `requirements.txt` or `scripts/setup-job-discovery.sh` changes. `.dockerignore`
  allows only `data/examples` from `data/`. Never remove those lines.
- **Fast deploy (fish), lost on recreate unless the image is rebuilt:** frontend: build `dist` in a throwaway
  `node:20-bookworm` container (`--security-opt label=disable`), `podman exec career-os rm -rf /app/dist`,
  `podman cp dist career-os:/app/dist`. Python: `tar --exclude=__pycache__ -C python -cf - . | podman cp - career-os:/app/python`.
  Node `scripts/` or `src/`: the same with tar, then `podman restart career-os`. Exact commands in `docs/ARCHITECTURE.md`.

Detail: `docs/ARCHITECTURE.md` (Container gotchas).

## Tests

Against the host `.venv` (Python 3.12: `uv venv -p 3.12 .venv`, `uv pip install -r requirements.txt`), never inside the image:

    npm run test:python        # or: .venv/bin/python -m pytest
    npm test                   # vitest, then the same pytest run

`pytest.ini` limits collection to `tests/python`. Two `network` tests hit live
Infostud and Workable and skip when unreachable; `-m "not network"` runs offline.
Do not build `.venv` with Python 3.15 (pinned pandas 2.3.3 has no wheel).

## Privacy rules and exceptions

Personal data stays on the server. Three steps send candidate data to the configured
provider, each behind an explicit confirm; the browser AI features send redacted text with no confirm yet; LLM tailoring is a known gap.

- **CV analysis** sends the text of one CV with name, e-mails, phones and links replaced
  by placeholders (`redact.py`), only after the confirm dialog has shown that exact text
  and the provider; `/api/ai/cv-analyze` refuses a body without `"confirm": true`.
- **Fit judge**, only with `--judge` (hand-entered jobs are judged like any other ad: the pasted ad text, never their notes or links): sends the ad plus a digest of
  `candidate-intelligence.json` (seniority, years, target roles, spoken languages,
  career narrative, skills, domains, project / ownership / leadership / impact examples,
  strengths, known gaps). Every line but the language list goes through `redact.py`
  with the profile's name and links first. Never sent: name, email, phone, salary,
  links, preferred locations, raw resume text, questionnaire answers. Add a field to `_candidate_digest`
  only deliberately, and update this list.
- **Evidence matcher** (`python/match_engine/matcher.py`), only under the same `--judge`
  confirmation (`match_posting` refuses without `confirmed=True`): sends the ad, its
  requirements, and the evidence index items (id, source, role, start, end, text), built
  from the profile and intelligence and passed through `redact.py` twice (building
  the index, and again in the matcher), each time with the profile's name and links. Never sent: gates
  (work authorization, locations, languages, salary), confirmed facts or their notes,
  name, contacts, links. Runs only in a judged scoring run with `CAREER_OS_ENGINE_SHADOW` on
  (shadow mode, `match_engine/shadow.py`); the judge's confirm dialog then lists it.
  `tests/python/test_engine_privacy.py` checks all of these at `requests.post`.
- **Browser AI features** (`scripts/run-ai.js`, the `/api/ai/*` routes: job analysis, cover letter, interview
  prep, outreach, company intelligence, career strategy, skill gap, application strategy, resume enhancement,
  chat): send the ad text, the job's scores and stage, and a profile summary (current role, target roles,
  locations, skills, years). Never sent: owner name, e-mail, phone, links; recruiter / contact names, e-mails,
  LinkedIn links, notes and activity text, and from the application tracker the CV used, file names and event history (only
  stage and dates are passed, `safeTracking` in `aiContextBuilder.js`; a typed stage label is never passed, TRACKER_PLAN 3.4) (left out where the context is built, `aiContextBuilder.js`; the
  outreach contact's name is the placeholder `[CONTACT NAME]`). One central step, `scripts/ai-redact.js`, runs
  on every context before the prompt is built and before the budget gate: it removes the owner's and the known
  contacts' identifiers (profile mirror, `redactionHints` from the browser, and every contact recorded in the
  application store, read server-side), every e-mail address (a company's
  too), phone-like numbers and profile-site links (LinkedIn, GitHub, ...); company sites stay. It fails closed:
  if it cannot run, or a final check still finds an identifier, the call is refused and logged
  (`ai_gate.py refuse`). No confirm dialog yet for these features (principle 14 asks for one).
  `tests/js/aiRedaction.test.js` checks each feature at the provider.
- **AI findings store** (`scripts/ai-findings-store.js`, first slice: `jobAnalysis` only): keeps the parsed answer and the redacted
  prompt under `data/ai/findings/job/` (700 / 600, git-ignored), looked up before the budget gate; nothing leaves the server. Never
  stored: keys, base URLs, an answer in which `ai-redact.js` (`findLeaks`) still finds an identifier. Details in
  `docs/redesign/STEP5_SERVER_MASTER_PLAN.md` section 2.8.
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

## Settings screen

`SettingsHome.jsx` is a shell: a left navigation (a `<select>` on mobile) over eight categories (Job search, Sources,
Applications, AI & costs, Privacy & security, Data & backups, General, Danger zone), a search box that only opens a
section, and every category kept mounted (hidden with CSS) so drafts survive switching. The map is
`src/modules/settings/settingsRegistry.js`; a new setting adds a section there and an entry in `RENDERERS`
(`tests/js/settingsRegistry.test.js` checks both), never a top-level card. Text that points to a section uses
`openSettings(sectionId)` / `SettingsLink`. Section titles stay verbatim (for example "AI budget", "Privacy: secrets and
keys"). Plan and as-built note: `docs/redesign/SETTINGS_PLAN.md`.

## Job Details page

The drawer (`JobDetailDrawer.jsx`) stays the quick view on the Jobs list, Board, Statistics and Outreach. Its "Open full details" button
goes to `#/jobs/<jobId>` (`JobDetailsPage.jsx`): the drawer body (`JobDetailBody.jsx`) in the main column and `ApplicationTrackerPanel` as a
sticky sidebar. There is no router: `modules/jobs/jobRoute.js` pushes the hash, `useJobRoute` (in `App.jsx`) reads it, so the hash wins over the saved
view on load and Back returns to the previous view. The page and the drawer read the stored record and write through the jobs store (`modules/jobs/jobsStore.js`): `patchJob(jobId, patch)`
reads the latest stored record at write time and applies only the given fields (`useJobPatcher` diffs what a component hands back against the copy it
rendered), so a stale copy cannot revert another view's change; `baseUpdatedAt` gives a `conflict` result instead of an overwrite, the shape for a
later server store. `useJobs` / `useStoredJob` re-render after any write, a `storage` event covers other tabs, and `useJobsSync` lets the Jobs,
Applications and Outreach screens take store writes in. **Still whole-object / whole-list:** those three screens save their whole list from memory
(`saveJobs(state)` effects), and their own handlers (`handleJobUpdated` for the table's `JobTailorActions`, `ContactDetailDrawer`, `FollowUpPanel`,
`RelatedContactsPanel` in the contact drawer, and `updateJobOutreach` / `updateJobStatus` on in-memory state) still merge whole objects. Step 2 moves them to the store.
Across tabs, `useBackgroundRefresh` (`App.jsx`) refetches the tracker cache and re-reads the job list when the tab becomes visible or focused and every 60 s while visible (`modules/applications/refreshPolicy.js`); an edited tracker field that changed elsewhere keeps the typed value and shows "Reload fields".
The drawer's tracking block is a read-only summary (`ApplicationTrackingSummary.jsx`, values from `modules/applications/trackingSummary.js`, the same application cache and `panelMode` as the page): stage badge, applied on, next follow-up, CV used, recruiter, history and note counts, empty fields as "Not recorded" / "Not scheduled". With no active application it offers "Mark Applied", which calls `markApplied` with `newApplicationDefaults` (today, the form's preselected CV, channel `company_site`; the full form starts from the same function) and has no separate-attempt choice, so a 409 points to Job Details. All tracking edits stay on the page. "Open full details" is disabled (tooltip "This posting is no longer in your jobs list") when the stored list lacks the job (`canOpenJobPage`). An unknown id shows "Job not found". Unsaved input: forms that call `useDraftDirty` (the tracker's three forms) make the button ask first
(`modules/jobs/draftGuard.js`); other drafts (AI tools, contacts) are not covered yet. Not built: more tabs, AI spent, "Is it real?".

## Manual jobs

"Add job" on the Jobs screen (`AddJobDialog.jsx`, helpers in `modules/jobs/manualJob.js`, flow in `modules/jobs/manualScoring.js`): `manualEntry: true`,
`provider: 'manual'`, status `new` (shown "Unreviewed"). The server is the master for the scored fields: `POST /api/jobs/manual/score`
(`scripts/run-manual-job.js`) runs `python/job_import/import_job_url.py --job-json -` (payload on stdin; no fetch, no model, no network), which stores the job in
`data/jobs/manual_jobs.json` (`python/job_scoring/manual_jobs.py`; discovery never writes it), scores it with the same `score_jobs()` over the same corpus a full run
uses and merges it into `scored_jobs.json`. `run_scoring.py` adds the manual file to every run (so Re-score, Re-scrape and the full pipeline keep the jobs; a manual
row wins over a discovered row with the same normalised URL, and `--min-score` never drops one). Scoring failure leaves the job Unreviewed with a "Score now" retry
(details page, and the note after saving); retry is idempotent. `runScoring` / `runFullPipeline` / `runJudgedScoring` first send the browser's manual jobs to
`/api/jobs/manual/sync`. Manual jobs get no enrichment (`aiEnrichment: "missing"`), and a `--judge` run includes them like any other ad (the ad text only).
Duplicates: same normalised URL (`normalizeJobUrl` / `normalize_url`, one fixture `tests/fixtures/url-normalisation.json` run by both) against this browser's list, the
discovered file, the scored file and the manual file; a different id is a clash, the same id is a retry.
`notes` and `extraLinks` are owner-only: they stay in the browser's job record (carried over by `importJobsFromFile`) and are in no payload to Python, file, log line or
AI context (`SCORING_FIELDS` is the whitelist on both sides; `summarizeJob` is a whitelist too; `tests/js/manualScoring.test.js`, `tests/python/test_manual_jobs.py`).
Add any new owner-only field to `MANUAL_FIELDS` and to those tests.

## Request guard (`/api`)

Every `/api` request passes `scripts/request-guard.js` first (`handleApiRoutes` in `api-handler.js`, used by the
production server and the Vite dev middleware): POST / PUT / PATCH need `Content-Type: application/json` (a DELETE only
when it has a body); the two binary uploads take their own type (`POST /api/cvs` PDF, `POST /api/backup/import` zip);
an `Origin` header must be an allowed origin; wrong type 415, wrong origin or host 403. It is not authentication.

- **Setting:** `CAREER_OS_ALLOWED_ORIGINS` in `.env`, comma separated, scheme optional and ignored, for example
  `https://careeros.void,http://localhost:3073`. With a list, the Origin AND the request's Host (or the proxy's
  `X-Forwarded-Host`) must be on it, which also stops DNS rebinding; reaching the app by another name (a LAN IP) then
  gets 403 until that name is added. With no list, an Origin must equal the request Host (same origin) and Host is not checked.
  A `.env` change needs `podman-compose up -d --force-recreate`.
- Credentials are masked in error bodies, SSE errors, ledger reasons and console output by `scripts/secret-mask.js`
  (`sk-`/`AIza` keys, `key=` / `token=` query values, Authorization, `li_at`, long tokens). Backup export and restore use
  one exclusion list, `scripts/secret-paths.js`; a restore with `..` or an absolute path in the archive is refused whole.
- **No login (owner-accepted, DECISIONS.md 2026-10-29):** no application login and no Caddy `basic_auth`; access is the home LAN, and
  remote access only through Tailscale. Add the Tailscale hostname to `CAREER_OS_ALLOWED_ORIGINS` if it is used. Revisit if the app is
  ever exposed outside the LAN or Tailscale.
- **Bind:** `docker-compose.yml` publishes `127.0.0.1:3073:5173`, loopback only; other devices go through the reverse
  proxy (Caddy `careeros.void` -> `127.0.0.1:3073`). `tests/js/composePorts.test.js` fails if a port is published on all
  interfaces. Inside the container the app still listens on 0.0.0.0:5173, as podman's forwarding needs.
- Plan, approved decisions and step order (1 network / API protection, 2 AI keys, 3 `li_at`,
  4 AI settings, 5 profile / intelligence / jobs migration, 6 browser AI confirm dialog), with the pre-migration
  checklist: `docs/redesign/BROWSER_STORAGE_POLICY.md`. Browser keys outside its allowlist are not added.

## Secret store (AI keys)

`scripts/secret-store.js` is the only code that writes `data/secrets/` and the only Node reader; Python reads `ai.json` read-only through
`python/llm/secret_store.py` (directory 700, files 600, atomic writes,
never logged). `data/secrets/ai.json` holds `{ provider: { key, baseUrl, setAt } }` for openai, openrouter, claude and gemini.
Routes: `GET /api/secrets` (set / not set, source, last 4 characters, base URL), `PUT` / `DELETE /api/secrets/ai/<provider>`
(`scripts/secrets-handler.js`); no route returns a key, and errors never quote the request. Settings > Privacy: secrets and keys
sets, replaces and removes a key, and moves the one an older build left in the browser (cleared only after the server confirms
the same last 4 characters).

- `run-ai.js` calls `resolveAiSettings()` once per call. A keyed provider takes its key **and base URL** from the store, then
  `.env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` only); an `apiKey` or `baseUrl` in a request is ignored, so there is no fallback
  to a key from the browser. No key answers "No API key configured" and makes no call. `claude-code`, `mock` and `ollama` need no key.
- A custom base URL (a proxy, openrouter) is entered with the key in Settings; the key is sent only there.
- The stored values and the `.env` keys are masked by exact value in every error, SSE event, gate record and console line
  (`secret-mask.js`); the patterns remain a second layer. Tests point the store at a temp dir (`CAREER_OS_SECRETS_DIR`, set in
  `vitest.config.js`) and never read the real one.
- The LinkedIn cookie is `data/secrets/linkedin.json` (`{ li_at, setAt }`), `PUT` / `DELETE /api/secrets/linkedin`, then `LINKEDIN_LI_AT`
  from `.env`. `POST /api/outreach/discover` ignores any cookie in the body. The scraper gets it only in the child's environment in deep
  mode (`--li-at` no longer exists; search mode strips it), and its text is masked. `data/outreach/linkedin_session.json` is no longer read.
- **Python reads the store too** (`python/llm/secret_store.py`, read-only; not named `secrets.py`, which would shadow the standard library). For the
  selected provider only (`openai`, `openrouter`), the key and pinned base URL come from the store; `.env` (`OPENAI_API_KEY`, ...) applies only when
  the store has no key for that provider. The intended setup is store only, so `.env` keys can be removed. A store file that is not private (group or
  other access, symlink, bad JSON) refuses the call, with no `.env` fallback; a missing key refuses before the gate (logged, ledger row), and no other
  provider is tried. A stored key goes only to its pinned URL or the provider's own address (`*_BASE_URL` does not redirect it). The exact key is masked
  in errors, log lines and ledger rows (`secret_store.mask`). Check without a call: `podman exec career-os python python/llm/secret_store.py status openai`.

## AI budget gate

Every real model call goes through `python/llm/ai_gate.py` before it is made (Python:
`llm_client.complete_json`, `claude_code._run`; Node: `scripts/ai-gate.js` from
`run-ai.js`). A new call site uses one of those, never a provider directly. Budget,
limits and the automation switch are in `data/ai/settings.json` (missing = budget 0,
automation off); the append-only ledger is `data/ai/usage-ledger.jsonl`; prices and
free / local / paid classes are in `src/data/aiPricing.json` (unknown = paid). Usage:
`GET /api/ai/usage`.

Settings screen > AI budget edits these through `PUT /api/ai/settings` and
`PUT /api/ai/pricing` (`scripts/ai-settings-handler.js`; validation and the atomic write
are in `ai_gate.py`). Raising what the gate allows (higher limit, removed call cap,
automation on, a looser price) needs `"confirm": true`, else 409 with the list. Price
edits are overrides in `data/ai/pricing-overrides.json`, merged over `aiPricing.json`;
free or priced needs a source note. No route writes or deletes ledger rows.

**Claude Code on a flat subscription** (`claudeCodeSubscription` in `data/ai/settings.json`, default off, owner decision 2026-10-29): when
enabled, a call by provider `claude-code` for an allowlisted feature (default only `jobAnalysis`) gets class `subscription`: cost 0, not
counted against the budget, written to the ledger, and limited by `maxCallsDaily` (default 5, in the settings timezone). Every other
`claude-code` feature (tailoring, job import, project scan, ...) and every other provider keep their class and stay refused at budget 0.
Turning it on, raising the cap or adding a feature needs `confirm: true`. A findings hit never reaches the gate, so it does not count.
The prompts still leave the machine for Anthropic (redacted). Rule: `python/llm/ai_gate.py` (`_call_row`, `_decide`).

## AI provider selection

One file, `data/config/ai-settings.json` (git-ignored, not in backups), holds the provider, model, temperature, max tokens, the ollama
base URL and the nine feature toggles; never a key. `python/llm/ai_selection.py` validates (unknown keys rejected, bounded numbers, fixed
provider list) and writes it atomically. `GET` / `PUT /api/ai/selection` (`ai-settings-handler.js`) go through the gate CLI
(`ai_gate.py selection-get` / `selection-put`), so the Node server and `llm_client.active_provider()` read the same file. Selecting a paid or
unknown-class provider (a change of provider, model or base URL) needs `"confirm": true`, else 409.

- **There is no default.** Nothing selected, an unreadable file, or a provider that side cannot run (`claude`, `gemini`, `mock` in Python;
  `deepseek`, `groq` in Node) refuses the call, logs it and writes a ledger refusal. No env key, `CAREER_OS_LLM_PROVIDER` or CLI fallback picks one.
  `run-ai.js` does not read a provider, model or limit from the request.
- Not covered: the features hard-wired to the Claude Code CLI (`llm_tailor.py`, job import, project scan) still call it directly through the gate.
- The browser holds no AI setting; an older `job-dashboard-ai-settings` is moved once from Settings > AI Provider (read back from the server before it is removed).

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
- The server is the master for profile, intelligence, jobs and applications (DECISIONS.md, 2026-10-29); the browser
  keeps UI state only (`docs/redesign/BROWSER_STORAGE_POLICY.md`). **Until migration step 5 ships**, the profile,
  intelligence and jobs still live in `localStorage` and are mirrored to `data/` on sync, so fix profile data in the
  profile form, not in the disk file. After it, the browser copy is removed per key, only after a preview, an owner
  confirmation and a verified server write. No secret (AI key, `li_at`) is stored in or sent from the browser once
  steps 2-3 ship; the server's `data/secrets/` (600 / 700) is the only holder. **Steps 2 (AI keys) and 3 (`li_at`) shipped.**
