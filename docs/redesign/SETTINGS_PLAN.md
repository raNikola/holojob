# Settings restructuring - plan

Status: PLAN with owner decisions recorded, 2026-10-29. This file is docs only: no code, no `data/` change, no AI call.

**Owner decisions (2026-10-29)**
- Categories, in nav order: **Job search, Sources, Applications** (Notifications is a section inside it), **AI & costs**
  (the automation switch lives here; there is no separate Automation category), **Privacy & security, Data & backups,
  General, Danger zone**. Resumes stays "later" (P5) and is not in the nav.
- **Shipped:** Track B (B1-B4, P9: the server is the only authority for AI provider, model, keys and budget; the browser
  holds no secret) and A7 (Settings > Applications: tracker panel, board columns, tracking switch).
- Open questions are answered or deferred in section 7. The first slice is defined in section 5.

Where the inventory (section 1) or the risks (section 6) describe browser-held AI state, that was true when the plan was
first written and is marked as such; Track B has since moved it to the server.

Inputs read: CLAUDE.md, DECISIONS.md (principles 13-16), GAP_ANALYSIS.md (module 15, 3.1 item 13, step 11),
TRACKER_PLAN 1.7 / 3.2 (Settings -> Applications), SOURCES_SPEC.md, and the code: `SettingsHome.jsx`,
`AISettingsPanel.jsx`, `AIBudgetPanel.jsx`, `AIProviderSelector/ModelSelector/FeatureToggles/HealthStatus/UsageDashboard`,
`ScoringWeightsPanel.jsx`, `ApplicationMigrationPanel.jsx`, `TopBar.jsx`, `PipelineOrchestrator.jsx`, `ProfileForm.jsx`,
`RelatedContactsPanel.jsx`, `appNavigation.js`, `App.jsx`, `aiSettings.js`, `scripts/api-handler.js`.

## 0. What Settings is today

- One view, `VIEWS.SETTINGS = 'settings'` (`appNavigation.js`), rendered by `<SettingsHome />` (`App.jsx:80`).
  No router: the active view is kept in `sessionStorage` (`VIEW_STORAGE_KEY`). So there are no URLs to deep-link to.
- `SettingsHome` is one long column of `Card`s: Data paths, Demo data, Pipeline API status, `AISettingsPanel`
  (which itself stacks AI budget, Models and prices, Gate usage, AI Provider, Provider health, Feature toggles,
  Usage and cost), Scoring weights, Application tracking migration, Backup / restore, Clear local data, a CLI `<details>`.
- Settings are scattered outside Settings too: the dark-mode toggle is in `TopBar`, search preferences (country,
  salary floor, locations, target roles) are in the Profile form, the provider group and country for a run are local
  state in `PipelineOrchestrator`. (The LinkedIn `li_at` cookie was typed into `RelatedContactsPanel` and held in
  `localStorage`; since B2 it goes to the server secret store.)
- Storage worlds with different save styles, which the new structure must make visible instead of hiding:
  1. **Browser `localStorage`**, for UI state and per-viewer display preferences only. Since B4 it holds no AI provider,
     model, key or feature toggle; what remains is the browser usage log and response cache, and (until migration
     step 5) the profile, intelligence and jobs.
  2. **Server file via a route**, save with validation and two-step confirm: AI budget, pricing, AI provider selection
     (`data/config/ai-settings.json`), secrets (`data/secrets/`), tracker settings.
  3. **Browser master mirrored to `data/` on sync** (profile, intelligence, scoring weights), until migration step 5.

## 1. Inventory (every existing setting)

Route column: **has** = a server route exists; **needs** = a new route is required before the setting can be server-side
(DECISIONS 15/16); **n/a** = browser-only or read-only by design.

Rows 1-6, 13 and 26 are updated to the current state (Track B and A7 shipped); the other rows are as first inventoried.

