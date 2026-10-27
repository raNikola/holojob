# Scoring engine contract

**v0.1 - draft for Phase 1.** Derived from [PHASE0_AUDIT.md](PHASE0_AUDIT.md) section 4 and the principles in
[DECISIONS.md](DECISIONS.md) (1-9). Nothing here is implemented yet. Where this draft goes beyond the audit
(a field, an enum value, a rule) it says so under "Open points", and the owner confirms those before Phase 1 is
built. Terms are defined in [../GLOSSARY.md](../GLOSSARY.md); acceptance criteria are in [../ROADMAP.md](../ROADMAP.md).

The engine is a module that takes one posting and one candidate evidence profile and returns requirements, a
status and evidence per requirement, gates, confidence, scores and questions. It does not import UI code, it does
not read files by itself, and every number in its output is computed by code. The model's only jobs are to read
the posting into requirements (quoting the ad) and to match requirements to the candidate's evidence (quoting the
evidence); code verifies both quotes.

## 1. Input

### 1.1 Fields

| Field | Type | Meaning |
|---|---|---|
| `posting.id` | string | Job id as in `discovered_jobs.json`. |
| `posting.title`, `company`, `location` | string | As listed. `location` may be empty. |
| `posting.description` | string | Full ad text. Every `postingQuote` must be a substring of it. |
| `posting.facts` | object | The enrichment facts (`llmFacts`: role track, seniority, years, work mode, country, visa text), including the `requirements[]` the extraction step produced (section 2.2). |
| `candidate.profileVersion` | string | Hash of everything under `candidate` that can change a result. Part of the cache key. |
| `candidate.roleFamily` | string or null | One id from the role-family config (for example `product`), chosen in the profile (`basicProfile.roleFamily`). Null when none is chosen: nothing is assumed, and the role-family gate is `unknown`. |
| `candidate.evidence[]` | array | The evidence index: one item per piece of text the candidate's history offers. |
| `evidence[].id` | string | Stable id within the profile version. |
| `evidence[].text` | string | The candidate's own words. Every `evidenceQuote` must be a substring of it. |
| `evidence[].source` | enum | `role`, `project`, `example`, `questionnaire`, `fact`. |
| `evidence[].role` | string or null | Employer or role the item belongs to; null when it has none. |
| `evidence[].start`, `end` | `YYYY-MM` or null | Period of the work described; null when unknown. |
| `evidence[].strength` | integer 0-4 | Evidence strength as measured from the text by code (section 4.3); the matcher may not raise it. |
| `candidate.confirmedFacts[]` | array | Answers the user gave to engine questions. `competencyId`, `has` (boolean), `note` (string, may be empty). A confirmed fact outranks inferred evidence. |
| `candidate.gates.workAuthorization` | object | Where the candidate may work without sponsorship and whether a sponsored role is acceptable (`jobFitPreferences.workAuthorization`). |
| `candidate.gates.allowedLocations` | string[] | Places the candidate accepts; empty gates nothing. |
| `candidate.gates.languages` | string[] | Spoken languages with level, for example `Serbian (native)`. A **closed list**: a language is covered when it is listed or is a close relative of a listed one (see "Language coverage"). Empty means unstated, not "none". |
| `candidate.gates.minSalaryEur` | number or null | Monthly floor in EUR; null when unset. |
| `candidate.gates.preferredLocations`, `remotePreference`, `relocation`, `country` | string[] / string or null | The commute and relocation preferences `location_match.py` reads; the location gate reuses that logic. |

Personal identifiers are never part of the input. The profile is redacted before it is built (DECISIONS.md
principle 14): no name, phone, e-mail or personal link appears in `evidence[].text`, `confirmedFacts[].note` or
anywhere else that can reach a provider.

