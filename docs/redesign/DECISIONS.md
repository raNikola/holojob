# Holojob - Product decisions

Owner and author: Nikola Randjelovic (raNikola).

Origin: fork of raNikola/holojob (AGPL-3.0), customized on DS9. The original repo is kept as the `upstream` remote for reference only.

## Thesis
Evidence-based job matching. The score measures evidence of what the candidate has actually done versus what a posting requires, not keyword overlap. AI marks facts with verbatim quotes; deterministic code computes every number.

## Principles
1. The scoring engine is an isolated module with a stable JSON contract: input = posting + candidate profile + confirmed facts; output = requirements, per-requirement evidence and status, gates, confidence, scores, questions. The app calls it; the engine does not depend on UI code.
2. Statuses are MET / PARTIAL / MISSING / UNKNOWN. UNKNOWN is never treated as MISSING: excluded from the coverage denominator, shown as its own count, turned into a question for the user, and lowers confidence. Below a confidence threshold, or above a threshold of unknown must-haves, the label is "Incomplete - answer N questions".
3. Evidence strength is 0-4: none, claim (listed), contextual (mentioned in a role), demonstrated (described as work done), demonstrated with a measurable outcome. Credits per level are code constants.
4. Each role family has a canonical competency list. Posting requirements map to canonical ids. Unmatched requirements become PROVISIONAL competencies with a deterministic temporary id and are scored immediately; user confirmation only promotes them into the permanent dictionary and market statistics.
5. Gates (work authorization / sponsorship, location / remote, language, salary floor, role family) are buckets - Apply / Check first / Blocked - never points.
6. Two scores only: Fit (evidence coverage, deterministic) and CV coverage (what the current CV shows). Role-family mismatch caps Fit.
7. User-facing output: label (Strong / Good / Partial / Weak / Incomplete), 0-100 number for sorting, must-have x/y, preferred x/y, unknown count, blocker count, gates, confidence, and a per-requirement "why" list with quotes.
8. AI may rephrase, structure and ask questions; it never adds facts. Generated CV and cover letter text passes a fact gate that blocks claims and numbers not in the CV or confirmed facts.
9. Stability is measured, not assumed: the same posting + profile must give the same result across runs (deterministic model settings, cache by content hash + profile version, reuse of the previous requirement frame).
10. Role families (Product, Engineering, Design, QA, Data, ...) hold title synonyms for search and the role gate, and later prompt variants for CV and cover letters. The old developer skill dictionary is kept as an alias list for Engineering/QA, not as a score source.
11. The skill/competency dictionary emerges from analyzed postings (market report) and is confirmed by the user, not hand-written from scratch.
12. The 17-question questionnaire is kept, optional, and restructured (story bank, skills with evidence, preferences, positioning, gates). AI can prefill it from the CV through the existing review screen.
13. Application tracking is independent of job discovery. An application has its own identity and its own store; it keeps a snapshot of the posting (title, company, location, URL, description, source, dates) taken when it is created. The posting may disappear from search results, close or be pruned from the ledger; the application, the CV version sent, its statuses, notes and full history stay permanently. Discovery never deletes, rewrites or re-keys an application.
14. Personal identifiers never leave the server. Anything sent to an AI provider is redacted first: full name, phone numbers, e-mail addresses and personal links (personal site / CV site, LinkedIn, GitHub and any other profile URL). Work history, roles, dates, bullets and skills may be sent, behind an explicit confirm, as the judge and CV analysis already do.
15. Single user for now. **The server is the master** for profile, intelligence, jobs and applications; the browser keeps UI state only (decided 2026-10-29, reverses the earlier "browser copy is the master" and the "comes later" wording). Access from several devices builds on this. New stores (applications, evidence, confirmed facts) are designed so they can move server-side without changing their shape.
16. Job sources are user configuration, not code. Which boards are active, which companies are watched and any source keys are edited in Settings and stored server-side under data/ (private, never in git). No source group is hard-coded as the default; the active set is the user's. companies/*.json in the repo becomes a one-time seed for migration only. Design: [SOURCES_SPEC.md](SOURCES_SPEC.md).

