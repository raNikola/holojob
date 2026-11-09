# Shared job database for several users: plan

Status: PLAN, 2026-11-09. Docs only: no code, no `data/` change, no AI call, no migration. **Not built and not scheduled.** It guides Step 5 and later work so that nothing built now has to be torn up when a second user arrives.

Principle 15 (single user for now) stays in force. Nothing in this plan changes today's behaviour.

Inputs read: `STEP5_SERVER_MASTER_PLAN.md` (sections 0 to 2.3, 2.8, 4 to 7, 9, 10), `DECISIONS.md` (principles, 2026-10-26 stable ids, Wave 1 and Wave 2 entries), `PHASE0_AUDIT.md` (headings only), `SOURCES_SPEC.md`, `data-shapes.md` (ledger, run log, job state, source switches), `.claude/rules/request-guard.md`, `.claude/rules/scoring.md`, `.claude/rules/markets-and-data-source.md`, and the code named in each section. Private files under `data/` were listed by name only; none was opened.

## 0. What is verified and what is not

Verified in code or docs (file named where it matters). Everything marked **to verify** was not checked and must be before it is relied on. Section 12 lists the questions only the owner can answer.

### 0.1 Conflicts with earlier decisions, stated openly (none is resolved silently)

| # | Existing rule | Conflict | Proposal (needs the owner) |
|---|---|---|---|
| C1 | STEP5 2.3: the join key of the owner overlay is `matchKey` (`url:<lowercased url>` or `tcl:<title>\|<company>\|<location>`), and `jobId` is "never the join key". | The owner now wants a global `jobId` for ads. Today there are two identities: `jobId`, computed **per provider** (JobSpy and the ATS providers through `_make_job_id` = `sha256(raw url)[:16]`, else a hash of `title\|company\|location`; Infostud as `sha1(url)[:16]`), and the browser `matchKey` (lowercased, trimmed). They differ when a URL differs only by case or whitespace, and the hash function is not the same for every source. | The catalog owns one stable `jobId`. `matchKey` stays as a compatibility alias in `identityKeys` (section 1.3). Per-user records reference `jobId`; the Step 5 overlay keeps `matchKey` until the catalog exists. |
| C2 | STEP5 section 10 / Q3 and request-guard.md: no login, access is the home LAN or Tailscale. | Several users need to be told apart. | A second mode, off by default, with a minimal identity (section 7). Single-user mode keeps the no-login decision. |
| C3 | Principle 16: job sources are the **user's** configuration. `data/config/sources.json` is the owner's switch, with consent. | A global scrape must not be switchable by one user. | Two levels: operator (global enable, consent, credentials) and per-user view preferences (section 4.5). Principle 16 is read as "the owner of the installation". |
| C4 | STEP5 2.8: `memory.json`, the findings store and `job-state.json` carry no user id. | Multi-user needs one. | The `userId` seam (section 6.2). Until then every path resolves to the single owner. |
| C5 | STEP5 2.8: the `job` findings entity key is `sha256(jobMatchKey)`, but its inputs include the profile summary and confirmed facts. | A finding keyed by the job is not ad-only. | Classified per feature in section 2.2. |
| C6 | STEP5 2.3 lists `status: new\|saved\|rejected\|applied_manually` in the overlay. `data-shapes.md` (built, Wave 5 j) says `new\|saved\|rejected` plus `keep`, and "Applied" is derived from the application store. | Two descriptions of one file. | This plan follows `data-shapes.md` (what is built). |

## 1. Three layers

```
Discovery           sources, queries, role families, scheduler, scrape runs   (finds ads; writes evidence)
   |  writes, single writer
   v
Job Catalog         one global record per ad, stable identity, content versions, global status
   ^  reads, never writes
   |
User Workspace      per user: scores, Keep, status, applications, notes, history, profile
```

- **Discovery** writes the catalog and nothing else. It never reads a user's profile or workspace.
- **Catalog** holds no personal data of any user (section 7.3) and no score.
- **Workspace** never writes the catalog. A user can ask for work (a Refresh, a re-extraction) but only the shared worker writes catalog records.

### 1.1 What one catalog record is

A catalog record is the union of today's `discovered_jobs.json` row, the ledger entry (`job_history.json`: `firstSeen`, `lastSeen`, `closedAt`, `llmFacts`, `provider`, `roleKey`, `seenUnder`, `job` snapshot, absence marks) and the staging evidence, minus everything per-user:

```json
{
  "jobId": "<stable, never reused>",
  "identityKeys": [ { "kind": "source_id|url|tcl", "value": "...", "strength": "strong|weak" } ],
  "sightings": [ { "source": "...", "scope": "<source>:<board-or-query-scope>", "firstSeenAt": "...", "lastSeenAt": "..." } ],
  "families": [ { "id": "product", "via": "scope|title_rule|manual", "taggedAt": "...", "familiesVersion": 3 } ],
  "global": { "state": "active|closed|stale|unknown", "since": "...", "evidence": "<ref to a proven read>" },
  "currentVersion": "<contentVersionId>",
  "versions": [ { "id": "...", "seenAt": "...", "contentHash": "...", "fields": { "title": "...", "company": "...", "location": "...", "textRef": "..." } } ],
  "extraction": { "llmFactsRef": "<key>", "factsKey": { "adContentHash": "...", "parserVersion": "...", "promptVersion": 5, "model": "...", "dictionaryVersion": "..." } }
}
```

This is a target shape for planning, not a spec to implement as is.

### 1.2 Same ad found twice versus similar ads (owner addition 1)

Two ads are **the same ad** only on a **strong** identity key:

| Strong key | Source of the key | Status today |
|---|---|---|
| Source-native ad id (Infostud ad id, Greenhouse/Lever/Ashby/Workable job id, Joberty id, JobSpy site id) | The provider's own id | Captured by the providers as `external_ids` (jobId -> the source's own id) but **kept in the staging line only**: the canonical job "has no slot for it" (`base_provider.py`, `infostud_client.py`). It does not reach the ledger or `discovered_jobs.json` as far as read; **to verify** per provider which sites give a usable id. |
| Canonical URL (host + path, tracking parameters stripped) | The ad URL | **Not normalised in the id step**: `_make_job_id` (`normalize_jobs.py`, used by `base_provider.py` and JobSpy) hashes the URL as given, and Infostud hashes it with sha1. I found no tracking-parameter or canonical-URL step in `normalize_jobs.py`, `dedupe_jobs.py` or `job_history.py`. The same ad with a different `utm_` parameter would get two ids. |

A **weak** key is `title|company|location` lowercased (the `tcl:` fallback, also what `_make_job_id` uses when a URL is missing). Two real openings (two "Product Manager, Acme, Belgrade" ads for different teams) collide on it.

Rules:
1. A strong match = the same ad found again: one record, another entry in `sightings`.
2. A weak match = **similar**, never merged. The record gets a `possibleDuplicateOf: [jobId]` link (a hint for the UI and for stats), and both records live on.
3. Cross-source copies of one posting (LinkedIn and the company's own board) are *similar* until a strong key proves otherwise. The existing `dedupe_jobs.py` behaviour is **to verify** against this rule before the catalog adopts it (it dedupes within a run today; what key it uses was not read).
4. No identity is ever re-keyed. A `jobId` already referenced by an application, Keep or the ledger stays valid; a better key is added to `identityKeys`.

### 1.3 Identity migration note

Today's ledger and applications use `jobId` as each provider computed it (hash function and input differ per provider, see the C1 row). The catalog keeps every existing `jobId` as is. Adding canonical-URL and source-id keys later can reveal that two existing ids are the same ad; that is recorded as a link, not a merge (a merge would re-key and break applications and the principle 13 snapshot).

## 2. Shared and per-user split (verified against the code)

### 2.1 Data inventory

| Data | Scope | Today | Why |
|---|---|---|---|
| Ads: `discovered_jobs.json`, ledger `job_history.json` (first/last seen, closed, absence, `sourceRuns`) | SHARED (catalog) | `data/jobs/` | Facts about the ad. `isNew` is per-user (relative to whom), see 5.3. |
| Staging, filtered ads, discard reasons, run log (`data/analytics/runs/*.json`), `pipeline_last_run.json` | SHARED (discovery) | `data/jobs/`, `data/analytics/` | Properties of a scrape run. |
| `llmFacts` (extraction), requirement frames `data/cache/requirement-frames.json` | SHARED, with the conditions in 2.3 | on the job row, in the ledger, `data/cache/` | Keyed by the ad content (2.2). |
| Closing guard state (`absentRuns`, `absentSince`, `lastAbsentRunId`, `sourceRuns`, Stale marks) | SHARED | in the ledger | Evidence about a board, not about a user. |
| Source definitions, provider groups, role family definitions (`src/data/roleFamilies.json`), skills dictionary, seed competency lists | SHARED, tracked in git | `src/data/`, `python/job_discovery/source_definitions.py` | Generic, no candidate data. |
| Source switches `data/config/sources.json`, consent times | SHARED (operator) + a per-user view preference | owner file | Section 4.5. |
| Scrape schedule, leases, backoff | SHARED (new) | none inside the app: `trigger: "scheduled"` exists in the run record, and `scripts/run-pipeline.js` says cron runs the same command from outside | Section 4. |
| Profile, CV library, `cvs/`, intelligence | PER-USER | `data/profile/`, `data/intelligence/` | Personal. |
| Scores: `scored_jobs.json`, shadow output, matcher and judge results, `engine.json`, `llm_fit.json`, `cv_analysis.json`, `engine-calibration.json`, `engine-stability.json` | PER-USER | `data/jobs/`, `data/cache/` | Depend on the profile (2.2). |
| Job state (`job-state.json`: status, `keep`), `rescored_kept.json`, hand-entered jobs `manual_jobs.json` and their `notes`, `extraLinks`, `sourceUrl` | PER-USER | `data/jobs/` | Owner-only by rule (CLAUDE.md). A manual job never enters the shared catalog. |
| Applications, events, files, tailored résumés `data/resumes/<jobId>/`, outreach contacts and messages | PER-USER | `data/applications/`, `data/resumes/`, `data/outreach/` | Personal; principle 13. |
| AI findings store, AI memory, usage ledger, budget settings, provider selection | PER-USER (the extraction budget is a shared scope, section 8) | `data/ai/` | Personal inputs and money. |
| Secrets: AI keys, `li_at` | PER-USER or OPERATOR, never browser | `data/secrets/` | Section 4.4 and 8. |
| Learned competency aliases and remaps `data/competency-aliases.json`, `data/requirement-remap.json`, `data/competency-report.json` and the audit files | **Needs a decision** | `data/` | DECISIONS 2026-10-26: the owner reviews them; contents not opened here. See 2.3. |
| Derived analytics `data/analytics/` other than run logs | PER-USER unless it is a pure scrape statistic | `data/analytics/` | **To verify** per file. |

### 2.2 Cache keys: what depends on the ad only and what on the profile

| Cache | Key (read from the code) | Depends on | Verdict |
|---|---|---|---|
| `llmFacts` (enrichment) | `job_fingerprint`: sha1[:16] of `PROMPT_VERSION` (5) \| title \| company \| description[:9000] (`job_fingerprint.py`) | the ad and the prompt version | **Ad-only.** Gap against owner addition 5: the **model and provider are not in the key**, and there is no separate parser version. A model change does not invalidate stored facts today. |
| Requirement frames | `frame_key`: the same hash without the prompt version (`requirement_frames.py`) | the ad, **and** `apply_remap`, which rewrites stored frames with `data/requirement-remap.json` | **Ad-keyed, but mutated by a curated file.** The key is ad-only; the content is rewritten when a provisional id gains a canonical id. See 2.3. |
| Requirement ids | provisional ids hash the requirement text (`requirement_ids.py`); seed ids come from `src/data/skillsDictionary.js` (a repo file) | requirement text, the dictionary | Ad-only **if** the dictionary is the tracked one. |
| `competencyId` inside `llmFacts` | the enrichment prompt lists the family's competency ids and the model proposes one; code accepts it by the precedence previous frame id > alias (seed, then learned) > skills-dictionary term > model proposal > provisional hash (`competency_mapping.py` docstring, `enrich_jobs._reuse_previous`). An accepted proposal is stored as a **pending learned alias** in `data/competency-aliases.json`, and a remap table `data/requirement-remap.json` rewrites ids | the tracked lists **and** two private `data/` files that the run itself writes | **Not ad-only.** The id in a stored fact depends on curation state that grows as ads are read. See 2.3. |
| Fit judge `llm_fit.json` | sha1[:16] of `PROMPT_VERSION` \| provider \| model \| the full prompt (`llm_enhancer.py _fingerprint`) | the prompt includes the redacted candidate digest | **Per-user.** |
| Matcher / engine `engine.json` | `cache_key(ad_fingerprint, profile_version, selected, requirements)` (`match_engine/matcher.py`) | the ad **and** the profile version | **Per-user.** Its ad part is reusable, its profile part is not. |
| CV analysis `cv_analysis.json` | the CV content hash (`cv_analysis/analysis.py`, **to verify**) | the CV | **Per-user.** |
| Findings store, `jobAnalysis`, `coverLetter`, `interviewPrep` | entity `job`, key includes profile summary, confirmed facts, memory (STEP5 2.8 manifest) | the profile | **Per-user**, although keyed by the job. |
| Findings store, `companyIntelligence` | company name, job posting text if sent, **AI memory entries** | memory makes it per-user | **Per-user** as built. A shared "company facts" record that excludes memory is a possible later split. |
| IDF corpus (term rarity) | built over the run's jobs (`scorer.py: build_idf([jobs in corpus])`, `row_state.in_idf_corpus`) | the whole job set scored | **A determinism hazard**, see 2.4. |

### 2.3 Shared extraction record (owner addition 5)

Shared extraction key = `adContentHash` (the ad's text, title, company, as the catalog stores it) + `parserVersion` (the extraction schema and post-processing code) + `promptVersion` + `model/provider` + `dictionaryVersion` (the tracked competency lists and skills dictionary). It never contains a user id, a profile hash, a confirmed fact or a memory entry.

Gaps against today's code, to close in a slice (section 10, S4):
- Add provider and model to the key. Decision needed on what a model change does (question Q5): invalidate everything (cost), or keep old facts valid until a prompt or parser bump and mark them `olderModel`.
- Split the parser version from the prompt version.
- The shared record keeps what the model said about the ad: requirements text, kind, importance, quote, the model's *suggested* competency id. **Resolved ids are not in the shared key.** The alias and remap files map requirement wording to a competency: that is dictionary curation about the market, not candidate data (it is written from ads, not from a profile), but it is curated by one owner and grows with the ads read. Two ways to handle it, for Q11: (a) treat it as **operator curation**, shared and versioned (`dictionaryVersion` in the key, frames rewritten only by the worker); (b) keep ids out of the shared record and resolve them per user on read. The plan prefers (a) because stable ids across users are the point of principle 4 and the 2026-10-26 decision. The files were not opened; their shape and any user-specific content (for example answers tied to a profile) are **to verify** first.
- Only the shared worker writes `llmFacts`, from the text **the worker itself scraped**. A user-submitted ad (a pasted URL via `import_job_url.py`, a hand-entered job) is private to that user and never feeds the shared cache. This is the main defence against cache poisoning between users (R4).
- Output is schema-validated before it is stored, as `enrich_jobs.py` already does.

### 2.4 The IDF corpus and the Fit-determinism rule

`skill_match` weights each keyword by rarity over the run's corpus, so a user's Fit for an ad depends on **which other ads are in the corpus**. A global corpus would make one user's Fit change when another user's family is added (a QA user's ads change what a PM user's "stakeholder" is worth).

Proposal: the corpus is **the set of ads visible to that user** (their families and region scopes), built at scoring time. A new family added by someone else changes nothing for a user who is not subscribed to it. This keeps the scoring rule (model marks facts, code scores, Fit deterministic for a given input set) and keeps today's single-user behaviour byte-for-byte. The cost is one IDF build per user per scoring run, which is what a run does today. Accepted cross-user effect: none. Question Q9 asks whether a shared, larger corpus is ever wanted.

Also unchanged: `row_state.in_idf_corpus` excludes closed ads and unfound rows; with a global state that still holds per ad, not per user.

## 3. Role families as tags (owner addition 2)

### 3.1 Definition

- A role family is a row in a tracked definition file (today `src/data/roleFamilies.json`, with `titleRules`, and `role_tier.py` reading it): `id`, title vocabulary (target, near, excluded), default search terms per language, competency list id, `familiesVersion`.
- **Tags, not tables.** One shared catalog; each ad carries `families[]` (many-to-many). No per-family physical database or table. Partitioning for performance, if it is ever needed, is a storage detail below the catalog interface (section 6.4) and does not appear in any record.
- An ad that fits several families (a "Product / Engineering manager" title) carries several tags and exists once.

### 3.2 How a tag is set (two sources, both deterministic)

1. **`scope`**: the scrape scope that found it (family F's query on source S). Weak evidence: a search returns off-family ads (the code already knows this: `role_filter.py` and the role tiers exist because searches return unrelated titles).
2. **`title_rule`**: the family's title vocabulary applied by code to the title (the existing role-tier logic, Target / Near). This is the authoritative tag; `scope` alone does not tag an ad whose title is Excluded for that family.
3. `manual`: an operator correction.

No model decides a tag (rule: the model marks facts, code decides).

### 3.3 Query to family

The query is not a user input in the shared design. A **scrape scope** is `(source, family, region)`; its search terms come from the family definition (not from any user's intelligence, which is where `run_discovery.py` reads them today: `load_intelligence`, `jobSpySearchTerms`). Today's `search_key` (hash of terms, locations, country, remote filters; `job_history.search_key`) becomes the scope key. A user does not "search"; they subscribe to families and regions (a view), and ask for a Refresh of those scopes.

A user whose profile wants a family nobody has defined (a new role) triggers an owner/operator request, not an ad hoc scrape (section 3.4).

### 3.4 Adding a family

1. Add the definition (title rules, search terms, competency list) in git, with a new `familiesVersion`.
2. Run a **tag backfill**: re-evaluate `title_rule` tags over the existing catalog. No scrape, no AI call. Dry run lists counts per family.
3. Create scopes for it (sources x regions) in the scheduler, initially paused.
4. Extraction for newly relevant ads follows the extraction trigger rule (section 8.3).

Tags are derived and recomputable, so a wrong definition is fixed by a new `familiesVersion` and a re-tag, never by deleting ads.

## 4. Scrape coordination (owner addition 3)

### 4.1 The scheduler is global and user-independent

State (new, shared, under the future shared directory): per scope `{ source, family, region, ttl, lastCompleteReadAt, lastAttemptAt, nextAllowedAt, lease: {runId, expiresAt}|null, backoff: {failures, until} }`; per provider `{ rateLimit, backoff }`.

Flow for a user pressing **Refresh**:
1. Show existing catalog results **immediately**, with a freshness line per scope ("read 3 h ago, next allowed in 2 h").
2. For each subscribed scope: fresh (inside TTL) = nothing to do; a run in flight (lease held) = **attach** to it (same run id, no second run); otherwise enqueue, subject to the provider's rate limit and backoff.
3. The user gets a run id and progress; they never get the ability to start a source the operator has disabled or to bypass TTL (only the operator can force).
4. Triggers: the scheduler (`trigger: "scheduled"`, an existing enum value), a user Refresh (enqueue only), the operator (force). A per-user daily cap on enqueues prevents one user from keeping the queue full (R9).

Existing pieces that already fit: one run writes at a time through `.pipeline.lock` (`pipeline_lock.py`), a single run record per run, `sourceRuns` per search key bucket, readClass per source and board, a cancel path (S6). The scheduler adds leases, TTL and freshness on top; it does not replace them. **Whether a lease can be a file lock for a single worker process or must be a table is part of Q6** (storage engine).

### 4.2 TTL per source and family

Set by the operator, per `(source, family)`, with provider-specific minimums (Infostud reads cost one request per ad, 1 s apart per the Wave 3 entry; JobSpy/LinkedIn is throttled). TTL values are decisions for the owner; the plan fixes only that the fresh check comes before any network call.

### 4.3 Rate limits and backoff per provider

Per provider: a minimum interval between requests, a global concurrency of 1 for fragile providers (LinkedIn via JobSpy, Infostud), exponential backoff after a throttled or failed read (the `readClass` values `incomplete` and `failed` already exist from Wave 1), and a circuit breaker that pauses the provider for all scopes after repeated 429/403. A throttled provider backs off for **everyone**, which is the point of sharing.

### 4.4 Credentials

- A provider credential used by the scheduler (LinkedIn `li_at` for JobSpy, any future key) is **operator-owned**: it lives in the operator's secret store, never in a user's workspace, never uploaded by a user for a shared scrape.
- `li_at` today is one person's account cookie (stored server-side in `data/secrets/`, used by `jobspy_adapter.py` and `outreach_scraper/scrape_linkedin_contacts.py`; steps 2 and 3 of the storage plan shipped, per `markets-and-data-source.md`). Using one person's logged-in session to scrape on behalf of other people is both a terms risk and an account risk for that person. See section 9.
- **Outreach scraping (contacts) stays per-user** with that user's own credential and consent; it is not part of the shared catalog.
- A user-supplied credential never reaches the shared worker's environment.

### 4.5 Disabled globally versus hidden per user

| Level | Who | Effect | Stored |
|---|---|---|---|
| Global enable/disable of a source, consent and terms note | operator only | the scheduler skips it: "skipped by operator", never an empty or failed read (today's `skipReason`, source_settings.py) | shared `sources.json` successor |
| Per-user hide of a source or family | each user | filters **that user's view and corpus**; nothing else changes | the user's workspace |

A per-user hide never reaches the scheduler. Principle 16's "active set is the user's" becomes "the operator's active set, filtered by each user's view" (conflict C3).

### 4.6 Skipped and failed sources, and the Wave 1 closing guard

The single discovery safety rule stays exactly as built: a throttled source never proves an ad disappeared; "ok with 0 read" is not proof; a confirmed-empty board is held; failed sources never affect closing; successful sources import independently; closing needs proof of a **complete** read of that board, two consecutive misses (S5c, `board_evidence`).

What multi-user adds, and how it is kept safe:
1. **Evidence is scoped.** An absence mark must name the scope that found the ad, `(source, board or category)`. A read of a different, narrower scope (another family's query, another region) proves nothing about an ad first found elsewhere. Search sources never close ads at all (JobSpy never closes, Wave 1), so family scoping affects only snapshot sources (Greenhouse, Lever, Ashby, board-per-company providers, Infostud categories): their scope is the whole board or category, never a query. **Verify in code** that `absentRuns` is incremented only by a complete read of the scope recorded in `seenUnder` / the board line; today `seenUnder` is a search key and the board evidence is per board, which looks compatible but was not traced line by line.
2. **Only the shared worker commits evidence.** The importer (`importer.plan_import`) is the one place that turns a read into held/absent/closed. A user request can enqueue a run; it cannot supply evidence, a read class, a staging file or an import.
3. **A user can never cause a close for others**, because (a) users never write the catalog, and (b) a close needs two complete reads of the board by the scheduler, whoever asked for them.
4. A scope disabled or skipped is `skipped`, which changes nothing (a run is skipped only when every source was).
5. A run for one family that fails does not lower another family's evidence; per-scope records keep them apart.
6. The Stale rule (30 days, three proven runs) is evaluated per scope on the shared evidence.

## 5. Two status axes (owner addition 4)

### 5.1 Global state (catalog, per ad)

`Active`, `Closed`, `Stale`, `Unknown`, derived by code from the ledger evidence (today's `isClosed`, `isStale`, `isAbsent`, `notFoundThisRun`, `closedAt`). `Unknown` = never proven either way (new source, held, unproven). Set only by the shared importer.

### 5.2 Per-user state

`Unreviewed`, `Saved` (Keep), `Rejected` (today `new|saved|rejected` plus `keep` in `job-state.json`), and **Applied**, which is derived from the application store, never stored in job state (as built). The two axes are independent: a user can have `Applied` on a `Closed` ad.

### 5.3 What the global axis may never touch

- **Global Closed never touches a user's application, snapshot, history or Keep.** (Principle 13 already says discovery never deletes, rewrites or re-keys an application; this extends it to the shared layer.)
- `isNew` is per-user (first time *this user's view* showed the ad), not a catalog field. The ledger's `isNew` today is relative to the single owner; in the shared design the catalog has `firstSeenAt` (global) and each user has a `firstSeenByUserAt`.

### 5.4 Change history and snapshots

- The catalog keeps **content versions**: when a re-scrape reads a different title, company, location or description, a new version is appended (hash plus text reference); the old one stays. Today the ledger keeps only the latest `job` snapshot and re-reads facts while the fingerprint is unchanged, so this is new work (S3).
- An application's snapshot is copied at creation (principle 13) and stores the `jobId` and `versionId` it was based on. **A changed description never alters that snapshot.** A user can see "the ad changed since you applied" (a diff against `currentVersion`), but the snapshot is read-only.
- **A shared ad is never deleted while any user references it** (application, Keep, status other than `new`, tailored résumé, a pending outreach). The pruner (today: 90 days after closing, `older_key` retention, `rescored_kept` pruning that already reads the application store) must read every user's reference list. The shared side stores **no** per-user reference index (it would reveal who tracks which ad); the privileged pruner asks each user store for its `jobId` list at prune time. Failure to read any user's list means **no pruning** (the same fail-safe as "an unreadable application store prunes nothing").
- Pruning shared content is the only deletion, it is a manual script, and it is dry-run first, like the existing prune scripts.

## 6. Storage layer, `userId` and migration (fits Step 5)

### 6.1 Two roots

```
data/shared/        catalog, ledger, discovery runs, scheduler state, ad-only caches, source config (operator)
data/users/<userId>/  profile, intelligence, scores, job-state, manual jobs, applications, resumes, outreach,
                      AI findings, memory, ledger of AI usage, budget, secrets, per-user caches
```

`userId` is an opaque random id, never an e-mail or a name. Single-user mode: `userId = "owner"` and the resolver maps both roots to today's `data/` paths, so **nothing moves** until the owner chooses.

### 6.2 What Step 5 must do now so that this stays cheap (no multi-user built)

Step 5 stores take a `root` argument already (`application-store.js`, `job-state-store.js`, `ai-findings-store.js`, whose first slices shipped on 2026-10-29). Add one rule for every new store and route:
1. Private records are addressed through `userPaths(root, userId)`; the id comes from the request context (a constant in single-user mode), **never from a body or a path parameter**.
2. Shared data is addressed through `sharedPaths(root)` and has a separate module with no per-user imports.
3. A route's access class is declared (`shared-read`, `user`, `operator`) and a test fails if a route reads a path outside its class.
4. Per-user records reference ads by the global `jobId` (C1), with `matchKey` kept as an alias until the catalog exists.
5. Backups: a per-user export contains only that user's tree; a shared export is separate and operator-only. A restore of a per-user backup never overwrites `data/shared/` (R14).

### 6.3 Migration from today's layout (no automatic migration)

The Step 5 protocol (section 3 there) applies: **preview (writes nothing) -> owner confirm -> backup -> verified write -> idempotent re-run**, owner-run, with a dry run that prints counts only. Per step:
1. Resolver in place, layout unchanged (no data move).
2. `userId` stamped on private stores' metadata (an additive field), dry run first.
3. Catalog build: derive catalog records from `discovered_jobs.json` plus the ledger; dry run prints counts of records, strong-key groups, weak-key collisions; nothing written.
4. Move `data/jobs/*` shared files under `data/shared/` and private files under `data/users/owner/`, as a copy with verification, the old paths kept until the owner removes them.
5. Only then a second user directory can be created.

Rollback at each step: the old files remain untouched until the owner prunes them.

### 6.4 Engine behind the interface

Today the shared data is JSON files rewritten wholesale by one Python writer (4 MB discovered, 14.5 MB ledger, 5.2 MB scored). That is fine for one writer, and a risk for several readers plus a scheduler worker. Put the catalog behind a small interface (`catalogStore`) so the engine can change. **A decision for the owner (Q6):** stay on files with one writer and atomic replace, or move the catalog to SQLite (WAL, works from both Node and Python) once there is a second user. The plan does not choose; it only requires that no code outside `catalogStore` knows the file layout.

## 7. Authentication and isolation

### 7.1 Minimal viable options (decision Q2)

| Option | What it is | Cost | Notes |
|---|---|---|---|
| A. Reverse-proxy identity | Caddy authenticates each user and sets a user header that the app trusts **only from the proxy**; the app stays bound to loopback (`docker-compose.yml` already publishes `127.0.0.1:3073`, tested by `composePorts.test.js`) | small | The request guard checks Origin and Host (it "is not authentication"). A spoofable header is only safe because nothing but the proxy can reach the app. |
| B. Tailscale identity | friends join the tailnet; the proxy passes the Tailscale user identity | small | Matches the existing "remote access only through Tailscale" decision. **To verify** how the identity header is exposed in this setup. |
| C. App accounts | username and password hash in the app, session cookie, CSRF protection on top of the existing guard | larger | The only option that does not depend on the proxy. |

Recommendation for planning: A or B first (identity from the trusted proxy), C only if the app is exposed beyond the LAN and Tailscale (the existing "revisit if exposed" clause). Whichever: the user id comes from the verified identity, **never** from a client-supplied field, and a request without identity is refused in multi-user mode.

### 7.2 Isolation guarantees (each needs a test when built)

1. A route resolves private paths only through `userPaths(root, ctx.userId)`.
2. No route accepts a user id, a path or a file name from the client for private data; uploads (CV PDF, backup zip) are stored under the caller's tree and listed only for the caller.
3. Static test: no module that handles shared data imports a per-user store, and the reverse for writes.
4. Cross-user test on a temp root with two users: every private `GET` of user B with user A's identity is 404 and leaks nothing, including through error text and timing-visible counts.
5. Logs, run records and ledger rows carry the `userId` only where needed and never profile text; secrets stay masked (`secret-mask.js`).
6. The AI context for user A is built only from A's tree (the `aiContextBuilder`, the memory and the findings store).

### 7.3 Shared data contains no personal data

- The catalog stores ad content as scraped. Ads can contain recruiter names, e-mails or phone numbers: that is third-party personal data in public ad text, kept as the ad has it (and a reason to prefer metadata-only for restricted sources, section 9). **To decide (Q10):** strip contact details from the stored ad text, or keep them as scraped.
- The catalog holds no score, no profile term, no search term derived from a profile, no user id, no per-user reference index.
- Search scopes come from family definitions, so a user's private intelligence (target roles, salary, preferred locations) never reaches a scrape query. (Today it does: discovery reads `jobSpySearchTerms` and locations from the owner's intelligence file. That is acceptable for one owner and must not carry over.)
- `notes`, `extraLinks`, `sourceUrl` of a manual job stay owner-only (CLAUDE.md).

## 8. Cost model

### 8.1 Two budgets

| Budget | Pays for | Gate scope |
|---|---|---|
| **Shared extraction budget** (operator) | `enrich_jobs.py` extraction: it reads only the ad, never the candidate, so no personal data is sent (`enrich_jobs.py` header). One paid read per `(ad content, parser, prompt, model, dictionary)` | a new gate scope `shared`, with its own settings and ledger rows |
| **Per-user budget** | fit judge, matcher, CV analysis, cover letter, interview prep, outreach, tailoring: everything that sees a profile | the existing per-user gate (`ai_gate.py`, `ai-gate.js`) with that user's keys |

Every model call still goes through the gate (CLAUDE.md privacy rule). The gate today reads `data/ai/settings.json` as the owner's budget; a `shared` scope and a `userId` on ledger rows are additions (S9).

### 8.2 Reuse

The single paid extraction per ad is reused through the shared key (2.3): the lookup runs **before** the gate reserves anything (the findings-store rule, I14), a hit costs nothing and writes no ledger row. Concurrent requests for the same ad key use a single-flight lock, so two users never pay twice (R6). A per-user price: none for extraction; they pay only for what sees their profile.

### 8.3 Who triggers extraction (a rule that uses no personal data)

Today extraction is gated by the owner's allowed locations (`outside_allowed_before_enrichment`, `allowedLocations`), which is a profile input. In a shared catalog the trigger must not be. Options for Q7:
1. **Eager by family tag and region scope**: the worker extracts every new ad whose title-rule tag is Target or Near in a configured family. Predictable cost, wastes spend on ads nobody reads.
2. **Lazy on first demand**: the first time a user's view needs facts (to score), the extraction runs under the shared budget and is then shared. Cost follows use; the first user waits.
3. **Hybrid**: eager for Target-tier ads, lazy for Near.

The location filter becomes **per-user scoring input** (a work-authorization cap applied by code, as `work_authorization.py` already does), not a gate on shared extraction.

### 8.4 Keys

Per-user AI keys stay per-user (secret store). The shared budget uses an operator key. A user's key is never used for a shared extraction, and the operator's key is never used for a user's profile-bearing call. Question Q4: who funds the operator key.

## 9. Legal and terms-of-service risks

**Not verified against the providers' current terms.** I did not fetch any terms page, and the rows below are what the repo records plus the shape of the risk. Each row says **to verify** until the owner or a fetch (the `web-fetch` agent can read the public terms pages, no personal data involved) confirms the text. No quotation of a provider's terms is made here.

### 9.1 Per-provider policy (owner addition 6)

Levels: **full** (store ad text, share with all users), **metadata** (store title, company, location, source, URL, dates; no description text; the user opens the original), **reference** (store only the URL and an id; fetch on demand under the user's own session), **none** (not in the shared catalog).

| Provider | What the repo records | Proposed shared level | To verify |
|---|---|---|---|
| LinkedIn (via JobSpy, `li_at`) | Anti-scraping is the central risk. The repo already has an open item "What the LinkedIn terms and account-risk assessment finds" (listed under the browser extension idea in `docs/ROADMAP.md`, not in the Phase 0 audit), and the cookie is one person's account (4.4). | **reference or metadata**; never the description text; **no shared scrape under a personal `li_at`**. Outreach contact scraping stays per-user. | terms text on automated access and copying; the account-ban risk; whether metadata-only changes the position |
| Joberty | `source_definitions.py`: "Undocumented API, terms restrict use", opt-in with recorded consent. | **none** in shared until the terms are read; stays a per-owner opt-in | terms text; whether sharing between users counts as redistribution |
| Infostud | Public site read category by category, one request per ad with 1 s spacing (Wave 3 entry). No terms recorded in the repo. | **metadata** until verified; full only if the terms allow reuse | terms and robots rules; rate expectations |
| Greenhouse, Lever, Ashby (company boards) | Public job-board APIs meant for listing. | **full** likely acceptable; verify each vendor's API terms | vendor API terms on caching and redistribution |
| Workable, WWR, RemoteOK, YC, Wellfound | Public listings; Wellfound uses a browser (`playwright_provider_base.py`). | **metadata** by default; verify | terms per site; RemoteOK and others often require attribution or linking back |

### 9.2 Options to reduce the risk (not mutually exclusive)

1. Per-provider policy file (operator-owned, tracked in git) that the worker obeys: what is stored, what is shared, TTL, whether a description may be kept.
2. Store a link and metadata, not the ad text, for restricted sources; the user's browser opens the original; extraction for those runs per-user on text the user's own session fetched (not shared).
3. Always keep attribution and a link back to the source on every shared ad.
4. Respect robots and rate limits per provider (4.3); honour a takedown by removing a source's content from the catalog (a source can be purged without touching users' applications, which hold their own snapshots).
5. Keep the shared catalog private to invited users on a private network (not a public service); that changes the exposure, not the terms.
6. Legal review by the owner before the first non-owner user, for any source marked metadata or reference only.

A snapshot in a user's application is that user's record of an ad they applied to; whether that is itself restricted for a given source is also **to verify**.

## 10. Slices (small, independently deliverable, ordered by risk, riskiest last)

None is scheduled. Each is docs-reviewed, then built with its own tests (offline, temp roots, no network, no AI call).

| Slice | Content | Touches data | Needs |
|---|---|---|---|
| S0 | This plan, the DECISIONS and ROADMAP entries | no | done with this doc |
| S1 | **Identity**: strong and weak keys, canonical URL function, source-native ids kept in the raw row; a read-only report script (counts only) of strong-key groups and weak-key collisions in the current data | no (report only) | Step 5 not required |
| S2 | **`userId` seam**: `userPaths` / `sharedPaths` resolvers, access-class test, single-user constant; every new Step 5 store uses it | no (layout unchanged) | part of Step 5 steps 1 to 4 |
| S3 | **Content versions** in the catalog (append-only), application snapshot stores `versionId`; changed-since-applied indicator | additive fields | S1 |
| S4 | **Extraction key**: model, provider, parser and dictionary versions in the key, `olderModel` rule, shared-write-only-by-worker rule | additive fields | decision Q5 |
| S5 | **Family tags**: `families[]`, deterministic tag from `title_rule`, backfill dry run, `familiesVersion` | additive field | S1 |
| S6 | **Scoped evidence** check: tests that closing and Stale depend only on complete reads of the recorded scope; scope key replaces the per-user `search_key` in the ledger buckets | possibly ledger fields | existing Wave 1 tests as the base |
| S7 | **Scheduler** (single user): leases, TTL, freshness line, single-flight, per-provider backoff; Refresh shows existing results first | new shared state | S6 |
| S8 | **Per-user corpus** for IDF and the two status axes mapped (`isNew` per user) | no data move | S2 |
| S9 | **Gate scopes**: `shared` extraction budget, `userId` on ledger rows | additive | S4 |
| S10 | **Provider policy file** and the metadata-only / reference modes | new tracked config | legal review (section 9) |
| S11 | **Auth** (option A or B) and the cross-user isolation tests with two users on a temp root | no | decision Q2 |
| S12 | **Owner-run migration** to `data/shared` and `data/users/owner` with preview, backup, verification | yes (owner runs) | S2, S3, S5, and a clean dry run |

## 11. Risk list

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Partial failure** of a scrape or an extraction batch leaves the catalog half-updated | One commit step per run (the existing commit marker `.commit-in-progress.json`, atomic replace); per-scope evidence; a failed scope changes nothing (Wave 1 rule). |
| R2 | **Concurrent writers** (Node routes, Python importer, a second user's request, the scheduler) | Single writer for the catalog (the worker, behind `.pipeline.lock` or a lease); users write only their own tree; per-directory locks already exist for the stores; `baseSha256` preconditions for user documents (Step 5). |
| R3 | **Retry** of a failed run double-counts evidence or reads | Evidence keyed by run id; `appliedRuns` already prevents a double count; leases with expiry; backoff, not instant retry. |
| R4 | **Cache poisoning between users**: one user's ad text or curation lands in a shared record | Only the worker writes shared facts, from text it scraped; user-imported ads stay private; schema validation; the key holds no user input; learned aliases applied per user on read (2.3). |
| R5 | **Deletion of a shared ad while another user has an application on it** | Never prune an ad any user references; the pruner reads each user's references and does nothing if any list is unreadable; applications hold their own snapshot (principle 13). |
| R6 | **Two users trigger the same paid extraction** | Single-flight lock per ad key; lookup before the gate. |
| R7 | **One user's activity changes another's Fit** | Per-user corpus (2.4); a test that adding ads outside a user's scope leaves their scores byte-identical. |
| R8 | **Wrong merge of two real openings** | Weak keys never merge; `possibleDuplicateOf` only; no re-keying (1.2). |
| R9 | **A user starves or abuses the scheduler** (Refresh spam, forced runs) | Enqueue-only, per-user daily cap, TTL check before any network call, operator-only force. |
| R10 | **A user's action closes ads for everyone** | Users never supply evidence; closing needs two complete reads by the worker; skipped and failed sources never close. |
| R11 | **A shared reference index leaks who tracks which ad** | No such index in shared data; pruner asks each user store. |
| R12 | **Existing-data migration** loses or mislabels data | Preview, confirm, backup, verified write, idempotent re-run (Step 5 protocol), owner-run, old paths kept; dry run prints counts only. |
| R13 | **Third-party personal data** in stored ads (recruiter contacts) | Q10; metadata-only for restricted sources. |
| R14 | **Restore of an old per-user backup overwrites newer shared data** | Backups are split by scope; a per-user restore never writes `data/shared/`; shared restore is operator-only. |
| R15 | **A model upgrade silently changes stored facts**, or forces a costly re-extraction | Key includes model; `olderModel` rule; re-extraction within the shared budget, lazily (Q5). |
| R16 | **A user's AI key or `li_at` is used for others** | Operator-owned shared credentials only; user keys never reach the shared worker. |
| R17 | **Terms violation or account ban** for a restricted source | Provider policy file, metadata or reference only, operator-owned credential, legal review before the first non-owner user. |
| R18 | **Header spoofing** if the proxy identity option is used | App bound to loopback only (tested); identity accepted only from the proxy; refused without identity in multi-user mode. |
| R19 | **Regression of today's single-user behaviour** | Every slice keeps single-user output byte-identical (resolver maps to current paths); existing tests stay green; dry-run comparison before any move. |
| R20 | **JSON files do not scale** to several readers and a worker | `catalogStore` interface; the engine decision Q6; no code outside it knows the layout. |

## 12. Open product questions for the owner

1. **Q1 Scope of sharing.** Who are the users (friends, colleagues) and how many? A handful on a private network, or open registration? This decides auth (Q2), legal exposure and the engine (Q6).
2. **Q2 Identity.** Option A (proxy identity), B (Tailscale identity) or C (app accounts)? Is it acceptable to reverse the "no login" decision for a multi-user mode only (conflict C2)?
3. **Q3 Operator role.** Is the owner the single operator who controls sources, credentials, TTLs and the shared budget? May a user request a new family or source?
4. **Q4 Who pays.** Does the operator fund the shared extraction budget, or do users chip in? Per-user keys for everything that sees a profile (this plan's default)?
5. **Q5 Model change.** When the extraction model changes, invalidate every stored fact (cost), or keep old facts valid until a prompt or parser bump and mark them `olderModel`?
6. **Q6 Storage engine.** Stay on JSON files with one writer, or move the catalog to SQLite when a second user arrives? (The plan keeps both possible.)
7. **Q7 Extraction trigger.** Eager, lazy on first demand, or hybrid (8.3)?
8. **Q8 LinkedIn.** Is a shared LinkedIn scrape wanted at all, given the account risk of one person's `li_at`? Default in this plan: reference or metadata only, no shared scrape under a personal cookie.
9. **Q9 Corpus.** Is a per-user corpus acceptable (this plan), or is a larger shared corpus ever wanted despite the cross-user effect on Fit?
10. **Q10 Contact details in ad text.** Strip recruiter names, e-mails and phones from stored shared ad text, or keep as scraped?
11. **Q11 Competency aliases and remap.** `competency-aliases.json` and `requirement-remap.json` map requirement wording to competency ids and rewrite the shared frames. Are they operator curation, shared and versioned (this plan's preference), or per-user? (Their contents were not opened here; the owner's confirmed answers are a separate, per-user thing.)
12. **Q12 Manual and imported ads.** May a user "promote" a hand-entered or URL-imported ad into the shared catalog? Default: never, they stay private.
13. **Q13 Reference data of shared families.** Who maintains `roleFamilies.json` and the competency lists, and how do other users' families (Dev, QA, Design) get their title vocabulary and competency lists, given the current ones are PM-centred?
14. **Q14 Legal review.** Is the owner willing to read the terms of Infostud, Joberty and the board vendors before the first non-owner user, or should the plan assume metadata-only for all of them until then?

## 13. What this plan does not do

- No code, no `data/` change, no AI call, no migration, no scrape.
- No change to scoring, the budget gate, redaction, the secret store, or the Wave 1 closing rule.
- No P1/P2 feature: family subscriptions as a product feature, new-ad notifications, canonical company dedupe and source coverage analytics are recorded as notes in [ROADMAP.md](../ROADMAP.md), not in this data plan.
- It does not edit `STEP5_SERVER_MASTER_PLAN.md`. The conflicts in 0.1 are for the owner to resolve; the proposal is that Step 5 adds the `userId` seam (6.2) and the `jobId` alias rule (C1) when it is next revised.
