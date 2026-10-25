# Holojob - Glossary

Terms used in [CLAUDE.md](../CLAUDE.md), [ARCHITECTURE.md](ARCHITECTURE.md), [redesign/DECISIONS.md](redesign/DECISIONS.md)
and [redesign/ENGINE_CONTRACT.md](redesign/ENGINE_CONTRACT.md). The redesign terms (Fit, requirement, evidence, gate,
...) describe the planned engine; the current pipeline terms (enrichment, fit judgement, ledger, role track, cap)
describe what runs today.

## Terms

**Bucket** - The outcome of the gates for one posting: Apply, Check first or Blocked. A bucket is never a number and
never changes Fit. See [Gate](#gate).

**Canonical competency** - An entry in a role family's fixed competency list (for example "stakeholder management" for
Product). Posting requirements are mapped to canonical ids so the same skill is the same id in every ad.

**Cap** - A rule in code that limits a score no matter what else is true, for example an off-track role capped at 50 or
a visa the candidate lacks. Caps live in `scorer.py`, never in prompts, and never hide a job.

**Confidence** - How much of a result rests on verified evidence instead of unknowns. UNKNOWN requirements and unverified
quotes lower it; below a threshold the label becomes "Incomplete".

**CV coverage** - The second score, next to Fit: how much of the posting's requirements the current CV shows (as opposed
to what the candidate's whole history could show). Computed with CV tailoring in Phase 4.

**Enrichment** - The LLM step that reads each ad, without ever seeing the candidate, and stores facts on the job
(`llmFacts`): work mode, role track, seniority, years, must-haves, country, visa text. It never scores.

**Evidence item** - One piece of the candidate's own text the engine may cite: a role description, a project, an example
or a confirmed fact, with its source, period and strength.

**Evidence strength (0-4)** - How strong an evidence item is: 0 none, 1 claim (listed), 2 contextual (mentioned in a
role), 3 demonstrated (described as work done), 4 demonstrated with a measurable outcome. Credits per level are code
constants.

**Fit** - The first score: how well the candidate's evidence covers the posting's requirements, 0-100, computed
deterministically by code. It replaces keyword overlap as the basis of ranking once shadow mode has been checked.

**Fit judgement** - Today's opt-in LLM step (`run_scoring.py --judge`) that compares an ad with a digest of the candidate
and returns a fit category; code turns the category into a small adjustment. Not the same as Fit.

**Gate** - A yes/no condition of a posting checked against the candidate: work authorization or sponsorship, location or
remote, language, salary floor, role family. Gates decide the bucket, not points.

**Ledger** - `data/jobs/job_history.json`: per job id, when it was first and last seen, whether it closed, a snapshot of the
job and its enrichment facts. It survives the discovery file being rewritten every run.

**MET / PARTIAL / MISSING / UNKNOWN** - The status of one requirement: MET (evidence shows it), PARTIAL (evidence covers
part of it), MISSING (checked and absent), UNKNOWN (the profile cannot settle it). UNKNOWN is never treated as MISSING:
it is excluded from the coverage denominator, counted separately and turned into a question.

**Provisional competency** - A requirement that matches no canonical competency. It gets a deterministic temporary id and
is scored immediately; the user confirming it only promotes it into the permanent dictionary.

**Requirement** - One thing a posting asks for (a skill, experience, domain, language, ...) with its importance (must,
preferred, nice) and a verbatim quote from the ad.

**Role family** - A group of related roles (Product, Engineering, Design, QA, Data, ...) that holds title synonyms for
search, the role gate and, later, prompt variants for CVs and cover letters. A mismatch caps Fit.

**Role track** - The enrichment fact that says what kind of work a job is (`product_management`, `product_ownership`,
delivery, ...). Today's scorer caps a job at 50 when the track is neither product management nor product ownership.

**Shadow mode** - Running the new Fit next to the current `matchScore` and showing both, while the new one changes no
ranking, label or priority until the owner has compared them on real runs.