| # | Setting | Component (file) | Where it lives now | Stored in | Route |
|---|---|---|---|---|---|
| 1 | AI provider (claude-code, mock, ollama, openai, claude, gemini, openrouter) | `AIProviderSelector` | AI Provider card | `data/config/ai-settings.json` (**was** `localStorage` `job-dashboard-ai-settings`; B3/B4 shipped). No default: nothing selected refuses the call | has (`GET` / `PUT /api/ai/selection`; a paid or unknown-class selection needs `confirm: true`) |
| 2 | Model | `AIModelSelector` | AI Provider card | same file | has (`/api/ai/models`, read only list; model saved through `/api/ai/selection`) |
| 3 | Base URL (ollama; a custom one for openrouter) | `AIProviderSelector` | AI Provider card | ollama URL in `ai-settings.json`; a keyed provider's URL is stored with its key in `data/secrets/ai.json` | has (`/api/ai/selection`, `/api/secrets`) |
| 4 | API key | Settings > Privacy: secrets and keys | Privacy & security | `data/secrets/ai.json` (600 / 700, outside backups; **was** plain text in `localStorage`; B1/B4 shipped) | has (`GET /api/secrets`, `PUT` / `DELETE /api/secrets/ai/<provider>`; no route returns a key) |
| 5 | Temperature, max tokens | `AISettingsPanel` | AI Provider card | `ai-settings.json` (O1: server) | has (`/api/ai/selection`) |
| 6 | Browser AI feature toggles (9 features) | `AIFeatureToggles` | Feature toggles card | `ai-settings.json` (O1: server) | has (`/api/ai/selection`; the gate is enforced in `run-ai.js` / `ai-gate.js` regardless) |
| 7 | Provider health (read only) | `AIHealthStatus` | Provider health card | none | has (`/api/ai/status`, `/api/claude/status`, `/api/claude/login`) |
| 8 | Daily / monthly limit, max paid calls per day / month, estimated output tokens, currency, timezone, automation switch | `AIBudgetPanel` | AI budget card | `data/ai/settings.json` | has (`GET /api/ai/usage`, `PUT /api/ai/settings`, confirm on raise) |
| 9 | Model prices and free / local / paid class | `AIBudgetPanel` `PricingTable` | Models and prices card | `data/ai/pricing-overrides.json` over `src/data/aiPricing.json` | has (`PUT /api/ai/pricing`) |
| 10 | Gate usage and ledger (read only) | `AIBudgetPanel` | Gate usage card | `data/ai/usage-ledger.jsonl` | has (`GET /api/ai/usage`) |
| 11 | Browser usage log and response cache (view, clear) | `AIUsageDashboard`, `aiUsageTracker`, `aiResponseCache` | Usage and cost card | `localStorage` | n/a (clear = local action) |
| 12 | Scoring weights (6 sliders) | `ScoringWeightsPanel` | Scoring weights card | intelligence (`localStorage` master, mirrored to `data/intelligence/candidate-intelligence.json`) | has (`/api/intelligence/save`, `/api/scoring/run`) |
| 13 | Application tracking switch, follow-up reminders switch, stage registry (columns, `interview` flag, retire / restore) | tracker panel in Settings > Applications (**A7, shipped**) | Applications | `data/applications/settings.json` | has (`GET/PUT /api/applications/settings`, `POST /api/applications/settings/stages`) |
| 14 | Application migration (dry run, run) | `ApplicationMigrationPanel` | own card | action, writes `data/applications/` + backup | has (`migrationClient`) |
| 15 | Backup export / restore | `SettingsHome` | Backup card | action | has (`/api/backup/export`, `/api/backup/import`) |
| 16 | Import jobs JSON only | `SettingsHome` | Backup card | `localStorage` jobs | n/a |
| 17 | Load demo data | `SettingsHome` | own card | `localStorage` + demo bootstrap | has (`/api/demo/bootstrap`) |
| 18 | Clear all local data | `SettingsHome` | own card | `localStorage` | n/a (and does not touch `data/`, which the label does not say) |
| 19 | Data paths (read only) | `SettingsHome` | own card | none | n/a (hard-coded text) |
| 20 | Pipeline API status (read only) | `SettingsHome` | own card | none | has (`/api/pipeline/health`) |
| 21 | CLI commands (copy) | `SettingsHome` | `<details>` | none | n/a |
| 22 | Dark mode | `TopBar`, `OnboardingWizard` | top bar, not Settings | **not persisted** (class on `<html>`) | n/a |
| 23 | Search country, target roles, preferred cities, minimum / desired salary, salary expectation | `ProfileForm` | Profile screen | profile (browser master) | has (`/api/profile/save`) |
| 24 | Providers group (`serbia` ...), country, tailor mode for a run | `PipelineOrchestrator` | Jobs > Pipeline, local state | none (resets each visit; `providers` default hard-coded `'serbia'`) | needs (SOURCES_SPEC `data/config/sources.json`) |
| 25 | Job boards on/off, watched companies | **none** (Phase 3b) | `provider_registry.py`, `companies/*.json` | repo files | needs |
| 26 | LinkedIn `li_at` cookie | `RelatedContactsPanel` | Outreach panel | `data/secrets/linkedin.json` (**was** `localStorage` `linkedin_li_at`; B2 shipped) | has (`PUT` / `DELETE /api/secrets/linkedin`) |
| 27 | Questionnaire (17 answers) | `QuestionnaireForm` | own screen | profile | has |
| 28 | Judge / matcher confirm, enrichment cap, shadow mode (`HOLOJOB_ENGINE_SHADOW`) | confirm dialogs, `.env` | not in Settings | env / CLI flags | needs for any that should be user-editable |
| 29 | Active view, jobs tab, chat history, AI memory, pipeline state | various | none | `sessionStorage` / `localStorage` | n/a (UI state, not settings) |

