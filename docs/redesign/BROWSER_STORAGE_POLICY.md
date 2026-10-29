# Browser storage - audit and policy

Status: PLAN, 2026-10-29. No code, no `data/` change, no AI call. Not committed.
Inputs read: CLAUDE.md, DECISIONS.md (principles 13-16), SETTINGS_PLAN.md (inventory rows 4, 11, 26, 29; Privacy category),
SOURCES_SPEC.md (ADR-0034 line), and the code: every `localStorage` / `sessionStorage` / `indexedDB` / `document.cookie` hit in
`src/` and `scripts/`, `aiSettings.js`, `AISettingsPanel.jsx`, `aiClient.js`, `aiProviderRegistry.js`, `providers/*`,
`scripts/run-ai.js`, `ai-gate.js`, `ai-settings-handler.js`, `api-handler.js` (AI, backup, outreach routes), `backup-handler.js`,
`local-server.js`, `linkedin-scraper-bridge.js`, `run-outreach.js`, `RelatedContactsPanel.jsx`, `scrape_linkedin_contacts.py`,
`python/llm/ai_gate.py` (`_call_row`), `llm_client.py` (key handling), `docker-compose.yml`, `Dockerfile`, `.gitignore`, `.env`
(key names only, no values), `index.html`, `vite.config.js`.

Owner rule this plan implements: **nothing is stored in the browser unless it is on an allowlist; secrets are never stored in or
sent from the browser; the server is the only holder.**

## 0. Findings in one page

Most urgent first.

1. **The AI API key is plain text in `localStorage`** (`job-dashboard-ai-settings.apiKey`) and **is sent in the body of every
   AI request** (`settingsForApi` -> `/api/ai/*`, `/api/ai/models`). `run-ai.js` takes `settings.apiKey` from that body and
   hands it to the provider. Nothing on the server stores it.
2. **The LinkedIn `li_at` cookie is plain text in `localStorage`** (`linkedin_li_at`) and travels in the body of
   `POST /api/outreach/discover` (`body.liAt`). The server then passes it to the Python scraper as **`--li-at <value>` on the
   command line**, readable by any local process through `/proc/<pid>/cmdline` / `ps`.
3. **The server listens on all interfaces with no authentication and no Origin / Content-Type check.**
   `server.listen(PORT)` has no host; `docker-compose.yml` publishes `"3073:5173"` on every host interface. `readBody` parses JSON
   whatever the Content-Type is, so a `text/plain` cross-site `fetch` from any web page the owner opens (no CORS preflight) can
   POST to `/api/*`. Today that can already overwrite profile / applications / AI budget settings; once the server holds keys it
   can also spend the owner's budget or replace the stored key.
4. **Backup export includes `data/outreach/`** (`DATA_DIRS`), and `data/outreach/linkedin_session.json` is one of the three
   places the bridge reads `li_at` from (arg, `LINKEDIN_LI_AT` env, that file). The file does not exist today, so no existing zip is
   affected, but the first owner who creates it puts the cookie into every backup.
5. **Backup restore has no guard.** `importBackupZip` writes every `data/...` entry with `path.join(root, entry.entryName)`:
   no `..` check (zip-slip: a crafted zip can write outside `data/`) and no refusal for `data/secrets/` or `data/ai/`.
6. **Only OpenAI-pattern keys are masked in errors.** `sanitizeKey` in `run-ai.js` replaces `sk-[A-Za-z0-9]{8,}` only. A Gemini key
   (`AIza...`), an Anthropic key (`sk-ant-...` is caught by luck), an OpenRouter key and `li_at` are not masked, and provider error
   text flows into `finishAiCall` / `recordAiRefusal` (ledger `reason`/`error`) and into the HTTP error response.
7. **Gemini sends the key in the URL query** (`...:generateContent?key=${apiKey}`) from the server to Google. Not a browser leak,
   but any proxy / error message that echoes the URL leaks it. Move to the `x-goog-api-key` header.
8. **`baseUrl` is browser-supplied and receives the key.** `openaiProvider` and `openrouterProvider` attach `Bearer <apiKey>` to
   whatever `baseUrl` the request body names. Once the server holds the key, any page that can POST to `/api/ai/*` (finding 3)
   could redirect the owner's key to an attacker's host. The design in section 3 pins `baseUrl` server-side.
9. **Personal data is cached in `localStorage`** in large amounts: the profile (name, e-mail, phone, links, CV-derived history),
   candidate intelligence, discovered / scored jobs (with `outreach` recruiter names, e-mails, LinkedIn links), AI chat, AI memory,
   AI response cache. These are not secrets but break the rule "nothing in the browser unless allowlisted". The profile and
   intelligence are today documented as **browser-master** (CLAUDE.md, last section; principle 15 says the move to server-master
   comes with multi-device). Changing that is an owner decision (open question Q1).