## Scope and rules
- Holojob stays the base app: UI, job sources incl. Serbian sites, AI provider layer, data.
- Other projects are references, not code sources. Study how they solved a problem (read their code and ADRs), then design and implement our own version that fits Holojob's stack, data model and conventions, simplified or improved where we can. Copy code verbatim only for a small pure function where re-writing it adds nothing; any such copy is listed in THIRD_PARTY_NOTICES.md. DaKheera47/job-ops stays ideas-only.
- No inline or per-file attribution comments. One THIRD_PARTY_NOTICES.md holds the MIT notice of every repo code was copied from; an entry is removed once that code is fully rewritten.
- Code, comments and identifiers are in English.
- Everything under data/ (incl. candidate-intelligence.json), CVs and secrets are private and never committed.

## Phases
The phase list, status and acceptance criteria live in one place: [../ROADMAP.md](../ROADMAP.md).

## Owner decisions log
- 2026-10-25 - Privacy: matching may send redacted work history (principle 14), behind the same explicit confirm as the judge.
- 2026-10-25 - Budget: matching keeps the judge's limit, the top 50 jobs per run by local score, everything cached.
- 2026-10-25 - Shadow mode: the new Fit is computed and shown next to the current matchScore and changes no ranking until the owner has compared the two on real runs.
- 2026-10-25 - Single user stays for now; multi-device access is a later goal (principle 15).
- 2026-10-25 - Application tracking must be independent of discovery (principle 13). There are no tracked applications yet, so no migration is needed.
- 2026-10-25 - Porting rule replaced: other projects are references, not code sources; verbatim copies only for small pure functions and listed in THIRD_PARTY_NOTICES.md (Scope and rules).
- 2026-10-25 - Principle 16 added: job sources are user configuration stored server-side under data/, not code; the repo's companies/*.json becomes a one-time migration seed. Spec: SOURCES_SPEC.md.
- 2026-10-26 - Stable requirement ids (principle 4 made concrete). The same real-world requirement worded differently across ads resolves to one canonical id, so the owner's answers are reused and model calls go down as more ads are processed. Design in ROADMAP.md (Phase 1 follow-up, "Stable requirement ids"); not yet implemented.
  - **Curated list.** One competency list per role family in `src/data/competencies/<family>.json`: id, one-line definition, kind, `aliases[]`, optional `parent`. Drafted from the owner's ads, reviewed by the owner, tracked in git (generic, nothing about the candidate). Parent/child is for display and evidence retrieval only: evidence for a parent never satisfies a narrower child requirement.
  - **Mapping inside the existing extraction call.** The prompt lists the family's ids with their definitions; the model picks a `competencyId` or NONE and must not force a match. Code accepts only ids on the list. Precedence: previous frame id > alias lookup > dictionary term > model suggestion > provisional. A remap table `prov:<hash>` -> canonical id is kept, so no id keyed by an old provisional id is lost.
  - **Two kinds of learned alias.** Pending aliases (model-suggested) stabilize ids and allow caching of model verdicts. Confirmed user answers apply ONLY to seed competencies and to aliases the owner has reviewed, so a wrong merge can never overwrite an answer. Learned aliases live under `data/` (private).
  - **Qualifiers stay fields, not part of the id** (years, level). An answer "SQL: yes" applies only to a requirement without a qualifier; "SQL 5+ years" stays open or becomes a question about the qualifier.
  - **Three separate operations.** (1) Does the requirement match a competency: AI proposes, the owner confirms new mappings. (2) Does the candidate have it: AI judges evidence, or a confirmed fact is used. (3) How much it contributes to Fit: code only.
  - **`profileVersion` is split.** An EVIDENCE version (evidence index + role family + prompt/engine version) is the only thing that invalidates cached model verdicts. Confirmed answers and gate values are NOT in the cache key; they are applied in code on top of cached verdicts. The matcher sends all requirements of an ad to the model, and answers override statuses in code.
  - **Gate quotes move from the matcher call into extraction**, which never sees the candidate, so an ad whose requirements all resolve locally makes zero matcher calls.
  - **Accuracy gate.** Before the mapping is relied on widely, a sample of about 100 real requirements is audited for correct, wrong and legitimately provisional mappings. The acceptable wrong-merge rate is set by the owner after the first measurement.
