# The Jobs list on the server: progress file

**Rule: update this file at the end of every prompt of this work: status, commit hash, what changed, what is next.**

## Goal

The browser holds only the ads currently shown on the Jobs list plus the owner's worked ads; the whole list lives on the server, and "Show more" pulls the next ads from it, with every filter, search, sort (tier order) and count giving the same result as today.

## Owner decisions (binding, 2026-11-24)

1. The browser holds only the ads currently shown on the Jobs list. The whole list lives on the server. "Show more" pulls the next ads. All existing filters, search, sort (tier order) and counts give the same result as today.
2. Shown pages live in memory only, never in `localStorage`. Worked ads (status, Keep, notes, outreach, assets, applications, hand-entered) stay stored in the browser as today.
3. Paging is **offset/limit plus a revision check** (the client gets "list changed, refresh" when the revision moved). **Not a keyset cursor.** Benchmarks: ApplyPack `skip`/`take` (`src/web/routes/jobs.tsx:260-336`), CareerPulse `offset` (`app/routers/jobs.py:15-40`).
4. The rules run on Node with the shared `src/modules/jobs/*` modules. The route imports them; there is no copy.
5. P3 (the Jobs screen reads pages) and P4 (other screens stop depending on the full list) ship together; deploy only after P4. Branch `keep-search-ads` (`eacec8b`) stays unmerged until P3 is done.
6. The page size is a Settings field next to `activeWindowDays`, its default written once, no number in code. `JOB_PAGE_SIZE` goes when P3 lands.
7. This supersedes "No pagination in this step" (STEP5_SERVER_MASTER_PLAN.md section 2.3) for the job list (DECISIONS.md, 2026-11-24).
8. **Binding requirement for P3/P4:** browser-only worked ads (`offList` rows and unsynced hand-entered jobs) must NOT disappear from the list when the server-paged list goes live. This is solved BEFORE P3/P4 are activated, not left for P5. It stays in Open items until done (mechanism proposed under "Browser-only worked ads", below).
9. On the P1 items (owner, 2026-11-24): a picked column breaks ties in the neutral order; the page size is 1 to 1000, default 100; the day for the deadline column comes from the browser; the `activeWindowDays` merge conflict is resolved when `keep-search-ads` is merged.
10. **Mechanism C is accepted as a BRIDGE, removed in P5** (owner, 2026-11-24): the browser sends its worked rows that the server does not hold as `extraRows` with each list request. Conditions: (1) a field ALLOWLIST (never `notes`, `extraLinks`, `sourceUrl` or any field not listed), with a test that private fields do not pass; (2) an oversized request body is a visible error, never silent truncation; (3) the P1 parity test is extended with those rows (order, totals, counts, every page). P2b also covers opening a browser-only ad (see "The rule for opening an ad").

## Phases

| # | Phase | Size | Status |
|---|---|---|---|
| P0 | Spike on a read-only copy: does Node 20 load the shared modules, slim row size, index build time and memory | S | done (see P0 result; commit in the Log) |
| P1 | Shared default sort-key function, parity harness, Settings page-size field. No route | M | done (commit in the Log); full tier green |
| P2 | Index in Node, `GET /api/jobs/list` (filters, search, sort, offset/limit, revision, counts, ids mode), full ad on open | L | done (commit in the Log); route not used by any screen yet |
| P2b | Browser-only worked ads in the paged list (binding requirement 8): `extraRows` bridge (removed in P5), allowlist, POST route, parity test, opening a browser-only ad | M | done (commit in the Log); the screen does not call it until P3 |
| P3 | The Jobs screen reads pages; the import stops loading the whole file; `JOB_PAGE_SIZE` and the lean/minimal storage tiers go | L | todo (needs P2b) |
| P4 | Other screens (Board, Statistics, Outreach, Resume library, Dashboard, AI context) stop depending on the full list; server stats route | M-L | todo (needs P2b) |
| P5 | Step 5's owner overlay for notes, outreach, tailored assets and AI insights. **Removes the `extraRows` bridge** (`extraRows.js`, the POST body field, `selectExtraRows` / `mergeLocalRow` and their tests) | L | todo, can wait |

P3 and P4 ship together. Nothing is deployed before P4.

## P0 result (2026-11-24, read-only copy of the real data; nothing under `data/` was modified)

No blocker. Two import breaks found and fixed; the numbers say the index can be rebuilt on every revision.

