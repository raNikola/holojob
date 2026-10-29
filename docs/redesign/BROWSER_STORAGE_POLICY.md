# Browser storage - audit and policy

Status: PLAN, 2026-10-29; **owner decisions Q1-Q8 approved 2026-10-29** (section 8, DECISIONS.md log). Step 1 below is partly shipped
(request guard `cd0cf74`, loopback bind `766bd7b`); **Q3 revised the same day: no application login and no Caddy `basic_auth`** (accepted risk, section 5.1). Docs only in this revision: no code, no `data/` change, no AI call.
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
   comes with multi-device). The owner approved the change on 2026-10-29 (Q1, section 8).

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
| `job-dashboard-theme` | local | Light / dark choice. The only key added to the list by Q5. | 16 |
| `career-os-demo-bootstrap-done` | session | Demo-mode flag; exists only in demo mode. | 8 |

**Q5 (decided):** AI settings (provider, model, temperature, max tokens, feature toggles, base URL) are stored server-side; no AI key
is allowlisted. The four existing UI-state keys above stay because they are harmless view state; `job-dashboard-theme` is the only new
key. (If you meant theme as the *only* key at all, the three view-state keys go too: say so and they become React state.)

Everything else in 1.1 is removed or moved. A key is a candidate for the list only if its value is a UI choice, contains no
text from a CV, ad, e-mail or contact, and is useless to someone who copies it.

### 2.3 Personal data and job data now cached in `localStorage`

Principle 15 and the tracker decision (2026-10-28, "the server file is the master, the browser keeps a read cache only") set
the direction. This plan goes one step further for the owner's rule: **no read cache in the browser either**, because a cache is
the same data.

- **Server is the master (Q1, decided)** for: profile (3), intelligence (4), discovered / scored jobs (5), applications (already; no browser copy), AI memory (8). The browser keeps UI state only. Each already has, or
  needs only a trivial, route: `/api/profile/save`, `/api/intelligence/save`, jobs write path, plus matching `GET`s.
- **Removed outright** (rebuildable or duplicate): AI response cache (9), browser usage log (10), AI chat history (7, component
  state only), pipeline state (6, derive from `data/jobs/.pipeline.lock` / run output), dead constant (11).
- **In-memory only** while the app is open (React state), loaded from the server on start.
- **Order of operations, to avoid data loss:** (a) the server copy must exist and be verified identical to the browser copy
  (hash compare, the way the tracker migration verifies each record against its payload) **before** the browser key is deleted;
  (b) deletion is a separate, owner-triggered step per key; (c) nothing prunes non-allowlisted keys automatically until
  (a) has been confirmed for that key. The generic "scrub" in step 5 only ever deletes keys that are both off the allowlist and
  already migrated.
- **Migration protocol (each of profile, intelligence, jobs; Q1):** (1) **preview**: the screen shows what is in the browser and what is on
  the server (counts, newest `updatedAt`, a content hash of each) and says which wins; (2) **owner confirmation**, an explicit button, never
  automatic; (3) **verified write**: the browser copy is sent to the server (when it is newer or the server has none), the server answers
  with the hash of what it stored, and the browser compares it with its own; (4) only after the hashes match is the browser key removed
  and a re-read confirms it is gone; (5) any mismatch or error leaves the browser copy untouched and shows the reason. The server file is
  backed up (timestamped copy under `data/backups/`) before it is overwritten. Nothing prunes a non-allowlisted key before its own step 4.
- The "browser copy of the profile is the master" line in CLAUDE.md and principle 15's "later" wording are **reversed** by the 2026-10-29
  decision (DECISIONS.md log, CLAUDE.md "No hard-coded markets" section). Until step 5 ships, the profile, intelligence and jobs keys are
  listed as "tolerated, scheduled for removal" in the allowlist file with an expiry note, so the test passes today and the exception is visible.

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
- Clear browser site data for the app origin (`https://careeros.void` and `http://localhost:3073`, whichever were used) once, to remove old copies, history entries and any
  `localStorage` leftovers in other profiles.
- Check old backup zips: the AI key was never in a backup (the export carried only profile / intelligence / jobs); a zip made
  **after** a `linkedin_session.json` existed would contain the cookie. Delete such zips.
- Do not reuse the same key for the `.env` copy; if `OPENAI_API_KEY` in `.env` is the same key, rotate it too.

## 5. Hardening checks that cost nothing

### 5.1 The server API is reachable from the LAN without auth

