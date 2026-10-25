# Holojob - Product decisions

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

## Scope and rules
- Holojob stays the base app: UI, job sources incl. Serbian sites, AI provider layer, data.
- Logic and code may be ported from MIT repos: career-ops-hq/career-ops, applypack/applypack, Gsync/jobsync, tcpsyn/CareerPulse, romit-23/jobapply. DaKheera47/job-ops is Commons Clause: ideas only, never copy its code.
- No inline or per-file attribution comments. One THIRD_PARTY_NOTICES.md holds the MIT notice of every repo code was copied from; an entry is removed once that code is fully rewritten.
- Code, comments and identifiers are in English.
- Everything under data/ (incl. candidate-intelligence.json), CVs and secrets are private and never committed.

## Phases
0. Read-only audit -> per-module decision: Reuse / Adapt / Build / Skip, with source paths, changes needed, effort, risks.
1. Scoring core: prefilter, requirement extraction, evidence matching + deterministic score, role families.
2. Evidence profile, questionnaire restructure, ask-user loop.
3. Application tracker: stages, append-only event log, channel, CV version, follow-up nudges, import of past applications.
4. Interview prep, CV / cover letter with fact gate, market report.
5. Feedback loop: conversion by channel and fit band, calibration against real outcomes.
