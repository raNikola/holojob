# Holojob - Product decisions

Owner and author: Nikola Randjelovic (raNikola).

Origin: fork of Shanupower/career-os (AGPL-3.0), customized on DS9. The original repo is kept as the `upstream` remote for reference only.

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
15. Single user for now. Access from several devices comes later; it will need server-side storage as the master instead of the browser's localStorage. New stores (applications, evidence, confirmed facts) are designed so they can move server-side without changing their shape.

## Scope and rules
- Career OS stays the base app: UI, job sources incl. Serbian sites, AI provider layer, data.
- Logic and code may be ported from MIT repos: career-ops-hq/career-ops, applypack/applypack, Gsync/jobsync, tcpsyn/CareerPulse, romit-23/jobapply. DaKheera47/job-ops is Commons Clause: ideas only, never copy its code.
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