### 1.2 JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://holojob.local/schemas/engine-input-0.1.json",
  "title": "EngineInput",
  "type": "object",
  "required": ["posting", "candidate"],
  "additionalProperties": false,
  "properties": {
    "posting": {
      "type": "object",
      "required": ["id", "title", "company", "description", "facts"],
      "additionalProperties": false,
      "properties": {
        "id": { "type": "string", "minLength": 1 },
        "title": { "type": "string" },
        "company": { "type": "string" },
        "location": { "type": "string" },
        "description": { "type": "string", "minLength": 1 },
        "facts": { "type": "object" }
      }
    },
    "candidate": {
      "type": "object",
      "required": ["profileVersion", "roleFamily", "evidence", "confirmedFacts", "gates"],
      "additionalProperties": false,
      "properties": {
        "profileVersion": { "type": "string", "minLength": 1 },
        "roleFamily": { "type": ["string", "null"], "minLength": 1 },
        "evidence": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["id", "text", "source", "strength"],
            "additionalProperties": false,
            "properties": {
              "id": { "type": "string", "minLength": 1 },
              "text": { "type": "string", "minLength": 1 },
              "source": { "enum": ["role", "project", "example", "questionnaire", "fact"] },
              "role": { "type": ["string", "null"] },
              "start": { "type": ["string", "null"], "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])$" },
              "end": { "type": ["string", "null"], "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])$" },
              "strength": { "type": "integer", "minimum": 0, "maximum": 4 }
            }
          }
        },
        "confirmedFacts": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["competencyId", "has"],
            "additionalProperties": false,
            "properties": {
              "competencyId": { "type": "string", "minLength": 1 },
              "has": { "type": "boolean" },
              "note": { "type": "string" }
            }
          }
        },
        "gates": {
          "type": "object",
          "required": ["workAuthorization", "allowedLocations", "languages", "minSalaryEur",
                       "preferredLocations", "remotePreference", "relocation", "country"],
          "additionalProperties": false,
          "properties": {
            "workAuthorization": { "type": "object" },
            "allowedLocations": { "type": "array", "items": { "type": "string" } },
            "languages": { "type": "array", "items": { "type": "string" } },
            "minSalaryEur": { "type": ["number", "null"], "minimum": 0 },
            "preferredLocations": { "type": "array", "items": { "type": "string" } },
            "remotePreference": { "type": ["string", "null"] },
            "relocation": { "type": ["string", "null"] },
            "country": { "type": ["string", "null"] }
          }
        }
      }
    }
  }
}
```

## 2. Steps

The engine runs two model steps and three code steps. A model step returns facts with quotes and never a number.

1. **Extraction (model).** Reads `posting.description` and returns `requirements[]` for the posting alone: text,
   kind, importance, a verbatim `postingQuote`, and a suggested canonical id from the role family's list. It never
   sees the candidate.
2. **Canonical mapping (code).** Maps each requirement to a canonical competency id of the role family. A
   requirement that maps to none gets a provisional id: `prov:` plus the first 12 hex characters of the SHA-256 of
   the requirement text, lower-cased and whitespace-collapsed. The id is deterministic, so the same ad gives the
   same provisional ids on every run.
3. **Matching (model).** Receives the requirements and the evidence index and returns, per requirement, a status
   proposal, the `evidenceId` it relied on, a verbatim `evidenceQuote` and a proposed strength. Gates are matched
   the same way (a quote from the ad for each condition).
4. **Verification and scoring (code).** Verifies every quote (section 5.2), applies confirmed facts, fixes the
   status and strength, computes counts, Fit, confidence, gates, bucket, label and caps.
5. **Questions (code).** Turns every UNKNOWN requirement and every `unknown` gate into a question for the user.

## 3. Output

### 3.1 Fields

| Field | Type | Meaning |
|---|---|---|
| `engineVersion` | string | Version of the engine code and its constants (section 6). |
| `promptVersion` | string | Version of the extraction and matching prompts. |
| `profileVersion` | string | Echo of `candidate.profileVersion`. |
| `adFingerprint` | string | Fingerprint of the ad content (`job_fingerprint.py`, the one definition). |
| `cacheKey` | string | `adFingerprint` + `profileVersion` + `promptVersion` (section 6). |
| `requirements[]` | array | One entry per requirement kept after extraction. |
| `requirements[].id` | string | Canonical competency id, or `prov:<hash>` when `provisional` is true. |
| `requirements[].provisional` | boolean | True when no canonical id matched. A provisional requirement is scored like any other. |
| `requirements[].text` | string | The requirement in the engine's words. |
| `requirements[].kind` | enum | `skill`, `experience`, `domain`, `education`, `certification`, `language`, `other`. Work authorization, location, salary and role family are gates, not requirements. |
| `requirements[].importance` | enum | `must`, `preferred`, `nice`. |
| `requirements[].postingQuote` | string | Verbatim words from the ad that state the requirement. |
| `requirements[].status` | enum | `MET`, `PARTIAL`, `MISSING`, `UNKNOWN` (section 4.1). |
| `requirements[].evidenceId` | string or null | The evidence item the status rests on; null for MISSING and UNKNOWN. |
| `requirements[].evidenceQuote` | string or null | Verbatim words from that item. |
| `requirements[].quoteVerified` | boolean | True only when code found `evidenceQuote` in the item's text (section 5.2). |
| `requirements[].strength` | integer 0-4 | Evidence strength credited (section 4.3). 0 when there is no evidence. |
| `gates[]` | array | One entry per gate, always all five. |
| `gates[].gate` | enum | `work_authorization`, `location`, `language`, `salary_floor`, `role_family`. |
| `gates[].result` | enum | `pass`, `unknown`, `fail`. |
| `gates[].quote` | string or null | Verbatim words from the ad behind the result; null when the ad says nothing. |
| `bucket` | enum | `apply`, `check_first`, `blocked` (section 5.4). Never a number. |
| `fit` | integer 0-100 | Evidence coverage of the requirements, after caps. Deterministic. |
| `cvCoverage` | integer 0-100 or null | What the current CV shows of the requirements. Phase 1 returns null; Phase 4 computes it. |
| `confidence` | number 0-1 | How much of the verdict rests on verified evidence rather than unknowns (section 5.3). |
| `label` | enum | `Strong`, `Good`, `Partial`, `Weak`, `Incomplete`. |
| `counts` | object | `mustMet`, `mustTotal`, `preferredMet`, `preferredTotal`, `unknown`, `blockers`, all non-negative integers. `unknown` counts UNKNOWN requirements of every importance; `blockers` counts must-haves with status MISSING plus gates with result `fail`. |
| `caps` | string[] | Names of the caps that lowered `fit`, from the enum in section 5.5. |
| `questions[]` | array | `competencyId` (a requirement id or a gate name) and the `question` text shown to the user. |

### 3.2 JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://holojob.local/schemas/engine-output-0.1.json",
  "title": "EngineOutput",
  "type": "object",
  "required": ["engineVersion", "promptVersion", "profileVersion", "adFingerprint", "cacheKey",
               "requirements", "gates", "bucket", "fit", "cvCoverage", "confidence", "label",
               "counts", "caps", "questions"],
  "additionalProperties": false,
  "properties": {
    "engineVersion": { "type": "string", "minLength": 1 },
    "promptVersion": { "type": "string", "minLength": 1 },
    "profileVersion": { "type": "string", "minLength": 1 },
    "adFingerprint": { "type": "string", "minLength": 1 },
    "cacheKey": { "type": "string", "minLength": 1 },
    "requirements": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "provisional", "text", "kind", "importance", "postingQuote",
                     "status", "evidenceId", "evidenceQuote", "quoteVerified", "strength"],
        "additionalProperties": false,
        "properties": {
          "id": { "type": "string", "minLength": 1 },
          "provisional": { "type": "boolean" },
          "text": { "type": "string", "minLength": 1 },
          "kind": { "enum": ["skill", "experience", "domain", "education", "certification", "language", "other"] },
          "importance": { "enum": ["must", "preferred", "nice"] },
          "postingQuote": { "type": "string", "minLength": 1 },
          "status": { "enum": ["MET", "PARTIAL", "MISSING", "UNKNOWN"] },
          "evidenceId": { "type": ["string", "null"] },
          "evidenceQuote": { "type": ["string", "null"] },
          "quoteVerified": { "type": "boolean" },
          "strength": { "type": "integer", "minimum": 0, "maximum": 4 }
        },
        "allOf": [
          {
            "if": { "properties": { "status": { "enum": ["MET", "PARTIAL"] } } },
            "then": { "properties": { "evidenceId": { "type": "string" }, "evidenceQuote": { "type": "string" } } }
          },
          {
            "if": { "properties": { "status": { "enum": ["MISSING", "UNKNOWN"] } } },
            "then": { "properties": { "evidenceId": { "type": "null" }, "evidenceQuote": { "type": "null" }, "strength": { "const": 0 } } }
          }
        ]
      }
    },
    "gates": {
      "type": "array",
      "minItems": 5,
      "maxItems": 5,
      "items": {
        "type": "object",
        "required": ["gate", "result", "quote"],
        "additionalProperties": false,
        "properties": {
          "gate": { "enum": ["work_authorization", "location", "language", "salary_floor", "role_family"] },
          "result": { "enum": ["pass", "unknown", "fail"] },
          "quote": { "type": ["string", "null"] }
        }
      }
    },
    "bucket": { "enum": ["apply", "check_first", "blocked"] },
    "fit": { "type": "integer", "minimum": 0, "maximum": 100 },
    "cvCoverage": { "type": ["integer", "null"], "minimum": 0, "maximum": 100 },
    "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
    "label": { "enum": ["Strong", "Good", "Partial", "Weak", "Incomplete"] },
    "counts": {
      "type": "object",
      "required": ["mustMet", "mustTotal", "preferredMet", "preferredTotal", "unknown", "blockers"],
      "additionalProperties": false,
      "properties": {
        "mustMet": { "type": "integer", "minimum": 0 },
        "mustTotal": { "type": "integer", "minimum": 0 },
        "preferredMet": { "type": "integer", "minimum": 0 },
        "preferredTotal": { "type": "integer", "minimum": 0 },
        "unknown": { "type": "integer", "minimum": 0 },
        "blockers": { "type": "integer", "minimum": 0 }
      }
    },
    "caps": {
      "type": "array",
      "items": { "enum": ["role_family_mismatch", "gate_blocked", "no_verified_evidence"] },
      "uniqueItems": true
    },
    "questions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["competencyId", "question"],
        "additionalProperties": false,
        "properties": {
          "competencyId": { "type": "string", "minLength": 1 },
          "question": { "type": "string", "minLength": 1 }
        }
      }
    }
  }
}
```

