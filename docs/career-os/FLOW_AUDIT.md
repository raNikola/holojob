# Career OS: flow and architecture audit

> **Historical.** Written for Career OS before the Holojob redesign; kept for its list of known problems. Current plans are in [../ROADMAP.md](../ROADMAP.md).

Written 2026-10-24, after the My CVs library (`6692378`), CV analysis (`6692378`) and
the review fixes (`0a27cf5`). It maps what the code does today, traced through the code
and not from the docs, and lists the problems found. Nothing in it has been fixed yet; it
is parked as a to-do list. Where something was inferred and not read in the code, the text
says so.

---

## Part 1: The flow, stage by stage

### Stage 0: where the data lives

Three copies of the truth exist:

- **Browser `localStorage`** holds `profile` (including `cvLibrary`, the questionnaire
  answers and `parsedData`), the intelligence, and the jobs state (job status, application
  tracking, tailored-asset pointers). The browser copy is the master.
- **`data/profile/candidate-profile.json`** and **`data/intelligence/candidate-intelligence.json`**
  are disk mirrors that Python reads. They are only written when something syncs them.
- **`data/jobs/*.json`** is pipeline output, and **`data/resumes/<jobId>/`** holds tailored files.
  **`data/profile/cvs/<id>.pdf`** holds the uploaded CV files.

### Stage 1: CV upload

There are two separate entry points, and they behave differently.

| | Edit Profile → "Upload resume" (`ResumeUpload.jsx`) | My CVs → "Upload new CV" (`CvLibrary.jsx`) |
|---|---|---|
| Text | pdfjs in the browser (`extractTextFromPdf`) | same |
| PDF stored | yes, `POST /api/cvs` → `data/profile/cvs/<id>.pdf` (best effort) | yes, required (fails if the API is down) |
| Becomes the active CV | **yes**, immediately | no, added as a non-default entry |
| Extraction | `applyResumeExtraction` (regex) writes `basicProfile`, `parsedData` and the GitHub link, then re-seeds Q2 and Q5 if they have fewer than 2 entries | `extractProfileFromResume(...).parsedData` goes into the entry only |
| Touches `profile.resume` | yes | no, until "Set as default" |
| Library entry | added as default | added as non-default |

Two more details:

- **LinkedIn-PDF mode** in Edit Profile goes through `/api/profile/import-linkedin` (Python
  heuristics) and also registers as a library entry.
- **"Set as default"** copies the entry's text and `parsedData` into `profile.resume`
  without re-running extraction. The outgoing default's form edits are written back into
  its entry first.

### Stage 2: CV analysis (My CVs → "Analyze with AI")

- **Call path:** the confirm dialog calls `/api/ai/cv-analyze`, which runs Python
  (`python/cv_analysis/run_cv_analyze.py`) through `llm_client` (the env provider,
  `gpt-6.1-sol` in the container) on the redacted text.
- **Check and storage:** the result is verified against the CV and stored on the library
  entry as `entry.analysis`. Nothing else changes.
- **Apply:** this works only for the default CV and writes the ticked items as follows:

| Field written | Who reads it |
|---|---|
| `parsedData.skills` | the intelligence generator (`skillsClassifier`), which feeds scoring, and tailoring |
| `parsedData.workExperience` (only new companies are appended) | the intelligence generator (`atsKeywordGenerator`, the narrative builder) and tailoring |
| `parsedData.education` and `certifications` | the intelligence generator and tailoring (education) |
| Questionnaire answers 4 and 17 | the intelligence generator (Q4 becomes `projectHighlights`), tailoring (Q17) |
| **`experienceDetail`, `competencyGroups`, `toolGroups`** | **nothing** (grep finds no consumer outside the CV code and the review UI) |

- **How applied changes reach scoring:** scoring reads only the intelligence file, never the
  profile. Applying a suggestion changes nothing in scoring until "Regenerate Intelligence"
  is pressed and the result is synced to disk. Nothing triggers that after Apply.

### Stage 3: Profile and Questionnaire

- **Editing:** `ProfileForm` edits `basicProfile` and the `parsedData` lists.
  `QuestionnaireForm` edits answers, plus the optional repo scan and the Q2/Q5 skill seeding.
- **Intelligence input:** `generateCandidateIntelligence` reads the whole profile through
  `normalizeProfile`. It requires full name, e-mail, at least one target role, resume text or
  skills, and **all 17 answers non-empty**. Otherwise it fails with a clear message.
- **What the profile and questionnaire become:**
  - **Skills:** `parsedData.skills` and answers 2 and 5 become `skillsMap` and `atsKeywordBank`.
  - **Experience:** `workExperience`, `projects` and answers 4 and 15 become `experienceMap` and the narrative.
  - **Preferences:** answers 1, 9-12 and the profile's location, salary, relocation, visa and
    language fields become `jobFitPreferences`.
- **Where it syncs to disk:** the profile is synced by the pipeline run, the Review step, the
  repo form and the tailor call. Intelligence is synced by Regenerate, Settings weights and
  the pipeline run.

### Stage 4: Discovery and scoring

What scoring actually reads:

- **Source:** only `candidate-intelligence.json`, never the profile or the CV.
- **Role match:** `roleStrategy.primary/secondary/avoid/searchRoleVariants`.
- **Skill match:** `atsKeywordBank` (high, medium, supporting), `skillsMap`, `resumeKeywords`,
  `candidateStrengths`, and `experienceMap.domainsWorkedIn/projectHighlights/ownershipExamples`.
- **Location match:** `jobFitPreferences.preferredLocations/remotePreference/relocation/country`.
- **Experience match:** `experienceMap.yearsOfExperience`, `candidateSummary.seniorityLevel`.
- **Industry and culture:** `preferredIndustries/avoidedIndustries`, and
  `culturePreference/preferredCompanyTypes/workToAvoid`.
- **Gating and display:** `workAuthorization` and `allowedLocations` cap scores. `minSalaryEur`
  is display only. `scoringWeights` set the weights.
- **Discovery input:** `searchStrategy` drives discovery.
- **Not used by scoring:** the raw CV text, `parsedData.education/certifications`, Q17,
  `competencyGroups`, `toolGroups`, `experienceDetail`.

### Stage 5: Applying to a job

- **What "Applied" does:** it is manual and stored only in the browser's jobs state. Ticking
  Applied in the job drawer sets `interviewStage` and `appliedDate`. "Save application" writes
  `applicationTracking` and sets the job status to `applied_manually`.
- **Where it shows:** the Applications screen is a sortable tracker with follow-up due dates,
  and the Dashboard and Outreach follow-ups read it. A re-import or re-score keeps tracking,
  status and tailored-asset pointers (`mergeStatusOnImport`).
- **What it doesn't do:** nothing submits an application, attaches a CV or tailors
  automatically. The tracker has no link to the CV you used.

### Stage 6: Tailored résumé and cover letter

Path: `JobTailorActions` → `/api/tailor/*` → `run_tailor.py`.

- **Inputs:** the browser profile is written to `data/profile/candidate-profile.json` on
  every tailor call, so the profile it uses is current. The **intelligence is read from
  disk**, so it may be stale. It also needs `scored_jobs.json`.
- **Content:** `parse_resume_from_profile` re-parses the default CV's raw text by structure,
  with the profile's `workExperience` list for titles and companies. Skill rows come from the
  CV's skills section, and extra `parsedData.skills` go into an added "Skills" row. Education
  is the first readable `parsedData.education` entry. The summary comes from Q17.
- **The LLM step:** it uses the Claude Code CLI (`python/llm/claude_code.py`), not the OpenAI
  provider, and its output is checked by the provenance checker. If it fails, it falls back
  to rule-based content. It reads the intelligence's `candidateSummary`, `skillsMap`,
  `experienceMap` and `atsKeywordBank.highPriority`.
- **Not used:** `experienceDetail`, `competencyGroups`, `toolGroups`, the library,
  `defaultCvId`, `entry.analysis`.

---

## Part 2: Edge cases

### Clear errors or empty states (fine)

- **No CV:** My CVs shows an empty state. Regenerate Intelligence says "Resume text or parsed
  skills are required."
- **Analysis not run:** the Analyze button is disabled for a CV with no text, and nothing
  downstream expects the analysis.
- **Questionnaire incomplete:** Regenerate refuses with a per-question message.
- **Missing `intelligence`, `scored jobs` or the Python venv:** the tailor and scoring routes
  return explicit errors.
- **No salary:** the pay is unknown, there is no badge, and the job always passes the salary
  filters.
- **No location on a job:** scores as a non-match without crashing. This branch was not fully
  traced.
- **Empty tailoring selection:** exits with "No jobs matched selection criteria."
- **No default CV set:** the code keeps a default whenever an entry exists. It can only occur
  by hand-editing the profile JSON. In that state the delete button would be allowed on every
  CV, and the next add would self-heal.

### Silent or misleading (worth attention)

1. **Edit Profile re-upload overwrites your edits.** `applyResumeExtraction` merges the
   extracted `basicProfile` over yours, including empty strings, and the extracted `parsedData`
   lists replace your edited lists. `_editedFields` only hides the confidence tags and
   protects nothing.
2. **The phone extractor has Indian defaults.** `profileExtractor.js` has `+91` and
   `[6-9]\d{9}` patterns, against the "no hard-coded markets" rule.
3. **Applied analysis suggestions do nothing for scoring until intelligence is regenerated and
   synced.** Nothing prompts for that, and the profile stays "correct" while scoring runs on
   old data. **Resolved in `d110fd4`:** Apply now regenerates the intelligence and syncs it to
   disk, and reports a failure with a retry. The related point in Part 4 (the analysis being
   an island) still stands for `experienceDetail`, `competencyGroups` and `toolGroups`, which
   have no consumer, and a skill outside the classifier's dictionary (Confluence, Miro, Slack)
   reaches the profile but barely changes `skillsMap`; extending the dictionary is a separate
   item if wanted.
4. **Applying skills changes the tailored CV.** All applied skills go into the extra "Skills"
   row, so tool names like Slack or Miro can appear as skills.