Good news, verified: no `document.cookie` and no `indexedDB` anywhere; no `innerHTML` / `dangerouslySetInnerHTML` / `eval` /
`document.write` anywhere in `src/` or `scripts/`; **no browser code calls a provider directly** (the providers in
`src/modules/ai/providers/*` are imported only by `aiProviderRegistry.js`, which is used by `scripts/run-ai.js` on the server), so a
strict `connect-src 'self'` will not break anything; the usage ledger rows contain no `baseUrl`, no error text and no key
(`_call_row` fields: provider, model, class, tokens, cost, feature, jobId); the backup export request carries only
`profile`, `intelligence`, `jobs` (no AI settings), so **no existing backup zip contains the AI key**.

## 1. Inventory

### 1.1 Browser storage keys

`ls` = localStorage, `ss` = sessionStorage. Class: **S** secret, **P** personal data (name, e-mail, phone, CV text, recruiter
data), **J** job-search data (not identifying alone, but the owner's private pipeline), **U** harmless UI state.

| # | Key | Store | File (writers / readers) | Holds | Class | Verdict |
|---|---|---|---|---|---|---|
| 1 | `job-dashboard-ai-settings` | ls | `aiSettings.js` (`loadAiSettings`, `saveAiSettings`); `AISettingsPanel`, `AIModelSelector`, `aiClient.js` | provider, model, temperature, maxTokens, **`apiKey`**, baseUrl, 9 feature toggles | **S** (apiKey) + U | Split: `apiKey` and `baseUrl` leave (server). Non-secret rest -> server `data/config/ai-browser.json` (it is enforced server-side anyway, see SETTINGS_PLAN row 6) or stays as one UI key (Q5). |
| 2 | `linkedin_li_at` | ls | `RelatedContactsPanel.jsx:25,59-60` | LinkedIn session cookie | **S** | Remove. Server secret store. |
| 3 | `job-dashboard-candidate-profile` | ls | `utils/storage.js` (`loadProfile`, `saveProfile`, `restoreProfile`, `clearProfile`), `ProfileContext.jsx`, mirrored to `data/profile/candidate-profile.json` on sync | name, e-mail, phone, links, languages, salary, work authorization, questionnaire answers, CV library metadata | **P** | Server-master (Q1). Browser keeps no copy once migrated. |
| 4 | `job-dashboard-candidate-intelligence` | ls | `intelligenceExport.js`; `ScoringWeightsPanel`, scoring | career narrative, skills, project / ownership examples, weights | **P** | Server-master (Q1). |
| 5 | `job-dashboard-discovered-jobs` | ls | `jobStorage.js` (`loadJobs`, `saveJobs`, slim fallback), `loadDemoData.js`, `SettingsHome` (clear) | ads, scores, status, `outreach` (recruiter names / e-mails / LinkedIn), cover letters | **P** + J | Server-master (`data/jobs/scored_jobs.json` already exists). Same path as the tracker. |
| 6 | `job-dashboard-pipeline-state` | ls | `pipelineState.js` | last pipeline run progress | J | Server-side or drop (Q5). |
| 7 | `job-dashboard-ai-chat` | ss | `AICommandCenter.jsx:14-27` | last 50 chat messages (can quote the ad, profile summary) | P (redacted but conversational) | Remove; keep in component state only (lost on reload). |
| 8 | `job-dashboard-ai-memory` | ls | `aiMemory.js` | goals, preferred companies, weaknesses, lessons | P | Server (`data/ai/memory.json`) or drop. |
| 9 | `job-dashboard-ai-cache` | ls | `aiResponseCache.js` | AI responses keyed by hash, 7-day TTL | P (responses quote the ad and profile) | Remove. Server already has `data/` caches and the ledger. |
| 10 | `job-dashboard-ai-usage` | ls | `aiUsageTracker.js`, `AIUsageDashboard` | per-call token / cost estimates | J | Remove: the server ledger (`GET /api/ai/usage`) is the truth; the browser log is a duplicate. |
| 11 | `job-dashboard-outreach-index` | none | `outreachStorage.js:1` only declares the constant | nothing written | - | Dead constant: delete. |
| 12 | `job-dashboard-active-view` | ss | `appNavigation.js:57,84` | current view id | U | **Allow** (ss). |
| 13 | `job-dashboard-jobs-tab` | ss | `appNavigation.js:93,101`, `DashboardHome`, `ResumeLibrary` | current jobs tab id | U | **Allow** (ss). |
| 14 | `job-dashboard-sidebar-collapsed` | ls | `sidebarState.js` | `"true"`/`"false"` | U | **Allow** (ls). |
| 15 | `career-os-demo-bootstrap-done` | ss | `loadDemoData.js:39,47` | `"1"` flag | U | **Allow** (ss), demo mode only. |
| - | dark mode | none | `TopBar`, `OnboardingWizard` | class on `<html>`, **not persisted today** | U | Add as allowed key `job-dashboard-theme` (ls) only if the owner wants it remembered (Q5). |

`document.cookie`: not used. `indexedDB`: not used. The server sets no cookies.

### 1.2 Where a secret travels browser -> server

| # | Route | Field | Sent as | Reader |
|---|---|---|---|---|
| T1 | `POST /api/ai/job-analysis`, `/resume-enhance`, `/cover-letter`, `/interview-prep`, `/outreach`, `/company-intelligence`, `/career-strategy`, `/skill-gap`, `/application-strategy`, `/api/ai/chat` | `settings.apiKey` (and `settings.baseUrl`) | JSON body (`aiClient.js:53` `settingsForApi`) | `run-ai.js:159` -> `provider.complete({apiKey})` |
| T2 | `POST /api/ai/models` | `settings.apiKey`, `settings.baseUrl` | JSON body (`aiClient.js:108-113`) | `getAiModels` -> `listProviderModels` |
| T3 | `GET /api/ai/status` | none: `getAiStatus({})` is called with empty settings, so every keyed provider answers "No API key configured" | - | **Health panel is blind for keyed providers**; it becomes accurate once the server holds the key. |
| T4 | `POST /api/outreach/discover` | `liAt` | JSON body (`outreachClient.js:10`) | `api-handler.js:720` -> `run-outreach.js` -> `linkedin-scraper-bridge.js` -> Python `--li-at <value>` (argv) |
| T5 | URL query | none carry a secret in the browser; `GET /api/ai/models?provider=` carries only the provider name | - | - |

### 1.3 Where a secret could be written to logs, backups, exports

| # | Place | Risk | Status |
|---|---|---|---|
| L1 | `data/ai/usage-ledger.jsonl` rows | `_call_row` writes provider, model, class, tokens, cost, feature, jobId: **no key, no baseUrl, no error text** | clean today |
| L2 | ledger `error` / refusal `reason` from `finishAiCall`, `recordAiRefusal` | provider error text through `sanitizeKey` (pattern `sk-...` only) | **leak possible** for `AIza...`, OpenRouter, li_at |
| L3 | HTTP error responses (`sendJson(res, 500, {error: e.message})`) and SSE `error` events | provider message echoed to the browser; same pattern masking only | **leak possible** |
| L4 | `console.error` / `console.warn` in server scripts and container stdout (`podman logs`) | the scraper bridge catches `e.message` from the spawn; argv is not logged today, but error text may include it | must be checked by the test in 6.4 |
| L5 | `/proc/*/cmdline` of the Python scraper (`--li-at`) | any local process, any container user | **leak today**, fix in step 3 |
| L6 | Backup export zip: `DATA_DIRS` includes `outreach` (`linkedin_session.json`) | cookie in a file the owner moves around | **leak once the file exists**, fix in step 1 |
| L7 | Backup zip also carries `data/profile`, `data/jobs`, `data/applications`... (personal data, not secrets) | by design | unchanged |
| L8 | Backup restore | writes any `data/...` path, no `..` guard, no `data/secrets/` refusal | **write primitive**, fix in step 1 |
| L9 | `.env` (`OPENAI_API_KEY`, and the commented `ANTHROPIC_API_KEY`, `LINKEDIN_LI_AT`) | server-side, git-ignored, passed to every child process through `process.env` and to the container by `env_file` | acceptable (server holds it); keep out of backups (not in `DATA_DIRS`) |
| L10 | `claude-config/` (Claude Code OAuth credentials, mounted at `/root/.claude`) | an existing server-side secret; git-ignored; not in `DATA_DIRS` | acceptable; add to the "must never be exported" list and to the test in 6.3 |
| L11 | Gemini request URL `?key=` | outbound, server -> Google; may appear in error text | move to header (step 2) |
| L12 | `git` | `.gitignore` already covers `.env`, `data/outreach/linkedin_session.json`, `data/secrets/`, `data/config/`, `claude-config/` | clean |

## 2. Policy

### 2.1 Rule

A browser key may be written **only** if it is in `src/modules/browserStorage/allowlist.js`
(`{ key, store: 'local'|'session', reason, maxBytes }`). All reads and writes go through one wrapper,
`browserStorage.get/set/remove`, which throws in development and tests (and drops the write and logs once in production) for any
key not on the list, and for any value over `maxBytes`. Direct use of `localStorage`, `sessionStorage`, `indexedDB` or
`document.cookie` outside that wrapper fails lint and the test in 6.1.

### 2.2 Allowlist

| Key | Store | Reason it may stay | maxBytes |
|---|---|---|---|
| `job-dashboard-active-view` | session | Which screen is open; lost on tab close; no content. | 64 |
| `job-dashboard-jobs-tab` | session | Which jobs tab is open. | 64 |
| `job-dashboard-sidebar-collapsed` | local | Layout preference, `true`/`false`. | 8 |
| `job-dashboard-theme` | local | Light / dark choice (new; only if wanted, Q5). | 16 |
| `career-os-demo-bootstrap-done` | session | Demo-mode flag; exists only in demo mode. | 8 |
| `job-dashboard-ai-ui` *(optional, Q5)* | local | Non-secret AI UI preferences (provider id, model, temperature, max tokens, feature toggles) if the owner prefers them per browser rather than in `data/config/`. Never `apiKey`, never `baseUrl`. | 2048 |

Everything else in 1.1 is removed or moved. A key is a candidate for the list only if its value is a UI choice, contains no
text from a CV, ad, e-mail or contact, and is useless to someone who copies it.

### 2.3 Personal data and job data now cached in `localStorage`

Principle 15 and the tracker decision (2026-10-28, "the server file is the master, the browser keeps a read cache only") set
the direction. This plan goes one step further for the owner's rule: **no read cache in the browser either**, because a cache is
the same data.

- **Server is the master** for: profile (3), intelligence (4), discovered / scored jobs (5), AI memory (8). Each already has, or
  needs only a trivial, route: `/api/profile/save`, `/api/intelligence/save`, jobs write path, plus matching `GET`s.
- **Removed outright** (rebuildable or duplicate): AI response cache (9), browser usage log (10), AI chat history (7, component
  state only), pipeline state (6, derive from `data/jobs/.pipeline.lock` / run output), dead constant (11).
- **In-memory only** while the app is open (React state), loaded from the server on start.
- **Order of operations, to avoid data loss:** (a) the server copy must exist and be verified identical to the browser copy
  (hash compare, the way the tracker migration verifies each record against its payload) **before** the browser key is deleted;
  (b) deletion is a separate, owner-triggered step per key; (c) nothing prunes non-allowlisted keys automatically until
  (a) has been confirmed for that key. The generic "scrub" in step 5 only ever deletes keys that are both off the allowlist and
  already migrated.
- Principle 15 / CLAUDE.md state that the browser copy of the profile is the master. Making the server the master therefore needs
  a DECISIONS.md log entry by the owner (Q1) and a CLAUDE.md edit in the same change. Until then the profile, intelligence and jobs
  keys are **listed as "tolerated, scheduled for removal"** in the allowlist file with an expiry note, so the test passes today
  and the exception is visible.

## 3. Secret store design

### 3.1 Location and format

- Directory `data/secrets/`, mode **700**; files mode **600**. Git-ignored already. Not in backup `DATA_DIRS`; export and restore
  both refuse any path under `data/secrets/` (and `claude-config/`).
- One file per secret kind, JSON, written atomically (temp file in the same directory, `fsync`, `rename`). **The mode is set when
  the file is created** (`open` with `0o600`, or a `umask(0o077)` for the process), never by `chmod` after the write, so the
  value is never briefly world-readable.
  - `data/secrets/ai.json`: `{ "<provider>": { "key": "...", "baseUrl": "https://..." , "setAt": "ISO" } }`
  - `data/secrets/linkedin.json`: `{ "li_at": "...", "setAt": "ISO" }`
  - Future source keys (principle 16) go in the same directory, not `data/config/`.
- **Reconcile with SOURCES_SPEC (ADR-0034 line):** that line puts source keys in `data/config/`. Secrets and configuration must not
  share a directory (config is backed up and shown; secrets are neither). Decision proposed: **`data/config/` holds the
  non-secret configuration, `data/secrets/` holds every credential**; edit the SOURCES_SPEC line accordingly when this lands.
- Environment keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `LINKEDIN_LI_AT` in `.env`) stay valid for headless use. Resolution order:
  `data/secrets/` first, then `.env`. The Settings screen shows which source is active.