## 4. Enums and scales

### 4.1 Status

| Status | Meaning | In the coverage denominator |
|---|---|---|
| `MET` | Verified evidence shows the candidate has done what the requirement asks. | yes |
| `PARTIAL` | Verified evidence covers part of it, or a related thing, or only a claim. | yes |
| `MISSING` | The candidate side was checked and shows the requirement is not met: a confirmed fact with `has: false`, or a profile that covers the topic and does not contain it. | yes |
| `UNKNOWN` | The profile cannot settle it. Silence is not failure. | **no** |

### 4.2 Importance

`must` requirements decide the label and the blocker count; `preferred` and `nice` add to Fit with smaller weights.
The weights are code constants (`IMPORTANCE_WEIGHT`, section 5.1).

### 4.3 Evidence strength

| Strength | Name | Meaning |
|---|---|---|
| 0 | none | No evidence. |
| 1 | claim | Listed, for example in a skills list. |
| 2 | contextual | Mentioned inside the description of a role. |
| 3 | demonstrated | Described as work the candidate did. |
| 4 | demonstrated with outcome | Described as work done, with a measurable outcome. |

Strength is measured from the evidence text by code when the evidence index is built (`evidence[].strength`). The
credit each level earns toward Fit is a code constant (`STRENGTH_CREDIT`, section 5.1). The matcher may report a
strength, but the engine credits `min(reported, evidence[].strength)`.

