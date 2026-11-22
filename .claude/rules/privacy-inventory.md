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


Personal data stays on the server. Four steps send candidate data to the configured
provider, each behind an explicit confirm (CV analysis, fit judge, evidence matcher, LLM tailoring); the browser AI features send redacted text with no confirm yet (Step 6).

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
  name, contacts, links. `languagesVersion` and `languageSettled` (a hash of the language list and requirement ids) are stored in the local cache entry only, never in the request; a changed list marks a cached answer stale locally (`staleReason`), and nothing is re-sent. Runs only in a judged scoring run with `HOLOJOB_ENGINE_SHADOW` on
  (shadow mode, `match_engine/shadow.py`); the judge's confirm dialog then lists it.
  `tests/python/test_engine_privacy.py` checks all of these at `requests.post`.
  `scripts/measure_holdout_matcher.py` is one more caller of `calibration/engine_sample.py` (same payload, same scan, same gate and confirm), pointed at a scratch data dir; it sends nothing without `--confirm` and `--max-usd`.
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
- **Project scan** (`claude_code.analyze_repo`): the model may use only `Read`, `Grep`, `Glob`, `LS`, `ls` and `wc` inside the repo. No `git` command
  (log, shortlog, show and `branch --format` print commit authors' names and e-mails), no `cat` or `find`; `Read(.git/**)` is denied as a second
  line. The commit count, dates and file count are computed by code (`git_stats`) and given in the prompt. `tests/python/test_project_scan_privacy.py`
  lists the allowed commands. The deny rule is the CLI's own and is not exercised by a test (that would be a paid call).
- **Competency grouping** (`python/job_scoring/competency_grouping.py`, feature `competency-grouping`, a manual command that needs `--confirm`, default cap $0.10, not part of any pipeline run): sends requirement texts from job ads and the role family's competency list (id, definition). **No candidate data.** Answers are cached in `data/cache/competency-grouping.json` (600). The confirmed facts store, the evidence map, answers, notes, history and `overrules` are never sent.
- **Fit 3 classification** (`python/match_engine/fit3.py`, feature `fit3-classify`, owner-run `scripts/measure_fit3.py`, estimate first, needs `--max-usd` and `--confirm`, never part of a scoring run): sends the job ad (title, description; the reply quotes the title and the ad) plus the closed lists (role names from `fit3_roles.json`, competency ids and definitions from `src/data/competencies/`). **No candidate data.** The reply is stored raw (ad quotes only) in the scratch dir or `data/cache/fit3.json` (600); code anchors it on read. The competency rows it produces reach the candidate only through the existing evidence matcher entry above (same confirm, redaction and gate); shadow mode reads stored answers and calls nothing for Fit 3. The candidate's seniority level and industries (read from the intelligence in `run_scoring`) are used locally for the seniority distance and the domain signal and are never sent; `merge_fit3_answers.py` and `check_fit3_bars.py` are offline and call nothing.
- **Embedding experiment** (`llm_client.embed()`, feature `embedding-experiment`, owner-run `scripts/measure_embedding_signal.py embed`, estimate first, needs `--max-usd` and `--confirm`, never part of any pipeline run; W5 step 4): sends the cleaned public text (title and HTML-stripped description) of the owner's LABELLED ads and of the applications' ad snapshots, as a list of strings and nothing else (`embed()` refuses any other shape before the gate). **No candidate data, no company, label, rating or application field.** Vectors stay in the scratch dir (600), never committed; an input over 16000 characters is truncated and counted.
- **Experiment B** (`python/calibration/fit_b.py`, feature `fit-b-experiment`, owner-run `scripts/measure_fit_b.py run`, estimate first, needs `--max-usd` and `--confirm`, never part of any pipeline run; exception in `scoring.md`): per ad sends the public ad text (title and HTML-stripped description, at most 16000 characters, redacted by `redact.py`) and a candidate summary at the plan's scope (current role, seniority, years, CV summary, experience titles / periods / bullets without employer names or locations, skills, certifications; P-full adds the owner-confirmed domains and capabilities of `historyEntries`). Redacted with the profile's identity, `find_leaks` fails closed when building the summary, and `owner_leaks` scans every outgoing request at estimate time and again at call time. **Never sent:** name, e-mail, phone, links, locations, salary, languages, target roles, work authorization, company, education institutions, confirmed facts or notes, labels, applications, notes. Ratings stay in the scratch dir (600). `tests/python/test_fit_b.py`.
- **Profile enrichment** (`data/profile-enrichment.json`, owner text with source tags, no contact data): its entries become evidence items, so they reach the provider inside the evidence matcher payload (same confirm, `redact.py` passes, owner-identifier scan and gate as above; employer names are part of role evidence there already). In the Experiment B P-full summary only, employer names are masked as "[employer]". Never sent: the `employers` list itself, the source tags, the ids.
- **Ad contact masking** (owner 2026-11-19): in an evidence-matcher request, e-mail addresses and phone numbers in the AD text become [EMAIL] / [PHONE] (`redact.mask_ad_contacts`, in `matcher.build_prompt`); the count is printed by `engine_missing.py`. The owner-identifier scan still runs on the masked prompt (its generic phone check reads digit runs by shape: see Engine fill). North American numbers are masked too. `tests/python/test_ad_contact_mask.py`, `tests/python/test_scan_ad_digits.py`.
- **Engine fill** (`python/job_scoring/engine_missing.py`, owner-run, estimate first, `--max-usd` and `--confirm`): the same payload as the evidence matcher entry above, for the ads without a current answer; the privacy scan masks only the evidence ids that read as a phone number, and an ad that still hits the scan is not sent. The scan's generic phone check reads an ad's digit runs by shape and context (`redact._phone_in_ad`, DECISIONS 2026-11-21: requisition numbers, dates, pay ranges and amounts are not phones); the owner's own e-mail, phone and name are checked unchanged. A third party's phone number in an ad is masked as `[PHONE]` and the ad is sent; an ad whose raw text carries the owner's own phone, e-mail, name or links is refused (`prelabel.owner_in_text`, `estimate`).
- **Provider error text** (`claude_code.safe_error`): output the provider returns inside an error string is cut to 200 characters with e-mails, phones and
  links removed before it reaches an error, the ledger or `llmIssues`.