Row 29 is state, not settings: it stays out of Settings. Rows 19, 20, 21 are information, not settings; they move to
"About / system".

## 2. Proposed categories

Decided by the owner (2026-10-29): the nav has eight categories: Job search, Sources, Applications, AI & costs,
Privacy & security, Data & backups, General, Danger zone. **Notifications** is a section inside Applications. The
**automation switch** is a section of AI & costs; there is no separate Automation category. **Resumes** is thin today,
so it is left out of the nav and added when Resume Manager starts (P5). **Privacy & security** is a real category
because it holds the secrets and keys panel and is where the "what leaves the server" rules should be visible
(today only CLAUDE.md shows them). **Applications** absorbs the migration. Order below is the left-nav order. Later
sections of this document write "Privacy" for Privacy & security.

| Category | Sections (collapsible groups) | Existing settings that go here |
|---|---|---|
| **Job search** | Search settings · Scoring weights · Gates and flags | 12, and 23 (PROPOSED P1: edited here, stored once in the profile object, read by the Profile screen; before A9 they stay in the Profile form) |
| **Sources** | Job boards · Watched companies · Source keys | 24, 25 (Phase 3b); keys per ADR-0034 |
| **Applications** | Tracking · Board columns · Notifications (follow-up reminders; P4) · Migration and import | 13 (shipped, A7), 14 (migration moves here in slice 1) |
| **Resumes** *(later, P5)* | CV library defaults · Tailoring defaults · Cover letter defaults | not in the slice 1 nav; added when Resume Manager starts. Future: modules 5 / 6 / 7 / 8 (section 4) |
| **AI & costs** | Provider and model · Budget and limits · Automation · Models and prices · Feature toggles · Usage and ledger · Cache | 1, 2, 3, 5, 6, 7, 8 (including the automation switch), 9, 10, 11 (4 is in **Privacy & security**) |
| **Privacy & security** | What leaves this server (read-only summary generated from the redaction rules) · Secrets and keys · Confirmations | 4, 26 (both already server-side); the "no confirm yet" browser AI gap (CLAUDE.md) shown honestly |
| **Data & backups** | Backup and restore · Import · Data locations · Demo data | 15, 16, 17, 19 |
| **General** | Appearance · Formats · System / about | 22, 20, 21. The budget timezone stays in AI & costs; a Calendar timezone will live in the Calendar section (P3) |
| **Danger zone** | Clear local data · Reset profile · Reset AI usage log · (future) purge applications | 18, plus destructive buttons pulled out of other categories (`Clear browser usage log`, `Clear cache` stay in AI & costs because they are low-risk; `Restore from backup` is destructive but stays in Data & backups behind its existing confirm, see risks) |

Plus a **search box** at the top of the nav. Search is over a static registry (section 3 of the first slice), not the
DOM.

Layout (structure only, polish is not a goal):

```
+--------------------+--------------------------------------------+
| [ Search settings ]| AI & costs                                 |
| Job search         | v Provider and model                       |
| Sources            |   ...                                      |
| Applications       | > Budget and limits                        |
|                    | > Automation                               |
| > AI & costs  (3)  | > Models and prices                        |
| Privacy & security |                                            |
| Data & backups     |                                            |
| General            |                                            |
| Danger zone        |                                            |
+--------------------+--------------------------------------------+
```

A `(3)` marks sections with unsaved changes (risks, section 6).

## 3. Where new settings go (rule table)

One rule: **a module never adds a Settings screen or a card at the top level. It adds a section to the category
below, registered in the settings registry (first slice).** Reading rule for "category": where does the owner look
for it - the *thing it controls*, not the module that owns it. Costs and limits always go to AI & costs.

| Planned module | Category -> section | What goes there | Stored (principle 15/16) |
|---|---|---|---|
| Job Discovery | **Sources** -> Job boards, Watched companies; **Job search** -> Gates and flags (search country default stays out: it comes from the profile) | boards on/off, company list, probe, last run; run frequency | `data/config/sources.json` |
| Job Details | **General** -> Display (which fields show) ; **Sources** -> Liveness (check frequency, D11) | show / hide `datePosted`, expiry; liveness interval | `data/config/display.json` (browser pref allowed), liveness in `sources.json` |
| Companies | **Job search** -> Watchlist; **Privacy** -> Contacts storage | watch / blocklist, contact retention | server store (D8) |
| Applications | **Applications** -> Tracking, Board columns, Follow-up reminders, Migration and import | tracking switch, stage registry, nudges, CSV import entry | `data/applications/settings.json` |
| Resume Manager | **Resumes** -> CV library defaults | default CV, versioning policy (D12), original-file retention | profile / `data/config/resumes.json` |
| Resume Match | **Resumes** -> Match defaults; weights stay in **Job search** | default CV used as evidence source, show gaps | `data/config/` |
| Cover Letter | **Resumes** -> Cover letter defaults | tone, length, language, sign-off | `data/config/` |
| Application Pack | **Resumes** -> Application pack | what a pack contains, default file names, "ask before freezing" | `data/config/` |
| Interviews | **Applications** -> Interviews | default interview types, prep question count, notes template | `data/applications/settings.json` (same file, new key) |
| Calendar | **Applications** -> Calendar (and **Privacy** -> Confirmations for any push to Google, D6) | ICS export, week start, default reminder lead time, Google connection | `data/config/calendar.json`, tokens in the secret store |
| Job Offers | **Applications** -> Offers | default currency, comparison period, benefits list | `data/applications/settings.json` |
| Salary Calculator | **Job search** -> Salary (floor lives in Profile; calculator rules are not user settings) ; **General** -> Formats (currency, gross / net default) | default engagement form, tax year pointer (read-only, source and date shown) | rules in versioned repo data, preference in `data/config/` |
| Statistics | **General** -> Formats ; **Applications** -> Reporting | date range default, the definition of "interviewing" (D9) | `data/config/` |
| AI usage / limits | **AI & costs** only (sections Budget and limits, Automation, Models and prices, Usage and ledger, Cache) | budget, caps, automation, per-module caps, cache TTL | `data/ai/settings.json` |

