# Competency memory MVP: spec

**Status: DRAFT (revision 3), 2026-11-11. Not approved, not scheduled.** Docs only: no code, no `data/` change, no model call, no migration. Implementation starts only after the owner approves this document, the P1 Stage B open decisions are settled, and the offline experiment in section 7 has run.

**Builds on P1 Stage B.** This branch is based on `p1-stage-b`. Its verdict vocabulary, Fit / confidence rules and open decisions (`DECISIONS.md`, "P1 scoring calibration: Stage A measured, Stage B rules decided" and "P1 Stage B: matcher stability, slices 1 and 2") come first; where this spec and Stage B differ, Stage B wins and the difference is listed in 0.1. Merge order: `p1-stage-b`, then this branch.

The goal in one line: Holojob groups what ads ask for, remembers what it learned about the candidate (from the CV and from answers), and reuses it on the next ads instead of judging the same experience again.

Inputs: owner discussion of 2026-11-11 (ApplyPack, JobApply, JobOps, JobSync, CareerPulse; ideas only), the review of revision 1, the P1 Stage A and Stage B records, `ENGINE_CONTRACT.md` (2, 4, 5, 6.1), `DECISIONS.md` 2026-10-26 (stable requirement ids), `ROADMAP.md` Phase 1 follow-up and Phase 2, and the code named in each section. No private file under `data/` was opened.

**Revision history.** 2: AI batch grouping (4.2, 3.4); remembered CV evidence as `cv_evidenced` (4.1, 3.5); experiment on the Stage A sample. 3: Stage B vocabulary (`CONTRADICTED`, `NOT_EVIDENCED`; `MISSING` retired; Incomplete label replaced by the unconfirmed-must flag); critical unconfirmed musts first in the queue; a fact below the required level gives PARTIAL; the evidence map learns only stable verdicts (repeat noise 9-19%); `rankingScore` is an offline variant only until Stage B open decision 3 is settled; the experiment replays the Stage B stored verdicts; our "contradiction" renamed **conflict** so it is not confused with the `CONTRADICTED` status.

## 0. What already exists and what this adds

| Piece | State today | What the MVP adds |
|---|---|---|
| Verdict vocabulary | Production engine: `MET` / `PARTIAL` / `MISSING` / `UNKNOWN`. Stage B (approved, calibration code only): `MET` / `PARTIAL` / `CONTRADICTED` / `NOT_EVIDENCED`, `MISSING` stops being a scoring status. | Uses the Stage B vocabulary throughout. |
| Evidence index, strength 0-4 | Built (`job_scoring/evidence_index.py`) | Nothing; it stays the only copy of the CV text. |
| Quote verification | Built (`match_engine/verify.py`); Stage B `matcher_v3.py` is stricter (a MET without a verified quote becomes NOT_EVIDENCED) | Nothing; it is what makes a verdict `cv_evidenced`. |
| Two identical readings, flag queue | Stage B, experiment only (`matcher_v3.aggregate_two`, `flag_queue`), never automatic in production | Used, when present, to decide what the evidence map may learn (4.1). |
| Canonical ids, seed, pending / reviewed aliases | Built (`requirement_ids.py`, `competency_mapping.py`, `product.json`, 121 entries) | AI batch grouping and link statuses `auto` / `demoted` (4.2). |
| Remembered CV evidence per competency | Not built; ROADMAP lists a deferred "per-competency verdict cache" | The competency evidence map (3.5, 4.1). |
| Confirmed facts store | Read side only (`confirmed_facts.py`, v1). Stage B: "no per-answer confirmed flag exists yet, so no questionnaire answer is sent". | Store v2 (3.1), write path, history. Every stored answer is explicitly confirmed by construction. |
| Applying a fact | Built for yes / no (`verify.apply_confirmed_fact`) | `partly`, `unknown`, years (4.4). |
| Answers applied on cached verdicts | Not built (contract 6.1) | Required (4.7). |
| Per-requirement level | Not built in production. Stage B: level fields and "MET below the required level becomes PARTIAL", offline preview only, unvalidated. | A `years` qualifier per requirement (3.2), aligned with the Stage B level rule. |
| Questions | Per ad (`fit.questions_for`); Stage B flag queue at most 3 per ad, musts first | One cross-ad queue, grouped and counted (4.3). |
| Fit and confidence | Stage B: always shown separately; Incomplete replaced by "unconfirmed: N must requirements"; ordering by fit x confidence is an offline variant only, never production | `rankingScore` as one more offline variant (section 5). |
| Owner-labelled calibration data | Stage A: 45 ads, 70 requirement lines, labels `functionFit` / `hardRequirements` / `overall`; Stage B replay over 44 ads (`v3_offline.py replay`) | The experiment adds its variants to that replay (section 7). |