### 4.4 Other enums

`bucket`: `apply`, `check_first`, `blocked`. `label`: `Strong`, `Good`, `Partial`, `Weak`, `Incomplete`.
`gate`: `work_authorization`, `location`, `language`, `salary_floor`, `role_family`. Gate `result`: `pass`,
`unknown`, `fail`. Evidence `source`: `role`, `project`, `example`, `questionnaire`, `fact`. `caps` values:
`role_family_mismatch`, `gate_blocked`, `no_verified_evidence`.

## 5. Invariants

Each invariant is a test in Phase 1.

### 5.1 Coverage and Fit

- **UNKNOWN is excluded from the coverage denominator.** Fit is the weighted credit of the MET, PARTIAL and MISSING
  requirements divided by the weight of those same requirements. An UNKNOWN requirement is never counted as MISSING,
  contributes no credit and no weight, appears in `counts.unknown`, becomes a question, and lowers `confidence`.
- With no MET, PARTIAL or MISSING requirement at all, Fit is 0 and the label is `Incomplete`.
- Constants, fixed in code and versioned with `engineVersion`: `STRENGTH_CREDIT` (credit per strength 0-4, the
  same for every requirement), `IMPORTANCE_WEIGHT` (weight per `must`, `preferred`, `nice`), `PARTIAL_FACTOR` (the
  share of the strength credit a PARTIAL earns). Values are set in Phase 1 against the fixtures (Open points).