**Status 2026-10-29:** the guard (bullets 1-2) and the loopback bind (bullet 3) are shipped. **Q3 is resolved as NO application login and NO
Caddy `basic_auth`.** This is a conscious, owner-accepted risk:

- Access stays inside the home LAN (Caddy `careeros.void` -> `127.0.0.1:3073`); remote access is only through **Tailscale**.
- Consequence, stated plainly: anyone who can reach `careeros.void` (any device on the LAN, any device on the tailnet) can read the
  profile and applications, change AI settings, spend the AI budget, and - once step 2 ships - replace a stored key. The Origin /
  Host / Content-Type guard stops cross-site pages in the owner's browser and DNS rebinding; it does not stop a device that talks to the API
  directly. Keys are never readable through the API (only `set` and the last 4 characters), which limits the damage to use and replacement.
- **Revisit this decision if** the app is ever exposed outside the home network or Tailscale (a port forward, Tailscale Funnel, a public
  DNS name, a shared tailnet with other people's devices) **or** a second user appears. Then add an authentication layer (Caddy
  `basic_auth` or `forward_auth`, or an app login) before anything else.
- **Tailscale hostname:** if the app is reached over Tailscale by a name (MagicDNS `ds9.<tailnet>.ts.net`, a `tailscale serve` URL, or a
  Caddy site on the tailnet), that exact hostname **must be added to `CAREER_OS_ALLOWED_ORIGINS`** in `.env`, for example
  `https://careeros.void,http://localhost:3073,https://ds9.<tailnet>.ts.net`, followed by `podman-compose up -d --force-recreate`.
  Without it the guard answers 403 (Host not allowed / Origin not allowed). A bare tailnet IP needs the same entry. The port stays on
  `127.0.0.1`; Tailscale must reach the app through Caddy or `tailscale serve`, never by publishing 3073 on another interface.

The text below is the original finding, kept for the reasoning.

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
     Q2 decided: loopback behind Caddy. Note that inside the container the app must bind `0.0.0.0` (podman port-forwarding); the restriction is the
     published address on the host.
  4. Authentication: **none, by decision (Q3)**; see the status note above. Remote access is only through Tailscale; revisit if the
     app is exposed beyond the LAN and the tailnet.
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

## 7. Implementation steps (order approved 2026-10-29)

Each is independently shippable with its own tests and rollback (revert the commit; secret files stay on disk). Steps 2-6 do not start
before the pre-migration checklist (section 9) passes for the step.

| # | Step | Status | Notes |
|---|---|---|---|
| 1 | **Network and API protection.** Request guard (JSON Content-Type, Origin / Host allowlist), backup export / restore guard and secret masking; published port on `127.0.0.1`; CSP and security headers (report-only first); `safeHref` for scraped links. **No Caddy `basic_auth` and no app login (Q3: accepted risk, 5.1).** | guard `cd0cf74` and bind `766bd7b` shipped; **CSP, `safeHref` open** | Add the Tailscale hostname to `CAREER_OS_ALLOWED_ORIGINS` if used. Checklist item 1 gates step 2. |
| 2 | **AI keys to the server.** `scripts/secret-store.js`, `/api/secrets` routes, Privacy > Secrets screen (AI part), `run-ai.js` / `getAiStatus` / `getAiModels` use the store and ignore a body `apiKey` and `baseUrl`, key and base URL pinned, `redactSecrets` (exact value) on error paths, Gemini header, key field removed from `AISettingsPanel`, owner-triggered migration with the rotation checklist (section 4). Tests 6.2 and 6.4 ledger part. | **shipped `e793fc5`** | What it touches and what it does not: section 10; as built: section 11. |
| 3 | **`li_at` without CLI arguments.** Same store; bridge reads the store; cookie passed to the scraper in the child's environment, never `--li-at`; request-body `liAt` and the session-file source dropped; outreach panel shows set / not set; migration. Test 6.4 (argv). | **shipped `615c5c3`** | As built: section 11a. |
| 4 | **AI settings to the server (Q5).** Provider, model, temperature, max tokens, base URL (non-secret part), feature toggles move to `data/config/`; one source of truth for the provider (removes the `llm_client.active_provider()` duplicate); `aiSettings.js` stops using `localStorage`. | **shipped `e139c81`** | As built: section 11b. |
| 5 | **Profile, intelligence and jobs migration with verification (Q1).** Storage wrapper, allowlist, ESLint rule and static test (6.1) first; then per key the preview / confirm / verified-write protocol of 2.3; then the redundant stores (AI response cache, browser usage log, chat history, AI memory, pipeline state) are removed. Jobs first (file exists, applications store is the template), profile last. | open | Large; split per key. |
| 6 | **Browser AI confirm dialog (Q8).** The nine browser AI features get the explicit confirm that shows the redacted text and the provider (principle 14), like the judge and CV analysis. | open | The next privacy task after the secrets migration (steps 2-3). |