### 0.1 Conflicts with earlier decisions (none resolved silently)

| # | Existing rule | Conflict | Proposal (needs the owner) |
|---|---|---|---|
| C1 | Stage B: NOT_EVIDENCED never lowers and never raises fit. Stage B open decision 3: what fit means when few requirements are settled. | Owner decision C (2026-11-11): an unconfirmed must gets a ranking prior. Stage B measured that silence out of fit inflates scores and breaks the ranking (production_like Spearman 0.54 to -0.16). | C is a candidate answer to open decision 3, not a separate rule. Fit stays as Stage B defines it until decision 3 is taken; `rankingScore` is evaluated as one more variant in the same replay (section 7) and decision 3 picks the winner. |
| C2 | 2026-10-26: curated list per family. | 2026-11-11: no hand-made seed now. | Keep `product.json`; do not expand it by hand. |
| C3 | 2026-11-11: the user does not edit the taxonomy. 2026-10-26: the owner confirms mappings. | Single user. | Separate by surface: the queue asks about experience only; link review stays in the competency report and audit tool. |
| C4 | Contract 2, step 5: questions from UNKNOWN only. | The discussion also queues PARTIAL. | Queue PARTIAL only at strength 0-1 (4.3). |
| C5 | 2026-10-26: answers apply only to seed and reviewed aliases. | Reliable equivalence should group automatically. | `auto` links carry answers and CV evidence only after an audit; values carried over them are labelled; demoting undoes them (4.2). Owner decision Q7. |
| C6 | 2026-11-11: a MET on one ad must not become universal. | The evidence map reuses a verified verdict. | Same id only, no level, never a narrower child, only stable verdicts, check mode first (4.1). |
| C7 | Revision 2 of this spec: a fact below the required years gives MISSING. | Stage B: MET below the required level becomes PARTIAL. | Follow Stage B: PARTIAL (4.4). |
| C8 | Revision 2: Incomplete hides the Fit number. | Stage B: Incomplete is replaced by the unconfirmed-must flag; fit and confidence always shown. | Follow Stage B (section 5). |

## 1. Terms

| Term | Meaning here |
|---|---|
| `MET` / `PARTIAL` | Quoted positive evidence (Stage B). PARTIAL: a verified quote covers a named part of the requirement, or the same thing at a lower level. |
| `CONTRADICTED` | Explicit evidence against: a verified conflicting quote, an owner answer "no", or closed-world absence (Stage B open decision 2). Affects fit. |
| `NOT_EVIDENCED` | Silence. Never lowers or raises fit (Stage B); lowers confidence; becomes a question. |
| Critical unconfirmed must | A must of a binary-prerequisite kind (explicit mandatory education, certification, language) that is NOT_EVIDENCED. Never moves fit, weighs double in confidence, holds the bucket at `check_first`, its question comes first (Stage B). |
| `user_confirmed` | Confirmed fact (3.1). Highest authority. |
| `cv_evidenced` | Competency evidence map entry (3.5): a stable, quote-verified MET or PARTIAL. |
| `ai_inferred` | A matcher proposal that failed verification. Never remembered. |
| Competency group | A canonical id plus every alias linked to it as `reviewed` or `auto`. |
| Conflict | Two incompatible claims of comparable authority about one group (4.5). Not the `CONTRADICTED` status. |

## 2. Decisions recorded (owner, 2026-11-11)