- Rootless podman maps container root to the host user (`ranikola`), so 600/700 protect against other host users, not against the
  owner or the container; that is the intended boundary (Q4).

### 3.2 Module and API

A single module `scripts/secret-store.js` (and a thin Python reader, `python/llm/secrets.py`) is the only code that reads or
writes the files. Everything else asks it.

| Function | Returns |
|---|---|
| `getSecret(kind, provider?)` | the value, **server-internal only**, never passed to a route handler's response |
| `describeSecrets()` | `{ ai: { openai: { set: true, last4: "a1b2", baseUrl, source: "store"|"env" }, ... }, linkedin: { set: false } }` |
| `setSecret(kind, provider, value, opts)` | validates, writes, returns `describeSecrets()` entry |
| `clearSecret(kind, provider)` | removes the entry |
| `redactSecrets(text)` | replaces every **currently stored** value (and `.env` values) in `text` with `[secret]` |

Routes (JSON only; see 5.1 for the Origin / Content-Type checks they sit behind):

- `GET /api/secrets` -> `describeSecrets()`: only `set`, last 4 characters (only if the value is >= 12 characters, else `****`),
  `baseUrl`, `source`, `setAt`. **No route, in any status or error path, returns a value.**
- `PUT /api/secrets/ai/<provider>` `{ key, baseUrl? }` -> stores; `DELETE /api/secrets/ai/<provider>` -> clears.
- `PUT /api/secrets/linkedin` `{ li_at }`, `DELETE /api/secrets/linkedin`.
- No `GET` of a single secret. Replacing = `PUT` again. Raising nothing in the budget gate, so no `confirm` needed; clearing asks
  for a UI confirmation only.