- 2026-10-28 - Application tracker (Phase 3, A2): the ten open questions in [TRACKER_PLAN.md](TRACKER_PLAN.md) section 9 are decided as recommended. A2 replaces the interim fix A1.
  - **Master location.** The server file `data/applications/applications.json` is the master from the first slice. The browser keeps a read cache only (principle 15).
  - **No deletion.** An application created by mistake is voided (`application_voided`), hidden from lists and kept on disk. A physical purge is a manual script outside the app.
  - **Undo a void** (owner follow-up, same day). An `application_restored` event undoes a void. The full event history is kept; a restore creates no new application and no duplicate statistic, and it is refused when it would create a duplicate open attempt.
  - **CSV `attempt` column is optional.** When present, it separates attempts at the same position. When absent, the existing dedupe rules apply unchanged (absent = 1).
  - **Ghosted is suggested only.** Nudge N2 offers a button. The system never writes an outcome on its own.
  - **Nudge thresholds are code constants:** 7 / 21 / 1 / 7 / 2 days for N1 / N2 / N3 / N4 / N5. Phase 5 may report them against real reply times and never tunes them automatically.
  - **Stages.** The stage enum is fixed, with a free label per event. Custom stages are not built.
  - **Outreach and tailored assets stay on the job record in A2.** A follow-up step after S4 moves outreach messages into application events.
  - **Frozen copies.** Every CV and cover letter sent is copied into `data/applications/files/<appId>/`, with its sha256.
  - **Migration ships.** The migration ships in S2 even if the dry run finds no tracked records, so legacy tracking in older backup exports still migrates.
  - **AI context.** `aiContextBuilder` stops sending recruiter name, e-mail and LinkedIn in S4.
  - **"Applied" is derived** from the application store. The job status `applied_manually` is removed in S4.
- 2026-10-29 - Tracker stages are configurable (stable ids), superseding the fixed stage enum; O1-O4 decided, O5-O6 deferred.
- 2026-10-29 - Browser storage policy approved (Q1-Q8 of [BROWSER_STORAGE_POLICY.md](BROWSER_STORAGE_POLICY.md)). Nothing is stored in the browser unless it is on an allowlist; secrets are never stored in or sent from the browser.
  - **Server is the master** for profile, intelligence, jobs and applications; the browser keeps UI state only. This reverses the "browser copy of the profile is the master" rule and principle 15's "later". Each migration needs a preview, an owner confirmation and a verified server write before the browser copy is removed.
  - **Network:** the port is published on `127.0.0.1` only behind Caddy (`766bd7b`); the request guard (JSON Content-Type, Origin / Host allowlist) is active (`cd0cf74`).
  - **Secrets:** `data/secrets/`, directory 700 and files 600, no extra encryption in v1 (rootless podman: file modes protect against other host users only). AI keys migrate by an owner-triggered move with a rotation checklist, including `OPENAI_API_KEY` in `.env` if it is the same key.
  - **AI settings server-side**; `job-dashboard-theme` is the only new allowlisted browser key. `AICommandCenter` chat history is in memory only.
  - **Step order:** 1 network / API protection (no Caddy auth, see Q3), 2 AI keys to the server, 3 `li_at` without CLI arguments, 4 AI settings to the server, 5 profile / intelligence / jobs migration with verification, 6 browser AI confirm dialog (principle 14), the next privacy task after the secrets migration. A pre-migration checklist gates steps 2 and 5; its first item is that no path bypasses Caddy (every published port and interface).
- 2026-10-29 - Q3 resolved as **no application login and no Caddy `basic_auth`** (replaces the `basic_auth` line of the entry above). Access stays inside the home LAN; remote access is only through Tailscale. This is a conscious, owner-accepted risk: any device on the LAN or tailnet can use the API (read data, spend the AI budget, replace a stored key); the Origin / Host / Content-Type guard protects against cross-site pages and DNS rebinding, not against a device talking to the API directly. Revisit if the app is ever exposed outside the home network or Tailscale (port forward, Funnel, public DNS, a second user). If the app is reached over Tailscale by name, that hostname must be in `HOLOJOB_ALLOWED_ORIGINS`.