## 8. Decisions (owner, approved 2026-10-29)

| # | Question | Decision |
|---|---|---|
| Q1 | Server as master for profile, intelligence, jobs | **Approved**, and for applications (already). The browser keeps UI state only. Migration needs a preview, confirmation and a verified write before the browser copy is removed (2.3). Reverses the "browser copy is the master" line (CLAUDE.md) and principle 15's "later". |
| Q2 | Bind address | **127.0.0.1 behind Caddy.** Shipped in `766bd7b`. Allowed origins: `https://careeros.void,http://localhost:3073`. |
| Q3 | Authentication in front of the app | **No application login and no Caddy `basic_auth`** (revised 2026-10-29, replaces the earlier `basic_auth` decision). Access stays inside the home LAN; remote access only through Tailscale. Owner-accepted risk, revisited if the app is exposed outside the home network or Tailscale (5.1). The Tailscale hostname goes into `CAREER_OS_ALLOWED_ORIGINS`. |
| Q4 | Trust boundary | **600 / 700 on `data/secrets/`, no extra encryption in v1.** Rootless podman maps container root to the host user; the file modes protect against other host users only. Revisit with multi-device access. |
| Q5 | Non-secret AI settings, theme | **AI settings server-side; theme is the only allowlisted browser key added** (2.2). |
| Q6 | Moving the key in the browser | **Yes, with a rotation checklist** (section 4), including `OPENAI_API_KEY` in `.env` if it is the same key. |
| Q7 | `AICommandCenter` chat history | **In memory only.** No server file, no browser storage. |
| Q8 | Confirm dialog for browser AI features | **Approved; the next privacy task after the secrets migration** (step 6). |

No open questions remain from the audit. Details the owner still picks when the step starts: the retention of the pre-overwrite backup copies (step 5).

## 9. Pre-migration checklist

All items must be true, and recorded in the commit message or CHANGELOG of the step, before step 2 stores a key (and again before
step 5 moves personal data). The owner runs the commands; fish syntax.

1. **No path to the API bypasses Caddy.** Caddy is the only way in (TLS, one hostname, access log); with Q3 it is not an authentication
   point, so this item is what keeps the LAN / Tailscale boundary real.
   - Every published port and interface: `ss -ltnp | grep -E ':(3073|5173)\b'` shows 3073 on `127.0.0.1` only and nothing on 5173
     (the container's port is not published); `podman ps --format '{{.Names}} {{.Ports}}' | grep career-os` shows `127.0.0.1:3073->5173/tcp`;
     `grep -n -A3 'ports:' docker-compose.yml` shows no other mapping; `/etc/caddy/Caddyfile.d/*` proxies to 3073 only from the
     `careeros.void` site (and any Tailscale site that is intended); IPv6 (`[::]`) is absent.
   - From another LAN device: `curl -m 5 http://192.168.50.20:3073/api/config` is refused; `curl -k https://careeros.void/api/config`
     answers 200 (no login by decision).
   - Tailscale: `tailscale serve status` lists only intended targets, and **`tailscale funnel status` shows nothing** (Funnel would put the
     app on the public internet, which voids the Q3 risk acceptance). The tailnet hostname in use is in `CAREER_OS_ALLOWED_ORIGINS`.
   - `npm run dev` (Vite) is not left running: it serves the same API on its own port without Caddy.
2. **Host / Origin / Content-Type guard active.** `tests/js/requestGuard.test.js` passes; through Caddy a foreign `Origin` gets 403 and a
   `text/plain` write gets 415 (commands in the step 1 report); `CAREER_OS_ALLOWED_ORIGINS` is set in `.env` and the container was recreated.
3. **Secrets never in GET responses, logs or backups.** Tests 6.2, 6.3 and 6.4 exist and pass with the canary value. After the first real
   key is stored, also check by hand: export a backup, unzip it in a scratch directory and search it for `secrets`, `linkedin_session` and the
   key's last 8 characters (no hit); search `podman logs career-os` and the Caddy access log for the same 8 characters (no hit);
   `curl -sk https://careeros.void/api/secrets` shows `set` and `last4` only (no login since Q3).
4. **Every AI call passes the budget gate.** The call sites are exactly `llm_client.complete_json`, `claude_code._run` and
   `run-ai.js` (`reserveAiCall` before `provider.complete`); `grep -rn "provider.complete\|api.openai.com\|api.anthropic.com\|generativelanguage" scripts python src`
   shows no other caller; `tests/js/aiGate.test.js` and `tests/python/test_ai_gate*.py` pass; the new key-resolution code sits **before**
   the gate call and adds no call of its own.

## 10. Step 2: what it touches and what it does not (safety for existing data)

**It will:**
- create `data/secrets/` (700) and `data/secrets/ai.json` (600) when the owner clicks "Move to server" or sets a key;
- add `/api/secrets` routes and the Privacy > Secrets screen;
- change `run-ai.js`, `getAiStatus`, `getAiModels`: the key and, for keyed providers (openai, openrouter, claude, gemini), the `baseUrl`
  come from the store, falling back to `.env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`); a key or base URL in the request body is ignored;