### 3.3 How the server uses the key

- `run-ai.js` stops reading `settings.apiKey` and `settings.baseUrl` from the request body. It calls
  `getSecret('ai', provider)` and uses the stored `{key, baseUrl}`. A keyed provider with no stored or env key answers
  "No API key configured" (the same message `getAiStatus` uses today).
- **`baseUrl` is pinned to the secret record.** For keyed providers (`openai`, `openrouter`, `claude`, `gemini`) the request may
  not override it; the provider default (`PROVIDER_DEFAULTS`) applies unless the owner set one with the key. This closes finding 8.
  Keyless providers (`ollama`) may take a `baseUrl` from the non-secret settings, since no credential is attached.
- `getAiStatus` and `getAiModels` use the stored key, so the provider health card works for keyed providers (T3).
- Python (`llm_client.py`) already reads keys from the environment only (never argv). `ai_gate`/`llm_client` call sites get the key
  from `python/llm/secrets.py` first, then env. Child processes receive a key only through **their own environment variable**
  set for that spawn, never through arguments, and only the one key that child needs (today every child inherits all of
  `process.env`).
- Gemini: send `x-goog-api-key` header, drop `?key=` (L11).
- LinkedIn: the bridge reads `li_at` from the store (drop the `data/outreach/linkedin_session.json` source and the request-body
  `liAt`), and passes it to the scraper by **environment variable** (`LINKEDIN_LI_AT` in the child's env only) instead of
  `--li-at`. `scrape_linkedin_contacts.py` already prints only JSON results and error strings, never its args; the change is the
  `--li-at` argument and its `argparse` default becoming `os.environ.get(...)`.

### 3.4 How the owner sets or replaces it (Settings)

Settings > **Privacy > Secrets and keys** (SETTINGS_PLAN category). One row per provider and one for LinkedIn:

```
OpenAI        set  ...a1b2   source: Settings   base URL: https://api.openai.com/v1      [Replace] [Remove]
Anthropic     not set                                                                     [Set key]
LinkedIn      not set  (deep outreach only)                                               [Set cookie]
```

- Input is a write-only password field in a dialog; the value is sent once (`PUT`), the dialog is cleared, and the UI never holds
  the value afterwards. No "show" button, no copy button, no autofill (`autocomplete="off"`).
- "Replace" overwrites; the old value is gone. The list in the AI Provider card shows only the provider, model and "key set".
- The AI Provider card loses its `API Key` input. The outreach panel loses the `li_at` input and shows
  "LinkedIn cookie: set / not set - manage in Settings > Privacy".

### 3.5 Never in logs, ledger or errors

- `redactSecrets` (exact-value replacement, not pattern) wraps **every** place a provider or scraper message leaves the server:
  `sendJson` error bodies, SSE `error` events, `finishAiCall` / `recordAiRefusal` text, scraper stderr, `console.*` in the server
  scripts. `sanitizeKey`'s pattern list is kept as a second layer, not the only one.
- The ledger keeps its current shape (no key, no baseUrl, no error text beyond the `redactSecrets` output).
- A shared helper `logSafe()` is the only logger the secret-handling modules may use; ESLint forbids `console.*` in
  `secret-store.js`.
- Request bodies are never logged (they are not today). The secret `PUT` handler must never echo the body in an error.

## 4. Migration of secrets already in the browser

Owner-triggered, one time, per secret. No automatic move.

1. On load, the Privacy > Secrets screen checks `localStorage` for `job-dashboard-ai-settings.apiKey` and `linkedin_li_at`. If a
   value is present it shows: "A key is stored in this browser. Move it to the server." with the masked value (first 3 + last 4).
2. **[Move to server]** sends the value with `PUT /api/secrets/...`, then calls `GET /api/secrets` and checks `set: true` and that
   the `last4` equals the last 4 characters of the value the browser holds.
3. Only then does the browser: set `apiKey` to `''` in `job-dashboard-ai-settings` (or remove `linkedin_li_at`), re-read the
   key to confirm it is gone, and show "Moved. Removed from this browser."
4. If any step fails the browser value is **not** touched and the error is shown (the secret store failed, nothing lost).
5. After a successful move, **new builds never write these keys again**; the wrapper throws on an `apiKey` / `linkedin_li_at`
   write. A "Remove from this browser without moving" button covers a key the owner wants to discard.
6. The same step must also run, once, in every other browser profile the owner has opened the app in; the screen shows the
   banner whenever it finds a value.

**What the owner does afterwards (rotate):**

- Treat the old values as exposed: they sat in plain text in browser storage (readable by any extension, any XSS and any person
  with disk access to the profile) and were sent in request bodies. **Rotate the AI provider key** at the provider after the move
  (create a new key, paste it in Settings, delete the old one) and **log out of LinkedIn / re-login** to invalidate the old `li_at`.
- Clear browser site data for the app origin (`http://<host>:3073`) once, to remove old copies, history entries and any
  `localStorage` leftovers in other profiles.
- Check old backup zips: the AI key was never in a backup (the export carried only profile / intelligence / jobs); a zip made
  **after** a `linkedin_session.json` existed would contain the cookie. Delete such zips.
- Do not reuse the same key for the `.env` copy; if `OPENAI_API_KEY` in `.env` is the same key, rotate it too.

## 5. Hardening checks that cost nothing

### 5.1 The server API is reachable from the LAN without auth

- Bind: `server.listen(PORT)` with no host binds all interfaces; `docker-compose.yml` publishes `3073:5173` on all host
  interfaces (also IPv6). Anyone on the LAN can open the app and call every `/api/*` route (read profile, read applications,
  export a backup zip, change AI settings, start AI calls on the owner's account, soon read masked keys and replace them).
- CORS: the server sends **no** `Access-Control-*` header, so other origins cannot *read* responses. This does not stop writes:
  `readBody` parses JSON regardless of `Content-Type`, so a `fetch(..., {method:'POST', mode:'no-cors', headers:{'Content-Type':'text/plain'}, body: '{...}'})`
  from any page the owner visits is a "simple" cross-site request with no preflight, and the server acts on it (CSRF). DNS
  rebinding against the LAN name is the same exposure with reads.
- Cheap fixes, in order:
  1. **Require `Content-Type: application/json` on every non-GET `/api` route** (415 otherwise). Browsers need a preflight for
     that header cross-site, and the server sends no CORS headers, so cross-site writes fail. Exception: the multipart / binary
     upload routes check an `Origin` match instead.
  2. **Check `Origin` (when present) and `Host` against an allowlist** from `.env` (`CAREER_OS_ALLOWED_HOSTS`, default
     `localhost:3073,127.0.0.1:3073`). Mismatch -> 403. This also stops DNS rebinding.
  3. **Bind explicitly:** `HOST` env (default `127.0.0.1`) and, in compose, `"127.0.0.1:3073:5173"` or the server's LAN IP. Which
     one is Q2. Note that inside the container the app must bind `0.0.0.0` (podman port-forwarding); the restriction is the
     published address on the host.
  4. Real authentication is **out of scope** here (single user, principle 15); revisit with multi-device access (Q3). Until then
     binding to localhost plus an SSH tunnel or a reverse proxy with auth is the safe remote path.
- `vite dev` (`npm run dev`) binds localhost by default (no `--host` in `package.json`); the dev API plugin shares the handlers,
  so the same checks must be applied there.

### 5.2 Content-Security-Policy

`index.html` has no CSP and the server sets no security headers. Add as headers in `serveStatic` / the HTML response (and a
`<meta http-equiv>` fallback for the dev server):

```
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
  img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none';
  form-action 'self'; frame-ancestors 'none'
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
X-Frame-Options: DENY
```

- `connect-src 'self'` is safe because no browser code calls a provider or a third-party API directly (verified, section 0).
  If anything loads a Google font or CDN asset, `public/` and `index.html` need a check before enabling; run in
  `Content-Security-Policy-Report-Only` first for a day.
- `style-src 'unsafe-inline'` is kept only because of Tailwind / inline styles; `script-src` stays strict (no `unsafe-inline`).
- `Cache-Control: no-store` on `/api/*` responses that carry personal data, so no browser or proxy keeps them.

### 5.3 Secrets in URLs

- Browser -> server: none (T5). Rule: **no route may take a secret, token or personal identifier in the query string or path.**
  The test in 6.2 fails a route whose handler reads `searchParams` for a name matching `key|token|secret|cookie|li_at`.
- Server -> vendor: Gemini `?key=` is the only one (L11); move to the header.
- Download links (`/api/resumes/...`, `cvDownloadUrl`) carry job / CV ids and file names, not secrets.

### 5.4 XSS sinks

- `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `dangerouslySetInnerHTML`, `document.write`, `eval`, `new Function`: **none** in
  `src/`, `scripts/`, `index.html`. React escapes text; no markdown renderer is used.
- Scraped or user-supplied text used as a link target (javascript: URL risk if an ad or the scraper returns one):
  - `src/components/jobs/JobDetailDrawer.jsx:115`, `src/components/jobs/JobTable.jsx:146` -> `href={job.jobUrl}` (from provider ads)
  - `src/components/outreach/ContactCard.jsx:47` -> `href={contact.linkedinUrl}` (scraped)
  - `src/components/outreach/LinkedInSearchLinks.jsx:18` -> `href={q.url}` (built in code, low risk)
  - Download links built from ids: `JobAIToolsPanel.jsx:176`, `JobTailorActions.jsx:106`, `ResumeLibrary.jsx:84`, `CvLibrary.jsx:77`
    (same-origin, low risk).
  - Fix: one helper `safeHref(url)` that returns the URL only for `http:` / `https:` and `undefined` otherwise; apply to the three
    scraped ones. All have `rel="noopener noreferrer"` already.
- A strict CSP (5.2) is the backstop: even a `javascript:` link or injected script cannot run inline.

### 5.5 Other cheap items

- `index.html` meta: add `<meta name="referrer" content="no-referrer">`.
- Request body size limits: `readBody` limits at 10 MB; the AI settings handler at 64 KB. Add a 16 KB limit on the secret routes.
- Do not set any cookie; if a cookie is ever needed (multi-device auth), `HttpOnly; Secure; SameSite=Strict`.
- Compose: do not put keys in `environment:` (it is visible in `podman inspect`); `env_file: .env` is the existing path; the
  `data/secrets/` store is preferred.

## 6. Test plan

All tests run on the host (`npm test`), offline, no AI calls. Secrets in tests are a fixed canary string
`SECRET-CANARY-7f3a9c1d` (long enough to pass the last-4 rule, not matching any real key pattern).

### 6.1 No storage key outside the allowlist

1. **Static test** (`tests/js/browserStorageAllowlist.test.js`): scan `src/**/*.{js,jsx}` and fail on any match of
   `localStorage|sessionStorage|indexedDB|document\.cookie` outside `src/modules/browserStorage/`. Reason: a runtime-only spy
   misses code paths no test executes.
2. **ESLint** `no-restricted-globals` (`localStorage`, `sessionStorage`, `indexedDB`) and `no-restricted-properties`
   (`window.localStorage`, `globalThis.localStorage`, `document.cookie`) on `src/**`, with an override only for the wrapper file.
3. **Runtime test**: with a fake `Storage`, the wrapper writes each allowlisted key and throws on `apiKey`, `linkedin_li_at`
   and a random key; a `maxBytes` overflow throws; `get` of a non-allowlisted key returns `null`.
4. **Allowlist file test**: every entry has `reason`, `store` and `maxBytes`; the tolerated-until-migrated entries (profile,
   intelligence, jobs) have an `until` note and the test lists them so they cannot be forgotten.

### 6.2 No API response contains a secret

`tests/js/secretsApi.test.js`: start the handler with `data/secrets/` in a temp directory seeded with the canary for every
provider, the LinkedIn cookie and a `.env` value, then assert `JSON.stringify(body)` and headers of **every** `GET` route and of
these paths do not contain the canary: `/api/secrets`, `/api/ai/usage`, `/api/ai/status`, `/api/ai/models`, `/api/settings*`,
`/api/pipeline/*`, `/api/outreach/*`, and the **error paths**: a provider that throws a message containing the canary, a mocked
fetch whose URL contains it (Gemini), a 500 from the secret route, a malformed `PUT`. `GET /api/secrets` returns `set` and
`last4` only. Also: `PUT /api/secrets` with the canary in an invalid body does not echo it. Request-side: assert `run-ai` ignores
`settings.apiKey` / `settings.baseUrl` in the body (the provider mock sees the stored key and the pinned base URL).

### 6.3 Backup export contains no secrets

`tests/js/backupSecrets.test.js`: seed `data/secrets/*.json`, `data/outreach/linkedin_session.json`, a `.env`, `claude-config/`
credentials and the canary inside `data/` copies; run `createBackupStream`, unzip in memory and assert (a) no entry path starts
with `data/secrets/`, `claude-config/`, `.env`, or is `linkedin_session.json`; (b) no entry's bytes contain the canary. Also
restore tests: an entry named `data/secrets/ai.json` is refused and reported; an entry `data/../../etc/x` or an absolute path is
refused (path is resolved and must stay inside `<root>/data/` and outside `data/secrets/`); other entries restore as before.
Ledger test: after a failing mocked provider call that throws the canary, `data/ai/usage-ledger.jsonl` does not contain it
(extends `tests/js/aiGate.test.js`).

### 6.4 Process and log tests

- The bridge test (mock `spawn`): argv never contains the cookie; the child env does.
- Capture `console.*` during the route tests above and assert the canary is absent.

## 7. Implementation steps

Each is independently shippable; every step has its own tests and a rollback (revert the commit; the secret files stay on disk).

| # | Step | Size | Notes |
|---|---|---|---|
| 1 | **Backup hardening.** Remove `outreach/linkedin_session.json` from export (explicit exclude list: `data/secrets/`, `linkedin_session.json`); restore refuses `..`, absolute paths, `data/secrets/`. Tests 6.3. | tiny | Urgent: no new storage needed, closes findings 4 and 5. |
| 2 | **AI key to the server.** `secret-store.js`, `/api/secrets` routes, Privacy > Secrets screen (AI part), `run-ai.js` / `getAiStatus` / `getAiModels` use the store and ignore body `apiKey` and `baseUrl`, key and baseUrl pinned, `redactSecrets` on error paths, Gemini header, `AISettingsPanel` loses the key field, owner-triggered migration + scrub (section 4). Tests 6.2 and L2/L3. | medium | Closes findings 1, 6, 7, 8. Do this first among the feature steps. |
| 3 | **LinkedIn cookie to the server.** Same store; bridge reads the store; argv -> env; drop the request-body `liAt` and the session-file source; outreach panel shows set / not set; migration. Test 6.4. | small | Closes finding 2 and L5. |
| 4 | **Request hardening.** JSON content-type required on writes, Origin / Host allowlist, `HOST` bind + compose published address, CSP and security headers (report-only first), `safeHref`. | small-medium | Closes finding 3. Needs Q2 answered. Should land **before** or together with step 2 if the server will be left bound to the LAN, because step 2 puts keys behind unauthenticated routes. |
| 5 | **Storage wrapper, allowlist, lint and static test.** Route every existing use through the wrapper; the tolerated-until-migrated entries keep the app working. Includes the dead constant removal (11) and the optional theme key. Tests 6.1. | medium | No behaviour change; makes the rule enforceable. |
| 6 | **Drop redundant browser stores.** AI response cache (9), browser usage log (10, use the server ledger), chat history (7), AI memory (8, to `data/ai/memory.json` or drop), pipeline state (6). One-time clear of the old keys. | small each | Low risk: all are rebuildable or duplicate. |
| 7 | **Server-master for profile, intelligence, jobs.** Per key: server copy verified equal, browser key cleared by an owner-triggered step, then removed from the tolerated list. Gated on the DECISIONS.md entry (Q1). | large | Do the jobs store first (the file exists, applications S2 is the template), profile last. |

Steps 1 and 4(i) can ship the same day. Steps 2 and 3 should not wait for 5-7.

## 8. Open questions for the owner

- **Q1.** Do you approve making the **server the master** for profile, intelligence and jobs (reversing the "browser copy is the
  master" line in CLAUDE.md and principle 15's "later" wording)? Without it step 7 cannot start and those keys stay as tolerated
  exceptions with an expiry date.
- **Q2.** Bind address: `127.0.0.1` only (use through SSH tunnel / reverse proxy from other devices), or a specific LAN IP
  (reachable from your own devices, still unauthenticated)? Which hostnames should the Host / Origin allowlist contain?
- **Q3.** Is a simple shared secret / basic auth in front of the app acceptable if you want to keep LAN access, ahead of the
  multi-device work? (Not in this plan; it would be one more step before 4.)
- **Q4.** Is the container's root = your host user mapping (rootless podman) acceptable as the trust boundary, with 600/700 on
  `data/secrets/` protecting against other host users only? Or do you want secrets encrypted at rest (a passphrase typed at
  start-up), which costs a start-up prompt?
- **Q5.** Which non-secret AI settings (provider, model, temperature, toggles) may stay in the browser as one allowlisted key,
  and do you want the theme remembered? Default proposed: AI settings go to the server, theme is an allowlisted key.
- **Q6.** The AI key currently in your browser: do you want me to propose the exact migration click path to run right after
  step 2, plus a note for rotating `OPENAI_API_KEY` in `.env` if it is the same key?
- **Q7.** Should the client-side `AICommandCenter` chat keep history across reloads (then it needs a server file) or is
  in-memory only fine?
- **Q8.** Browser AI features still send redacted text without a confirm dialog (principle 14). That is out of scope here, but it
  is the next privacy gap; schedule it after step 4?