- Fit is an integer 0-100, computed with integer or fixed-precision arithmetic so the same inputs always round the
  same way.

### 5.2 Quotes: `quoteVerified` and downgrade

- A quote is verified when, after normalization (Unicode NFKC, diacritics folded as in `text_utils.py`, whitespace
  collapsed, case folded), it is a substring of the text it claims to come from.
- `postingQuote` is checked against `posting.description`. A requirement whose `postingQuote` is missing or not
  found is dropped before scoring and reported in a `warnings` entry of the run log; the engine does not score
  what the ad does not say.
- `evidenceQuote` is checked against `evidence[].text` of `evidenceId`. `quoteVerified` is true only on a match.
- **Downgrade on a missing or unverified evidence quote.** A MET or PARTIAL proposal whose `evidenceQuote` is
  missing, empty or unverified is downgraded one step (MET to PARTIAL, PARTIAL to UNKNOWN), `quoteVerified` is
  false, and `strength` is capped at 1 (claim) when the status stays PARTIAL. A requirement the matcher marks
  MISSING needs no quote. A status never rises because of a quote.
- A confirmed fact with `has: true` makes the requirement MET with `evidenceId` set to the fact's evidence item and
  `quoteVerified` true; `has: false` makes it MISSING. Both skip the model's proposal for that requirement.

### 5.3 Confidence and the Incomplete label

`confidence` is the weight of the requirements that rest on a verified status (MET, PARTIAL or MISSING with
`quoteVerified` where a quote is required) divided by the weight of all requirements, with gates counted at the
weight of a `must`. The label is `Incomplete` when either threshold is crossed:

| Constant | Meaning |
|---|---|
| `MIN_CONFIDENCE` | `confidence` below this gives `Incomplete`. |
| `MAX_UNKNOWN_MUST_RATIO` | UNKNOWN `must` requirements divided by `mustTotal` above this gives `Incomplete`. |

The label text is "Incomplete - answer N questions", where N is `questions.length`. The values are named
constants in code, set in Phase 1.

### 5.4 Gates are buckets

- A gate never adds or removes points. Gates only set `bucket`: any `fail` gives `blocked`; otherwise any
  `unknown` gives `check_first`; otherwise `apply`.
- A `fail` gate is also reported in `counts.blockers` and in `caps` as `gate_blocked`, which limits the label (a
  blocked posting is never `Strong` or `Good`), not the number.
- Gate results come from code, not from the model: work authorization from the existing `work_authorization.py`
  statuses, location from `location_match`, `geography.py` and `location_text.py` (a remote ad is unknown until its text says Serbia, the Balkans or worldwide; a stated geography outside the allowed places fails), language from `candidate.gates.languages` against
  the ad's stated languages, salary floor from `salary.py`, role family from the role-family config. The model
  contributes only the quote from the ad.
- Gates read the discovered job with its `llmFacts` (`match_engine/gates.py`), not `posting`: salary, `isRemote`,
  `workMode`, `remoteEligibility` and `visaSponsorship` are not posting fields.
- `caps` lists every cap whose condition holds, including `gate_blocked`, which never moves Fit. A blocked label
  that would be `Strong` or `Good` becomes `Partial`; `Partial`, `Weak` and `Incomplete` stay.

### 5.5 Caps and labels

- **Role-family mismatch caps Fit.** When the posting's role family differs from `candidate.roleFamily`, Fit is
  limited to `ROLE_MISMATCH_FIT_CAP`, and `caps` contains `role_family_mismatch`.
- `no_verified_evidence` applies when no requirement has `quoteVerified` true: Fit is limited to
  `UNVERIFIED_FIT_CAP`.
- Labels from Fit, when not `Incomplete`: `Strong` at or above `LABEL_STRONG_MIN`, `Good` at or above
  `LABEL_GOOD_MIN`, `Partial` at or above `LABEL_PARTIAL_MIN`, otherwise `Weak`. The thresholds are code
  constants.
- The existing caps (off-track 50, red flag 54, work authorization 25/40/45) belong to the current
  `matchScore`. In shadow mode they stay with that score; the engine's Fit has its own caps listed above.

### 5.6 Determinism and privacy

- Same input, same cache key, same output: a cache hit returns the stored output byte for byte.
- The engine writes nothing outside its return value and its cache.
- Provider payloads contain no name, phone, e-mail or personal link; a test asserts it (ROADMAP.md, Phase 1).