- **D1 MVP first.** Prove that grouping and remembering cut questions without hurting matching.
- **D2 Source priority** `user_confirmed > cv_evidenced > ai_inferred`; `cv_evidenced` needs a direct quote from the candidate's own text.
- **D3 Transfer only between equivalent competencies:** same group, no stricter level.
- **D4 Experience level is a structured attribute,** not a separate competency.
- **D5 Frequency and impact are separate;** the MVP queue orders by frequency.
- **D6 Frequency is a snapshot** of the active pool; one ad counts once per group.
- **D7 Re-score only active ads,** with no new matcher call.
- **D8 A conflict needs comparable authority;** a model disagreeing with the user is not one.
- **D9 Unknowns in ranking: option C** with a calibrated `RANKING_PRIOR`; settled together with Stage B open decision 3 (C1).
- **D10 Revoking a fact** moves it to `unknown` with history kept.
- **D11 Success = fewer questions without lower accuracy,** against a recorded baseline.
- **D12 Questions never block** discovery, scoring or applying.
- **D13 AI batch grouping** of new requirement terms; reliable equivalence groups automatically, uncertain stays separate.
- **D14 Proven CV experience is remembered** as `cv_evidenced`, not shown as confirmed by the user, without copying the CV text.

## 3. Data model

### 3.1 Confirmed facts store v2

File unchanged: `data/profile/confirmed-facts.json` (private, 600). `STORE_VERSION` 2. A v1 file is read as v2 (`has: true` -> `yes`, `has: false` -> `no`, timestamps null) and rewritten as v2 only on the next save.

```json
{
  "version": 2,
  "facts": [
    {
      "competencyId": "product-leadership",
      "answer": "yes",
      "qualifier": { "kind": "years", "value": 7 },
      "note": "",
      "answeredAt": "2026-11-11T10:00:00Z",
      "overrules": [],
      "history": [
        { "answer": "unknown", "qualifier": null, "at": "2026-10-30T09:00:00Z", "via": "queue" }
      ]
    }
  ]
}
```

| Field | Rule |
|---|---|
| `competencyId` | Canonical or `prov:` id; one live fact per id. |
| `answer` | `yes` / `partly` / `no` / `unknown` ("I don't know", kept so the question is not repeated). |
| `qualifier` | `{kind: "years", value: 0-40}` or null. |
| `note` | Owner-only, never in a payload. |
| `overrules[]` | Evidence ids the owner overruled in a conflict (4.5). |
| `history[]` | Up to 20 previous answers; `via`: `queue`, `edit`, `revoke`, `conflict`, `cv_confirm`. |

Every fact is an explicit owner confirmation, so it satisfies Stage B's "answers the owner explicitly confirmed". It is still **applied in code** (4.4), not sent to the matcher: code needs no model call for it, and nothing about the candidate's answers leaves the server.

### 3.2 Requirement level (years)

Extraction gets one optional field per requirement: `qualifier: {kind: "years", value: <int>} | null`, read only from the ad's words and verified against `postingQuote`. This bumps `PROMPT_VERSION`, so stored ads are re-extracted once under the budget gate; the cost is estimated before the bump (Q4). It should share one definition with the Stage B level fields (`matcher_v3.py`), so production and calibration compare levels the same way (to align when M8 is built).

### 3.3 Queue entry (computed, not stored)

```
{ competencyId, displayText, memberTexts[], adCount, mustCount, criticalCount, kind,
  reason: "conflict" | "critical_must" | "not_evidenced" | "partial_claim" | "level" | "unstable",
  exampleAds: [jobId, ...max 3] }
```

### 3.4 Link statuses and the grouping cache

`data/competency-aliases.json` (existing, private) gets two statuses next to `pending` and `reviewed`:

| Status | Comes from | Groups for the queue | Carries answers and CV evidence |
|---|---|---|---|
| `reviewed` | seed, or the owner in the audit tool | yes | yes |
| `auto` (new) | batch grouping, `high`, accepted by code | yes | only after the audit (C5); labelled as carried |
| `pending` | extraction suggestion, or grouping `uncertain` | no; marked "possible duplicate of X" | no |
| `demoted` (new) | the owner rejects a link | no | no; never proposed again for that text |

Grouping answers are cached in `data/cache/competency-grouping.json` (private), keyed by normalized requirement text plus a grouping prompt version.

### 3.5 Competency evidence map (`cv_evidenced` memory)

`data/cache/competency-evidence.json` (private). One entry per group, pointing into the evidence index:

```json
{
  "version": 1,
  "evidenceVersion": "<evidence index hash>",
  "entries": {
    "acceptance-criteria": {
      "status": "MET",
      "evidenceId": "role:3:b2",
      "evidenceTextHash": "<sha256 of the item text>",
      "strength": 3,
      "stability": "two_readings",
      "learnedFrom": { "jobId": "...", "requirementId": "...", "via": "reviewed" },
      "learnedAt": "2026-11-11T10:00:00Z",
      "checks": { "agree": 0, "disagree": 0 }
    }
  }
}
```

No candidate text is stored: ids, hashes, a status, a strength. Never a confirmed fact; a user fact always wins.

## 4. Flows

Order inside one run: extraction -> batch grouping (4.2) -> facts and map applied (4.1, 4.4) -> matcher only for what is still open -> scoring -> map updated -> queue built (4.3).

### 4.1 Remembering CV evidence

**What the map may learn.** Stage B measured 9-19% repeat noise, almost all on the PARTIAL boundary (silence / PARTIAL, PARTIAL / MET). A map that froze one noisy reading would spread the noise to every ad. So an entry is written only from a verdict that is:

- `MET` or `PARTIAL` with a verified quote, on a requirement with **no level**, reached through the seed, a `reviewed` or (once switched on) an `auto` link; and
- **stable:** where two identical readings exist, both agree and the line is not flagged (`aggregate_two`); where only one reading exists, only `MET` at strength 3-4 is learned (`stability: "one_reading"`), and PARTIAL is not learned at all.

Never learned: `CONTRADICTED`, `NOT_EVIDENCED`, a requirement with a level, a `pending` link. Dropped when `evidenceTextHash` no longer matches (the CV changed) or `evidenceVersion` changes.

**How it is used.**

1. Before the matcher, code looks up a requirement: confirmed fact first (4.4), then the map.
2. A map hit on a requirement with no level sets the status from the entry and the requirement is not sent; an ad whose requirements all resolve makes no matcher call.
3. A requirement with a level never resolves from the map.
4. **Check mode first (C6):** the map is written and looked up, but the matcher is still asked, and `checks` count agreement. It replaces calls only after the owner has seen the agreement rate; a group with any disagreement stays in check mode.
5. The map appears in "What Holojob knows about you" as **From your CV**, with the quote. Confirm -> user fact (`via: "cv_confirm"`). Reject -> `answer: "no"`, evidence id in `overrules`.

A side effect worth measuring: a stable entry gives the same verdict for the same competency on every ad, which is exactly the consistency the 9-19% noise lacks.

### 4.2 AI batch grouping

**Input:** requirement texts of the active pool that are still `prov:` or behind a `pending` link and not in the grouping cache. Ad text only, no candidate data; through `ai_gate` with its own feature (`competency-grouping`) and a per-run cap. A privacy-inventory line when built.

**Call:** batches of up to N texts (Q8), with the family's competency list (id, definition). Per text: `same_as: <id>` or `group: <label>` with `confidence: high | uncertain`, or `none`. The prompt asks for a conservative answer and explains "equivalent" (the same thing worded differently; not broader, narrower or related; the level ignored). It holds no threshold.

**Code decides:** `high` + kinds compatible (`kinds_compatible`) + id on the family list -> `auto`. A `high` group of new texts -> a deterministic provisional group id, members `auto`, listed as a `product.json` candidate in the competency report (added only by the owner). Anything else -> `pending`. A `demoted` text is never linked again for that id.

**Before `auto` carries answers (C5):** an audit sample of `auto` links (`competency_audit.py`, about 100), owner-labelled; the owner sets the acceptable wrong-merge rate. Until then `auto` links only group the queue.

Example: "Writing acceptance criteria" and "Defining acceptance criteria" -> one group. "A/B testing" and "Statistical experiment design" -> two groups.

### 4.3 The question queue

Built after each scoring run, from the **active pool**: open ads that passed the role filter and are not Rejected or Applied (field names to verify against `row_state.py` and the application store).

**What enters,** per group, after facts and the map:

1. `conflict` (4.5).
2. `critical_must`: a critical unconfirmed must (Stage B).
3. `not_evidenced`: NOT_EVIDENCED, and no `unknown` answer for the group.
4. `level`: an answer without years, and a requirement in the pool has a years level.
5. `partial_claim`: PARTIAL at strength 0-1 (listed only).
6. `unstable` (only where two readings exist): a line `aggregate_two` flagged, grouped across ads instead of the per-ad flag queue's three lines.

