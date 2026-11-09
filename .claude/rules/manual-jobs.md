---
paths:
  - "src/modules/jobs/**"
  - "scripts/run-manual-job.js"
  - "scripts/run-ad-fill.js"
  - "python/job_import/**"
  - "python/job_scoring/manual_jobs.py"
  - "python/job_scoring/run_scoring.py"
  - "tests/js/manual*.test.js"
  - "tests/js/adFill.test.js"
  - "tests/python/test_manual_jobs.py"
  - "tests/python/test_ad_ai.py"
---

# Manual jobs and Fill from ad

"Add job" on the Jobs screen (`AddJobDialog.jsx`, helpers in `modules/jobs/manualJob.js`, flow in `modules/jobs/manualScoring.js`): `manualEntry: true`,
`provider: 'manual'`, status `new` (shown "Unreviewed"). The server is the master for the scored fields: `POST /api/jobs/manual/score`
(`scripts/run-manual-job.js`) runs `python/job_import/import_job_url.py --job-json -` (payload on stdin; no fetch, no model, no network), which stores the job in
`data/jobs/manual_jobs.json` (`python/job_scoring/manual_jobs.py`; discovery never writes it), scores it with the same `score_jobs()` over the same corpus a full run
uses and merges it into `scored_jobs.json`. `run_scoring.py` adds the manual file to every run (so Re-score, Re-scrape and the full pipeline keep the jobs; a manual
row wins over a discovered row with the same normalised URL, and `--min-score` never drops one). Scoring failure leaves the job Unreviewed with a "Score now" retry
(details page, and the note after saving); retry is idempotent. `runScoring` / `runFullPipeline` / `runJudgedScoring` first send the browser's manual jobs to
`/api/jobs/manual/sync`. Manual jobs get no enrichment (`aiEnrichment: "missing"`), and a `--judge` run includes them like any other ad (the ad text only).
Duplicates: the add-time check refuses the same identity URL (`identityJobUrl` / `identity_url`: host lowercased, hash and trailing slash stripped, tracking parameters removed, `?gh_jid=`-style parameters kept; fixture `tests/fixtures/url-normalisation.json` run by
both; the query-stripping `normalizeJobUrl` / `normalize_url` remain only as its base) against this browser's list, the discovered file, the scored file and the manual file, and shows the clash; a different id is a clash, the same id is a retry. The
silent paths (`with_manual`, `importJobsFromFile`) use the same key (boards that tell postings apart by query string must not collapse to one job); `scored_jobs.json` `meta.manualJobs` counts the rows a manual job replaced.
The description is optional (Title and Company, plus a Job URL or a description, are required): a job without ad text is saved Unreviewed and unscored ("No description: paste the ad text to score it"), is only clash-checked on the server (`--check-only`, writes nothing), is not synced, and is scored once the text is pasted on Job Details. The old Source select is replaced by an optional `sourceUrl`.
`notes`, `extraLinks` and `sourceUrl` are owner-only: they stay in the browser's job record (carried over by `importJobsFromFile`) and are in no payload to Python, file, log line or
AI context (`SCORING_FIELDS` is the whitelist on both sides; `summarizeJob` is a whitelist too; `tests/js/manualScoring.test.js`, `tests/python/test_manual_jobs.py`).
**Edit** (button on a hand-entered job's details, same form prefilled; `editManualJob` in `manualScoring.js`, `editChanges` in `manualJob.js`): saved through `patchJob` (same id, `createdAt` / `firstSeen` kept, `updatedAt` set; status and tracking untouched). A changed title, company, description, location or salary re-scores on the server (`/api/jobs/manual/score`, same path as "Save text and score"); only notes, links, Source URL or Job URL changed does not (a new Job URL is clash-checked, ignoring the job itself, and stored on the server with `/api/jobs/manual/sync`, unscored). The scored description cannot be removed. `jobUrl`, `site` and `updatedAt` of a hand-entered job win over the scored file on re-import (`MANUAL_ONLY_FIELDS`). Tests: `tests/js/manualEdit.test.js`.
**Delete** (button next to Edit, hand-entered jobs only; `deleteManualJob` in `manualScoring.js`, `scripts/manual-job-delete.js`, `import_job_url.py --delete-job`): the server refuses when the application store names the job in any way, voided included, then removes it from `manual_jobs.json`, `scored_jobs.json` and `job-state.json`; only then does the browser drop its copy. Application records are never touched. Tests: `tests/js/manualJobDelete*.test.js`, `tests/python/test_manual_jobs.py`.
Add any new owner-only field to `MANUAL_FIELDS` and to those tests (`sourceUrl` has a canary there).

**Fill from ad (Add job form, step 1, no AI; step 2 is the privacy bullet above):** the button next to Job URL calls `POST /api/jobs/ad/fetch` (`scripts/run-ad-fill.js` -> `python/job_import/ad_fill.py fetch`).
The body is the address only (never Notes, links, Source URL or any profile data). The page is fetched by `python/job_import/safe_fetch.py`, the only fetcher with SSRF
limits: http(s) on ports 80/443 only, no credentials in the URL, every resolved address must be public (private, loopback, link-local, Tailscale's 100.64/10, NAT64/6to4/Teredo
are refused, so `holojob.void` and `127.0.0.1:3073` cannot be fetched), the connection is pinned to the checked address, redirects are followed by hand (3 max, each hop checked),
no cookies/auth/Referer/proxy/compression, 2 MB and 15 s limits, HTML only, login walls and LinkedIn posts refused. `ad_reader.py` reads schema.org JobPosting JSON-LD only
(title, company, location, description with its breaks, salary only when it reads as EUR per month, else unknown). Nothing is written. The page text stays in the Node process
behind a 15-minute token (`cachedPage`), never in the browser. The form (`modules/jobs/adFill.js`) fills **empty fields only**, marks them "suggested" until edited, and saves
nothing before Save. A failed or unreadable fetch changes nothing and shows a message chosen in `run-ad-fill.js` (`failureMessage`) from the failure code and HTTP status only, never from the page: `bot_check` (a Cloudflare-style challenge, recognised and not bypassed), 404/410, other HTTP errors, login wall, not HTML, timeout/unreachable, JavaScript-only page; every one ends "paste the ad text". If the page leaves fields empty, the form offers "Extract the missing fields with AI": a confirm panel shows the exact redacted text, the fields and the gate's answer (or why it is refused); values come back as suggestions into empty fields only. The URL import (`import_job_url.py`) uses the same `safe_fetch`.