- **Node 20.20.2 loading the shared modules:** 5 of 13 failed as written, all for two reasons (a bare `import ... from '../../data/geography.json'` in `jobFilters.js`, which needs an import attribute on Node 20; and four relative imports without `.js` in `jobStats.js` / `followUps.js`). Fixed: `with { type: 'json' }` on the geography import, `.js` on the four specifiers, and ESLint's `ecmaVersion` for `src/**` raised 2022 to 2025 (import attributes). Vite, Vitest and ESLint accept it. The static import closure of the list rules is 17 files and about 1,960 lines, no `.jsx`. A test (`tests/js/sharedModulesNode.test.js`) now loads 12 shared modules in a plain Node process and fails with Node's own error if either break returns.
- **Python step the route would spawn per revision (`all_ads.py`, today's route):** 0.34 s wall, 146 MB peak, a 4.8 MB answer.
- **Node, ledger 45.6 MB (4,427 entries):** read 89 ms, parse 114 ms; `scored_jobs.json` (3.06 MB, 91 rows) parse 12 ms. After the parse: heap 115 MB, RSS 189 MB. The spike's peak with every row copy it made on top: RSS 291 MB.
- **Slim row (`slimJob`: no `description`, `llmFacts`, `engineShadow`):** a scored row is 24 KB full and 4.2 KB slim on average (91 rows: 2.2 MB full, 0.4 MB slim). A ledger-only row is 584 B slim (4,427 rows: 2.5 MB), but it carries no score: scores exist only in `scored_jobs.json`.
- **Query cost:** filter + default sort + counts over 4,427 slim rows: 30 ms mean; over the 91 scored rows: 0.9 ms. An index rebuild on a revision is about 0.5 s (0.34 s Python + 0.2 s Node), so rebuilding on every revision is fine.
- **Findings for later phases:** the real `scored_jobs.json` has 91 rows while the list has 471: the 390 held JobSpy ads have no scored row (the file predates the carry-over restore). `dayOf` is the local midnight, so the day for the deadline column must come from the client, not the server's time zone (done in the P1 query: `today` is an input).

## P2 result (2026-11-24)

`GET /api/jobs/list` and `GET /api/jobs/list/ad` (`scripts/job-list.js`, registered in `api-handler.js` after `/api/jobs/all`). No screen calls them yet. They write nothing (the one thing that can write is `ensureViewCurrent`, the check every job route makes).

- **Rules:** none in the route. It builds the input from the server's files and calls `queryJobList` (P1), the same module the screen's pipeline is checked against. The stored rows are `importJobsFromFile(scored_jobs.json)`, the route's rows are `all_ads.py` (spawned through the existing `readAll`), the statuses are `job-state.json`, the applications are the application store and its settings.
- **Request:** `mode` (required), `offset`, `filters` (JSON, every key and type checked against the Jobs screen's own `DEFAULT_FILTERS`), `classes`, `recent`, `sort` (JSON, a known column and asc/desc), `today` (the browser's day; required for the deadline sort), `revision`, `ids=1`. A `limit` is refused with 400: **the page size is the Settings field `jobsPageSize`**, read through the gate on every request; a value that is not a whole number of ads is a 500 naming the field, never a default.
- **Answer:** `rows` (slim: no `description`, `llmFacts`, `engineShadow`), `total`, `nextOffset` (null on the last page), `limit` (the Settings value used), `revision`, `meta`, and `counts` on the first page only (`offset` 0; `null` after, because "Show more" needs rows only): `stats` (computeJobStats + tracker), `tiers`, `classOptions`, `notOnBoardHidden`, `copies`, `hasServerOnly`, and the filter panel's `facets` (sites, providers, companies, priorities, status options, `hasScores`).
- **Revision:** a hash of the size and modification time of the seven files the list is made from (scored list, ledger, view, filtered ads, job-state, application store and its settings). It reads no file. A request that carries a `revision` that is no longer current gets `{ ok, changed: true, revision }` and no rows: the client says "list changed, refresh". The index (stored rows, route rows, statuses, applications) is kept in memory per revision and rebuilt when it changes; two requests at once build it once.
- **ids mode:** every matching ad in order (`ids`) and the ones a bulk action can reach (`selectableIds`), for select-all across pages.
- **Full ad on open:** `GET /api/jobs/list/ad?jobId=` returns the whole scored row (text, facts) with the owner's status and the application's tracking laid over it. An ad with no scored row (ledger-only) answers 404 and points to `GET /api/jobs/history/<jobId>`, which already serves its text.
- **Failures:** a list that cannot be made is 503 with the reason (as `/api/jobs/all`); an unreadable `scored_jobs.json` is a 500, not an empty list; demo mode is 404 (the demo bundle has no server list: P3 decides what the screen shows then).
- **Real data, read-only (symlinks to the data files, the Python step run for real):** All holds 7,146 rows (the ledger 4,427 plus filtered ads). First request 0.9 s (index build with `all_ads.py`), later requests 0.1 to 0.4 s, 183 MB RSS. The first All page is 464 KB (the counts and facet lists are most of it: 7,146 company options), the second Active page 70 KB. A page is the rows only; the cost left is composing and sorting the whole list per request (about 0.4 s for All), which a later step can memoize per revision and day.
- **Tests:** `tests/js/jobsListRoute.test.js` (35 tests: pages equal the query's, slim rows, filters/classes/sort reach the query, ids mode, revision refusal, index kept and rebuilt, one build for two requests, 12 request refusals before any file is read, page size from the gate and never guessed, 503/500/404/405, the full ad); the parity test now also covers ids and rows-only pages.

## Browser-only worked ads (binding requirement 8): the mechanism, accepted as a bridge

**The risk:** the server list does not hold an `offList` row (a row the owner worked on that the last scored file no longer has) or a hand-entered job that was never synced (saved without a description, or while the server was away). Once the Jobs screen reads server pages, those rows would vanish, and a count or an order that mixes server rows with local ones would no longer match what the server says.

**Options considered**
- **A. Sync them to the server first.** Hand-entered jobs have a server home (`manual_jobs.json`, `/api/jobs/manual/sync`), but a job with no description is not synced by design and is only scored once text is pasted; `offList` rows have no server home until P5 (orphans in the owner overlay). A alone cannot be done before P3/P4 without building P5.
- **B. Merge the browser's rows into the paged result on the client.** Offsets, totals, counts and the tier order are the server's; local rows spliced in afterwards break all four (a page of 100 becomes 103, "Show more" skips or repeats, counts disagree).
- **C. (proposed) Send the browser-only worked rows with the request, and let the server rank them with the rest.** The server adds them to `stored` for that one request (never persisted, never logged) and runs the same `queryJobList`, so order, totals, counts and pages are consistent by construction. Rows the server also holds (same `jobId` or `jobMatchKey`) are not added twice: the server's ad fields win, as `importJobsFromFile` decides today.

**What C needs (P2b, size M)**
1. A `POST /api/jobs/list` variant with the same parameters in the body and `extraRows` (the browser's rows the server does not hold). POST because of the size; it writes nothing. The request guard already accepts JSON POSTs, and a body over the 1 MB default limit answers 413 (about 300 rows at 3 KB; past that, option A for the manual jobs shrinks the set).
2. A whitelist of the fields an extra row may carry (the filter, sort and display fields and the status/Keep flags, plus the description a text search reads), the same idea as `SCORING_FIELDS`. **`notes`, `extraLinks` and `sourceUrl` are never sent** (manual-jobs rule: owner-only, in no payload).
3. The revision stays the server's; the set of extra rows is client state, sent with every request, so a changed set restarts the paging on the client.
4. The parity harness gains the browser-only rows (the P1 fixture left them out on purpose): the browser input holds `offList` and unsynced manual rows, the server input gets them as `extraRows`, and the same ids, order, pages and counts must come out. That is the test that lets P3/P4 be activated.
5. For the client (P3): a selector that names the browser-only worked rows (stored rows with `offList`, or `manualEntry` not yet on the server), and the rule that a row the server holds is shown from the server's answer.

**Decision (owner, 2026-11-24): C, as a bridge removed in P5.** Its conditions are decision 10 above. A, B and C as considered are kept here as the record.

## P2b result (2026-11-24)

**What was built**
- `src/modules/jobs/extraRows.js`, one file for the browser and the server: `EXTRA_ROW_FIELDS` (the allowlist), `selectExtraRows(stored)` (what the browser sends), `checkExtraRows(rows)` (what the server accepts), `applyExtraRows(stored, rows)` (the merge for one request), `mergeLocalRow` (a browser-only row is shown from the browser's copy).
- **What is sent:** a browser-only row (`offList`, or hand-entered) in full, as the allowlist lets it out; a row the server may hold that the owner has worked on here, as its owner state only (`status`, `keptByUser`, one `ownerWork` flag, and the three values of a legacy tracking object that the counts read: `applied`, `interviewStage`, `followUpDate`); nothing for any other row. **Why the second kind:** whether a row is "worked" (`hasUserData`) decides what Active shows and which crm counts there are, and it reads notes, outreach, assets and insights, which must not be sent. They go as the one flag `ownerWork`, which `hasUserData` now also honours (a stored row never carries it).
- **Never sent, by construction:** `notes`, `extraLinks`, `sourceUrl`, `sourceChoice`, outreach, tailored assets, AI insights, `llmFacts`, `engineShadow`, and a tracking object's notes, contacts and addresses. The allowlist names what may go; nothing names what may not.
- **The server refuses, it does not clean:** a field outside the allowlist, a tracking field outside the three, a bad or repeated `jobId`, `ownerWork` other than `true` is a 400 that names the row and the field and never quotes a value. A server row keeps its ad fields; an extra row can only add owner state to it (a hand-entered job with the address of a server row under another id replaces that row, as an import does).
- **Route:** `POST /api/jobs/list` with the GET's parameters in a JSON body plus `extraRows`; the answer adds `extra: { sent, notOnServer }` so the browser sees what was taken. The rows are added to the stored rows for that request only: nothing is stored, nothing is written (a test compares the data dir before and after), the revision is the server's. An ids-mode request takes them too, so select-all reaches a browser-only ad.
- **Oversize:** a body over the JSON limit (`MAX_JSON_BODY_BYTES`, 1 MB, about 300 browser-only rows) is a **413 in words** ("The browser's own ads are too many to send with one list request ... Nothing was cut: no list was made."), and the client (`fetchListPage`) returns it as `{ ok: false, tooLarge: true, message }` to be shown, never a shorter list. Past that size, syncing the hand-entered jobs (option A) shrinks the set.
- **Client:** `src/modules/jobs/jobListClient.js` (`buildListBody`, `fetchListPage`, `shownRows`, `openAd`). It has no write path: it imports no storage setter.

**The rule for opening an ad (owner, 2026-11-24).** `extraRows` are not stored on the server, so `/api/jobs/list/ad` cannot return a browser-only ad (it answers 404, and a test says so). An ad opens from the browser's stored row whenever there is one (`openAd` returns `source: 'local'` with no request, the same first choice `resolveJob` has always made); its actions (status, notes, outreach, Mark Applied, tailoring) are the existing code on the same stored row, unchanged, and persist in `localStorage` as today. An ad with no stored row opens from the server, read-only, until the owner presses Keep (`source: 'server'`, `readOnly: true`); one with no scored row either is left to the ledger fallback in `resolveJob`. **An ad that is only a server row is never written to the browser's list**: listing, paging and opening one writes no storage (a test spies `localStorage.setItem` and compares the stored key).

**Tests**
- `tests/js/jobListParity.test.js` (extended): a fixture where the browser holds `offList` rows, hand-entered jobs (some synced, some not, with notes, links and a source address), and owner work on rows the server holds; the server input is built only from `selectExtraRows` + `applyExtraRows`; the same ids, order, every page and every count as the screen's pipeline on the full rows, for four seeds. A test shows the check fails when the extra rows are left out. The picked-column sort is now compared with the browser's order too. Mutation-checked: dropping `ownerWork`, `salaryMonthlyEur`, `roleClass`, `eligibility`, `isClosed` or `applyDeadline` from the allowlist fails it.
- `tests/js/extraRows.test.js` (39): private fields never pass (each of eleven names, on both kinds of row), the server refuses them without quoting a value, the merge rules, no input is changed. Adding `notes` and `sourceUrl` to the allowlist fails 10 tests.
- `tests/js/jobsListExtraRows.test.js` (real HTTP): the rows are in the list and the counts, stored nowhere, the revision unmoved, ids mode, refusals by field, the 413 and the server carrying on, the GET's rules on the POST.
- `tests/js/browserOnlyAds.test.js` (jsdom, real server, real browser store): a browser-only row appears in the paged list; opens from local data with no request; an action on it (`patchJob`: status, notes, tailored assets, outreach) persists in the browser and the next page shows it; its private words never leave; server-only rows write no storage.

## P2b follow-up: slim rows and the cap (2026-11-24, owner decision)

The 1 MB request limit of `POST /api/jobs/list` stays in code: a technical safety cap, not an owner limit. It is made hard to reach.
- **Slim rows:** the ad's text is 88% of a row's bytes and only a text search reads it, so `selectExtraRows` sends `description` only with `withText`, which `buildListBody` sets while the search box is not empty. Measured on the 91 real scored rows (field sizes only): a row with the allowlisted fields is 10.8 KB on average with the text and **1.3 KB without it (1.8 KB at most)**; the next largest fields are `eligibility` 232 B and `workAuthorization` 224 B. An owner-work flag entry (a row the server holds) is a few hundred bytes. So a 1 MB request holds roughly **780 typical rows** instead of about 95. A test sends 600 browser-only rows with 9.5 KB texts as one ordinary request (it is under half the cap).
- **Over the cap, in words:** the server's 413 names the cap (`limitBytes`); the client (`fetchListPage`) answers `{ ok: false, tooLarge: true, rowCount, message }`, and the message says how many ads of which kind (hand-entered, left the list, owner work on a server ad), that nothing was cut and no list was made, and what to do. **What to do is limited:** the only removal that exists today is deleting a hand-entered job (Job Details, Delete); there is no removal of an off-list row. That is an open item below, not something the message hides.
- The parity test sends the text exactly when a search is on, and a test shows a search over slim rows finds fewer of the browser's own ads, which is why.

## Open items

- **Binding requirement 8 (browser-only worked ads) stays open until done.** The mechanism is built and tested (P2b: allowlist, POST route, parity test with the browser's rows, the opening rule), but no screen calls it yet. It is done when P3/P4 use `buildListBody`, `shownRows` and `openAd` and the screen shows an `offList` row and an unsynced hand-entered job after the switch; it must not be activated before that.
- **The bridge is removed in P5** (decision 10): `extraRows.js`, the POST `extraRows` field, `selectExtraRows`, `mergeLocalRow` and their tests go when the owner overlay holds those rows on the server.
- **Size limit of the bridge:** one request carries about 780 slim browser-only rows (1 MB); with a text search on, about 95. Past that the owner sees the error with the row count. Syncing hand-entered jobs to the server (option A) would shrink the set; not built. **There is no way to remove an off-list row from the browser today** (only to delete a hand-entered job): to be decided with P5 or sooner if the cap is ever reached.
- **Legacy tracking:** a row's legacy `applicationTracking` reaches the server as three values only; the notes, recruiter and links in it stay in the browser. If the owner's rows carry more that a count or filter reads, the parity test will show it when a field is added.
- The page size is 1 to 1000, default 100 (owner, 2026-11-24). `JOB_PAGE_SIZE` stays in the screen until P3.
- `activeWindowDays` exists only on `keep-search-ads` (`eacec8b`). Merging it with this branch needs a small conflict resolution in `python/llm/ai_gate.py`, `src/modules/ai/gateClient.js`, `src/components/ai/AIBudgetPanel.jsx` and `tests/js/aiSettingsHandler.test.js`; the owner has decided this is done when `keep-search-ads` is merged (after P3).
- **The screen still runs its own pipeline** until P3 (only `JobTable`'s sort calls the shared `orderRows`); the parity test holds the two together meanwhile.
- **Not yet in the query or route:** the filter panel's distinct location list, memoizing the composed list per revision and day.
- **Scale:** the index holds the full stored rows (the text search reads descriptions). With `keep-search-ads` merged and a run that includes JobSpy, about 3,100 scored rows (47 MB file in the simulation) would be held, which fits (the P0 ledger parse already holds 115 MB); the paged answer is what keeps the browser small.
- Settings home for the page size: the AI-budget settings file for now (same store as the run limits); a dedicated Jobs section is the alternative.
- The offline case (API down): worked ads only, with a notice (own proposal, P3). Demo mode: the route answers 404; P3 decides what the demo shows.
- The real-data numbers above come from a one-off, read-only run, not from a test: the tests use a fake Python step, as `/api/jobs/all`'s do.

## Waiting

- `keep-search-ads` (`eacec8b`): open ads of a search source the latest search did not return stay scored and in Active, with the Active period in Settings. Unmerged until P3 is done.
- `rescrape-fixes` is the same commit as `main` (`b4bc763`); nothing waits there.

## Log

(one entry per prompt: status, commit hash, what changed, what is next)

**Prompt 1, 2026-11-24: P0 and P1 done, commit `fd082ea` (branch `jobs-list-server`, from `main` `b4bc763`; not pushed, no build deployed).**
- Changed: progress file, ROADMAP link, DECISIONS entry (supersedes "No pagination in this step" for the list); P0 spike and its two import fixes (see P0 result); `defaultSortKey` / `compareDefault` / `orderDefault` / `SORT_COLUMNS` / `DEFAULT_SORT` / `orderRows` in `jobTableModel.js`, with `JobTable` calling `orderRows`; `jobListQuery.js` (`queryJobList`); Settings field `jobsPageSize` (gate settings, form, panel).
- Tests added: `tests/js/jobListParity.test.js` (seeded property test: ids, order, every page, counts; mutation-checked), `tests/js/sharedModulesNode.test.js`, `tests/python/test_jobs_page_size_setting.py`, a form round-trip in `tests/js/aiSettingsHandler.test.js`. Full tier green (lint, Vitest, pytest incl. slow, build).
- Next: P2 (index in Node, `GET /api/jobs/list`, revision check, slim rows, ids mode), after the owner has seen the open items above (the tie-order change and the page-size bounds). `keep-search-ads` (`eacec8b`) stays unmerged until P3.

**Prompt 2, 2026-11-24: P2 done, commit `79e5144` (branch `jobs-list-server`; not pushed, no build deployed).**
- Changed: `scripts/job-list.js` (the two routes, the in-memory index per revision, request checks, slim rows), registered in `scripts/api-handler.js`; `readAll` exported from `scripts/job-all-read.js`; `DEFAULT_FILTERS` exported from `jobStorage.js`; `queryJobList` gained `withIds` and `withCounts`; the progress file (P2 result, binding requirement 8 with the proposed mechanism and what it needs, the owner's decisions on the P1 items, new phase P2b) and a DECISIONS addendum.
- Tests added: `tests/js/jobsListRoute.test.js` (35); the parity test also covers ids and rows-only pages. Full tier green (lint, Vitest, pytest incl. slow, build).
- Real data, read-only: first All request 0.9 s, later 0.1 to 0.4 s, 183 MB; see P2 result.
- Decision needed from the owner: the mechanism for browser-only worked ads (proposal C, "Browser-only worked ads"). Requirement 8 stays open until P2b is done.
- Next: P2b (extraRows, POST variant, whitelist, parity with the browser-only rows) once the owner agrees to C or names another mechanism; then P3 and P4 together. `keep-search-ads` (`eacec8b`) stays unmerged until P3.

**Prompt 3, 2026-11-24: P2b done, commit `890bfa3` (branch `jobs-list-server`; not pushed, no build deployed).**
- Changed: `src/modules/jobs/extraRows.js` (the allowlist, `selectExtraRows`, `checkExtraRows`, `applyExtraRows`, `mergeLocalRow`), `src/modules/jobs/jobListClient.js` (`buildListBody`, `fetchListPage`, `shownRows`, `openAd`), `POST /api/jobs/list` in `scripts/job-list.js` (the body's `extraRows`, a visible 413), `hasUserData` honours the `ownerWork` flag; the progress file (decision 10, the P2b result, the opening rule, the bridge's removal in P5) and a DECISIONS addendum.
- Tests added: the parity test extended with the browser's rows (four seeds, mutation-checked), `extraRows.test.js` (39), `jobsListExtraRows.test.js` (real HTTP), `browserOnlyAds.test.js` (jsdom: a browser-only row appears in the paged list, opens from local data, an action on it persists, server-only rows write no storage), a shared test server in `tests/js/setup/jobsListServer.js`. Full tier green (lint, Vitest, pytest incl. slow, build).
- Requirement 8 stays open: the mechanism is built and tested, but no screen calls it yet. It is done when P3/P4 use it.
- Next: P3 and P4 together (the Jobs screen reads pages through `buildListBody` / `fetchListPage` / `shownRows` / `openAd`; the other screens stop depending on the full list; `JOB_PAGE_SIZE` and the lean/minimal storage tiers go). Nothing is deployed before P4. `keep-search-ads` (`eacec8b`) stays unmerged until P3.