Two supporting rules:
1. **Storage follows data, not UI.** New settings are server-side under `data/config/` or `data/<module>/settings.json`
   with the tracker's atomic write; browser `localStorage` only for per-viewer display preferences (principle 15).
2. **Anything that can raise spend, send data out, or delete is flagged in the registry** (`risky: 'spend' | 'egress' | 'delete'`)
   and must use the existing two-step confirm pattern (`SaveResult` in `AIBudgetPanel`).

## 4. Settings missing today that future modules need

| Module | Missing setting | Note |
|---|---|---|
| Job Discovery | Active boards, company list, probe, key per keyed source, run schedule | Phase 3b / SOURCES_SPEC |
| Job Details | Liveness check interval, what counts as `expired` (D11) | |
| Companies | Company key policy (exact `norm()`), contact storage location | D8 |
| Applications | Tracking switch, stage registry UI, reminders (S5); nudge thresholds are code constants (not settings); CSV import entry | TRACKER_PLAN 3.2 |
| Notifications | Channel (in-app only today), quiet hours | D7; ApplyPack has a Notifications tab, we start with a section under Applications |
| Resume Manager | Default CV, version lineage policy | D12 |
| Resume Match | Which CV is the evidence source | GAP module 6 |
| Cover Letter | Tone, length, language | GAP module 7 |
| Application Pack | Pack contents, default names | |
| Interviews | Default types, prep options | |
| Calendar | ICS / Google, reminder lead time, week start | D6 |
| Job Offers | Default currency and period | |
| Salary Calculator | Engagement form default, tax year | D5 |
| Statistics | Date range, "interviewing" definition | D9 |
| AI usage / limits | Per-module caps, cache TTL, **confirm for pipeline enrichment** (GAP finding 1), D1 (does "budget 0" include claude-code and ollama) | |
| General | **Persisted** dark mode (today it resets), display timezone, date / currency format, language | |
| Privacy | Server-side secret store for API keys and `li_at`; a read-only "what leaves this server" page; the browser-AI confirm (principle 14, CLAUDE.md "no confirm yet") | |

## 5. Implementation sequence: two tracks

Two independent tracks. **Track A** is UI only and changes no behavior. **Track B** touches secrets and AI calls and has
its own tests. Every step is marked with what it needs first; "independently shippable" means the app works, and the
tests pass, after that step alone. Neither track blocks the other, except where a step says so.

### What slice 1 changes, and what it does not

Slice 1 = A1 + A2 + A3 (they can be one commit or three), with the existing panels placed as below. Track B and A7
are shipped, so the panels being moved already include the server-side secrets and AI selection, and the
Applications tracker panel.

**Changes**
- Adds a pure registry module `src/modules/settings/settingsRegistry.js` and its test `tests/js/settingsRegistry.test.js`
  (unique category and section ids; every section names an existing category; search finds "budget" -> AI & costs,
  "backup" -> Data & backups, "weights" -> Job search; every `render` is a function).
- `SettingsHome.jsx` becomes a shell: a left navigation with the eight categories (Job search, Sources, Applications,
  AI & costs, Privacy & security, Data & backups, General, Danger zone) and a right panel. The existing panels are moved
  under them, not rewritten. **All categories stay mounted** (hidden with CSS) so typed drafts survive switching.
- Placement: scoring weights under Job search; the tracker panel (tracking switch, board columns, Notifications) and
  **the application migration panel under Applications**; AI budget, pricing, provider and model, feature toggles,
  usage and the automation switch under AI & costs; secrets and keys under Privacy & security; backup / restore, import,
  demo data and data paths under Data & backups; pipeline status and CLI commands under General;
  **Clear local data under Danger zone, with its confirm unchanged** (same button, same `window.confirm`).
