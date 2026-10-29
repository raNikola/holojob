# Step 5: the server becomes the master for profile, intelligence, jobs and the remaining browser data

Status: PLAN, 2026-10-29, revised with the owner's decisions on Q-A to Q-K (section 9). Docs only: no code, no `data/` change, no AI call, no commit.
Revision 2 (2026-10-29): owner answers to Q-L, Q-M, Q-N (changed) and Q-O are applied (sections 2.8, 6, 9); the cache key now lists every input per feature.
Revision: **Q-B changed.** The browser AI cache is not simply removed: a server-side **AI findings store** replaces it (section 2.8, step 2b).
Implements: BROWSER_STORAGE_POLICY section 7, step 5, and Q1 / Q7 of section 8 (DECISIONS.md log 2026-10-29).

Inputs read: CLAUDE.md, BROWSER_STORAGE_POLICY.md, DECISIONS.md, data-shapes.md, TRACKER_PLAN.md (sections 2, 6d: the
migration precedent), and the code that touches each key: `utils/storage.js`, `ProfileContext.jsx`, `jobStorage.js`,
`pipelineState.js`, `intelligenceExport.js`, `aiMemory.js`, `aiResponseCache.js`, `aiUsageTracker.js`, `aiClient.js`,
`aiContextBuilder.js`, `AICommandCenter.jsx`, `autoLoadJobs.js`, `usePipelineAutoRefresh.js`, `profileSync.js`,
`intelligenceSync.js`, `loadDemoData.js`, `SettingsHome.jsx`, `backupClient.js`, `backup-handler.js`, `save-profile.js`,
`save-intelligence.js`, `api-handler.js` (profile / intelligence / scoring / pipeline / backup routes), `application-store.js`
(atomic write, lock), `applicationsClient.js` (the cache pattern), `run_scoring.py`, `allowlist.js`.

## 0. Findings that shape the design

1. **`scored_jobs.json` cannot hold the owner's job state.** `run_scoring.py` rewrites it wholesale (`write_text`, not atomic,
   line 264) on every scoring run. The state that exists *only* in the browser today (`status`, `outreach`, `tailoredAssets`,
   `aiInsights`, legacy `applicationTracking`) therefore needs its own Node-owned file that the pipeline never writes.
2. **`mergeStatusOnImport` is the only thing that carries that state across a re-import**, and it runs in the browser, keyed by
   `url:<jobUrl>` or `tcl:<title>|<company>|<location>` (not `jobId`). After step 5 the join moves to the server and exists in one place.
3. **A browser-computed hash will never equal what the server stored today.** `saveProfileToDisk` drops `_confidence` and
   `_editedFields`, stamps `meta.updatedAt`, and uses plain `writeFileSync`; `saveIntelligenceToDisk` is also non-atomic. The
   verified write needs its own, side-effect-free route and a canonical form (section 3.2).
4. **`/api/profile/save` and `/api/intelligence/save` are full replaces with no precondition.** An old tab or a second device
   overwrites newer server data silently. A hash precondition (409 on mismatch) is what makes "a second device sees the same data" true.
5. **No `GET /api/profile` exists.** Intelligence has `GET /api/intelligence/candidate`; scored jobs `GET /api/scoring/jobs` (demo-mode aware).
6. **Paths that would overwrite the master once it is on the server** (all closed in section 5): demo load, `body.profile` /
   `body.intelligence` on discovery and pipeline runs, backup export (appends the client payload over the disk copy), backup restore
   (overwrites wholesale, then `SettingsHome` pushes intelligence back into `localStorage`), Settings clear / reset.
7. **Synchronous readers.** `loadProfile`, `loadIntelligence`, `loadJobs`, `loadAiMemory` are called synchronously by
   `aiContextBuilder.js`, `DashboardHome`, `ResumeLibrary`, `CareerStrategyScreen`, `ProfileContext`'s initial state and the
   pipeline screens. One in-memory client cache (the `applicationsClient.js` pattern) keeps them synchronous after a gated first load, with no `localStorage`.
8. **Coupling between keys decides the order.** `loadProfile` runs migrations and writes them back (`migrateQuestionnaireAnswers`,
   `repairProjectsAnswer`, `ensureCvLibrary`); `migrateOnboardingComplete` reads `loadIntelligence()`; `regenerateIntelligence`
   keeps `scoringWeights` from the browser copy.
9. **The browser jobs copy may already be lossy.** `saveJobs` falls back to a slim copy (no `description`, `llmFacts`, `engineShadow`)
   and then to memory only when the ~5 MB quota is hit. The server file is 5.2 MB for 450 jobs; with the overlay fields in the same key the quota can already have
   been exceeded, so **an overlay may already be lost, and the preview must show that instead of assuming it** (section 2.3).
10. **Chat, usage log and AI cache are decided separately** (section 2.6). Chat stays in memory (Q7, unchanged); the usage log is replaced by the ledger; the AI cache is replaced by a server-side findings store (Q-B, changed by the owner), which supersedes the "cache removed, repeats are paid calls" line of BROWSER_STORAGE_POLICY 2.3 (updated there too).

`data/chat/` (`messages.json`, `rooms.json`, `dm_requests.json`, last touched Oct 15) is an upstream leftover. It has nothing to do with the
AI chat (`job-dashboard-ai-chat`) and nothing here reads or writes it. Left alone; listed so nobody confuses the two.

## 1. Inventory per browser key

Sizes below are **server-side** (the browser cannot be read from here). The browser sizes are measured by the preview (section 3.1).
Class: P personal, J job-search data, U harmless UI.

