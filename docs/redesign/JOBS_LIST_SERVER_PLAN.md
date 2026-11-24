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

## Phases

| # | Phase | Size | Status |
|---|---|---|---|
| P0 | Spike on a read-only copy: does Node 20 load the shared modules, slim row size, index build time and memory | S | done (see P0 result; commit in the Log) |
| P1 | Shared default sort-key function, parity harness, Settings page-size field. No route | M | done (commit in the Log); full tier green |
| P2 | Index in Node, `GET /api/jobs/list` (filters, search, sort, offset/limit, revision, counts, ids mode), full ad on open | L | todo |
| P3 | The Jobs screen reads pages; the import stops loading the whole file; `JOB_PAGE_SIZE` and the lean/minimal storage tiers go | L | todo |
| P4 | Other screens (Board, Statistics, Outreach, Resume library, Dashboard, AI context) stop depending on the full list; server stats route | M-L | todo |
| P5 | Step 5's owner overlay for notes, outreach, tailored assets and AI insights | L | todo, can wait |

P3 and P4 ship together. Nothing is deployed before P4.

## P0 result (2026-11-24, read-only copy of the real data; nothing under `data/` was modified)

No blocker. Two import breaks found and fixed; the numbers say the index can be rebuilt on every revision.

- **Node 20.20.2 loading the shared modules:** 5 of 13 failed as written, all for two reasons (a bare `import ... from '../../data/geography.json'` in `jobFilters.js`, which needs an import attribute on Node 20; and four relative imports without `.js` in `jobStats.js` / `followUps.js`). Fixed: `with { type: 'json' }` on the geography import, `.js` on the four specifiers, and ESLint's `ecmaVersion` for `src/**` raised 2022 to 2025 (import attributes). Vite, Vitest and ESLint accept it. The static import closure of the list rules is 17 files and about 1,960 lines, no `.jsx`. A test (`tests/js/sharedModulesNode.test.js`) now loads 12 shared modules in a plain Node process and fails with Node's own error if either break returns.
- **Python step the route would spawn per revision (`all_ads.py`, today's route):** 0.34 s wall, 146 MB peak, a 4.8 MB answer.
- **Node, ledger 45.6 MB (4,427 entries):** read 89 ms, parse 114 ms; `scored_jobs.json` (3.06 MB, 91 rows) parse 12 ms. After the parse: heap 115 MB, RSS 189 MB. The spike's peak with every row copy it made on top: RSS 291 MB.
- **Slim row (`slimJob`: no `description`, `llmFacts`, `engineShadow`):** a scored row is 24 KB full and 4.2 KB slim on average (91 rows: 2.2 MB full, 0.4 MB slim). A ledger-only row is 584 B slim (4,427 rows: 2.5 MB), but it carries no score: scores exist only in `scored_jobs.json`.
- **Query cost:** filter + default sort + counts over 4,427 slim rows: 30 ms mean; over the 91 scored rows: 0.9 ms. An index rebuild on a revision is about 0.5 s (0.34 s Python + 0.2 s Node), so rebuilding on every revision is fine.
- **Findings for later phases:** the real `scored_jobs.json` has 91 rows while the list has 471: the 390 held JobSpy ads have no scored row (the file predates the carry-over restore). `dayOf` is the local midnight, so the day for the deadline column must come from the client, not the server's time zone (done in the P1 query: `today` is an input).

## Open items

- `activeWindowDays` exists only on `keep-search-ads` (`eacec8b`), not on `main`. The page-size field is added to the same gate-settings store (`python/llm/ai_gate.py`, `gateClient.js`, `AIBudgetPanel.jsx`) on this branch from `main`; merging both branches needs a small conflict resolution in those three files and in `tests/js/aiSettingsHandler.test.js`.
- **Owner-visible change in P1 (decide or revert):** a picked column sort (title, company, ...) now breaks ties in the neutral order (remote-feasible, newest, jobId) instead of the list's arrival order, which differs between a browser and a server. The default sort and the tier sort are unchanged (a property test shows the new single sort key equals `notReadFirst(closedLast(blockedLast(defaultOrder)))`).
- **Page size bounds and default are my proposal:** `jobsPageSize`, whole ads 1 to 1000, default 100 (today's `JOB_PAGE_SIZE`, which stays until P3). The owner did not give bounds.
- **`today` (deadline column) comes from the client.** `queryJobList` takes it as an input; P2's route must pass the browser's day, not the server's.
- **Known parity gap, by design:** rows only the browser has (an `offList` row, a hand-entered job not yet synced) are not in the server's list; P5 (orphans) covers them. The parity fixture leaves them out.
- **The screen still runs its own pipeline** until P3 (only `JobTable`'s sort now calls the shared `orderRows`); the parity test holds the two together meanwhile. `JOB_PAGE_SIZE` stays until P3.
- **Not yet in the query (P2/P3):** slimming the page rows (`slimJob`), an ids-only mode for select-all, the `revision` value, and the filter panel's other derived lists (locations).
- Select-all across pages needs an ids mode in the route (P2).
- Settings home for the page size: the AI-budget settings file for now (same store as the run limits and `activeWindowDays`); a dedicated Jobs section is the alternative.
- The offline case (API down): worked ads only, with a notice (own proposal, P3).

## Waiting

- `keep-search-ads` (`eacec8b`): open ads of a search source the latest search did not return stay scored and in Active, with the Active period in Settings. Unmerged until P3 is done.
- `rescrape-fixes` is the same commit as `main` (`b4bc763`); nothing waits there.

## Log

(one entry per prompt: status, commit hash, what changed, what is next)

**Prompt 1, 2026-11-24: P0 and P1 done, commit `fd082ea` (branch `jobs-list-server`, from `main` `b4bc763`; not pushed, no build deployed).**
- Changed: progress file, ROADMAP link, DECISIONS entry (supersedes "No pagination in this step" for the list); P0 spike and its two import fixes (see P0 result); `defaultSortKey` / `compareDefault` / `orderDefault` / `SORT_COLUMNS` / `DEFAULT_SORT` / `orderRows` in `jobTableModel.js`, with `JobTable` calling `orderRows`; `jobListQuery.js` (`queryJobList`); Settings field `jobsPageSize` (gate settings, form, panel).
- Tests added: `tests/js/jobListParity.test.js` (seeded property test: ids, order, every page, counts; mutation-checked), `tests/js/sharedModulesNode.test.js`, `tests/python/test_jobs_page_size_setting.py`, a form round-trip in `tests/js/aiSettingsHandler.test.js`. Full tier green (lint, Vitest, pytest incl. slow, build).
- Next: P2 (index in Node, `GET /api/jobs/list`, revision check, slim rows, ids mode), after the owner has seen the open items above (the tie-order change and the page-size bounds). `keep-search-ads` (`eacec8b`) stays unmerged until P3.