- on the owner's click, after the server confirmed `set` and the same last 4 characters, blank the `apiKey` field of the browser key
  `job-dashboard-ai-settings` and re-read it.

**It will not touch:**
- `data/profile/`, `data/intelligence/`, `data/jobs/`, `data/applications/`, `data/resumes/`, `data/outreach/`, `data/ai/`
  (budget settings, pricing overrides, the usage ledger: unchanged, still append-only), `data/config/`, backups already made;
- the rest of `job-dashboard-ai-settings` (provider, model, temperature, max tokens, toggles; they move in step 4), and every other
  browser key (profile, intelligence, jobs, `linkedin_li_at`: step 3 and step 5);
- `.env` and `claude-config/`: read only. Rotating `OPENAI_API_KEY` in `.env` is an owner action, never done by the app;
- the scoring engine, the Python `llm_client` (it already reads keys from the environment only), the judge, the evidence matcher and the
  redaction rules (`redact.py`, `ai-redact.js`); the budget gate still decides before every call.

**Behaviour change to expect:** until the key is moved, keyed providers answer "No API key configured" (the body key is ignored by
design; there is no fallback that would keep the secret on the wire). The default `claude-code` provider, `mock` and `ollama` need no
key and are unaffected. A custom base URL (openrouter, a proxy) must be entered together with the key in Settings > Privacy, because the
browser value is no longer used for keyed providers. A failed move leaves the browser value in place (nothing is lost). Rollback: revert the commit; the browser value is still there
until the owner confirms the move, and after it the key is in `data/secrets/ai.json` (delete the file to clear it) and should be
treated as rotated anyway.

## 11. Step 2 as built (2026-10-29, `e793fc5`)

Follows section 10. Where the build made a choice the text left open:

- **Key rules.** A key is 12 to 512 characters with no spaces or control characters, so the last-4 check of the move is always possible
  (a shorter `.env` value is described as `****`). A base URL must be plain `http(s)` without credentials, query or fragment.
- **A replace without a base URL drops the one pinned before**: the key and its URL are one record. The Settings form pre-fills the
  current URL.
- **One effective settings object per call** (`resolveAiSettings`): the gate, the provider, status and models all see the same key and
  host. The gate is told the pinned URL, else the provider's own (`PROVIDER_DEFAULTS`), never the one in the request. Only `ollama`
  takes a base URL from the request (no credential is attached).
- **Missing key** returns "No API key configured" after redaction and before the gate: nothing is reserved. Status and models use the
  stored key; with a key set, the Provider health card now makes the provider's own `/models` request (no tokens, not a model call).
- **Move verification** requires `set`, `source === "store"` (a matching `.env` key does not count) and the same last 4 characters.
  The browser provider is only a default: the owner picks which provider the key belongs to. "Remove from this browser without moving" exists.
  If the server already holds a key for that provider (a rotated one, with an older key still in another browser profile), Move asks first
  and shows both last-4 values, and refuses when they are the same. The base URL field is shown for openai and openrouter only; claude and
  gemini use fixed endpoints.
- **A legacy key stays in the browser until moved**: `saveAiSettings` neither takes `apiKey` from the form nor erases the stored one;
  after the move it can never come back. The allowlist (`src/modules/browserStorage/allowlist.js`, data only) and its test land here;
  the wrapper and ESLint rule are still step 5.