**Order:** by reason in the order above; within a reason, `adCount` descending, then `mustCount`, then id. A critical must is asked before any frequency, as Stage B decided.

**Shown:** the competency, its `memberTexts`, "appears in N of M active ads", up to three example ad titles, Yes / Partly / No / I don't know, and optional years. Never ids, aliases or link statuses.

### 4.4 Applying a fact to a requirement

Code, in `verify.apply_confirmed_fact`. A fact overrides the map and the matcher.

| Fact | Requirement with no level | Requirement with `years >= N` |
|---|---|---|
| `yes`, no years | `MET`, strength `CONFIRMED_FACT_STRENGTH` | Matcher verdict stands; queued as `level` |
| `yes`, V years | `MET` | `MET` if V >= N, else `PARTIAL` (Stage B level rule) |
| `partly`, no years | `PARTIAL`, strength `CONFIRMED_FACT_STRENGTH` | Matcher verdict stands; queued as `level` |
| `partly`, V years | `PARTIAL` | `PARTIAL` |
| `no` | `CONTRADICTED` | `CONTRADICTED` |
| `unknown` | Matcher verdict stands; not queued again | Same |

The years comparison is exact (the 1-year tolerance in 4.5 is for conflict detection only). A PARTIAL from the comparison carries its reason ("7 years confirmed, ad asks 10+"). Facts reach a requirement only through the seed, `reviewed`, or a switched-on `auto` link.

### 4.5 Conflicts

Two claims about one group, both at `cv_evidenced` or above:

1. The owner answered `no`, and the map or the evidence index has a verified quote at strength 3-4 for that group, not in `overrules`.
2. The owner's years value is below the CV's dated experience for that group by **more than 1 year**.