5. **Applying education fixes tailoring only through `parsedData.education`.** If the
   "differs" suggestion is left unticked, tailored CVs keep printing the cut-off ".Sc."
   degree. The same wrong entry feeds the intelligence generator.
6. **A job with a thin description still gets tailored.** No guard checks that the description
   exists, so the output would be generic.
7. **Intelligence can be stale relative to the profile in tailoring.** The profile is current
   but the intelligence is not, and tailoring uses `skillsMap`, `experienceMap` and
   `atsKeywordBank` from the intelligence file.
8. **Duplicate library entries.** Uploading the same PDF twice makes two entries, and a
   LinkedIn export becomes a "CV" entry too.
9. **Every CV's full text and analysis lives in the profile.** It is written to localStorage,
   the disk mirror and the backups, and it is sent as the `profile` body to the discovery and
   tailor routes. Large CVs and analyses could hit the localStorage limit.
10. **Cancel in Edit Profile and the library:** if a CV is analyzed or renamed during a
    session, Cancel restores the earlier state, including losing the analysis.

---

## Part 3: Nav inventory (`VIEWS.*`)

- **ONBOARDING:** the 6-step wizard (Welcome, Upload resume, Your profile, Repositories,
  Questionnaire, Review & export). Shown until `onboardingComplete`.
- **PROFILE_EDIT:** the same wizard in edit mode, with Cancel restoring a snapshot. It is not
  in the sidebar and is reached through Edit buttons.
- **DASHBOARD:** stat cards (readiness, intelligence, jobs, resumes generated, applications,
  follow-ups, API) and shortcuts.
- **PROFILE:** read-only profile cards with per-section Edit, "Re-upload Resume" and
  "Regenerate Intelligence".
- **INTELLIGENCE:** shows and exports the generated intelligence file.
- **JOBS:** three tabs: Jobs (table, filters, detail drawer), Pipeline (run, score, judge,
  tailor in bulk) and Analytics.
- **APPLICATIONS:** the application tracker and AI insights.
- **RESUMES:** tailored per-job résumés from `data/resumes/`, with download links.
- **MY CVS:** the uploaded CVs and the CV analysis.
- **CAREER_STRATEGY:** career direction, skill gap and AI memory (JS AI stack).
- **AI_COMMAND ("AI Copilot"):** chat over the data (JS AI stack).
- **OUTREACH:** LinkedIn contact discovery, follow-ups and drafts.
- **QUALITY:** audit of tailored assets, flagging unsafe outputs.
- **SETTINGS:** data paths, demo data, pipeline status, backup and restore, and clear data.
  The scoring weights panel and the AI provider selector live in other places (the weights
  panel, AI Copilot).

---

## Part 4: Redundancy and islands

### Same data editable from several places

- **Skills:** the Profile form's skills list, Q2 and Q5 in the questionnaire (auto-seeded from
  the CV, then editable), the repo scan (adds skills), and analysis Apply. Q2/Q5 and
  `parsedData.skills` are separate lists that nothing keeps in sync.
- **Projects:** `parsedData.projects` (CV extraction), Q4 (selected from those plus themes),
  the repo scan, and analysis Apply, which writes Q4.
- **Experience and education:** `parsedData.workExperience` and `education` (Profile form), and
  the CV text itself (what tailoring re-parses). Analysis Apply writes `experienceDetail` and
  the lists. Three representations can disagree.
- **Active CV vs library:** `profile.resume` is the live default's data, mirrored back into the
  entry on switch. A browser-only edit is not in the stored copy until then.
- **Disk vs browser:** the profile and intelligence mirrors only update on certain actions.

### Look similar, aren't connected

- **CV analysis is mostly an island today.** Skills, education, certifications, new roles and
  Q4/Q17 reach the intelligence and tailoring only through the existing fields, and only after
  regenerating. Its three newest outputs (`experienceDetail`, `competencyGroups`, `toolGroups`)
  have no consumer.
- **Two résumé-AI paths:** the Resume Strategist ("Evaluate", JS stack, suggestions only) and
  the Python tailoring. They share no data.
- **Two cover-letter generators:** the JS `coverLetter` feature (`ai_cover_letter.md`) and
  Python's `cover_letter.md`.
- **Two questionnaire renderers:** `ReviewScreen`'s answer display and the Profile page's
  (`modules/profile/answerDisplay.js`).
- **My CVs vs Resumes:** both list résumé files, but Resumes are tailored outputs and My CVs
  are the uploads. Nothing links a tailored résumé to the CV it was based on.

### Three LLM stacks that don't share settings

- **Python `llm_client`** (env provider): enrichment, the judge and CV analysis.
- **Python `claude_code.py`:** tailoring, project scan and job-URL import.
- **JS `ai/*` providers** (browser settings): Copilot, strategy, job AI tools and the Resume
  Strategist.

### Dead or suspect code

No unreferenced source files were found. The questionable items are the Indian phone patterns
noted in Part 2; the `_editedFields` mechanism, which only hides a UI tag; the JS
`coverLetter` feature, whose output has no downstream use found; and the interview-prep
route, which serves `data/interviews`, a folder that doesn't exist yet. Not every AI feature
flag was checked.