- **Gemini** sends `x-goog-api-key`; the key is no longer in the URL (L11).
- **Not done here:** `python/llm/secrets.py` (section 10 leaves Python alone; `llm_client` keeps reading `OPENAI_API_KEY` from the environment,
  so rotating or removing it in `.env` affects the Python judge, matcher and enrichment); ~~LinkedIn `li_at` (step 3)~~ (shipped, section 11a); the CSP and `safeHref`.
- `.dockerignore` gained `data/secrets` and `claude-config` (owner-approved), so a build never copies them into an image layer.

### Pre-migration checklist record (section 9) for step 2

| # | Item | State |
|---|---|---|
| 1 | No path bypasses Caddy (ports, LAN `curl`, Tailscale `serve` / `funnel`, no Vite dev server) | **Owner to run; not checked by this step. Do not click "Move to server" until it passes.** |
| 2 | Origin / Host / Content-Type guard | `tests/js/requestGuard.test.js` passes; `secretsApi.test.js` shows a foreign Origin 403 and `text/plain` 415 on `PUT` / `DELETE /api/secrets/...`. The `.env` setting and the container recreate are the owner's. |
| 3 | Secrets never in GET responses, logs or backups | Tests 6.2 and 6.3 and the ledger / console part of 6.4 pass with the canary (`secretsApi.test.js`, `backupSecrets.test.js`, `secretStore.test.js`). The by-hand search after the first real key is the owner's. |
| 4 | Every AI call passes the gate | `grep -rn "provider.complete\|api.openai.com\|api.anthropic.com\|generativelanguage" scripts python src` finds one caller, `scripts/run-ai.js` (after `reserveAiCall`), and the gated Python client `llm_client.py`; the rest are provider implementations and default URL constants. `aiGate.test.js`, `aiKeyResolution.test.js` and `test_ai_gate*.py` pass. Key resolution adds no call of its own. |

Ledger note: the ledger is written by `python/llm/ai_gate.py` from what Node hands it, so the test asserts on the text handed to the gate
(`finish`, `refuse`, `reserve`); the exact-value mask runs before that.

## 11a. Step 3 as built (2026-10-29, `615c5c3`)

- **Store.** `data/secrets/linkedin.json` `{ li_at, setAt }` (700 / 600, atomic, never overwritten when unreadable); `describeSecrets()` gains
  `linkedin: { set, source, last4, setAt }`. Resolution: the store, then `LINKEDIN_LI_AT` in `.env`; both are exact-masked. Each file has its
  own cache. Routes `PUT` / `DELETE /api/secrets/linkedin` (same guard, fixed error text, nothing echoed). A cookie follows the key rule
  (12 to 512 characters, no spaces or control characters).
- **Request.** `POST /api/outreach/discover` no longer reads `liAt` (or anything else) for the cookie; the client stopped sending it.
- **Process.** `--li-at` is gone from the scraper. The bridge puts `LINKEDIN_LI_AT` in the child's environment in deep mode only; in search
  mode the variable is removed from the inherited environment. Python reads it and pops it before Playwright starts. Deep mode without a
  stored cookie does not start the scraper. Scraper stderr and the `error` / `status` it prints are masked in the bridge, and again in
  `run-outreach.js` before `metadata.linkedinScrape` is written to `data/outreach/<job>/contacts.json` (which backups include).
- **Session file.** `data/outreach/linkedin_session.json` is no longer read. It did not exist on this server when the step was built.
  If it ever does: set the cookie in Settings, delete the file, and delete backups made while it existed.
- **UI.** Privacy: secrets and keys has a LinkedIn row (Set / Replace / Remove) and a banner for a cookie found in the browser:
  Move to server (PUT, then GET: `set`, `source === "store"`, same last 4, only then `removeItem` and a read-back; a different cookie
  already on the server asks first, the same one is refused), or Remove from this browser without moving. The outreach panel shows
  set / not set and the last 4 and has no cookie input. Deep mode now needs the ticked box, the accepted risk **and** the typed
  "I understand" (the typed sentence used to gate only the cookie field).
- **Entry gate (restored in `e3438c8`).** The cookie input used to be disabled until the risk box was ticked and "I understand" typed; step 3
  moved the input to Settings and dropped that. The Set / Replace form shows the warning and needs the box and the phrase again (field, Save and the
  submit handler; `linkedinConsent.js`). The move banner is not gated: that cookie was entered under the old gate.