## 6. Versioning

| Version | Where | Changes when |
|---|---|---|
| `engineVersion` | Output; semantic version of this contract plus the code and constants. | A schema, enum, invariant or constant changes. |
| `promptVersion` | Output; one string for the extraction and matching prompts. | Either prompt changes. |
| `profileVersion` | Input and output; a hash of the evidence index, confirmed facts and gates. | Anything in `candidate` changes. |
| `adFingerprint` | Output; `job_fingerprint.py`. | The ad content changes. |

**Cache key = `adFingerprint` + `profileVersion` + `promptVersion`.** The provider and model are part of the stored
entry, not of the key, so a switch of model is a visible miss that is recorded. An entry stored under a different
`engineVersion` is recomputed from the cached model answers when the model steps are unchanged, and re-run
otherwise. The previous requirement frame of the same ad is fed back to the extraction step so that requirement ids
stay stable across runs (DECISIONS.md principle 9): the prompt lists the previous id and text of each requirement, the
model names the previous id of a requirement it reads again, and code reuses that id and text when the id is in the
frame and not already taken. Frames are stored in `data/cache/requirement-frames.json`, keyed by the ad's content
without the prompt version, so they survive a prompt bump (`job_scoring/requirement_frames.py`). Model calls use
deterministic settings where the provider allows: OpenAI gets temperature 0 and a fixed seed, which OpenAI treats as
best effort, so stability is measured with tolerances (`match_engine/stability.py`, ROADMAP.md Phase 1) and never
assumed byte-identical. A model that rejects one of these settings is asked again without it.

### 6.1 Planned: evidence and answers versions (not yet implemented)

Owner decision of 2026-10-26 ([DECISIONS.md](DECISIONS.md)). The table and cache key above describe the code as it
is today; this subsection describes the change that is planned and is not built. Until it is, `profileVersion`
stays one hash that covers confirmed facts and gates.

`profileVersion` is split in two:

| Version | Covers | Invalidates cached model verdicts |
|---|---|---|
| `evidenceVersion` | The evidence index, the role family, `promptVersion` and `engineVersion`. | Yes. It is the only thing that does. |
| `answersVersion` | Confirmed facts and gate values. | No. |

The cache key becomes `adFingerprint` + `evidenceVersion`. The matcher sends every requirement of the ad to the model
and caches its verdicts under that key. Confirmed answers and gates are then applied in code on top of the cached
verdicts at every scoring run, which costs no model call: an answer overrides a status, never a stored model answer.
A new answer therefore changes the result but never forces a re-match. An answer applies only to a requirement that
resolves to the same canonical competency and carries no stricter qualifier than the answer (DECISIONS.md, 2026-10-26).
The output echoes both versions. Gate quotes come from the extraction step (which never sees the candidate), so an ad
whose requirements all resolve locally makes no matcher call.

Contract version `0.x` may change without notice. From `1.0` a change to a field or enum is a major version.

## 7. Errors

- **A failed call keeps the local score.** If extraction or matching fails (provider error, timeout, malformed JSON
  after one retry, schema violation), the engine returns no Fit for that posting. The posting keeps its current
  `matchScore`, label and priority, and the failure is logged on the run. A failed call is never cached.
- A malformed answer for one requirement drops that requirement with a warning; the rest are scored.
- Invalid input (a schema violation, empty description) is rejected before any model call and costs nothing.
- Per-run budget: at most 50 postings per run go to the model, highest local score first, equal scores in input
  order; a posting beyond the cap still uses a cached output (DECISIONS.md owner decisions).
- Shadow mode: the engine's output is stored next to the current score and changes no ranking, label or priority.

## Open points

These are the places where this draft decides something the audit left open. Each needs the owner's confirmation or
a calibration run on `tests/fixtures/postings/` before Phase 1 code depends on it.

1. Values of `STRENGTH_CREDIT`, `IMPORTANCE_WEIGHT`, `PARTIAL_FACTOR`, `MIN_CONFIDENCE`, `MAX_UNKNOWN_MUST_RATIO`,
   `ROLE_MISMATCH_FIT_CAP`, `UNVERIFIED_FIT_CAP` and the three label thresholds.
   Proposed in engine 0.2.0 from one matcher run on the fixtures (`match_engine/calibrate.py`, reasoning in
   `match_engine/constants.py`); pinned by `tests/python/test_engine_snapshot.py`. Awaiting the owner's review.