Not conflicts: a matcher proposal against a fact; a strength 0-2 claim against a `no`; closed-world absence against a `yes` (the owner's answer settles it); two separate groups that look alike.

**Until resolved:** both kept, the requirement is NOT_EVIDENCED, the queue names both sides, the ad says "Excludes A/B testing: conflicting information." **Resolved:** the choice becomes the fact (`via: "conflict"`); choosing `no` adds the evidence id to `overrules`.

### 4.6 Editing and revoking

"What Holojob knows about you" lists user facts and From your CV entries apart. Edit (old value to `history`) or revoke (to `unknown`); confirm or reject a CV entry. Every change re-scores active ads (4.7). No staleness re-checks in the MVP.

### 4.7 Re-scoring after an answer

An answer changes facts, never the evidence index, so no matcher call is needed. This needs the version split of contract 6.1: today `profileVersion` hashes the confirmed facts, so an answer would resend every affected ad. **The split is the first slice (M1).**

## 5. Scoring and display

Stage B rules apply: fit and confidence are always shown separately; the Incomplete label is replaced by "unconfirmed: N must requirements"; a critical unconfirmed must holds the bucket at `check_first`. This spec adds no production ranking change.

**`rankingScore`, offline variant only.** Fit's arithmetic, but a NOT_EVIDENCED must is in the denominator and earns `RANKING_PRIOR x STRENGTH_CREDIT[3]`; a critical unconfirmed must earns nothing toward it (Stage B: it never moves fit); NOT_EVIDENCED preferred / nice stay out. Same caps, exact arithmetic. It lives next to Stage B's fit x confidence variant in the replay and nowhere else. Whether any ranking variant reaches production is Stage B open decision 3 (C1).

**Markers on the ad:** a value that came from a CV entry ("from your CV") or over an `auto` link ("from your answer about X"); a requirement left out for a conflict or a pending link.

## 6. Privacy

- Batch grouping sends ad requirement texts only, through `ai_gate`; a privacy-inventory line when built.
- Facts, answers, notes, history, `overrules` and the evidence map are never sent. The matcher keeps receiving no confirmed facts (`shadow.NEVER_SENT`); the map only removes requirements from what it sends.
- The level extraction reads the ad only.
- New `data/` files follow `private-file-modes.md`; the queue and fact list are local API routes under `request-guard.md`.

## 7. Offline experiment (before any production change)

**Where:** add the variants to `python/calibration/v3_offline.py replay`, on the same stored verdicts and the same 44 ads, so the result sits in the same table as the Stage B rows. No model call.

- **Variants:** the Stage B rows (current formula; silence out of fit; with closed-world absence; strict proxy), fit x confidence, and `rankingScore` with `RANKING_PRIOR` 0.3 / 0.5 / 0.7, each with and without closed-world absence (Stage B open decision 2).
- **Ground truth:** Stage B reports Spearman against the owner's `overall` level; keep that for comparability and add `hardRequirements`, which judges requirements, as Fit does. `functionFit` is the role gate's concern and is not used. Not "would I apply": it mixes fit with interest.
- **Metrics:** Spearman per mode (`production_like` and `diagnostic` never pooled); median and mean change of the score; ads with confidence under 0.5 in each variant's top 10 (the "few settled requirements jump ahead" failure).
- **Read with the n:** 21 and 23 ads, one labeller, verdicts on one ad not independent. A Spearman difference under about 0.05 is no difference.
- **After slice 3:** if the owner approves and runs Stage B slice 3, rerun the same variants on its two-reading verdicts: the PARTIAL boundary moves, and with it every variant.
- **Pick:** recorded in `DECISIONS.md` as the answer to Stage B open decision 3.

**Baseline for D11,** recorded before the MVP ships: queue size and group count on the current active pool (from cached output), and the replay above. After two runs with the MVP: questions remaining, verdicts changed, replay agreement again, and the map's agree / disagree counts.

## 8. Not in the MVP

Global knowledge graph and typed links; impact score; embeddings; staleness re-validation; feedback from answers into link quality; level kinds other than `years`; expanding `product.json` by hand; multi-user; any production ranking change.

## 9. Proposed slices (not approved)

| # | Slice | Depends on |
|---|---|---|
| M0 | Settle Stage B open decisions 1-3 (slice 3, closed-world absence, fit with few settled requirements) | owner |
| M1 | Version split (contract 6.1) | - |
| M2 | Fact store v2 | - |
| M3 | Answer application, Stage B vocabulary, years (4.4) | M2, M0 |
| M4 | `rankingScore` variants in the Stage B replay | - |
| M5 | Batch grouping; `auto` carries nothing yet | - |
| M6 | Audit of `auto` links; switch on carrying | M5, owner |
| M7 | Evidence map in check mode, stable verdicts only | M1, M0 |
| M8 | Level in extraction, shared with the Stage B level fields; `PROMPT_VERSION` bump | Q4 |
| M9 | Queue builder, conflicts, local API | M3, M5 |
| M10 | UI: queue, What Holojob knows about you, ad markers | M9, M7 |

**Tests** (fixtures only, never `data/`): v1 -> v2 read; every row of 4.4 incl. below-level PARTIAL; `pending` and `demoted` never carry, `auto` only when switched on; grouping code rules on recorded answers; the map never learns CONTRADICTED, NOT_EVIDENCED, a level, a pending link, a flagged line, or a one-reading PARTIAL, and drops an entry when the text hash changes; frequency snapshot stable and excluding Rejected / Applied / Closed; queue order puts conflicts and critical musts first; each conflict rule and non-rule; a re-score after an answer makes no provider call; `rankingScore` exact values. **Conflict fixtures:** synthetic profiles that answer against their own CV on purpose (a `no` against a demonstrated quote; years below the CV by 2+; by exactly 1, which must not trigger; a `no` against a strength 0-2 skill, which must not trigger).

## 10. Open questions for the owner

| # | Question | Proposal |
|---|---|---|
| Q1 | Approve this spec | After M0 |
| Q2 | Which PARTIAL is queued | Strength 0-1 only |
| Q3 | Years tolerance | 1 year, conflict detection only |
| Q4 | Years level in the MVP | Yes, after a cost estimate for the re-extraction |
| Q5 | Calibration data | The Stage B replay (44 ads) |
| Q6 | Stage B results recorded | Done on `p1-stage-b` (5c2a27d) |
| Q7 | `auto` links carry answers and CV evidence (C5) | Yes, after the audit and a wrong-merge rate the owner sets |
| Q8 | Grouping batch size and per-run cap | 150 per batch; cap from the first run's count |
| Q9 | Stage B open decisions 1-3 | See `DECISIONS.md`, "P1 Stage B", Open decisions; this spec waits for them |