- **Browser.** `linkedin_li_at` stays in `TOLERATED_UNTIL_MIGRATED` (until step 5's scrub) because `src/modules/outreach/linkedinCookie.js`
  names it to read and remove it; nothing writes it (a static test checks).
- **Tests.** `tests/js/linkedinSecret.test.js` (store modes, routes, argv and child environment through an injected `spawn`, masking in
  stderr, move order, backup export / restore with a real store file), `tests/python/test_scraper_cli.py` (the real script has no `--li-at`).
  No test starts the scraper, fetches a page or writes under `data/`.

### Pre-migration checklist record (section 9) for step 3

| # | Item | State |
|---|---|---|
| 1 | No path bypasses Caddy | **Owner to run (same as step 2). Do not click "Move LinkedIn cookie to server" until it passes.** |
| 2 | Origin / Host / Content-Type guard | `linkedinSecret.test.js`: foreign Origin 403, `text/plain` 415 on `PUT` / `DELETE /api/secrets/linkedin`. |
| 3 | Secrets never in GET responses, logs or backups | Tests pass with a LinkedIn canary. The by-hand search after the real cookie is stored is the owner's (backup zip, `podman logs career-os`, and `ps` during a deep run). |
| 4 | Every AI call passes the gate | Unchanged: this step adds no AI call. |

## 11b. Step 4 as built (2026-10-29, `e139c81`)

- **One file.** `data/config/ai-settings.json`: `provider`, `model`, `temperature` (0 to 2), `maxTokens` (1 to 200000), `baseUrl` (ollama only,
  plain http(s)), `features` (the nine toggles). Validated and written by `python/llm/ai_selection.py` (strict, atomic, an unreadable file is never
  overwritten); no field can hold a key, and `apiKey` in a body is rejected as an unknown setting. `data/config/` is git-ignored and **not in
  backups**, so a restore leaves the selection as it is (or empty on a new machine: select once).
- **Routes.** `GET /api/ai/selection` answers the selection, each provider's class and `nodeProviders`; `PUT` takes `{ settings, confirm }`. A paid or
  unknown-class provider needs `confirm: true` when the provider, model or base URL changes (409 with the reason); temperature, tokens and toggles never do.
  `claude-code` is `paid` class in `aiPricing.json`, so choosing it asks too. Provider list: the nine priced providers; each side refuses those it cannot run.
- **Same reader.** Node asks `ai_gate.py selection-get`; Python calls `llm_client.active_provider()` (`ai_selection.require()`). `tests/python/test_ai_selection.py`
  runs the CLI Node uses and `active_provider()` on one file. `run-ai.js` takes provider, model, temperature, tokens and the ollama URL from the selection and
  reads none from the request; the client stopped sending them.
- **No silent switch.** No default: nothing selected, an unreadable or invalid file, or a provider that side cannot run refuses the call, logs it, and writes a
  ledger refusal. `OPENAI_API_KEY` & co, `CAREER_OS_LLM_PROVIDER` and the claude-code fallback no longer choose. A selected keyed provider without a key fails
  ("No API key configured" / "OPENAI_API_KEY is not set") and tries no other. The budget gate and redaction run as before.
- **Python callers.** A judged scoring run, CV analysis and enrichment stop with the message when nothing is selected; a local re-score (no call) uses
  `peek_provider()` and never fails for want of one. The `--provider` / `--judge-provider` flags of the dev scripts still name a provider explicitly for one run.
  Not covered: `llm_tailor.py`, job import and the project scan call the Claude Code CLI directly through the gate, whatever is selected.
- **Browser.** Settings > AI Provider loads from and saves to the server and lists every provider with its class (and which path can run it). Nothing is written to
  `localStorage` (a static test checks that only `aiSettings.js` names the key and has one `setItem`). Migration: **Move AI settings to server** sends only the
  non-secret fields (a base URL only for ollama, unknown toggles dropped), reads the selection back, and only then removes them; a paid provider asks first, a
  different selection already on the server asks before it is replaced, an equal one is not rewritten. A key still waiting for its move stays in the entry.
- **Provider health and models** still list every provider (a probe, not a call) and the model list uses the provider named in the request.

### Pre-migration checklist record (section 9) for step 4

| # | Item | State |
|---|---|---|
| 1 | No path bypasses Caddy | Unchanged; owner's. |
| 2 | Origin / Host / Content-Type guard | `aiSelection.test.js`: foreign Origin 403, `text/plain` 415 on `PUT /api/ai/selection`. |
| 3 | Secrets never in responses, logs or backups | The file has no secret field; a body carrying a key is rejected and not echoed (test). |
| 4 | Every AI call passes the gate | Unchanged: the selection is read before the gate, adds no call; a refusal is a ledger row. |