2. The exact downgrade rule on an unverified quote (section 5.2) and what makes a MISSING legitimate rather than
   UNKNOWN (section 4.1).
3. The bucket rule (section 5.4) and the `gate_blocked` label limit.
4. The fields added to the audit's output: `promptVersion`, `profileVersion`, `adFingerprint`, `cacheKey` and the
   `kind` enum.
5. Whether the salary floor, which is display-only in today's score, becomes a gate in the engine (principle 5
   says it does).

## Language coverage (closed list)

The profile's spoken-languages list is closed: the owner is not asked to list the languages he does not speak.
`match_engine/gates.py` (`LANGUAGE_COVERAGE`, `covered_languages`) widens it with a small table, one row per family:

| Members (speaking any covers all of them) | Also covered |
|---|---|
| Serbian, Croatian, Bosnian, Montenegrin, Serbo-Croatian (BCS / BCMS) | Macedonian (the owner states he understands it) |

"BCS" alone is not read in ad text (it is the British Computer Society in UK ads); it counts only as "BCS language".

Per language an ad names (`language_demands`): **required** when the extraction marks the requirement must-have or the
clause asks for it (fluent, native, required, mandatory, essential), **optional** when the importance is not must or the
clause calls it a plus / advantage / preferred / nice to have, **mentioned** when the ad names it with no sign of either.
Alternatives ("German or English", "English and/or Russian") are one demand, met when any one is covered.

- A required, uncovered language: language gate `fail` (the ad leaves the top-50 pick before any matcher call) and
  `settle_language` gives MISSING.
- An optional language never fails or excludes. `settle_language` gives MET when covered, else MISSING as for any
  optional requirement (a CV item that mentions it still goes to the matcher).
- A bare mention: gate `unknown` (confidence only, no exclusion).
- No languages listed in the profile: `unknown`.
- Conflict: a must-have language the list does not cover, which a CV item mentions. The gate fails the ad and the
  requirement is MISSING; the matcher is not asked, and the conflict is added to `warnings` for the owner to settle.

## Per-ad evidence selection (optional, default off)

`match_engine/evidence_select.py`. With `HOLOJOB_ENGINE_EVIDENCE_SELECT` set (`1` = strict, `focused` = looser;
changing `.env` needs `podman-compose up -d --force-recreate`) the matcher is sent, per ad, only the evidence items that
share a keyword with a requirement it is asked about, plus the core: the first item of every role and every `fact`
item (the tool and skill lists the MISSING rule needs). Items are sent unchanged, with their ids, so every quote stays
verbatim; the verifier still resolves ids over the **whole** index. The requirements, gates, output schema and prompt
are unchanged, and it only ever sends less than the full index (privacy list in `CLAUDE.md` still holds).

Cache key: `adFingerprint:profileVersion:promptVersion`, plus `:sel-1` (strict) or `:sel-1-focused` when selection is on.
The key keeps the **full** evidence version (`profileVersion`), not a hash of the selected subset, so any CV change
invalidates every entry, as before; the suffix keeps results made from a subset apart from full-index ones. With the flag
off, keys are exactly the old keys. Bump `SELECTION_VERSION` when the selection logic changes.

## Compact evidence format (optional, default off)

`HOLOJOB_ENGINE_COMPACT_EVIDENCE=1` sends the evidence index as JSON with no indentation, no spaces after
separators and no null or empty fields (`matcher.compact_evidence`). Every item keeps all of its text, its id and
the fields it has; a field that is absent means null. Unset or `0`: the payload is byte-identical to before.

- **No version bump.** The instructions to the model are word for word the same (they never described the blob's
  layout); only the blob's formatting differs. `promptVersion`, `profileVersion` and the cache key are unchanged, so
  existing cache entries stay valid and answer lookups in either format.
- New cache entries carry `payloadFormat` (`full` or `compact-1`) as metadata only, not in the key. If the compact
  layout ever changes, change the name there; if instruction text must change, that is a `MATCH_PROMPT_VERSION` bump.
- Independent of `HOLOJOB_ENGINE_EVIDENCE_SELECT`; the verifier still resolves ids over the full index.
- `.env` change needs `podman-compose up -d --force-recreate`.