- Adds one `sessionStorage` key (`job-dashboard-settings-category`) for the selected category.
- Adds the `openSettings(sectionId)` helper in `appNavigation.js` and re-points the existing text references that name
  a Settings section (`PipelineOrchestrator.jsx`, `ApplicationTrackerPanel.jsx`, the "tracking is off" link; re-grep
  for the current line numbers, they have moved).

**Does not change**
- **No new settings and no behaviour change.** No component logic: `AISettingsPanel`, `AIBudgetPanel`,
  `ScoringWeightsPanel`, `ApplicationMigrationPanel`, the tracker panel, secrets, backup and demo handlers are mounted as
  they are, with their section titles verbatim (CLAUDE.md names "Settings screen > AI budget" and "Settings > Privacy:
  secrets and keys").
- No storage: no new file under `data/`, no new route, no `.env` change. Profile fields stay in the Profile form.
- No AI call path: nothing near `ai-gate.js`, `ai_gate.py`, `run-ai.js`, `redact.py`, `ai-redact.js` or the secret store
  is touched.
- No URL or hash routing (A4), no unsaved-changes layer (A8), no dark-mode persistence (A6).
- Sources shows an empty-state line where its content is not built yet. Resumes is not in the nav (P5).

**Slice 1 as built (2026-10-29).** Shipped as defined above, in two code commits (registry and test; shell, moves and
`openSettings`). Differences from the plan text:
- The registry is pure data (id, category, title, keywords, `risky`, an optional `note`); it holds no `render`.
  `SettingsHome` keeps a `RENDERERS` map keyed by section id, and the test checks that its keys equal the registry ids.
- One `AI budget, provider and usage` section (`ai-budget`) holds `AISettingsPanel` whole; splitting it is A5.
  Likewise `application-tracking` holds `ApplicationSettingsPanel` whole.
- Notifications is registered under Applications with a one-line note ("not configurable yet"): the follow-up
  reminders switch does not exist in the UI. Sources is empty and shows its note.
- The selected category is kept in `sessionStorage` (`job-dashboard-settings-category`, on the allowlist); the hash
  route stays A4. `openSettings` sets the category, leaves the section id for `SettingsHome` and dispatches
  `holojob:open-settings`; `App` switches the view.
- Re-pointed to `openSettings`: `PipelineOrchestrator` (AI budget), `ApplicationTrackerPanel` (migration),
  `ApplicationBoard` (tracking is off). `RelatedContactsPanel` still names "Settings > Privacy" as text.
- O9 needed no new test: `tests/js/backupSecrets.test.js` already checks that an export carries nothing from
  `data/secrets/` and that a restore cannot write it.
- The "Clear all local data" label is unchanged (A10 rewords it).

### Track A - UI only, no behavior change

| Step | What | Needs first | Independently shippable |
|---|---|---|---|
| **A1** | **Settings registry + test.** `settingsRegistry.js`: `{ id, category, section, title, keywords[], risky?, render }`, stable ids, `searchSettings(query)`. `tests/js/settingsRegistry.test.js`: unique category and section ids; every section names an existing category; `searchSettings` finds "budget" -> AI & costs, "backup" -> Data & backups, "weights" -> Job search; every `render` is a function. | nothing | Yes. Pure data, nothing imports it yet. |
| **A2** | **Navigation shell + section ids.** `SettingsHome` renders nav, panel and search from the registry. All categories stay mounted and are hidden with CSS, so typed values survive switching. Selected category in `sessionStorage`. Mobile: nav becomes a `<select>`. | A1 | Yes. Same cards, same behavior, new frame. |
| **A3** | **`openSettings(sectionId)` helper.** Sets category and section, then switches the view to Settings. Re-point `PipelineOrchestrator.jsx:262`, `ApplicationTrackerPanel.jsx:157` and the "tracking is off" link. | A1 (A2 to be visible) | Yes. Without A2 it falls back to opening Settings. |
| **A4** | **Hash routing** `#settings/<category>/<section>` (PROPOSED P8). No router library. App reads the hash on load and on `hashchange`; opening a section writes it; Back works. The `sessionStorage` view memory stays for every other view. | A2, A3 | Yes. |
| **A5** | **Split `AISettingsPanel`** into AI & costs sections (Provider and model, Budget and limits + Automation, Models and prices, Feature toggles, Usage and ledger, Cache). Unwrapping, no logic change. Provider and model already read the server (B3 shipped). | A2 | Yes. |
| **A6** | **Persist dark mode** (General > Appearance), `TopBar` toggle stays as a shortcut to the same value. Small `localStorage` key. | A2 | Yes. This is the one step here that adds a behavior (a remembered display preference), not a pure move. |
| **A7** | **SHIPPED.** **Settings > Applications** (TRACKER_PLAN S5): tracker panel with the tracking switch, board columns (rename, reorder, add, remove = retire, restore). The follow-up reminders switch sits in the Notifications section (P4). The panel is moved under the Applications category by slice 1; the migration panel joins it there. | A2 | Yes. |
| **A8** | **Unsaved-changes layer:** `useSettingsDirty()`, a dot in the nav, `beforeunload` and an in-app prompt. Never auto-saves a spend-raising change. | A2 | Yes. |
| **A9** | **Job search settings editor** (PROPOSED P1): country, target roles, cities, minimum / desired salary, salary expectation, edited in Settings > Job search. The stored value stays the profile object (browser master, mirrored on sync). The editor and the Profile form both read and write it through the same `useProfile().updateProfile` path; there is never a second copy or a second save. | A2 | Yes, but it moves where a field is edited, so it needs its own test that the Profile form shows the value saved in Settings and the reverse. |
| **A10** | **Danger zone consolidation:** typed confirmation, wording that says what is and is not removed ("Clear local data" leaves `data/` untouched), a backup offer first. Browser clears and resets only (P2). | A2 | Yes. |
| **A11** | **Privacy page:** a read-only "what leaves this server" list generated from one constant, with a test that checks it against the CLAUDE.md privacy list. | A2 | Yes. Read only. |

Later, by their own features, one registry entry each: Sources (Phase 3b), Resumes (when Resume Manager starts), and
the module sections in section 3.

### Track B - security and AI

**Status: B1-B4 shipped (P9).** The table is kept as the record of what each step had to do and prove. The server is
now the only holder of AI keys and `li_at` (`data/secrets/`), of the provider selection (`data/config/ai-settings.json`)
and of the budget; the browser holds none of them. Details: CLAUDE.md, sections "Secret store (AI keys)" and "AI provider
selection".

Rule for every step in this track: **every AI call must still pass the budget gate and the redaction step.** That
means `ai_gate.py` (`llm_client.complete_json`, `claude_code._run`) and `ai-gate.js` from `run-ai.js`, then
`redact.py` / `ai-redact.js`. No step adds a provider call that bypasses them, and each step keeps the existing gate,
redaction and privacy tests passing (`tests/python/test_engine_privacy.py`, `tests/js/aiRedaction.test.js`, the ledger
and gate tests). No step is run with a real provider; tests use `mock` or a stub transport. The known gaps in CLAUDE.md
(browser AI features without a confirm dialog, LLM tailoring without redaction) are not part of this track.

| Step | What | Tests it needs | Needs first | Independently shippable |
|---|---|---|---|---|
| **B1** | **Server secret store, AI API key.** New directory `data/secrets/` (git-ignored, **outside** the backup `DATA_DIRS`, file mode 0600, atomic write). Routes: set, clear, and a status read that returns only `{ set, last4 }`, never the value. `run-ai.js` reads the key on the server instead of `settings.apiKey` from the request body; the body field is ignored. One-time move: the Settings screen offers "Move key to server", writes it, then deletes it from `localStorage`. | the key never appears in a GET response, a log line, an error (`sanitizeKey`), the usage ledger or a backup ZIP; after the move `localStorage` holds no key; a request body carrying `apiKey` is ignored; a call with no stored key is refused with a clear message; gate and redaction tests unchanged | nothing | Yes. |
| **B2** | **Server secret store, LinkedIn `li_at`.** Same store and routes; the scraper bridge reads it on the server; `RelatedContactsPanel` shows set / not set only and deletes the `localStorage` copy. Check `data/outreach/` (it is in the backup `DATA_DIRS`) for a session file and keep it out of the ZIP. | same set as B1 for this secret; backup test that no secrets directory or session file is archived | B1 (store and routes) | Yes. |
| **B3** | **Single provider selector on the server** (PROPOSED P9). Provider, model, base URL live in one server file (proposed `data/ai/provider.json`, next to the budget). `llm_client.active_provider()`, `run-ai.js` and the Settings selector all read it, so the budget gate and the selector can never disagree. The browser selector becomes a view over `GET` / `PUT`. Unknown provider = paid, as in `aiPricing.json`. | Python and Node resolve the same provider from the same file; env keys no longer pick a provider silently (see O4); a paid provider cannot be selected without the gate having a known price; free / local / paid class shown matches `aiPricing.json` | B1 | Yes. |
| **B4** | **Remove secrets and provider from browser state.** `aiSettings.js` stops storing `apiKey`, `provider`, `model`, `baseUrl`; `aiClient.js` stops sending them. Temperature, max tokens and feature toggles: see O1. | `localStorage` after a normal session contains no key (grep test over `aiSettings` save output); `aiClient` request has no `apiKey`; existing `aiRedaction` test still checks every feature at the provider | B1, B3 | Yes. |

Not in Track B, and not allowed by it: any new route that calls a model, any change that lowers a limit check, any
automation switch default. A change that raises what the gate allows still needs `"confirm": true`.

## 6. Risks

| Risk | Detail | Mitigation |
|---|---|---|
| **No router, no deep links** | The app switches views from `sessionStorage`. Messages elsewhere say "Settings, AI budget" (`PipelineOrchestrator.jsx:262`) and "Settings -> Application tracking migration" (`ApplicationTrackerPanel.jsx:157`), and the tracker's "tracking is off" screen links to Settings. After the change those names still must resolve. | Registry gives every section a stable id. Add `openSettings(sectionId)` in `appNavigation` (sets category + section, then `setView(SETTINGS)`) in slice 1 and point those three messages at it. Hash routes in A4 (PROPOSED P8). |
| **Renamed labels break docs and text** | CLAUDE.md names "Settings screen > AI budget" and "Application tracking migration". | Keep these section titles verbatim; update CLAUDE.md in the same commit that moves them. |
| **Unsaved changes** | Today each card has its own Save. A nav that unmounts a category loses typed values (AI provider block, pricing draft, budget form, weights sliders). The pricing editor and budget form even keep drafts in local state. | Slice 1: keep all categories mounted (hide with CSS) so nothing is lost on switch. A8: dirty registry + "unsaved" dot + `beforeunload`/in-app prompt. Never auto-save a spend-raising change. |
| **Raising spend or automation** | AI budget uses a server-enforced two-step confirm (409 with list). A shell must not wrap it in anything that auto-submits, and search results must not render a bare toggle for automation. | Registry flag `risky`; search opens the section, never renders the control inline. Keep `SaveResult` as the only pattern. |
| **Destructive actions** | `Clear all local data` uses `window.confirm` and only clears the browser, though users read it as "clear everything". `Restore from backup` overwrites `data/`. Moving them to a Danger zone could lull people if the confirm gets weaker. | Keep both confirms as they are in slice 1. A10: typed confirmation ("type DELETE"), say exactly what is and is not removed, offer a backup download first. Restore stays in Data & backups but gets the same wording rule. |
| **Secrets in `localStorage`** | **Resolved.** The AI key and `li_at` were plain text in the browser (inventory rows 4, 26). | Fixed by Track B (B1, B2, B4): `data/secrets/`, no route returns a key, the browser copy is cleared once the server confirms. Remaining work: O9, a test that backups exclude `data/secrets`. |
| **Two sources of truth for AI provider** | **Resolved.** Browser and Python used to pick the provider separately. | P9 / B3: `data/config/ai-settings.json` is the only source, there is no default and no env fallback (O4). |
| **Settings the browser owns vs files the server owns** | Profile / intelligence / scoring weights are browser-master (`localStorage`) and mirrored; showing them in Settings invites editing the disk file by hand, which is overwritten. | P1 keeps one stored copy of the search settings (the profile object) with two views; weights keep their current save path (`saveIntelligence` + `saveIntelligenceToDataDir`). |
| **Search drift** | A hand-written keyword list rots. | Registry is the single source for nav, search and deep links; test that every rendered section is registered (via a `data-settings-section` attribute check in a render test, or a code review rule). |
| **Mobile** | `AppShell` has a mobile "More" menu that routes to Settings; a left nav needs a collapsed form. | Under a width breakpoint the nav becomes a `<select>` at the top. Structure only. |
| **Test environment** | The host has no Node (GAP analysis). | O10: JS tests run in a throwaway `node:20-bookworm` container with `--security-opt label=disable` (never `:Z`). Python tests run on the host `.venv`. State which were not run. |

## 7. Decisions and open questions

**Status: P1-P8 PROPOSED, pending owner confirmation, except where the owner has since decided (P4 and P5 are
reflected in the category list; P9 is shipped). The open questions O1-O10 below were answered or deferred by the
owner on 2026-10-29.**

| # | Topic | PROPOSED | Effect on the plan |
|---|---|---|---|
| P1 | Search settings (was Q1) | Move to **Settings > Job search**. The Profile screen reads the **same stored values**; there is one source, never two independent copies. The stored value stays in the profile object (browser master, mirrored to `data/profile/` on sync, `frontend.md`). | A9. Reverses the earlier recommendation ("Edit in Profile" link). Profile stops being a second editor, or edits the same state. |
| P2 | Danger zone (was Q2) | Browser clears and resets only. No purge in the UI (DECISIONS 2026-10-28). | A10. |
| P3 | Timezone (was Q5) | The budget's IANA timezone stays the **budget's day boundary only**. A future Calendar gets its **own** timezone setting in its own section. No single app-wide timezone. | None now. The General row "display timezone" is dropped from section 2. |
| P4 | Notifications (was Q6) | A **section under Applications**, not a category, until D7 (channels). | A7 (shipped) holds the follow-up reminders switch there. |
| P5 | Resumes (was Q7) | The category is **added when Resume Manager starts**. Not in slice 1. | Section 2 keeps the row as "later". |
| P6 | UI language (was Q8) | Out of scope. No section reserved. | None. |
| P7 | Scoring weights (was Q9) | Stay in **Job search**, with a note on "Save & re-score". | Note text added in A2 or later; no move. |
| P8 | Deep links (was Q3) | Hash routing `#settings/<category>/<section>`. No router library. | A4. The multi-device router question is deferred. |
| P9 | AI authority (was Q4) | The **server is the only authority** for AI provider, model, keys and budget. **The browser stores no secrets.** | **Shipped:** Track B (B1-B4). |

### Open questions: owner answers (2026-10-29)

- **O1** Temperature, max tokens and the nine browser feature toggles: **answered, server.** They live in
  `data/config/ai-settings.json` with the provider and model (shipped in B3/B4).
- **O2** Secret store location: **keep `data/secrets/`** (outside backups and git). Not `.env`.
- **O3** Selecting a paid provider: **confirm required, and enforced.** A paid or unknown-class selection (a change of
  provider, model or base URL) needs `"confirm": true`, else 409.
- **O4** Env keys and the `active_provider()` fallback: **no fallback, documented.** There is no default; nothing
  selected refuses the call, logs it and writes a ledger refusal (CLAUDE.md, "AI provider selection").
- **O5** Does a salary or role change in Settings trigger `regenerateIntelligence()` like the Profile form, and does the
  onboarding wizard keep writing the same fields: **deferred until the profile is server-master** (migration step 5).
  A9 waits for it.
- **O6** Moving an existing key: **moot.** B1/B4 shipped; the older browser key is moved from Settings > Privacy and cleared
  only after the server confirms the same last 4 characters.
- **O7** Hash routing next to the `sessionStorage` view memory: **the hash route wins on load.** Implemented later (A4),
  not in the first slice. Whether Back steps through sections stays to be decided with A4.
- **O8** `.gitignore` for `data/applications/`, `data/config/`, `data/secrets/`: **resolved.** `git check-ignore -v` shows
  all three ignored (`.gitignore` lines 43-45).
- **O9** Backup scope: **add a test that backups exclude `data/secrets`** (and the LinkedIn session file). Open work item;
  Phase 3b adding `data/config/` to `DATA_DIRS` must not add secrets.
- **O10** Test run: JS tests run in a **throwaway `node:20-bookworm` container with `--security-opt label=disable`, never
  `:Z`** (the repo is not relabelled). Python tests run on the host `.venv` with `-m "not network"` offline.


## Files this plan will touch (when executed)

Slice 1 (A1-A3) only: `src/components/settings/SettingsHome.jsx` (shell), `src/modules/settings/settingsRegistry.js` (new),
`src/modules/appNavigation.js` (`openSettings`), the existing text references to a Settings section (re-grep), `tests/js/settingsRegistry.test.js` (new).
Reuse, unchanged: `AISettingsPanel`, `AIBudgetPanel`, `ScoringWeightsPanel`, `ApplicationMigrationPanel`, `Card`, `Button`,
`Alert`. Docs: this file; a one-line pointer in `docs/ROADMAP.md` (Settings consolidation step) and a CLAUDE.md update
only for section names that move.

## Verification of this document

- Every row in section 1 was read from the file named; rows 13 and 25 are "not in the UI yet" by design.
- Not verified: the remaining screens that may hold settings I did not open (Intelligence screen filters, Quality
  Audit run options, Outreach run options, `JobFilters`). Slice 1 should start with a grep for `localStorage` and
  "Save" in those to confirm the inventory is complete.

## Reset profile (as built, 2026-11-01)

Danger zone > Reset profile (`ResetProfilePanel.jsx`). A dialog lists what is removed and kept (`RESET_REMOVES` / `RESET_KEEPS` in
`modules/profile/profileReset.js`), offers "Download backup (JSON)" (profile and intelligence as the browser holds them; the CV PDFs are
only in the server folder) and enables the button when `RESET` is typed exactly. `POST /api/profile/reset` with `{"confirm":"RESET"}`
(`scripts/profile-reset.js`) copies `data/profile/*` (except `.gitkeep`) and `data/intelligence/candidate-intelligence.json` into
`data/profile.bak-YYYYMMDD-HHMMSS/{profile,intelligence}/`, checks the sizes, and only then removes the originals; a failed copy deletes
the partial backup and keeps everything (`backup_failed`). Nothing to move answers ok with no backup (idempotent). Answers are fixed
codes; no profile text is echoed. Only after the server says ok does the browser clear `job-dashboard-candidate-profile` and
`job-dashboard-candidate-intelligence`, reset the context, and open onboarding. Jobs, applications, AI data, secrets, config and
`project-intelligence.json` are not touched. Scoring weights live inside the intelligence file, so they go back to the defaults (the
backup keeps them). A second open tab still holds the old profile in memory until it reloads.
