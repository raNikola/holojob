---
paths:
  - "python/llm/**"
  - "python/match_engine/**"
  - "python/job_scoring/**"
  - "python/job_import/**"
  - "python/cv_analysis/**"
  - "python/resume_generator/**"
  - "python/project_intelligence/**"
  - "scripts/run-ai.js"
  - "scripts/ai-*.js"
  - "scripts/run-ad-fill.js"
  - "scripts/run-cv-analyze.js"
  - "scripts/run-tailor.js"
  - "scripts/run-project-scan.js"
  - "tests/python/test_engine_privacy.py"
  - "tests/python/test_ad_ai.py"
  - "tests/js/aiRedaction.test.js"
---

# Privacy inventory: what each model-calling step sends

The always-on privacy rules are in CLAUDE.md; this is the per-feature inventory they refer to. Moved verbatim from CLAUDE.md.


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
  name, contacts, links. Runs only in a judged scoring run with `HOLOJOB_ENGINE_SHADOW` on
  (shadow mode, `match_engine/shadow.py`); the judge's confirm dialog then lists it.
  `tests/python/test_engine_privacy.py` checks all of these at `requests.post`.
- **Fill from ad, AI step** (Add job form, `python/job_import/ad_ai.py`, `POST /api/jobs/ad/ai-preview` / `ai-extract`): sends **no candidate data**. It sends the text of one
  job page the server itself fetched (held in the Node process behind a token, never taken from the browser), with the owner's name, every e-mail address, phone number and link
  removed by `redact.py` (the profile's name and links read server-side; a final check fails closed if anything of the owner's is left), plus a fixed instruction naming only the
  fields still empty after the no-AI step. Never sent: Notes, extra links, Source URL, the profile, the CV, anything the browser posts besides the token and field names. It
  runs only on the Claude Code subscription: the gate must classify the call `subscription` (feature `job-import` in `claudeCodeSubscription.features`, which the owner adds with the checkbox in
  Settings > AI budget (it needs the usual confirm; no code adds it), else it is refused with that hint and the manual form stays. `ai-preview` calls no model and returns exactly the text and the gate's
  answer; `ai-extract` needs `"confirm": true` (409 without). Code accepts a value only if the text shows it (pay must read as EUR per month; a description is cut from the text
  between two quoted snippets, cut from the original page text so the stored ad has no placeholders), so nothing is invented. Pay ranges are protected from the phone-number redaction so the AI can see them. `tests/python/test_ad_ai.py`, `tests/js/adFill.test.js`.
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
- **AI findings store** (`scripts/ai-findings-store.js`, features `jobAnalysis` and `companyIntelligence`): keeps the parsed answer,
  the cache key and the input hash under `data/ai/findings/<job|company>/` (700 / 600, git-ignored), looked up before the budget gate;
  nothing leaves the server. Never stored: the prompt, keys, base URLs, an answer in which `ai-redact.js` (`findLeaks`) still finds an identifier. Details in
  `docs/redesign/STEP5_SERVER_MASTER_PLAN.md` section 2.8.
- **Profile import** (`python/profile_import`, `scripts/run-profile-import.js`, Wave 7): no model, no network, no gate; a static test keeps it so. Failures answer with a fixed code only (no text, no file name); `/api/profile/import/impact` is read-only and answers counts and profile versions. The import backup (`/api/profile/backup`) is a local file under `data/backups`.
- **LLM tailoring** (`resume_generator/llm_tailor.py`, Claude Code CLI) sends parsed CV sections (about_me, experience, skill_categories,
  education), an intelligence summary and project intelligence, and the ad. Every text is redacted first (`redact.py` with the name and links the parser
  read), then a final check (`redact.find_leaks`) fails closed: if anything of the candidate's is left, nothing is sent. A draft that copies a
  placeholder (`[NAME]`, `[EMAIL]`, ...) is rejected. **Confirm:** `/api/tailor/run` and `/api/tailor/stream` answer 409 `confirm_required` without `"confirm": true` (except `noLlm: true`, rule-based, sends nothing); `/api/tailor/preview` (`run_tailor.py --preview`) returns the exact redacted prompt per job and the AI gate's answer and calls no model; `generate_llm_content` itself sends nothing without `confirmed=True`, and the CLI needs `--confirm`. The dialog is `TailorConfirmDialog.jsx` (single job, bulk). The pipeline's tailoring step is rule-based (`noLlm`). `tests/js/tailorRoutes.test.js`, `tests/python/test_llm_tailor.py`.
- **Project scan** (`claude_code.analyze_repo`): read-only tools in the repo; `git log` and `git shortlog` are not allowed, because they print commit
  authors. `git show` can still print an author line (remaining risk).
- **Provider error text** (`claude_code.safe_error`): output the provider returns inside an error string is cut to 200 characters with e-mails, phones and
  links removed before it reaches an error, the ledger or `llmIssues`.