| # | Key | Store | Holds | Writers | Readers | Server today | Class | Plan |
|---|---|---|---|---|---|---|---|---|
| 1 | `job-dashboard-candidate-profile` | ls | `basicProfile`, `resume` (raw CV text), `repositories`, `questionnaire.answers`, `meta`, `cvLibrary[]` (each with `rawText`, `parsedData`, `analysis`), `defaultCvId`, plus `_confidence`, `_editedFields` | `saveProfile` (via `ProfileContext`, ~15 actions), `restoreProfile`, `loadProfile` write-back, demo load | `loadProfile` in `ProfileContext`, `aiContextBuilder`, pipeline / onboarding screens | `data/profile/candidate-profile.json`, 65 KB, mirror written by `POST /api/profile/save` (drops `_confidence` / `_editedFields`); `candidate-profile.bak-q4.json` 22 KB (old, keep); `cvs/*.pdf` already server-side | P (name, e-mail, phone, links, salary, CV text) | Server master (step 6) |
| 2 | `job-dashboard-candidate-intelligence` | ls | the 14 top-level sections of the intelligence incl. `scoringWeights` (owner-set in Settings) and `meta` | `saveIntelligence` (profile screens, review, weights panel, CV apply, demo, restore) | `loadIntelligence` (screens, `regenerateIntelligence`, `migrateOnboardingComplete`, `aiContextBuilder`, `PipelineOrchestrator`) | `data/intelligence/candidate-intelligence.json`, 11 KB, mirror via `POST /api/intelligence/save`; `GET /api/intelligence/candidate` | P (narrative, examples, salary) | Server master (step 5) |
| 3 | `job-dashboard-discovered-jobs` | ls | `{ meta, jobs[], filters, importedAt, slim? }`; each job = pipeline fields + browser-only `status`, `outreach`, `tailoredAssets`, `aiInsights`, legacy `applicationTracking` | `saveJobs` (4 screens' effects), `importJobsFromFile`, `updateJob*`, `loadDemoData` | `loadJobs` in 6 screens, `aiContextBuilder`, `backupClient`, `ApplicationMigrationPanel` | `data/jobs/scored_jobs.json` 5.2 MB / 450 jobs, rewritten by `run_scoring.py`; has `status` only; `discovered_jobs.json` 4 MB, `job_history.json` 14.5 MB (pipeline-owned) | P (outreach: recruiter names, e-mails, LinkedIn) + J | Split: pipeline file stays, new Node-owned overlay (step 4) |
| 4 | `job-dashboard-pipeline-state` | ls | last-run timestamps, counts, `runningStep` | `PipelineOrchestrator`, `JobDiscoveryScreen`, `usePipelineAutoRefresh` | `JobDiscoveryScreen` | `/api/pipeline/health` (counts, `generatedAt`, mtime), `pipeline_last_run.json` 1.5 KB, `.pipeline.lock` | J | Derived, no store (step 2) |
| 5 | `job-dashboard-ai-memory` | ls | goals, preferred companies / industries, strengths, weaknesses, recommended skills, lessons | `mergeFeatureIntoMemory` in `aiClient.js` after each AI feature | `loadAiMemory` in `aiContextBuilder`, `CareerStrategyScreen` | nothing | P (derived from AI output about the owner) | Server file (step 3) |
| 6 | `job-dashboard-ai-cache` | ls | AI responses by hash, 7-day TTL, max 200 | `aiResponseCache.js` | `aiClient.js` | the gate ledger, `data/cache/*` (different things) | P (responses quote the ad and profile) | Removed and replaced by the server AI findings store (step 2b, section 2.8); the browser entries are not migrated |
| 7 | `job-dashboard-ai-usage` | ls | per-call token / cost estimates, last 400 | `aiUsageTracker.js` | `AIUsageDashboard` | `data/ai/usage-ledger.jsonl`, `GET /api/ai/usage` (the truth; **`data/ai/` does not exist yet on this server**: budget 0, no calls made) | J | Dropped; dashboard reads the ledger (step 2) |
| 8 | `job-dashboard-ai-chat` | ss | last 50 chat messages | `AICommandCenter` | same | nothing | P | In memory only (Q7) (step 2) |
| 9 | `job-dashboard-outreach-index` | none | constant, nothing written | - | - | - | - | Delete constant (step 2) |
| 10 | `job-dashboard-ai-settings`, `linkedin_li_at` | ls | legacy; already server-side (steps 2-4) | read-and-remove only | `aiSettings.js`, `linkedinCookie.js` | `data/secrets/`, `data/config/ai-settings.json` | S / U | Stay until the generic scrub (step 7) |
| 11 | active-view, jobs-tab, sidebar-collapsed, theme, demo flag | ss / ls | UI state | | | | U | Allowlisted, unchanged |

`filters` (inside key 3) are UI state, but `searchText`, `minSalary`, `desiredSalary*` fail the allowlist rule (a salary figure is personal).
They leave the jobs key; see Q-D.

## 2. Target design per key

Common to every new server file:

- **Module per store with a `root` argument** (the way `application-store.js` takes `root`), so tests run on a temp data directory. No store module reads `process.cwd()`.
- **Shared writer.** Lift `writeAtomic` (temp file in the same directory, fsync, rename, best-effort directory fsync) and `withLock` (per-directory promise chain) out of `application-store.js` into `scripts/atomic-store.js`; `application-store.js` imports them (pure refactor, its tests must stay green). Profile / intelligence / overlay / memory writes use them; `save-profile.js` and `save-intelligence.js` keep their CLI entry but call the new module.
- **Version = sha256 of the canonical bytes on disk** (section 3.2). Reads return `{ doc, sha256 }`. Writes take `baseSha256` and answer **409 `{ code: "stale", current: { doc, sha256 } }`** when the file changed since (a stale tab, a second device). A missing file has `sha256: null`; the first write needs `baseSha256: null`.
- **No destructive route.** No `DELETE`, and no route that replaces a document with an empty one. "Reset profile" becomes a new document version written through the same guarded route after a typed confirmation, with the previous bytes copied to `data/backups/` first (section 5.5).
- **Unreadable or malformed file = error 500, file untouched, no fallback to defaults** (the tracker rule). A missing file is the empty state, never filled from `data/examples/` outside explicit demo mode.
- **Browser loads** by `GET`, into the in-memory client cache (section 2.7). Nothing is cached in `localStorage` or `sessionStorage`.

### 2.1 Profile (step 6, last)

- **Path:** unchanged, `data/profile/candidate-profile.json` (Python and `save-profile.js` already use it). Same shape as data-shapes.md "Candidate profile", plus the browser-only fields it lacks today.
- **`_confidence` / `_editedFields`:** kept in the file (small, no personal text, `markFieldEdited` and the extraction confidence badges need them across devices). Proposed shape addition: `"_confidence": { "<field>": "<string>" }`, `"_editedFields": { "<field>": true }`. Python ignores unknown keys (to be verified by a test: the scoring run on a profile with both keys). See Q-E.
- **Routes (new):**
  - `GET /api/profile` -> `{ profile, sha256 }` or `{ profile: null, sha256: null }`.
  - `PUT /api/profile` `{ profile, baseSha256 }` -> normal save: server stamps `meta.updatedAt`, writes atomically, answers `{ profile, sha256 }` (the browser replaces its in-memory copy with the answer, like the tracker). 409 stale as above. The old `POST /api/profile/save` is kept for the CLI / Python callers until step 6 ships, then answers 410-style "use PUT /api/profile" (not removed from tests until then).
  - `POST /api/profile/migrate/preview` and `/migrate` (section 3).
- **Load-time normalisation moves to a pure function, not to the read.** `loadProfile`'s migrations (`migrateQuestionnaireAnswers`, `repairProjectsAnswer`, `ensureCvLibrary`, `migrateOnboardingComplete`) stay browser code (`normalizeProfile(raw, intelligence)`, extracted unchanged, pure). They run on the loaded document in memory; the result is saved through `PUT` **only when it differs** and only after the first user action, never silently during load. This removes today's write-during-read.
- **Browser:** `ProfileProvider` initial state comes from the client cache after the gated load; `saveProfile` becomes `await putProfile(next)` with optimistic state and rollback to the server's answer on 409 / error (a visible "profile changed elsewhere, reloaded" notice, never a silent overwrite).
- **Python:** unchanged path and shape; `profileVersion` / `updatedAt` semantics unchanged.

### 2.2 Intelligence (step 5)

- **Path:** unchanged, `data/intelligence/candidate-intelligence.json`; shape unchanged.
- **Routes:** `GET /api/intelligence/candidate` (exists; gains `sha256` in an envelope `GET /api/intelligence` -> `{ intelligence, sha256 }`; the old route stays for Python / demo callers), `PUT /api/intelligence` `{ intelligence, baseSha256 }`, `POST /api/intelligence/migrate/preview` + `/migrate`. `POST /api/intelligence/save` is kept until step 5 ships, then redirects to the guarded path.
- **`scoringWeights` are the one owner-set field**, and `regenerateIntelligence` reads the previous copy to keep them. After the move it reads the **in-memory cache** (loaded from the server), so a regeneration on a second device keeps the same weights. Test in section 6.
- Intelligence is derived data, but regeneration is not free (AI-free, but `previousIntelligence`-dependent), so it migrates by the full protocol, not by "just regenerate".

### 2.3 Jobs (step 4): pipeline file + owner overlay + server-side join

Three parts with one owner each.

| Part | File | Owner | Holds |
|---|---|---|---|
| Pipeline output | `data/jobs/scored_jobs.json` (and discovered / history) | Python only | job facts, scores, `meta`; **never** gets owner state |
| Owner overlay | `data/jobs/job-state.json` (new) | Node `scripts/job-state-store.js` only | owner state per job |
| Joined view | none (computed) | `GET /api/jobs` | pipeline job + overlay, the shape `loadJobs().jobs` has today |

`job-state.json`:

```json
{
  "version": 1,
  "updatedAt": "<ISO timestamp>|null",
  "jobs": {
    "<matchKey>": {
      "jobId": "<string>",
      "status": "new|saved|rejected|applied_manually",
      "statusAt": "<ISO timestamp>|null",
      "tailoredAssets?": "<same as today>",
      "aiInsights?": "<same as today>",
      "outreach?": "<same as today, incl. contacts, messages, activity>",
      "applicationTracking?": "<legacy object, carried verbatim until TRACKER S4>",
      "record?": "<full job record, only for a job the browser had and scored_jobs.json does not>"
    }
  }
}
```

- **`matchKey` is exactly `jobMatchKey` of today** (`url:<lowercased trimmed jobUrl>`, else `tcl:<title>|<company>|<location>` lowercased). `jobId` is stored for display and for the Python-side tailoring paths (`data/resumes/<jobId>/`), never as the join key.
- **The join keeps `mergeStatusOnImport`'s semantics, moved to one server function `joinJobs(scoredJobs, overlay)` (shared pure module, also tested against the old function on a fixture):**
  - `status` and `applicationTracking`: the **overlay value wins** (preserved value), default `'new'`;
  - `tailoredAssets`, `aiInsights`, `outreach`: the **incoming (pipeline) value wins when it has one**, else the overlay's. The pipeline never writes these, so in practice the overlay supplies them; the rule is kept so behaviour does not change if a future pipeline field appears.
  - `record` entries (browser-only jobs, e.g. a hand-imported file) are appended when no pipeline job has their key.
- **Orphans (Q-J, decided): kept, shown as history / recovery, never as active jobs.** The old merge dropped the preserved state of a job that left the list (the browser replaced `jobs` with the incoming ones). The overlay keeps an entry whose job vanished from `scored_jobs.json` (the ad closed or was pruned). `joinJobs` returns the joined active list `jobs[]` **without** orphans and a separate `orphans[]` (entries with no pipeline job, excluding `record` entries, which are active browser-only jobs); `GET /api/jobs` carries `orphanCount`, and `GET /api/jobs/orphans` lists them for **Settings > Privacy > Job history (recovery)**: a read-only list (title / company from the last known `record` or `jobId`, status, counts of outreach contacts, messages and tailored assets, last update) with an export of one entry as JSON. Orphans never appear in the job table, the board, the statistics or any AI context. If the ad reappears under the same `matchKey` the entry rejoins automatically. Nothing deletes an orphan: no route and no button; pruning is a manual script, like a tracker purge. Growth is bounded by what the owner does (outreach text is the large part).
- **Routes (new):**
  - `GET /api/jobs` -> `{ meta, jobs[] (joined, active only), orphanCount, importedAt?, overlaySha256, scoredMtime }`; `GET /api/jobs/orphans` -> the history / recovery list (Q-J). Demo mode answers from the demo bundle as `/api/scoring/jobs` does.
  - `PATCH`-free: `POST /api/jobs/:matchKey/state` `{ patch, baseOverlaySha256? }` merges allowed fields (`status`, `tailoredAssets`, `aiInsights`, `outreach`) into one entry under the lock and answers the entry. `applicationTracking` is **not** writable (the tracker store owns it; TRACKER S2 already blocks the writes). `:matchKey` is URL-encoded in the path or sent in the body (`POST /api/jobs/state` `{ key, patch }`) to avoid path-escaping `|`.
  - `POST /api/jobs/migrate/preview` + `/migrate`.
  - The auto-refresh (`usePipelineAutoRefresh`) polls `/api/pipeline/health`, then `GET /api/jobs`; `importJobsFromFile` and `mergeStatusOnImport` leave the pipeline-refresh path (they remain only for the hand-import of a JSON file, which becomes `POST /api/jobs/import` writing `record` entries; Q-F).
- **`filters`:** UI state leaves the jobs document (Q-D, decided): **React state only**. No browser key, no allowlist entry; a reload resets them. `searchText`, `minSalary`, `desiredSalaryMin` and `desiredSalaryMax` are never stored anywhere (the salary defaults still come from the profile when the filter is `null`). The `filters` field of an old browser jobs key is counted in the preview and discarded when the key is removed (it is not migrated).
- **The pipeline never sees the overlay.** `run_scoring.py` is not changed. A scoring run can no longer erase owner state because it never held it.
- **`run_scoring.py`'s non-atomic write** is a separate, small Python fix (write to temp + `os.replace`), proposed as step 4a because a half-written `scored_jobs.json` would break `GET /api/jobs`. It touches no data and no scoring decision.
- **Size:** the overlay is small (status, a few KB of outreach per job). `GET /api/jobs` returns the 5.2 MB file joined; same payload as `GET /api/scoring/jobs` today. No pagination in this step.

### 2.4 AI memory (step 3)

- **Path:** `data/ai/memory.json` (git-ignored with the rest of `data/`; **include in backups**, the file is personal-data-derived and small). Shape = `getDefaultMemory()` plus `version` and `updatedAt`.
- **Routes:** `GET /api/ai/memory` -> `{ memory, sha256 }`, `PUT /api/ai/memory` `{ memory, baseSha256 }`. `mergeFeatureIntoMemory` becomes a server-side merge `POST /api/ai/memory/merge` `{ featureId, result }` under the lock, so two tabs appending lessons cannot lose each other's lines (dedupe-append is order-independent, which makes it safe).
- **Privacy:** the memory is derived from AI output and is used as context for later AI calls. It goes through `ai-redact.js` like every context (unchanged). It never holds contact names (the output schemas do not carry them); the migration preview shows the lists and the owner confirms.
- `data/ai/` does not exist on this server today; the budget gate treats a missing `data/ai/settings.json` as budget 0. Creating `memory.json` there must not make the gate think settings exist: the gate reads only its own files (test).
- **Decided (Q-C): kept as a server file.** Dropping it is no longer an option in this plan.

### 2.5 Pipeline state (step 2): derived, no storage

`derivePipelineStateFromHealth(health, jobs)` already computes everything but `runningStep` and `lastTailoringRun`. `runningStep` comes from `.pipeline.lock` (add `running: boolean` and the lock's mtime to `/api/pipeline/health`); `lastTailoringRun` from `/api/tailor/status` (`tailoring` already in health). No new file, no new write route.

### 2.6 AI cache, usage log, chat history: what "server master" means for them (revised: Q-B changed)

The brief lists these under "server becomes the master". Result per key:

| Key | Result |
|---|---|
| `job-dashboard-ai-usage` | Removed (step 2). `AIUsageDashboard` reads `GET /api/ai/usage` (the ledger: provider, model, class, tokens, cost, feature, jobId). The browser estimator `aiCostEstimator` stays only for the pre-call estimate. The "Clear browser usage log" button is removed (no destructive route; the ledger is append-only). |
| `job-dashboard-ai-cache` | **Removed and replaced by the server-side AI findings store (step 2b, section 2.8)** (Q-B, changed by the owner). The browser keeps no response cache; the server answers a repeat from a stored finding **before** the budget gate reserves anything, so a hit costs nothing. A repeat call happens only when the input changed or the finding is stale. The Python judge, matcher and CV analysis keep their own content-hash caches under `data/cache/` (unchanged, not merged into the findings store). |
| `job-dashboard-ai-chat` | In component state only (Q7, **unchanged**). The chat call already passes `skipCache: true`, so chat is neither looked up in nor written to the findings store; a reload loses the conversation. |
| `job-dashboard-outreach-index` | Dead constant deleted (step 2). |

**Conflicts with earlier decisions, resolved here and recorded in BROWSER_STORAGE_POLICY (sections 1.1 row 9, 2.3, 7 row 5, 8):**
- **Q7 (chat in memory only): no conflict.** Chat is not an entity and is never stored.
- **Policy 2.3 "Removed outright ... AI response cache (9)" and 1.1 row 9 "Remove. Server already has `data/` caches and the ledger":** superseded. The cache is still removed *from the browser*, but its job is taken over by a persistent server store, not by nothing. The sentence "each repeat is a real, budget-gated call" no longer holds.
- **Principle 14 / the redaction rule:** unchanged and applied twice (section 2.8: nothing identifying is sent, nothing identifying is stored).
- **"Every real model call goes through the gate":** a findings hit is not a model call, so nothing is reserved and no ledger row is written; the call path for a miss is unchanged (section 2.8, test I14).

### 2.7 How the browser loads server state (no localStorage cache)

One module `src/modules/serverState/serverStateClient.js`, built like `applicationsClient.js`:

- State `{ status: 'idle'|'loading'|'ready'|'error', profile, intelligence, jobs, memory, shas, error }`, `subscribe`, `getServerState`, `refresh(kind)`, `put*` functions that replace the cached document with the server's answer and leave it unchanged on failure.
- **`loadProfile()` / `loadIntelligence()` / `loadJobs()` / `loadAiMemory()` keep their names and synchronous signatures** but read from this cache (and throw/return the empty state while `status !== 'ready'`). This is what keeps `aiContextBuilder.js`, `DashboardHome`, `ResumeLibrary`, `CareerStrategyScreen` unchanged. The writers (`saveProfile`, `saveIntelligence`, `saveJobs`) become async and return the server's answer.
- **App shell gate:** until the first load is `ready`, the app renders a loading screen; on `error` it renders "The server is not reachable. Nothing is shown from this browser." with a Retry button. **No fallback to a browser copy and no empty-state rendering on error** (an empty cache would make the owner think the profile was lost, or invite a first-run wizard that overwrites it). This is the same rule the tracker uses (`loading` / `error` show no form).
- **Refresh (version polling, Q-I, decided):** on window focus and every 30 s while the jobs screens are open (the existing poll), the client re-reads `sha256`s (`HEAD`-style cheap `GET /api/state/versions` -> `{ profile, intelligence, jobsOverlay, scored, memory }` hashes); a change triggers a reload of that document, and a pending local edit that raced it is rebased or surfaced as the 409 notice. This is what makes a second device see the same data without a manual reload.
- **API unavailable** (Q-G, decided): the current `ensureApiAvailable` path returned `{ ok:false }` and the app worked from `localStorage`. After step 5 the app **requires** the server, with **no silent browser fallback** and no read-only copy (it already needs it for backups, tracker, AI and the pipeline). The README states it. Demo mode without a server keeps working from the bundled examples **in memory only**.

### 2.8 The server-side AI findings store (new, step 2b)

Replaces the browser AI response cache and goes further: it is a **persistent record of what the AI has said about each entity**, not a 7-day cache. Written and read only by the Node server (`scripts/ai-findings-store.js`, takes `root`), called from `run-ai.js`. No browser storage of any kind.

**First slice shipped (2026-10-29, commit "AI findings store, first slice").** Only entity `job` and feature `jobAnalysis`; everything else in this section is still to do. Differences from the text below, all small:
- The job entity key is `sha256(jobId)` first 16 hex: the context carries `jobId`, not the `url:` / `tcl:` match key. A job without a `jobId` is not stored.
- A finding stores the cache key and the input hash, never the prompt text (as in the plan above). Identifier check and credential check run on the answer before it is stored.
- Freshness: `DEFAULT_FRESHNESS_DAYS.jobAnalysis = 7`, the TTL of the browser cache it replaces; no override file yet. `PROMPT_VERSIONS.jobAnalysis = "1"`.
- The manifest is taken from the redacted context: job posting, job scores, job stage, profile summary, AI memory. The jobAnalysis context carries no user-confirmed facts yet.
- Not done: the `mock` provider is never stored; `refresh: true` (request body, sent by "Regenerate" as `skipCache`) skips the lookup; the browser cache is still in front of the server; no `GET /api/ai/findings`, no backup rules, no other features or entities, no `atomic-store.js` (step 1 is not in the tree, so the store has its own atomic write; appends are synchronous in one process).

**Entities and records.** One record per entity; findings are appended, never edited or removed.

| Entity type | Entity key (opaque, no personal text) | Features that write to it |
|---|---|---|
| `job` | `sha256(jobMatchKey)` first 16 hex (the same `url:` / `tcl:` key as the overlay) | `jobAnalysis`, `coverLetter`, `interviewPrep` |
| `company` | `sha256(lowercased trimmed company name)` first 16 hex | `companyIntelligence` |
| `contact` | `sha256(contact identity)` first 16 hex, computed in memory from the LinkedIn URL or name and never stored | `outreach` |
| `resume` | `sha256(resumeVersionId)` first 16 hex | general CV analysis: `resumeEnhancement` in its general mode (Q-N) |
| `resumeJob` | `sha256(resumeVersionId + ":" + jobMatchKey)` first 16 hex | job-specific `resumeEnhancement` (Q-N) |
| `candidate` | the fixed key `candidate` | `careerStrategy`, `skillGap`, `applicationStrategy` (Q-M) |

**Resume version identity (`resumeVersionId`).** `<cvLibrary id>:<sha256 of the CV text, first 16 hex>`. Editing or replacing the CV text gives a new identity, hence a new record; the old record stays as history. Resume enhancement is **not** bound only to a job (Q-N, changed): general analysis is keyed by the resume version alone, job-specific enhancement by resume version + job posting. The Python CV analysis keeps its own cache under `data/cache/` (unchanged).

Chat has no entity (Q7).

**Path and shape** (git-ignored with the rest of `data/`, one file per entity, written with `atomic-store.js` under a per-directory lock; a malformed file is an error and is never overwritten):

`data/ai/findings/<entityType>/<entityKey>.json`

```json
{
  "version": 1,
  "entity": { "type": "job|company|contact|resume|resumeJob|candidate", "key": "<16 hex>", "label?": "<string: job title and company, company name, CV label; never for a contact>" },
  "findings": [
    {
      "id": "<entityKey>:<seq>",
      "seq": 1,
      "at": "<ISO timestamp>",
      "feature": "<string>",
      "provider": "<string>",
      "model": "<string>",
      "promptVersion": "<string>",
      "inputHash": "<sha256 hex of the canonical redacted messages>",
      "cacheKey": "<model>|<promptVersion>|<inputHash>",
      "finding": "<the parsed result object the feature returns>",
      "source": "model"
    }
  ]
}
```

- `findings` only grows at the end; `seq` runs 1..n; an `assertAppendOnly` check (the tracker's pattern) runs before every write. There is no update and no delete route. `source` is `model` today (reserved for a later `user_edit`).
- **The cache key is `model + prompt version + input hash`**, as decided. `provider` is recorded on the finding but is not in the key. The input hash is over the **redacted** messages (the same text that would be sent) **and a declared input manifest**: the sha256 of each input the feature depends on (table below), so an input that changes but does not reach the prompt text still invalidates, and nothing is hashed that the feature does not use. It never contains an identifier. A change in the resume, the job posting or a user-confirmed fact therefore always misses the matching finding; the old finding stays as history.

**Inputs per feature** (the manifest; the exact fields are fixed from `aiContextBuilder.js` when step 2b is built, and test I17 fails if a feature's context reads an input that is not listed here). All features also depend on the model and `PROMPT_VERSIONS[feature]`.

| Feature | Entity | Inputs in the key |
|---|---|---|
| `jobAnalysis` | `job` | job posting text; the job's scores and stage; profile summary; user-confirmed facts; AI memory entries sent |
| `coverLetter` | `job` | job posting text; profile summary; resume version identity (CV text hash) if the CV is sent; user-confirmed facts; AI memory entries sent; tone / options in the request |
| `interviewPrep` | `job` | job posting text; the job's scores and stage; profile summary; user-confirmed facts; AI memory entries sent |
| `companyIntelligence` | `company` | company name; job posting text if sent; AI memory entries sent |
| `outreach` | `contact` | the contact's role and relation (identity only as a placeholder); job posting text; profile summary; user-confirmed facts; message options |
| `resumeEnhancement`, general | `resume` | resume version identity (CV text hash); profile summary; user-confirmed facts; AI memory entries sent |
| `resumeEnhancement`, job-specific | `resumeJob` | resume version identity; job posting text; profile summary; user-confirmed facts; AI memory entries sent |
| `careerStrategy`, `skillGap`, `applicationStrategy` | `candidate` | profile summary; intelligence digest; user-confirmed facts; the job set or scores the feature reads; AI memory entries sent |

"User-confirmed facts" are the owner's confirmed answers and gate values. They are an input only where the feature's context carries them; where it does, a changed fact changes the hash.
- **Prompt versions are a new dependency:** `aiPromptLibrary.js` has no version today. Each feature gets a `PROMPT_VERSIONS[feature]` constant (a string bumped by hand when its prompt or output schema changes; a test fails if a prompt's text hash changes without a bump).

**The lookup runs before the budget gate reserves anything.** In `run-ai.js` `runAiFeature`, the order becomes: read selection -> redact and `assertClean` -> **compute `inputHash`, look up `(entity, cacheKey)`** -> on a fresh hit return it -> only on a miss: key check -> `reserveAiCall` -> provider -> `finishAiCall` -> parse -> **append the finding**. A hit therefore reserves nothing, makes no provider call and writes no ledger row; it works without an API key. The response carries `cached: true`, `findingId`, `foundAt`. A repeat call happens **only when** (a) no finding with that `cacheKey` exists (the input, model or prompt version changed), or (b) the matching finding is stale (older than the retention period), or (c) the user explicitly asks for a fresh answer (`refresh: true`, replacing `skipCache`; still redacted and gated like any call; it appends a new finding and never replaces the old one).

**Retention (configurable; Q-L decided).** Retention is a **freshness window** with **built-in defaults in code** (per feature, a `DEFAULT_FRESHNESS_DAYS` table in `ai-findings-store.js`; the initial values are proposed in the step 2b change and shown to the owner, no value is decided here). The owner edits them in Settings > AI; the edits are stored in `data/config/ai-findings.json` -> `{ "version": 1, "freshnessDays?": <number 1..3650>, "perFeature?": { "<feature>": <number> } }`, which holds **overrides only**: with no file the defaults apply (the earlier "no file = no hits" rule is withdrawn). Not added to `ai-settings.json` (its Python validator rejects unknown keys and is shared with the pipeline). **Expiry means a cache miss only**: a finding older than its window is *stale* (not served as a hit, shown as history) and a new call appends a new finding. **Records are never deleted automatically**; physical removal is a manual script, as for the tracker and Q-H.

**Privacy (principle 14).**
- No API key, base URL, cookie or secret is ever in a finding (the store has no access to the secret store; a test seeds the canary and searches the files).
- **Contact data is redacted before it is sent and before it is stored.** The prompt is built from `redactContext` output (contact name is the placeholder `[CONTACT NAME]`; e-mails, phones, profile links are removed by `ai-redact.js`). The input itself is never stored, only its hash. Before an append, the finding text is scanned with the same identifier check (`assertClean` against the owner's and every known contact's identifiers); on a hit the finding is **not stored** (the call result is still returned once, with a warning), so a model echo of an identifier cannot reach disk. The `contact` entity key is a hash and has no `label`.
- The findings are still personal-data-derived (they describe the owner and the ads): they live under `data/ai/`, are git-ignored, included in backups (section 4.4), and never leave the server except as context for a later call, through the same redaction step as every context.

**Browser:** `aiClient.js` drops `getCachedResponse` / `setCachedResponse` / `buildCacheKey` / `aiResponseCache.js`, sends `refresh` instead of `skipCache` where the owner pressed "Regenerate", and shows "from stored finding, <date>" when `cached` is true. The AI settings panel replaces "Clear cache" with a read-only count per entity type (no destructive button). New read route: `GET /api/ai/findings?type=<type>&key=<key>` -> the record (used for a history view); no write route is exposed, the only writer is `run-ai.js`.

**Proposed `data-shapes.md` block** (section 8 item 1): section **AI findings** with the path, the JSON above, the retention file shape, and the line "Written only by `scripts/ai-findings-store.js` from `run-ai.js`; append-only; contains no secret and no contact identifier."

**Migration and rollback.** Nothing is moved from the browser: the old cache entries are keyed by a hash of the un-redacted prompt and may quote identifiers, so they cannot match a new input hash and are not migrated. Step 2b removes the browser cache code and does a one-time `removeItem` of `job-dashboard-ai-cache` (derived data, rebuildable); `TOLERATED_UNTIL_MIGRATED` loses its entry. There is no preview and no confirmation because no owner data is moved. The store starts empty and a zero-data run is the normal case. **Rollback:** revert the commit. The files under `data/ai/findings/` stay on disk, harmless and unread; deleting the directory is a manual action. Because there is no browser copy to restore, the cost of a rollback is only that repeat calls are paid again (the pre-step-5 behaviour had a 7-day browser cache; the gap is the same as Q-B's original option). A corrupted file is never overwritten; the store reports the entity as unreadable and the call is treated as a miss (the finding is not appended to the damaged file).

**New dependencies and conflicts (full list):**
1. Per-feature `PROMPT_VERSIONS` in `aiPromptLibrary.js` (no version exists today).
2. `scripts/atomic-store.js` (step 1) for atomic append and the lock.
3. A hook point in `run-ai.js` between redaction and `reserveAiCall` (and before the "No API key" return). `ai-gate.js` and `python/llm/ai_gate.py` are **not** changed; the gate is simply not reached on a hit. No ledger row for hits.
4. `ai-redact.js` identifier check reused for the finding scan (a new exported helper that returns the check without throwing).
5. `data/config/ai-findings.json` and a Settings control (retention); not in `ai-settings.json`.
6. Backup export / restore: `data/ai/findings/` included; restore merges by finding `id` (append-only union) and never overwrites; `secret-paths.js` unchanged (no secret names).
7. Conflicts: Q7 none; policy 2.3 and row 9 superseded (updated); "chat `skipCache`" kept as the rule that excludes chat; the Python judge / matcher / CV-analysis caches are separate and stay (possible later unification is out of scope).
8. A stale or old finding can be wrong after the ad or profile changed *without* changing the redacted input (it cannot: the hash covers the input); a model or prompt-version bump forces a new call by key.

## 3. Migration protocol (one protocol, per key; profile, intelligence, jobs, memory)

Reuses the tracker's (TRACKER_PLAN 2.1, 6d) and the AI-settings step's (BROWSER_STORAGE_POLICY 11b) pattern, with the stronger "browser copy is removed only after a verified write" rule of section 2.3. Each key has its own `migrate/preview` and `migrate`, so steps ship independently.

### 3.1 Preview (writes nothing)

`POST /api/<kind>/migrate/preview` with `{ browser: <the raw parsed browser document>, browserBytes: <number>, browserKeyPresent: <boolean> }`. The server computes and returns:

- **State**: one of `empty-both`, `browser-only`, `server-only`, `identical`, `browser-newer`, `server-newer`, `diverged` (both non-empty, canonical hashes differ, and neither contains the other: see 3.4).
- **Counts per side** (field-level, the same function for both): profile: `cvLibrary` entries, per-CV `rawText` length, `questionnaire.answers` count and non-empty answers, `targetRoles`, `preferredLocations`, `languages`, `workAuthorization.holds`, `repositories.githubLinks`, `_editedFields` keys, `meta.updatedAt`; intelligence: item count of every list, `scoringWeights` (the six numbers), `meta.generatedAt`; jobs: scored jobs in file, overlay entries by `status`, jobs with `outreach` (contacts / messages / activity), with `tailoredAssets`, with `aiInsights`, with legacy `applicationTracking`, browser-only jobs (no match in `scored_jobs.json`), `slim` flag, `filters` present; memory: items per list.
- **Sizes**: `browserBytes` (measured in the browser: `new Blob([raw]).size`), server file bytes, and the localStorage total for the origin, so the owner sees whether the jobs key was already slimmed (`slim: true`) or absent.
- **`canonicalSha256` of each side** and **`previewSha`** = sha256 of the canonical JSON of the posted `browser` document (exactly the tracker's rule: apply is refused unless the same input was previewed).
- **Warnings**: browser copy is `slim` (descriptions and `llmFacts` missing: the server's file is the authority for those, the overlay is still taken), `meta.updatedAt` older than the server, jobs in the browser with no server match, an overlay field present on the server already.
- **What would be written**, as a list, and which side "wins" per rule in 3.4. A zero-data browser (`browserKeyPresent: false`) is a valid preview: `empty-both` or `server-only`, "nothing to move".

### 3.2 Canonical form and the verified write

- **`canonicalize(doc)`** (`src/modules/serverState/canonical.js`, pure, shared by browser and server, in a path both can import as `application-store.js` already imports from `src/`): JSON with object keys sorted recursively, arrays in order, `undefined` dropped, numbers as `JSON.stringify` gives them, two-space indent, trailing newline. The server stores exactly these bytes.
- **The migration write is pure**: it stamps nothing and drops nothing (`_confidence`, `_editedFields`, `meta.updatedAt` all kept as the browser has them). The normal `PUT` stamps `updatedAt`; the migration `POST` does not, so the hashes can match.
- **Order, under the store lock, stopping at the first failure:**
  1. Check `previewSha` equals the sha of the posted document now (409 `no_preview` otherwise; nothing written).
  2. Check the server file's current sha equals the `serverSha256` the preview returned (409 `server_changed`: someone wrote in between).
  3. **Backup**: copy the current server file (if any) to `data/backups/step5-<kind>-<YYYYMMDD-HHMMSS>[-n]/<name>` and write `browser-document.json` (the posted document, re-serialised). If the backup write fails, nothing else happens.
  4. Compute the new server document by the conflict rule (3.4). For `browser-only` / `server-empty` it is the browser document.
  5. Write atomically.
  6. **Re-read the file from disk**, canonicalise, compute sha256 and the field counts of 3.1.
  7. `verifyMigration(browserDoc, storedDoc, rule)`: the field-level assertions below; on failure restore the pre-write bytes from step 3 and answer 500 with the failed assertion.
  8. Append the run to `data/<dir>/migration-step5.json` (`{ version, runs: [ { ranAt, kind, previewSha, state, counts: { browser, server, stored }, backupPath, rule, result } ] }`, last 50 runs, like `migration.json`).
  9. Answer `{ ok, storedSha256, counts: { before: { browser, server }, after }, backupPath }`.
- **Browser side, only after a 2xx:** compute `canonicalize(browserDoc)` sha256 locally and compare it with `storedSha256` **when the rule was "browser wins"** (they must be equal), or with the sha of the document the preview said would be written (merge rules). Then `GET` the document back (a second, independent read), compare its sha256 with `storedSha256`, and only then `removeItem` the key and read it back to confirm it is gone. Any mismatch or error: the browser key is not touched, the reason is shown, the run stays in `migration-step5.json` as failed.
- **Field-level assertions** (`verifyMigration`): every count in 3.1 equal between the chosen source and the stored document; profile: every `cvLibrary[i].rawText` byte-equal, every questionnaire answer equal, `_editedFields` equal; intelligence: `scoringWeights` equal, every list equal; jobs: for every overlay entry in the browser, the stored entry equals it field for field, the number of entries with outreach contacts equals, `record` kept for every browser-only job; memory: lists equal. **A count that went down is always a failure**, never a warning.
- **Idempotent:** a second run on the same input is `identical`; the preview says "nothing to write", apply writes no document and no backup, only logs the run (the bytes of the document and its sha are unchanged, as in tracker 6d).
- **Lossless:** nothing in the browser document is dropped on the way in (section 3.4 appends rather than replaces).
- **Works with zero data:** `empty-both` and `server-only` previews are valid; apply with `empty-both` writes only `migration-step5.json` and then lets the browser remove an absent key (a no-op). `server-only` removes nothing server-side and nothing in the browser.
- **The key is removed by an owner button per key** ("Move to server and remove from this browser"), never automatically and never as a side effect of a screen load. A second button, "Remove from this browser without moving", exists only for a browser copy the owner has already seen identical on the server (`identical` state) or explicitly chooses to discard after reading the preview (typed phrase).

### 3.3 Where the buttons live

Settings > Privacy gets a "Browser data" section listing each remaining key with its state (nothing / identical / needs move / differs) and the Move button; the same panel shows the allowlist state. The gate is the pre-migration checklist (BROWSER_STORAGE_POLICY section 9); item 1 (no path bypasses Caddy) is the owner's to run before the profile and jobs moves, as for steps 2-3. The panel disables Move for a key whose preview was not run in this session.

### 3.4 A second browser profile with different data (conflict rules, never silent)

The owner has used the app in several browser profiles; each may hold its own version of every key, and the server may hold a third.

- **States and what apply does:**

| State | Rule |
|---|---|
| `empty-both`, `server-only`, `identical` | Nothing to merge. |
| `browser-only` (server file missing or empty) | Browser document is written. |
| `browser-newer` / `server-newer` (by `meta.updatedAt` / `meta.generatedAt`, and one side is a strict superset by the field counts) | Write the newer side; the older is kept in the backup. Preview names the winner and shows the diff of counts. The owner confirms. |
| `diverged` (both have something the other lacks) | **Apply is refused (409 `diverged`)** until the owner picks a rule in the preview: "keep server, keep this browser copy in the backup and remove it", or "replace the server with this browser copy (server copy goes to the backup)", or **"merge"** where a deterministic merge exists (below). No default. |
| second browser after a first migration | The server already holds the data; this browser's copy is `identical` (remove it), `server-newer` (remove it, the server wins, backup written), or `diverged` (the same choice). |

- **Deterministic merges (offered only where they lose nothing):**
  - **Jobs overlay**: per `matchKey`; `status` takes the later `statusAt` (browser entries without `statusAt` count as older than any server `statusAt`, and a conflict on status is listed, not silent); `outreach.contacts / messages / activity` are unioned by their own ids / timestamps; `tailoredAssets` and `aiInsights` take the later `generatedAt` / `updatedAt`; `record` entries are unioned. Every resolved conflict is listed in the run log.
  - **AI memory**: union of the lists (dedupe-append, case-insensitive), the same function `mergeFeatureIntoMemory` uses.
  - **Profile and intelligence: no automatic merge.** They are documents with meaning (a questionnaire answer is not an array). The choices are the two replace options only, with the discarded side kept in `data/backups/step5-.../` and shown field by field in the preview. This is deliberate: a wrong merge of a CV text or a salary is worse than a deliberate choice.
- **Never silent:** a backup is written on every apply that changes an existing server file, and the run log names the rule. Nothing deletes a backup.
- **After the first successful move of a key, the app treats the server as the only source.** A browser profile that still has the key shows the Privacy banner (as for the AI key move) on every load until the owner resolves it; it is never read as data.

## 4. Interaction with discovery, pipeline runs, import, the tracker and backups

### 4.1 Discovery and pipeline runs

- `POST /api/discovery/run` and `/api/pipeline/run` stop reading `body.profile` / `body.intelligence`; the server reads `data/profile/` and `data/intelligence/` (what Python reads anyway). Today the browser pushes its copy in, which is the path that would let a stale browser overwrite the master. Once step 6 ships the bodies' profile / intelligence fields are ignored (rejected if present, 400, so a stale client fails loudly). `PipelineOrchestrator` stops calling `saveProfileToDataDir` / `saveIntelligenceToDataDir` before a run.
- `/api/tailor/run`, `/api/jobs/import-url`, `/api/outreach/*` take `profile` from the body today (`runTailor`, `runJobImport`); same change, read from disk.
- A run takes the existing `.pipeline.lock`; the overlay and the profile are not touched by it, so a run and a save never contend. `GET /api/jobs` during a run reads the last complete `scored_jobs.json` (made atomic by step 4a).

### 4.2 `mergeStatusOnImport` and the import functions

- `joinJobs` (section 2.3) replaces the per-screen `importJobsFromFile(payload, state)` calls in `autoLoadJobs`, `usePipelineAutoRefresh`, `JobDiscoveryScreen` (4 places), `PipelineOrchestrator`, `SettingsHome`. Those components stop merging; they refresh the cache from `GET /api/jobs`.
- `mergeStatusOnImport` and `importJobsFromFile` stay as pure functions for the hand-import of a JSON file (Q-F) and as the reference the `joinJobs` test compares against. They are deleted with the generic scrub if the owner chooses to drop file import.
- **Import never drops server data** (invariant I5): a re-import writes only `record` entries and never overwrites an existing overlay entry's `outreach`, `tailoredAssets`, `aiInsights` or `status` (the keep-on-conflict rule of 3.4 applied per entry).

### 4.3 The application tracker

- The tracker store stays as built (`data/applications/`, append-only, its own lock, its own backup copy before a restore merges). The overlay carries the legacy `applicationTracking` **verbatim and read-only** until TRACKER S4 removes it (the tracker migration preview reads `loadJobs().jobs`, which now comes from the joined view, so `ApplicationMigrationPanel` still sees the legacy objects; its payload and `previewSha` rules are unchanged).
- Order constraint: **do not run the jobs overlay migration before the tracker migration has been run and `unmappable` is 0**, or the legacy tracking object would be moved twice by two protocols. If the owner has already run the tracker migration, the overlay copy of `applicationTracking` is informational (the tracker's `legacy` field holds the original). The jobs preview shows the count of legacy tracking objects and states whether the tracker migration has run (`data/applications/migration.json` present, last run `unmappable: 0`).
- The overlay never writes `applicationTracking` after the migration (`updateJobRecord` already ignores it).
- `trackingView.js` / `overlayTracking` keep working: they take `state.jobs` and the store.

### 4.4 Backups (export and restore)

- **Export includes** `profile`, `intelligence`, `jobs` (incl. `job-state.json`), `ai` (`memory.json`, `findings/`, and the existing `settings.json` / `pricing-overrides.json` / `usage-ledger.jsonl` if present; `data/ai/` added to `DATA_DIRS`), `applications`, `resumes`, `outreach`, `audits`, `cache`. **Excludes** `data/secrets/`, `data/config/` (as today: `ai-settings.json` is non-secret but machine-specific; unchanged), `claude-config/`, `.env`, anything `isSecretPath` matches. `data/backups/` stays excluded (it can be 45 MB and holds older copies; the step-5 backups there are the restore point for a failed migration, not for export).
- **Export stops appending the client payload.** `createBackupStream(root, { profile, intelligence, jobs })` today appends the browser's copy *after* archiving the directories, which makes a zip with two entries of the same name and lets the browser overwrite the disk copy. After step 5 the zip is built from disk only; `backupClient.js` sends no body. Until each key's migration has run, the existing client payload is still appended for that key only (so a not-yet-migrated owner still gets their browser data into the zip), and the zip is built with a de-duplicated entry list (the appended one replaces the directory copy rather than adding a second entry).
- **Old zips are a recovery source.** In zips made before step 5, `data/jobs/scored_jobs.json` holds the **browser jobs state** (`{ meta, jobs[], filters, importedAt }`) instead of pipeline output. This is where an overlay lost to the localStorage quota may still exist. Restore must recognise it (the document has `filters` / `importedAt` and no `meta.scoringVersion`) and **route it to the overlay import**, not drop it over `scored_jobs.json`.
- **Restore** (`importBackupZip`) changes per path:
  - `data/profile/candidate-profile.json`, `data/intelligence/...`: not overwritten blindly. If the target exists and differs, the restore writes the backup copy to `data/backups/step5-restore-<ts>/` first, then applies the diverged / newer rule of 3.4 through the same preview (a restore is a migration whose "browser" side is the zip). The first slice answers `refused: ["data/profile/..."]` with the reason `needs_preview` unless the target is missing or identical, and the Settings screen offers the preview. (Today it overwrites and then `SettingsHome` pushes intelligence into `localStorage`; that push is removed.)
  - `data/jobs/scored_jobs.json`: pipeline output, written only if the zip's file is pipeline-shaped; an old browser-state-shaped one goes to the overlay import.
  - `data/jobs/job-state.json`: merged with the 3.4 overlay rule (never replaces), like the application store's `mergeFromBackup`.
  - `data/ai/memory.json`: union merge. `data/ai/findings/**`: union by finding `id`, never overwritten or removed (an entity file present on both sides gets the missing findings appended; a conflicting `id` with different content is kept from the server and listed). `data/ai/usage-ledger.jsonl`: **never overwritten** (append-only); the restore adds rows not present (dedupe by the row's own fields) or skips it with a listed reason. `data/ai/settings.json`: not restored over an existing one (raising limits needs `confirm`; restore must not bypass it): listed as refused with the reason.
  - The restore keeps `refused` honest: every skipped path is listed with a reason.
- Tests extend `backupSecrets.test.js` (section 6).

## 5. Existing paths that would overwrite the master (and the fix)

| # | Path | Today | Fix |
|---|---|---|---|
| 5.1 | Demo load (`loadDemoData`, `SettingsHome` "Load demo") | writes localStorage, then `saveProfileToDataDir` + `saveIntelligenceToDataDir`: wipes the real profile on the server | Demo mode is a server config (`getAppConfig().demoMode`, exists) that serves the bundle from `/api/demo/bootstrap`, in memory, **writing nothing under `data/`**. "Load demo" in a non-demo server is removed, or refused with 409 when real profile data exists. The `career-os-demo-bootstrap-done` flag stays. |
| 5.2 | `body.profile` / `body.intelligence` on discovery, pipeline, tailor, job import | stale browser overwrites or feeds the run | read from disk (4.1) |
| 5.3 | Backup export client payload | duplicate zip entries, browser over disk | disk only (4.4) |
| 5.4 | Backup restore | wholesale overwrite, then pushes intelligence into `localStorage` | preview rule per path; no `localStorage` push (4.4) |
| 5.5 | Settings "Reset profile" (`resetProfile` -> `clearStorage`), "Clear" in `SettingsHome` (`clearIntelligence`, jobs key removal), "Clear cache" / "Clear browser usage log" in `AISettingsPanel` | remove browser keys (destructive) | No server `DELETE`. "Reset profile / intelligence" writes the default document through `PUT` with `baseSha256`, after a typed confirmation, and the replaced bytes are first copied to `data/backups/step5-reset-<kind>-<ts>/`. "Clear jobs" is removed (the overlay is never deleted; a job can be hidden by `status: rejected`). "Clear cache" and "Clear usage log" disappear with their keys (section 2.6). |
| 5.6 | `ProfileContext` mount effect (`loadProfile()` on mount, `setProfile`) | re-reads localStorage | replaced by the client cache subscription |
| 5.7 | `usePipelineAutoRefresh` `onImport({ ...next, meta })` replaces the whole jobs state in the browser | would overwrite unsaved browser overlay | the overlay lives on the server; the refresh replaces only the pipeline part of the cache |

## 6. Invariants and tests

All offline, on a temp data directory through the `root` parameter, no AI call, no network (pattern of `applicationMigration.test.js`, `secretMigration.test.js`). Browser-side logic is tested the way the tracker's is (`trackerController`-style pure controllers plus an injected `transport`, as `configureClient` allows).

| # | Invariant | How it is tested |
|---|---|---|
| I1 | **A cleared browser loses nothing.** | With the migration done (server files present), a fake `Storage` is emptied; `refresh()` yields profile, intelligence, jobs (joined with overlay) and memory byte-equal (canonical sha) to before. Static test: no `src/**` file reads a non-allowlisted key after step 7. |
| I2 | **A second device sees the same data.** | Two client instances on one temp root: A writes the profile via `PUT`; B's `GET /api/state/versions` poll sees a new sha, reloads, and B's cache equals A's. B's `PUT` with the old `baseSha256` returns 409 `stale` with the current document and does not write (file bytes and mtime unchanged). Same for intelligence, overlay (`status`), memory. |
| I3 | **Import never drops server data.** | Overlay with outreach / tailoredAssets / aiInsights / status for N keys; run `joinJobs` against a `scored_jobs.json` that (a) has the same jobs, (b) lacks some of them, (c) has new ones, (d) is rewritten by a scoring run. Every overlay entry still present afterwards; the old `mergeStatusOnImport` and `joinJobs` give identical results on the shared fixture (the semantics test); a hand-import of a file never overwrites an existing entry. |
| I4 | **The pipeline cannot erase owner state.** | A scoring run (the real `write_text` path against a temp output, or a stub that rewrites the file) leaves `job-state.json` byte-identical (sha). |
| I5 | **Migration is idempotent, lossless, backed up.** | Per key: dry run writes nothing (listing and mtimes of the temp tree unchanged); apply without or with a wrong `previewSha` is 409 and writes nothing; apply writes the backup before the document (backup mtime earlier; an unwritable backup directory leaves the document unwritten); second apply is `identical` and the document bytes are unchanged; `verifyMigration` is run with a deliberately corrupted write (a field dropped) and restores the pre-write bytes; zero data is a valid run. |
| I6 | **Browser key removal only after a verified write.** | Controller test with a transport that fails at each stage (preview, apply 500, hash mismatch, re-read mismatch): the key is present after every failure and absent only after the full success path; order of calls asserted. |
| I7 | **Conflicts are never silent.** | `diverged` is refused (409) without an explicit rule; for each rule the discarded side is in the backup directory byte-for-byte; the run log names the rule; the overlay merge test covers status by `statusAt`, outreach union, assets by date, and lists a status conflict. |
| I8 | **Canonical hash agrees across browser and server.** | One fixture set (profile with `_confidence`, unicode, nulls, nested arrays) hashed by `canonicalize` in the browser module and re-hashed from the file the server wrote; equal. Key-order permutations of the input hash equal. |
| I9 | **Atomic and locked.** | Concurrent `PUT`s with the same `baseSha256`: exactly one 200, the rest 409, file is one valid document; a crash simulated between temp write and rename (the temp file left behind) leaves the target untouched. `application-store.js` tests stay green after the `atomic-store.js` lift. |
| I10 | **Master paths are closed.** | Demo load writes nothing under the temp `data/` (tree unchanged); `discovery/run` with a `profile` body is 400 / ignored and the run reads disk; backup export builds from disk and has no duplicate entry names; restore of an old browser-shaped `scored_jobs.json` goes to the overlay; restore never overwrites `usage-ledger.jsonl` or `data/ai/settings.json`. |
| I11 | **Secrets and privacy unchanged.** | `backupSecrets.test.js` extended: `data/ai/memory.json` and the overlay are in the zip, `data/secrets/` is not; `aiRedaction.test.js` still passes with memory read from the server; the memory file contains no contact name (schema test on the merge). |
| I12 | **Zero-data and load failure.** | Empty temp root: `GET`s answer the empty state, no file is created by a read; unreadable (malformed) profile file: `GET` is 500, the shell shows the error screen, and no write route overwrites it; the app never renders the first-run wizard on a load error. |
| I14 | **A findings hit costs nothing and is checked before the gate.** | `runAiFeature` with a seeded finding and an injected `reserveAiCall` / provider spy: a fresh hit returns the stored finding, `reserveAiCall` and the provider are **never called**, no ledger row is written, and it works with no key. Same input after a model change, a `PROMPT_VERSIONS` bump, a changed input, freshness expiry, or `refresh: true` is a miss that goes through the gate and appends a new finding (the old one is still there). With no `ai-findings.json` the built-in defaults apply; a finding past its window is a miss and is still on disk afterwards (nothing deleted). |
| I15 | **Findings are append-only and contain no identifier or secret.** | `assertAppendOnly` rejects an edit, a removed finding and a `seq` gap; concurrent appends under the lock keep both; a finding that echoes the owner's name, a known contact's name, an e-mail or a link is not stored (call result still returned); the canary key never appears in `data/ai/findings/**`; a `contact` record has no `label` and its key is not derivable without the identity; chat (`skipCache`) writes no finding. |
| I16 | **Findings survive backup and restore, merged.** | Export contains `data/ai/findings/**`; restore into a store with other findings gives the union by `id`, never fewer findings than before; a corrupted entity file is reported and skipped, not overwritten. |
| I17 | **The cache key covers every input.** | For each feature in the 2.8 table: changing the resume text, the job posting, a user-confirmed fact, the profile summary or the memory entries sent (each separately, including a change that does not alter the prompt text) gives a different `cacheKey` and a miss; changing an input the feature does not use gives the same key. The model and `PROMPT_VERSIONS` are in the key. General `resumeEnhancement` (`resume`) is unaffected by a job change; job-specific (`resumeJob`) misses on a change of either the resume version or the posting. A feature whose context reads an input missing from the manifest fails the test. |
| I18 | **A hit never duplicates memory.** | `mergeFeatureIntoMemory` is run twice with the same finding, and once more on a hit: `memory.json` is byte-identical after the first run. If this test cannot be made to pass, the merge is skipped on a hit (Q-O). |
| I13 | **Allowlist.** | `browserStorageAllowlist.test.js` (exists) fails on any key or storage API outside the list; step 7 removes `TOLERATED_UNTIL_MIGRATED` entirely. |

Verification once built (owner runs, commands proposed, not assumed): `npm test`; then per key `Settings > Privacy > Browser data`: run Preview, read counts against the browser's DevTools `localStorage` sizes, Move, and check that the `data/backups/step5-*` directory and `migration-step5.json` appear; clear site data, reload, confirm the same counts; open a second browser profile and confirm the banner and the `server-newer` / `identical` state.

## 7. Smallest first slice and ordered, independently shippable steps (riskiest last)

**First slice = step 1 plus step 2 (derived and removable keys): no personal-data move, no migration, immediately reduces what the browser holds** (usage log, chat history and pipeline state; the AI cache follows in step 2b) **and builds the wrapper that guards every later step.** It touches no profile, intelligence or job file.

| Step | Content | Moves personal data? | Rollback |
|---|---|---|---|
| **1** | Storage wrapper `browserStorage.get/set/remove` over the allowlist (throws in dev / test, drops and logs once in production); ESLint `no-restricted-globals` / `-properties`; the static test of policy 6.1 promoted from "lists the users" to "no use outside the wrapper". Shared `scripts/atomic-store.js` lift (pure refactor of `writeAtomic` / `withLock`). `canonical.js`. | No | revert |
| **2** | Derived and removed keys: pipeline state from `/api/pipeline/health` + lock; usage dashboard reads `/api/ai/usage`; browser usage log removed; chat in memory only; dead `outreachIndex` constant deleted; the "Clear usage" button removed. **The browser AI cache is left in place until step 2b** (so there is never a window with no cache). | No (removes copies) | revert; nothing to restore (derived) |
| **2b** | **AI findings store** (section 2.8): `ai-findings-store.js`, `PROMPT_VERSIONS`, lookup before `reserveAiCall` in `run-ai.js`, append after a successful call, retention file and setting, `GET /api/ai/findings`, backup export / restore rules; in the same commit the browser cache code (`aiResponseCache.js`, `buildCacheKey` use in `aiClient.js`, "Clear cache") is removed and `job-dashboard-ai-cache` is removed once. Tests I14-I18. Needs step 1 (`atomic-store.js`). | New server data (AI output about the owner and ads, redacted); no browser data moved | revert; `data/ai/findings/` stays on disk unread; repeat calls are paid again |
| **3** | AI memory to `data/ai/memory.json` with `GET` / `PUT` / merge routes and the full preview / confirm / verified-write / backup protocol (3). Smallest real migration, so the protocol is proved on the lowest-value data. | Yes (small) | revert; backup under `data/backups/` |
| **4a** | `run_scoring.py` atomic write (temp + `os.replace`). | No | revert |
| **4** | Jobs: `job-state-store.js`, `joinJobs`, `GET /api/jobs`, `POST /api/jobs/state`, migration with the 3.4 overlay merge, screens read the joined view, `filters` leave the jobs key, `/api/backup` overlay rules and the old-zip recovery. Gated on the tracker migration state (4.3). | Yes (outreach, assets) | revert; overlay and backup are on disk; browser key untouched until the owner moves it |
| **5** | Intelligence: envelope routes, `baseSha256`, in-memory cache, `scoringWeights` kept across devices; migration. Runs before the profile because `migrateOnboardingComplete` reads it. | Yes | as above |
| **6** | Profile: `GET` / `PUT /api/profile`, `normalizeProfile` extracted pure, no write-during-read, async `saveProfile`, demo and reset paths closed (5.1, 5.5), discovery / pipeline / tailor read from disk (4.1), restore and export rules (4.4); migration. The riskiest: 15 mutators, CV text, the first-run wizard, and every other step's reader depends on it. | Yes (identity, CV text) | as above |
| **7** | Generic scrub of the remaining legacy keys (`job-dashboard-ai-settings` once its key is moved, `linkedin_li_at`; the old jobs key with its discarded `filters`), `TOLERATED_UNTIL_MIGRATED` emptied, DECISIONS.md log entry, CLAUDE.md and data-shapes.md updated (section 8). The scrub deletes only keys that are off the allowlist **and** whose server copy was verified. | No | revert; per-key backups exist |

Steps 3-6 each ship with their own tests (section 6 rows) and their own Settings > Privacy > Browser data row. Each is independently useful and none requires the next.

## 8. Doc edits proposed (to be applied with the step that makes them true; not edited now)

1. **`data-shapes.md`, line 5** ("Where data lives"). Replace the "browser `localStorage` is the master" paragraph with:

   > Where data lives: **the server is the master** for the profile, intelligence, the owner's job state (`job-state.json`), AI memory and applications; the pipeline files (`discovered_jobs.json`, `scored_jobs.json`, `job_history.json`) are written only by the Python pipeline. The browser keeps UI state only (an allowlist, BROWSER_STORAGE_POLICY 2.2) and loads server data into memory. Everything under `data/` except `data/examples/` is git-ignored and private.

   Line 7 (browser keys): replace with the allowlisted keys only. "Candidate profile" Purpose: "master", not "mirror"; add `_confidence`, `_editedFields`. "Scored jobs": remove the "copy in browser key" phrase; the "Fields added later, in the browser job store" block moves to a new **Job state** section with the shape of 2.3. New sections: **AI memory** (2.4), **AI findings** (2.8), **Step 5 migration run log** (3.2, `migration-step5.json`), **Step 5 backups** (`data/backups/step5-<kind>-<ts>/`). Last section "Not stored by the app": delete the line about "Browser AI settings ... in `localStorage` only".
2. **`CLAUDE.md`, last section** ("No hard-coded markets, no borrowed data"): the sentence "Until migration step 5 ships, the profile, intelligence and jobs still live in `localStorage` ... fix profile data in the profile form, not in the disk file" is replaced, per key, as each ships, by: "the profile form edits the server copy; the file under `data/` is the master and is edited only through the app or the migration; do not edit it by hand while the app is open (the sha precondition will refuse the next save)". Also the Tests section gains the new test file names.
3. **`DECISIONS.md`** gets one log line per shipped step, and one dated line for the owner decisions Q-A to Q-K including the changed Q-B (findings store) when the owner asks for the log to be written; principle 15 is already worded correctly.
4. **`BROWSER_STORAGE_POLICY.md`**: **already updated in this revision** for the changed Q-B (1.1 row 9, 2.3 "Removed outright", section 7 row 5, section 8 note under Q7); step 5 row split into 5.1-5.7 pointing here and section 11d "Step 5 as built" per step come with the steps.
5. **`.claude/rules/frontend.md`**: the loader rule ("no `localStorage` outside the wrapper; sync readers read the server-state cache").

## 9. Owner decisions on Q-A to Q-K (2026-10-29) and remaining open questions

| # | Question | Decision (owner) | Where it lands |
|---|---|---|---|
| Q-A | Order | **Profile last.** | Section 7 order unchanged: 1, 2, 2b, 3, 4a, 4, 5, 6, 7. |
| Q-B | Cache, usage log, chat | **CHANGED.** Usage -> ledger; chat -> memory only (Q7); **the cache is replaced by a server-side AI findings store**, one persistent record per entity with append-only findings, cache key = model + prompt version + input hash, configurable retention, no API keys, contact data redacted before it is stored or sent, **the lookup runs before the budget gate reserves anything** (a hit costs nothing), a repeat call only when the input changed or the finding is stale. The browser cache is still removed. | Sections 2.6, 2.8, step 2b, tests I14-I16; BROWSER_STORAGE_POLICY 1.1 / 2.3 / 7 / 8 updated. |
| Q-C | AI memory | **Keep, as a server file** (`data/ai/memory.json`). | 2.4, step 3. |
| Q-D | Job filters | **React state only.** `searchText` and the salary figures are never stored; no allowlist key for filters. | 2.3. |
| Q-E | `_confidence` / `_editedFields` | **Keep** in the server profile file. | 2.1. |
| Q-F | Hand-import of a jobs JSON file | **Keep** (`POST /api/jobs/import` writes `record` entries into the overlay, never over pipeline jobs). | 2.3, 4.2. |
| Q-G | Server required | **Yes. No silent browser fallback.** | 2.7. |
| Q-H | Pre-overwrite copies in `data/backups/step5-*` | **Keep all. Manual prune script only.** | 3.2, 10. |
| Q-I | Refresh cadence | **Version polling** (focus + 30 s, `GET /api/state/versions`); no websocket / SSE. | 2.7. |
| Q-J | Overlay entries for jobs that left the list | **Keep, shown as history / recovery, not as active jobs.** | 2.3 (`orphans[]`, `GET /api/jobs/orphans`, Settings > Privacy > Job history). |
| Q-K | No-bypass-Caddy check | **Repeat it before the jobs migration (step 4) and the profile migration (step 6).** The migration buttons stay disabled until the owner records it. | 3.3, BROWSER_STORAGE_POLICY section 9. |

**Owner decisions on Q-L to Q-O (2026-10-29)**, from the changed Q-B:

| # | Question | Decision (owner) | Where it lands |
|---|---|---|---|
| Q-L | Retention | **Freshness window with built-in defaults in code, editable in Settings.** Expiry means a cache miss only; records are never deleted automatically. | 2.8 (Retention), I14 |
| Q-M | Entity for `careerStrategy`, `skillGap`, `applicationStrategy` | **A separate `candidate` record** for the global AI features. | 2.8 (entities), I17 |
| Q-N | Resume features | **CHANGED.** `resumeEnhancement` is not bound only to a job. General CV analysis is keyed by the resume version identity (`resume`); job-specific enhancement is keyed by resume version + job posting (`resumeJob`). | 2.8 (entities, inputs per feature), I17 |
| Q-O | Memory merge on a hit | **Only if the operation is proven idempotent.** A test must show a hit never duplicates memory; otherwise the merge is skipped on a hit. | 2.8, I18 |

Cache key requirement (owner): the key includes all relevant inputs, the prompt version and the model; a change in the resume, the job posting or user-confirmed facts invalidates the matching result (2.8, "Inputs per feature", I17). No open questions remain from the findings store.

## 10. What this plan does not do

- No code, no `data/` change, no AI call, no commit, no push. It does not run any migration, and it does not touch the 5.2 MB `scored_jobs.json`, `job_history.json` or any other pipeline file.
- No authentication (Q3 stands). The `baseSha256` check protects against a stale tab or device, not against a hostile client on the LAN.
- No change to scoring, the gate (`ai-gate.js`, `ai_gate.py`: the findings lookup happens before it is reached), redaction rules, the secret store, or the AI settings file (`ai-settings.json`; retention lives in its own file).
- No unification of the Python caches (`data/cache/llm_fit.json`, `engine.json`, `cv_analysis.json`) with the findings store.
- No multi-user model (principle 15). One server document per kind.
- No real-time sync, no CRDT, no pagination of `GET /api/jobs`.
- No encryption of the new files beyond the existing `data/` handling (Q4).
- No change to `data/chat/` (upstream leftover) or to `data/applications/` beyond reading its migration state.
