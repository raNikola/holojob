# Holojob - Data shapes (DS9)

Structure of every data file the app reads or writes. Only shapes: `<string>`, `<number>`, `<boolean>`, `<null>` and `<x>|<y>` for mixed values, `[...]` for lists, `<id>` for a map keyed by ids, a trailing `?` on a key where some records omit it. No value is copied from candidate or profile data. Generated from the files on DS9 on 2026-10-25, plus the code for data that lives only in the browser; keys rechecked against the code and the files on 2026-11-02.

Where data lives: the server as master is decided (DECISIONS.md principle 15) but **not built**. Until step 5 ([STEP5_SERVER_MASTER_PLAN.md](STEP5_SERVER_MASTER_PLAN.md)) ships, the profile, intelligence and job list live in the **browser's `localStorage`**; `data/profile/` and `data/intelligence/` are mirrors written by sync actions and read by the Python pipeline, and the pipeline files (`discovered_jobs.json`, `scored_jobs.json`, `job_history.json`) are written by the pipeline, not by sync. Applications (tracker) are already on the server: the [Application store](#application-store) under `data/applications/` is the master and the browser keeps a read cache (stored job records may still carry the old `applicationTracking` field, never written since the migration, until tracker step S4 removes it). Everything under `data/` except `data/examples/` is git-ignored and private.

Browser keys (the list is `src/modules/browserStorage/allowlist.js`): `localStorage` `job-dashboard-candidate-profile`, `job-dashboard-candidate-intelligence`, `job-dashboard-discovered-jobs`, `job-dashboard-pipeline-state`, `job-dashboard-sidebar-collapsed`, `job-dashboard-theme`, `job-dashboard-ai-cache`, `job-dashboard-ai-memory`, `job-dashboard-ai-usage`; `sessionStorage` `job-dashboard-active-view`, `job-dashboard-jobs-tab`, `job-dashboard-settings-category`, `job-dashboard-ai-chat`, `career-os-demo-bootstrap-done`; legacy values only read once and removed: `job-dashboard-ai-settings`, `job-dashboard-discovery-options`, `linkedin_li_at`.

## Candidate intelligence

- **Path:** `data/intelligence/candidate-intelligence.json`
- **Purpose:** Rule-based digest of the profile that scoring and discovery read (the only candidate file scoring reads). Also sent, minus private fields, to the judge.
- **Written by:** `generateCandidateIntelligence` in the UI (Regenerate Intelligence, also after CV Apply), synced to disk; copy in browser key `job-dashboard-candidate-intelligence`.

```json
{
  "candidateSummary": {
    "candidateType": "<string>",
    "seniorityLevel": "<string>",
    "oneLinePitch": "<string>",
    "careerNarrative": "<string>",
    "positioningStatement": "<string>",
    "unknown": ["careerNarrative|positioningStatement"]
  },
  "roleStrategy": {
    "primaryTargetRoles": [
      "<string>"
    ],
    "secondaryTargetRoles": [
      "<string>"
    ],
    "stretchRoles": [
      "<string>"
    ],
    "avoidRoles": [
      "<string>"
    ],
    "searchRoleVariants": [
      "<string>"
    ]
  },
  "skillsMap": {
    "technicalSkills": [
      "<string>"
    ],
    "frontend": [
      "<string>"
    ],
    "backend": [
      "<string>"
    ],
    "database": [
      "<empty>"
    ],
    "cloudDevOps": [
      "<string>"
    ],
    "aiAutomation": [
      "<string>"
    ],
    "productBusiness": [
      "<string>"
    ],
    "leadership": [
      "<string>"
    ],
    "softSkills": [
      "<string>"
    ]
  },
  "experienceMap": {
    "yearsOfExperience": "<string>",
    "domainsWorkedIn": [
      "<string>"
    ],
    "projectHighlights": [
      "<string>"
    ],
    "ownershipExamples": [
      "<string>"
    ],
    "leadershipExamples": [
      "<string>"
    ],
    "businessImpactExamples": [
      "<string>"
    ]
  },
  "jobFitPreferences": {
    "preferredCompanyTypes": [
      "<string>"
    ],
    "preferredIndustries": [
      "<string>"
    ],
    "avoidedIndustries": [
      "<string>"
    ],
    "country": "<string>",
    "workAuthorization": {
      "holds": [
        {
          "jurisdiction": "<string>",
          "basis": "<string>"
        }
      ],
      "openToSponsorship": "<boolean>"
    },
    "allowedLocations": [
      "<string>"
    ],
    "relocation": "<string>",
    "preferredLocations": [
      "<string>"
    ],
    "remotePreference": "<string>",
    "salaryExpectation": "<string>",
    "minSalaryEur": "<number>",
    "desiredSalaryEur": {
      "min": "<number>",
      "max": "<number>"
    },
    "culturePreference": [
      "<string>"
    ],
    "workToAvoid": [
      "<string>"
    ]
  },
  "candidateStrengths": [
    "<string>"
  ],
  "candidateWeaknesses": [
    "<string>"
  ],
  "resumeKeywords": [
    "<string>"
  ],
  "atsKeywordBank": {
    "highPriority": [
      "<string>"
    ],
    "mediumPriority": [
      "<string>"
    ],
    "supportingKeywords": [
      "<string>"
    ]
  },
  "searchStrategy": {
    "recommendedSearchQueries": [
      "<string>"
    ],
    "linkedinSearchQueries": [
      "<string>"
    ],
    "jobSpySearchTerms": [
      "<string>"
    ],
    "locationFilters": [
      "<string>"
    ],
    "remoteFilters": [
      "<string>"
    ]
  },
  "languages": [
    "<string>"
  ],
  "roleFamily": "<null>|<string>",
  "scoringWeights": {
    "roleMatch": "<number>",
    "skillMatch": "<number>",
    "locationMatch": "<number>",
    "experienceMatch": "<number>",
    "industryMatch": "<number>",
    "cultureMatch": "<number>"
  },
  "meta": {
    "generatedAt": "<string>",
    "sourceProfileVersion": "<string>",
    "intelligenceVersion": "<string>"
  }
}
```



## Candidate profile

- **Path:** `data/profile/candidate-profile.json`
- **Purpose:** The candidate: form fields, the active résumé, repositories, questionnaire answers. Browser key `job-dashboard-candidate-profile` is master; this is a mirror.
- **Written by:** Profile form / onboarding wizard; `POST /api/profile/save`.

```json
{
  "basicProfile": {
    "fullName": "<string>",
    "email": "<string>",
    "phone": "<string>",
    "location": "<string>",
    "currentRole": "<string>",
    "experienceYears": "<string>",
    "targetRoles": [
      "<string>"
    ],
    "preferredLocations": [
      "<string>"
    ],
    "remotePreference": "<string>",
    "salaryExpectation": "<string>",
    "minSalaryEur": "<number>",
    "desiredSalaryMinEur": "<number>",
    "desiredSalaryMaxEur": "<number>",
    "languages": [
      {
        "language": "<string>",
        "proficiency": "<string>"
      }
    ],
    "workAuthorization": {
      "holds": [
        {
          "jurisdiction": "<string>",
          "basis": "<string>"
        }
      ],
      "openToSponsorship": "<boolean>"
    },
    "allowedLocations": [
      "<string>"
    ],
    "relocation": "<string>",
    "roleFamily": "<string>"
  },
  "resume": {
    "fileName": "<string>",
    "uploadedAt": "<string>",
    "rawText": "<string>",
    "parsedData": {
      "skills": [
        "<string>"
      ],
      "projects": [
        "<string>"
      ],
      "education": [
        "<string>"
      ],
      "workExperience": [
        "<string>"
      ],
      "certifications": [
        "<string>"
      ],
      "links": [
        "<string>"
      ],
      "summary?": "<string> (from an import; absent when the CV had none)"
    },
    "importSource": "<string>"
  },
  "repositories": {
    "githubLinks": [
      "<string>"
    ],
    "localRepoPaths": [
      "<empty>"
    ]
  },
  "questionnaire": {
    "answers": [
      {
        "id": "<number>",
        "question": "<string>",
        "answer": "<string>",
        "source?": "resume"
      }
    ]
  },
  "meta": {
    "createdAt": "<string>",
    "updatedAt": "<string>",
    "profileVersion": "<string>",
    "questionnaireVersion": "<string>",
    "lastStep": "<number>",
    "onboardingComplete": "<boolean>",
    "completedAt": "<string>",
    "onboardingFinishedEarly?": "<boolean>",
    "completeProfileDismissedAt?": "<string>"
  }
}
```

More profile fields, in the browser and in the mirror:

```json
{
  "_confidence": { "<field>": "<string>" },
  "_editedFields": { "<field>": "<boolean>" },
  "defaultCvId": "<string>|<null>",
  "cvLibrary": [
    {
      "id": "<string>",
      "label": "<string>",
      "fileName": "<string>",
      "uploadedAt": "<string>",
      "filePath": "<string>|<null>",
      "rawText": "<string>",
      "parsedData": "<same shape as resume.parsedData, plus experienceDetail, competencyGroups, toolGroups>",
      "importSource": "<string>",
      "analysis?": {
        "facts": "<same shape as cv_analysis facts below>",
        "rejected": ["<string>"],
        "fingerprint": "<string>",
        "provider": "<string>",
        "model": "<string>",
        "promptVersion": "<string>",
        "analyzedAt": "<string>",
        "applied?": ["<string>"],
        "lastApply?": { "at": "<string>", "count": "<number>", "state": "<string>", "error?": "<string>" }
      }
    }
  ],
  "resume.parsedData.experienceDetail?": [{ "title": "<string>", "company": "<string>", "location?": "<string>", "start": "<string>", "end": "<string>", "description?": "<string>", "bullets": ["<string>"] }],
  "resume.parsedData.competencyGroups?": [{ "label": "<string>", "items": ["<string>"] }],
  "resume.parsedData.toolGroups?": [{ "label": "<string>", "items": ["<string>"] }]
}
```

`profile.resume` is always a copy of the default `cvLibrary` entry. List-type questionnaire answers are stored one entry per line with a trailing newline.

The questionnaire is optional. A skipped question has no entry (an emptied answer removes its entry; an empty string is never stored), so the unknown list is derived: the 17 questions minus those with a non-empty `answer`. `source: "resume"` marks an answer seeded from the résumé (questions 2 and 5); editing it replaces the entry without `source`, which confirms it. `onboardingFinishedEarly` is set when onboarding completed with questions still unknown; `completeProfileDismissedAt` records "Not now" on the Complete your profile card. In the intelligence file, `candidateSummary.unknown` lists summary fields left empty because nothing answers them yet; no filler text is stored.


## Import draft (transient)

- **Where:** in memory only, between the parse route and the Save button of the import wizard. Never written to `data/`, never put in `localStorage`; an unsaved draft is lost on a refresh.
- **Purpose:** what one import source yielded, for the review screen. It is not a profile format: every field maps onto the profile shape above, and `applyImportDraft` (`src/modules/profile/importDraft.js`) is the only code that turns a reviewed draft into a profile.
- **Made by:** `POST /api/profile/import/parse` (body `{ "source": "paste" | "resume_pdf" | "linkedin_pdf", "text": "<string>" }`, JSON, up to 200 KB of text; a PDF is read to text in the browser and only the text is sent), which runs `python/profile_import/text_parser.py` and writes nothing. Headings and field labels ("Education", "Obrazovanje", "Ime i prezime:", ...) come from `src/data/sectionHeadings.json`, one block per language, in Latin or Cyrillic script; the same file feeds the CV library upload (`src/utils/profileExtractor.js`). The three sources go through the one parser; `linkedin_pdf` is a mode of it (the "Top Skills" heading, company-before-title entries, "Page N of M" footers listed under `ignored`). A new language is a new block there, with no code change.

```json
{
  "source": "paste|resume_pdf|linkedin_pdf",
  "fileName": "<string>",
  "rawText": "<string>",
  "headline": "<string>",
  "summary": "<string>",
  "basicProfile": { "fullName?": "<string>", "email?": "<string>", "phone?": "<string>", "location?": "<string>", "currentRole?": "<string>", "experienceYears?": "<string>" },
  "parsedData": {
    "skills": ["<string>"], "projects": ["<string>"], "education": ["<string>"],
    "workExperience": ["<string>"], "certifications": ["<string>"],
    "experienceDetail": [{ "title": "<string>", "company": "<string>", "location": "<string>", "start": "<string>", "end": "<string>", "description": "<string>", "bullets": ["<string>"] }],
    "educationDetail": [{ "text": "<string>", "degree": "<string>", "school": "<string>", "year": "<string>" }],
    "competencyGroups": [{ "label": "<string>", "items": ["<string>"] }]
  },
  "languages": [{ "language": "<string>", "proficiency": "<string>" }],
  "links": ["<string>"],
  "confidence": { "<field>": "high|medium|low|derived", "experienceDetail.<n>": "high|medium|low", "educationDetail.<n>": "medium|low", "summary": "medium" },
  "unplaced": [{ "label": "<string>", "text": "<string>" }],
  "ignored": [{ "name": "<string>", "reason": "<string>" }],
  "warnings": ["<string>"]
}
```

- `email`, `phone` and `links` are the only places a contact detail appears; the parser removes them from every other string. `rawText` keeps the whole input, contact details included.
- `links` becomes `resume.parsedData.links` on save, and GitHub links are also added to `repositories.githubLinks`. `languages` becomes `basicProfile.languages`, with a level only when it is one of the profile's levels.
- `headline` is the title line under the name ("TECHNICAL PRODUCT LEADER ..."), shown as a hint. It is the `currentRole` only when the text has no experience entry; otherwise `currentRole` is the title of the current (else latest) entry. Target roles are never read from a CV: the draft has no such field.
- `experienceYears` is `"derived"`: the largest "10+ years", "over 10 years" or "12 years of experience" in the summary and top lines, else the years since the earliest entry start (with a warning saying so).
- An experience entry is a title / company (and place) line plus a date range; the lines under it are the `description` (before the first bullet) and `bullets`, with wrapped lines joined. `workExperience` is the derived `"Title — Company | start – end | description bullets"` line of each `experienceDetail` entry (JS `deriveWorkExperience` and Python `_derived_line` must stay identical); it is the plain lines of the section when no dated entry was recognised.
- **Entry headers** are read by evidence, not by one layout (`split_entry_header` in `text_parser.py`). Dates anchor an entry; the header is the line(s) above the dates (the default, and LinkedIn's company-then-title), the remainder of the date line (date-first: "2020 – 2023  Title, Company"), or the lines under the dates when nothing sits above the first one and role-like lines sit under it (flattened two-column CVs; decided once per section). A single header string is split by its separator (`at`, `@`, `-`, `–`, `—`, `|`, `·`, a trailing `(Company)`, a comma); the side that names a role (`role_words.json`; `weakRoleWords` such as "software" count less) is the title. A bare comma splits only with a legal suffix ("Inc."), a place after a pipe, or when another entry of the same section was split on a comma. When the evidence does not decide (both or neither side names a role, "Product Manager, Payments"), the line stays whole in `title`, `confidence["experienceDetail.<n>"]` is `low` and a warning names the entry number (never the text). A parenthetical beside the dates ("(US-based startup)") is a note: it is the first line of `description`, never the company; a parenthetical place is the `location`. Employment words ("Full-time") beside a title are dropped from the header.
- **Bullets and sub-headings:** a bullet starts only on a marker (•, -, *, –, a number; a marker alone on its line leads the next line); every unmarked line continues the bullet above it. Before the first bullet, lines are `description`. A short Title Case line without a full stop, followed by bullets, is a sub-heading: it ends the description, is not in any bullet, and is listed under `ignored` as "Sub-heading: ...". With no bullets in the CV, the text is the `description`.
- `summary` is the text of a Summary / Profile / About section (wrapped lines joined, a blank line kept as a paragraph break), empty when there is none. It is shown on the review screen as a Summary card (Fill / Replace current / Keep current, like a basic field) and saved to `resume.parsedData.summary` and to the new My CVs entry's `parsedData.summary`; `choices.summary` is `"use"` or `"keep"`. It is no longer in `unplaced`.
- `educationDetail` is how each education line was read: the last date range or year is `year`; the piece with a school word is `school`; the piece with a degree word (and the field of study after it, when the school is named elsewhere) is `degree`; one unmarked piece beside a school is the `degree`. A line that does not fall into those places leaves `degree` and `school` empty and keeps only the year (`educationDetail.<n>` is `low`, with a warning); the line itself stays in `education` and `text`. `text` is the education line it was read from. **Display only:** the review screen shows "Read as: ..." under a line while the line still equals `text`; saving writes the `education` lines and not `educationDetail`. School-then-degree (LinkedIn) and year-then-degree line pairs become one line.
- `unplaced` is text that fits no field (interests, lines the parser could not read).
- **My CVs > Add** reads the PDF text in the browser and sends it to the same parse route (`source: "resume_pdf"`); the entry's `parsedData` is the draft's lists and entries (`draftParsedData`, no `educationDetail`). If the route cannot be reached or refuses the text, the older in-browser reader (`profileExtractor.js`) fills it and the notice says so. It is shown on the review screen and stays in `rawText`; nothing is dropped.
- Saving adds a `cvLibrary` entry with `importSource: "pasted_text"`, `filePath: null`, `fileName` and `label` of the form `Pasted text <YYYY-MM-DD>`. It is not the default CV unless the profile had none. For a PDF source (`importSource` `resume_pdf` or `linkedin_pdf`) the file is first stored through `POST /api/cvs` (best effort), the entry takes the stored id and `filePath`, and `fileName` / `label` come from the PDF's name.
- "Education & Certifications" style sections are split by `python/profile_import/education_words.json` (certificate words first, then degree, then institution words); a line that is neither goes to `unplaced`.

## CV files

- **Path:** `data/profile/cvs/<id>.pdf` (`<id>` = 16 hex characters made by the server)
- **Purpose:** the uploaded PDF behind a `cvLibrary` entry (`filePath` = `profile/cvs/<id>.pdf`). Entries migrated from before the library have `filePath: <null>`.
- **Written by:** `POST /api/cvs`; removed by `DELETE /api/cvs/:id`. Binary, `%PDF-` checked, up to 10 MB.

## CV analysis cache

- **Path:** `data/cache/cv_analysis.json`
- **Purpose:** Last LLM analysis per redacted CV text, so a repeat costs nothing. Key = fingerprint of redacted text + provider + model + prompt version.
- **Written by:** `python/cv_analysis/run_cv_analyze.py`.

```json
{
  "<fingerprint>": {
    "facts": {
      "summary": "<string>",
      "draftCareerSummary": "<string>",
      "skills": [
        "<string>"
      ],
      "keyProjects": [
        {
          "name": "<string>",
          "summary": "<string>"
        }
      ],
      "experience": [
        {
          "title": "<string>",
          "company": "<string>",
          "start": "<string>",
          "end": "<string>",
          "bullets": [
            "<string>"
          ]
        }
      ],
      "competencyGroups": [
        {
          "label": "<string>",
          "items": [
            "<string>"
          ]
        }
      ],
      "toolGroups": [
        {
          "label": "<string>",
          "items": [
            "<string>"
          ]
        }
      ],
      "education": [
        {
          "degree": "<string>",
          "school": "<string>",
          "year": "<string>"
        }
      ],
      "certifications": [
        {
          "name": "<string>",
          "issuer": "<string>",
          "year": "<string>"
        }
      ]
    },
    "rejected": [
      "<empty>"
    ],
    "analyzedAt": "<string>"
  }
}
```



## Discovered jobs

- **Path:** `data/jobs/discovered_jobs.json`
- **Purpose:** Output of discovery after dedupe and history merge; input of enrichment and scoring. Rewritten every run (closed jobs stay 14 days).
- **Written by:** `run_discovery.py`, `enrich_jobs.py` (adds `llmFacts`).

```json
{
  "meta": {
    "generatedAt": "<string>",
    "sourceRunId": "<string>",
    "searchTerms": [
      "<string>"
    ],
    "locations": [
      "<string>"
    ],
    "remoteFilters": [
      "<string>"
    ],
    "country": "<string>",
    "providers": [
      "<string>"
    ],
    "providerCounts": {
      "jobspy": "<number>",
      "infostud": "<number>",
      "workable": "<number>",
      "greenhouse": "<number>",
      "lever": "<number>",
      "ashby": "<number>",
      "joberty?": "<number>"
    },
    "rawCount": "<number>",
    "dedupedCount": "<number>",
    "duplicateCount": "<number>",
    "history": {
      "new": "<number>",
      "known": "<number>",
      "reopened": "<number>",
      "changed": "<number>",
      "carriedFacts": "<number>",
      "closed": "<number>",
      "keptFullerDescription": "<number>",
      "keptFailedBoard": "<number>",
      "keptEmptyBoard": "<number>",
      "keptSourceNotRun": "<number>"
    }
  },
  "jobs": [
    {
      "jobId": "<string>",
      "provider": "<string>",
      "source": "<string>",
      "title": "<string>",
      "company": "<string>",
      "location": "<string>",
      "site": "<string>",
      "jobUrl": "<string>",
      "description": "<string>",
      "datePosted": "<string>",
      "salary": "<string>",
      "employmentType": "<string>",
      "isRemote": "<boolean>",
      "searchTerm": "<string>",
      "searchLocation": "<string>",
      "scrapedAt": "<string>",
      "status": "<string>",
      "firstSeen": "<string>",
      "lastSeen": "<string>",
      "closedAt": "<null>",
      "isNew": "<boolean>",
      "isClosed": "<boolean>",
      "llmFacts": {
        "workMode": "<string>",
        "workModeEvidence": "<null>|<string>",
        "roleTrack": "<string>",
        "roleTrackEvidence": "<null>|<string>",
        "seniority": "<string>",
        "yearsRequired": "<null>|<number>",
        "requirements": [
          {
            "id": "<string>",
            "text": "<string>",
            "kind": "<string>",
            "importance": "<string>",
            "postingQuote": "<string>",
            "provisional": "<boolean>"
          }
        ],
        "mustHaves": [
          "<string>"
        ],
        "niceToHaves": [
          "<string>"
        ],
        "domain": "<null>|<string>",
        "listingFlags": [
          "<string>"
        ],
        "jobCountry": "<null>|<string>",
        "remoteEligibility": [
          "<string>"
        ],
        "visaSponsorship": "<string>",
        "visaEvidence": "<null>|<string>",
        "_fingerprint": "<string>"
      },
      "workMode?": "<string>",
      "expiresAt?": "<string>",
      "category?": "<string>",
      "standardizedPosition?": "<string>",
      "tags?": [
        "<string>"
      ],
      "seniority?": "<string> (Joberty)",
      "domains?": ["<string>"],
      "technologies?": ["<string>"],
      "applyUrl?": "<string>",
      "externalId?": "<string>"
    }
  ]
}
```



## Manual jobs

- **Path:** `data/jobs/manual_jobs.json`
- **Purpose:** Jobs the owner typed in (Add job). Kept apart because discovery rewrites `discovered_jobs.json` and scoring rebuilds
  `scored_jobs.json` from it. `run_scoring.py` adds these jobs to every run; a manual row wins over a discovered row with the same
  normalised URL. Never written by discovery. In backups with the rest of `data/jobs/`.
- **Written by:** `import_job_url.py --job-json` (called by `POST /api/jobs/manual/score` and `/sync`). Only the scoring fields
  (`SCORING_FIELDS` in `manual_jobs.py`) are stored: `jobId` (`manual-<uuid>`), `title`, `company`, `description`, `jobUrl`, `location`,
  `salary` (text as typed), `site`, `provider: "manual"`, `manualEntry: true`, `sourceChoice` (older records only), `status`, `createdAt`, `firstSeen`,
  `lastSeen`, `scrapedAt`, `updatedAt`. Notes, extra links and the Source URL are not stored here; they stay in the browser's job record.

```json
{ "jobs": [ { "jobId": "manual-<uuid>", "title": "...", "company": "...", "description": "...", "jobUrl": "...", "provider": "manual", "manualEntry": true } ] }
```

## Scored jobs

- **Path:** `data/jobs/scored_jobs.json`
- **Purpose:** Everything in discovered jobs plus scores, label, priority, reasons, work-authorization status, salary parse. What the UI job list loads (copy in browser key `job-dashboard-discovered-jobs`). The browser copy can also hold rows the file lacks, marked `offList: true`, kept only for the owner's data ([decision](../DECISIONS.md#offlist-rows-keep-the-owners-data-2026-11-03)); that mark is never in this file.
- **Written by:** `run_scoring.py` (`--judge` adds `llmFit`; with `CAREER_OS_ENGINE_SHADOW` on, every job with an
  engine output gets `engineShadow` and `meta.engineShadow` counts them, see "Engine shadow output").

```json
{
  "meta": {
    "generatedAt": "<string>",
    "sourceRunId": "<string>",
    "discoveryRunId": "<string or null: the run-log record of the discovery run these jobs came from>",
    "scoringVersion": "<string>",
    "intelligenceGeneratedAt": "<string>",
    "discoveryGeneratedAt": "<string>",
    "weights": {
      "roleMatch": "<number>",
      "skillMatch": "<number>",
      "locationMatch": "<number>",
      "experienceMatch": "<number>",
      "industryMatch": "<number>",
      "cultureMatch": "<number>"
    },
    "judge": {
      "scored": "<number>",
      "judged": "<number>",
      "fromCache": "<number>",
      "beyondLimit": "<number>",
      "belowThreshold": "<number>",
      "closed": "<number>",
      "failed": "<number>",
      "refused": "<number>",
      "refusal": "<null>|<string>",
      "limit": "<null>|<number>",
      "threshold": "<number>"
    },
    "engineShadow": {
      "enabled": "<boolean>",
      "matched?": "<number>",
      "cached?": "<number>",
      "uncached?": "<number>",
      "beyondLimit?": "<number>",
      "noRequirements?": "<number>",
      "closed?": "<number>",
      "failed?": "<number>",
      "excluded?": "<number>",
      "refused?": "<number>",
      "refusal?": "<null>|<string>",
      "limit?": "<null>|<number>"
    },
    "aiEnrichment": {
      "jobsWithoutFacts": "<number>",
      "jobs": "<number>"
    },
    "manualJobs": {
      "count": "<number>",
      "replacedRows": "<number>"
    },
    "quality": {
      "reduced": "<boolean>",
      "reason?": "<string>"
    },
    "jobCount": "<number>",
    "summary": {
      "excellent": "<number>",
      "strong": "<number>",
      "good": "<number>",
      "weak": "<number>",
      "reject": "<number>"
    }
  },
  "jobs": [
    {
      "jobId": "<string>",
      "provider": "<string>",
      "source": "<string>",
      "title": "<string>",
      "company": "<string>",
      "location": "<string>",
      "site": "<string>",
      "jobUrl": "<string>",
      "description": "<string>",
      "datePosted": "<string>",
      "salary": "<string>",
      "employmentType": "<string>",
      "isRemote": "<boolean>",
      "searchTerm": "<string>",
      "searchLocation": "<string>",
      "scrapedAt": "<string>",
      "status": "<string>",
      "firstSeen": "<string>",
      "lastSeen": "<string>",
      "closedAt": "<null>",
      "isNew": "<boolean>",
      "isClosed": "<boolean>",
      "llmFacts": {
        "workMode": "<string>",
        "workModeEvidence": "<null>|<string>",
        "roleTrack": "<string>",
        "roleTrackEvidence": "<null>|<string>",
        "seniority": "<string>",
        "yearsRequired": "<null>|<number>",
        "requirements": [
          {
            "id": "<string>",
            "text": "<string>",
            "kind": "<string>",
            "importance": "<string>",
            "postingQuote": "<string>",
            "provisional": "<boolean>"
          }
        ],
        "mustHaves": [
          "<string>"
        ],
        "niceToHaves": [
          "<string>"
        ],
        "domain": "<null>|<string>",
        "listingFlags": [
          "<string>"
        ],
        "jobCountry": "<null>|<string>",
        "remoteEligibility": [
          "<string>"
        ],
        "visaSponsorship": "<string>",
        "visaEvidence": "<null>|<string>",
        "_fingerprint": "<string>"
      },
      "matchScore": "<number>",
      "matchLabel": "<string>",
      "applyRecommendation": "<string>",
      "priority": "<string>",
      "roleMatch": "<number>",
      "skillMatch": "<number>",
      "industryMatch": "<number>",
      "experienceMatch": "<number>",
      "locationMatch": "<number>",
      "cultureMatch": "<number>",
      "matchedSkills": [
        "<string>"
      ],
      "missingSkills": [
        "<string>"
      ],
      "redFlags": [
        "<string>"
      ],
      "reasons": [
        "<string>"
      ],
      "scoreBreakdown": {
        "roleMatch": {
          "raw": "<number>",
          "weight": "<number>",
          "weighted": "<number>"
        },
        "skillMatch": {
          "raw": "<number>",
          "weight": "<number>",
          "weighted": "<number>"
        },
        "industryMatch": {
          "raw": "<number>",
          "weight": "<number>",
          "weighted": "<number>"
        },
        "experienceMatch": {
          "raw": "<number>",
          "weight": "<number>",
          "weighted": "<number>"
        },
        "locationMatch": {
          "raw": "<number>",
          "weight": "<number>",
          "weighted": "<number>"
        },
        "cultureMatch": {
          "raw": "<number>",
          "weight": "<number>",
          "weighted": "<number>"
        }
      },
      "workAuthorization": {
        "status": "<string>",
        "place": "<string>",
        "reason": "<string>",
        "location?": {
          "state": "pass|unknown|fail",
          "flag": "<null>|<string>",
          "quote": "<null>|<string>",
          "reason": "<string>"
        }
      },
      "salaryMonthlyEur": {
        "<one of>": [
          {
            "min": "<number>",
            "max": "<number>",
            "currency": "<string>",
            "converted": "<boolean>"
          },
          "<null>"
        ]
      },
      "belowMinSalary": "<boolean>|<null>",
      "hardCapped": "<boolean>",
      "manualEntry?": "<boolean>",
      "createdAt?": "<string>",
      "updatedAt?": "<string>",
      "aiEnrichment?": "missing",
      "workMode?": "<string>",
      "expiresAt?": "<string>",
      "category?": "<string>",
      "standardizedPosition?": "<string>",
      "tags?": [
        "<string>"
      ],
      "seniority?": "<string> (Joberty)",
      "domains?": ["<string>"],
      "technologies?": ["<string>"],
      "applyUrl?": "<string>",
      "externalId?": "<string>"
    }
  ]
}
```

Fields added later, in the browser job store and not in this file until saved:

```json
{
  "llmFit?": { "fit": "<string>", "fitReason": "<string>", "requirements": [{ "requirement": "<string>", "status": "<string>", "evidence": "<string>|<null>" }], "missing": ["<string>"], "dealbreakers": ["<string>"], "fromCache": "<boolean>" },
  "applicationTracking?": {
    "applied": "<boolean>", "appliedDate": "<string>", "applicationUrl": "<string>",
    "recruiterName": "<string>", "recruiterEmail": "<string>", "recruiterLinkedIn": "<string>",
    "notes": "<string>", "followUpDate": "<string>",
    "interviewStage": "<string: Applied|HR Screen|Technical Round 1|Technical Round 2|Assignment|Hiring Manager|Final Round|Offer|Rejected|Withdrawn>",
    "lastUpdated": "<string>"
  },
  "tailoredAssets?": {
    "resumeMd": "<string>", "resumeHtml": "<string>", "resumePdf": "<string>", "resumeDocx": "<string>", "resumeJson": "<string>",
    "coverLetterMd": "<string>", "coverLetterPdf": "<string>", "generatedAt": "<string>", "contentEngine": "<string>",
    "llmIssues": ["<string>"], "warnings": ["<string>"], "provenancePassed": "<boolean>", "provenanceIssues": ["<string>"], "validation": "<object>"
  }
}
```


## Job history ledger

- **Path:** `data/jobs/job_history.json`
- **Purpose:** Survives discovery rewrites: first/last seen, closed, a snapshot of each job, and the enrichment facts (reused while the ad fingerprint is unchanged). Dropped after 90 days closed.
- **Written by:** `job_scoring/job_history.py`.

```json
{
  "version": "<number>",
  "updatedAt": "<string>",
  "jobs": {
    "<id>": {
      "firstSeen": "<string>",
      "lastSeen": "<string>",
      "closedAt": "<null>",
      "llmFacts": {
        "workMode": "<string>",
        "workModeEvidence": "<null>|<string>",
        "roleTrack": "<string>",
        "roleTrackEvidence": "<null>|<string>",
        "seniority": "<string>",
        "yearsRequired": "<null>|<number>",
        "requirements": [
          {
            "id": "<string>",
            "text": "<string>",
            "kind": "<string>",
            "importance": "<string>",
            "postingQuote": "<string>",
            "provisional": "<boolean>"
          }
        ],
        "mustHaves": [
          "<string>"
        ],
        "niceToHaves": [
          "<string>"
        ],
        "domain": "<null>|<string>",
        "listingFlags": [
          "<string>"
        ],
        "jobCountry": "<null>|<string>",
        "remoteEligibility": [
          "<string>"
        ],
        "visaSponsorship": "<string>",
        "visaEvidence": "<null>|<string>",
        "_fingerprint": "<string>"
      },
      "provider": "<string>",
      "roleKey": "<string>",
      "seenUnder": "<string>",
      "job": {
        "jobId": "<string>",
        "provider": "<string>",
        "source": "<string>",
        "title": "<string>",
        "company": "<string>",
        "location": "<string>",
        "site": "<string>",
        "jobUrl": "<string>",
        "description": "<string>",
        "datePosted": "<string>",
        "salary": "<string>",
        "employmentType": "<string>",
        "isRemote": "<boolean>",
        "searchTerm": "<string>",
        "searchLocation": "<string>",
        "scrapedAt": "<string>",
        "status": "<string>",
        "workMode?": "<string>",
        "expiresAt?": "<string>",
        "category?": "<string>",
        "standardizedPosition?": "<string>",
        "tags?": [
          "<string>"
        ],
        "seniority?": "<string> (Joberty)",
        "domains?": ["<string>"],
        "technologies?": ["<string>"],
        "applyUrl?": "<string>",
        "externalId?": "<string>"
      },
      "seeded?": "<boolean>"
    }
  }
}
```



## Discovery run log

- **Path:** `data/analytics/runs/<startedAt>-<runId>.json`, one file per run, kept 90 days.
- **Purpose:** What each discovery run did per source, for the Activity screen.
- **Written by:** `run_discovery.py` through `run_log.py`. Field meanings: [DECISIONS.md](../DECISIONS.md#activity-slice-1-as-built-2026-11-02).

```json
{
  "version": 1,
  "runId": "<string>",
  "trigger": "manual | pipeline | scheduled",
  "startedAt": "<string>",
  "finishedAt": "<string>",
  "status": "ok | partial | failed | skipped",
  "sources": [
    {
      "name": "<string>",
      "status": "ok | partial | failed | skipped",
      "read": "<number>",
      "kept": "<number>",
      "new": "<number>",
      "error": "<string or null>",
      "boardsFailed": [
        "<string>"
      ],
      "skipReason": "<string or null>"
    }
  ],
  "issues": [
    {
      "level": "error | warning",
      "source": "<string or null>",
      "message": "<string>"
    }
  ]
}
```

## Last pipeline run

- **Path:** `data/jobs/pipeline_last_run.json`
- **Purpose:** Step timings and counts of the last full run, shown in the Pipeline tab.
- **Written by:** `run_pipeline.py`.

```json
{
  "startedAt": "<string>",
  "status": "<string>",
  "steps": [
    {
      "step": "<string>",
      "seconds": "<number>",
      "exitCode": "<number>"
    }
  ],
  "discovery": {
    "providerCounts": {
      "jobspy": "<number>",
      "infostud": "<number>",
      "workable": "<number>",
      "greenhouse": "<number>",
      "lever": "<number>",
      "ashby": "<number>",
      "joberty?": "<number>"
    },
    "raw": "<number>",
    "deduped": "<number>",
    "history": {
      "new": "<number>",
      "known": "<number>",
      "reopened": "<number>",
      "changed": "<number>",
      "carriedFacts": "<number>",
      "closed": "<number>",
      "keptFullerDescription": "<number>",
      "keptFailedBoard": "<number>",
      "keptEmptyBoard": "<number>",
      "keptSourceNotRun": "<number>"
    }
  },
  "enrichment": {
    "enrichedShare": "<number>",
    "extracted": "<number>",
    "cached": "<number>",
    "failed": "<number>",
    "notRead": "<number>",
    "refused": "<number>"
  },
  "quality?": {
    "reduced": "<boolean>",
    "reason": "<string>",
    "note": "<string>"
  },
  "scoring": {
    "jobs": "<number>",
    "labels": {
      "excellent": "<number>",
      "strong": "<number>",
      "good": "<number>",
      "weak": "<number>",
      "reject": "<number>"
    },
    "priority": {
      "P1": "<number>",
      "P2": "<number>",
      "Reject": "<number>",
      "P3": "<number>"
    },
    "scoreBands": {
      "85-100": "<number>",
      "70-84": "<number>",
      "55-69": "<number>",
      "40-54": "<number>",
      "0-39": "<number>"
    },
    "workAuthorization": {
      "authorized": "<number>",
      "outside_allowed": "<number>",
      "unknown": "<number>",
      "needs_visa_silent": "<number>",
      "needs_visa_refused": "<number>"
    },
    "hardCapped": "<number>",
    "applyNow": "<number>"
  },
  "finishedAt": "<string>"
}
```



## Other job files

- `data/jobs/normalized_jobs.json` - discovery output before dedupe (same job fields as discovered jobs, list under `jobs`).
- `data/jobs/raw_jobs.csv` - raw provider rows, one column per job field above plus provider-specific extras.
- `data/jobs/.pipeline.lock` - empty lock file while a pipeline runs.

## Fit judgement cache

- **Path:** `data/cache/llm_fit.json`
- **Purpose:** Cached judge answers per job, valid while the ad, digest, prompt version and provider/model are unchanged.
- **Written by:** `job_scoring/llm_enhancer.py` (`--judge`).

```json
{
  "<id>": {
    "fit": "<string>",
    "fitReason": "<string>",
    "requirements": [
      {
        "requirement": "<string>",
        "status": "<string>",
        "evidence": "<null>|<string>"
      }
    ],
    "missing": [
      "<string>"
    ],
    "dealbreakers": [
      "<string>"
    ]
  }
}
```

Map keys are cache fingerprints. The cache is also read, without any model call, by every local scoring run.

## Requirement frames

- **Path:** `data/cache/requirement-frames.json`
- **Purpose:** The last requirements read from each ad, fed back to its next extraction so a requirement read again keeps its id and text (DECISIONS.md principle 9, ENGINE_CONTRACT.md section 6). Generated from ads only, never from the candidate; gitignored like the rest of `data/cache/`.
- **Written by:** `job_scoring/enrich_jobs.py` and `match_engine/calibrate.py` (`job_scoring/requirement_frames.py`). `match_engine/stability.py` keeps its own frames inside `data/cache/engine-stability.json`.

```json
{
  "<frameKey>": [
    {
      "id": "<string>",
      "text": "<string>",
      "kind": "<string>",
      "importance": "<string>"
    }
  ]
}
```

Map keys are `requirement_frames.frame_key()`: the ad's title, company and description, without the prompt version, so a frame survives a prompt bump. An ad whose text changes gets no frame from here; the requirements on its own `llmFacts` are used instead.

## Engine shadow output

- **On:** each scored job as `engineShadow`, when `CAREER_OS_ENGINE_SHADOW` is on (`match_engine/shadow.py`).
- **Purpose:** The Phase 1 engine's verdict next to `matchScore`, read only (ENGINE_CONTRACT.md section 7). Nothing
  reads it to rank, sort, filter or label; the UI shows it in a dashed "new engine (shadow)" box.
- **Shape:** the contract's output (section 3) plus `labelText`, `warnings`, `provider`, `model`, `fromCache`. A
  failed matcher call is `{"engineVersion", "error"}` and is not cached. No field when there is no output.

```json
{
  "engineVersion": "<string>",
  "promptVersion": "<string>",
  "profileVersion": "<string>",
  "adFingerprint": "<string>",
  "cacheKey": "<string>",
  "requirements": [{ "id": "<string>", "text": "<string>", "importance": "<string>", "status": "<string>",
                     "strength": "<number>", "postingQuote": "<string>", "evidenceId": "<null>|<string>",
                     "evidenceQuote": "<null>|<string>", "quoteVerified": "<boolean>" }],
  "gates": [{ "gate": "<string>", "result": "<string>", "quote": "<null>|<string>" }],
  "fit": "<number>",
  "confidence": "<number>",
  "label": "<string>",
  "labelText": "<string>",
  "bucket": "<string>",
  "caps": ["<string>"],
  "counts": { "mustMet": "<number>", "mustTotal": "<number>", "preferredMet": "<number>",
              "preferredTotal": "<number>", "unknown": "<number>", "blockers": "<number>" },
  "questions": [{ "competencyId": "<string>", "question": "<string>" }],
  "cvCoverage": "<null>",
  "warnings": ["<string>"],
  "provider": "<string>",
  "model": "<null>|<string>",
  "fromCache": "<boolean>"
}
```

## Engine cache

- **Path:** `data/cache/engine.json`
- **Purpose:** The matcher's verified answers per posting, keyed by the contract's cache key (ad fingerprint, profile
  version, prompt version). Written only by a judged run; every other scoring run re-applies them without a call, and
  Fit, gates and label are recomputed from them in code under the current constants.
- **Written by:** `match_engine/shadow.py` (from `run_scoring.py --judge`).

## Outreach contacts

- **Path:** `data/outreach/<jobId>/contacts.json`
- **Purpose:** Recruiter and hiring contacts found for one job, plus ready-made search links.
- **Written by:** Outreach module (`python/outreach_scraper`).

```json
{
  "jobId": "<string>",
  "discoveredAt": "<string>",
  "contacts": [
    {
      "name": "<string>",
      "title": "<string>",
      "company": "<string>",
      "linkedinUrl": "<string>",
      "source": "<string>",
      "roleQuery": "<string>"
    }
  ],
  "searchQueries": [
    {
      "label": "<string>",
      "url": "<string>",
      "type": "<string>"
    }
  ],
  "metadata": {
    "providers": [
      {
        "provider": "<string>",
        "recommendedTitles?": [
          "<string>"
        ],
        "note?": "<string>"
      }
    ],
    "ats": "<null>",
    "linkedinScrape": {
      "mode": "<string>",
      "queriesRun": "<number>",
      "contactsFound": "<number>"
    }
  }
}
```



## Tailored résumé (JSON Resume)

- **Path:** `data/resumes/<jobId>/<Name>_<Company>_<Role>_Resume.json`
- **Purpose:** Structured copy of one tailored résumé. The folder also holds `tailored_resume.md/.html`, the `.pdf` and `.docx` renders, `cover_letter.md`, the cover letter `.pdf` and, when AI-written, `ai_cover_letter.md`. The paths are recorded in the job's `tailoredAssets`.
- **Written by:** `python/resume_generator/run_tailor.py`.

```json
{
  "$schema": "<string>",
  "meta": {
    "version": "<string>",
    "lastModified": "<string>",
    "generatedBy": "<string>"
  },
  "basics": {
    "name": "<string>",
    "name_last": "<string>",
    "label": "<string>",
    "email": "<string>",
    "phone": "<string>",
    "url": "<string>",
    "summary": "<string>",
    "location": {
      "city": "<string>"
    }
  },
  "work": [
    {
      "name": "<string>",
      "position": "<string>",
      "summary": "<string>",
      "highlights": [
        "<string>"
      ]
    }
  ],
  "skills": [
    {
      "name": "<string>",
      "keywords": [
        "<string>"
      ]
    }
  ],
  "education": [
    {
      "institution": "<string>",
      "studyType": "<string>",
      "endDate": "<string>"
    }
  ],
  "languages": [
    {
      "language": "<string>",
      "fluency": "<string>"
    }
  ]
}
```



## Quality audits

- **Path:** `data/audits/*.json`
- **Purpose:** Reports from the quality-audit tool (`ats_score_report`, `cover_letter_quality_report`, `job_lead_quality_report`, `resume_quality_report`, `system_audit_report`). Each is `{ generatedAt, jobs: [per-job scores and issues], average... }`. Example (ATS report):
- **Written by:** `python/quality_audit`.

```json
{
  "generatedAt": "<string>",
  "jobs": [
    {
      "jobId": "<string>",
      "title": "<string>",
      "company": "<string>",
      "atsScore": "<number>",
      "atsLabel": "<string>",
      "atsBreakdown": {
        "contactInfo": "<number>",
        "structure": "<number>",
        "keywordMatch": "<number>",
        "readability": "<number>",
        "truthSafety": "<number>"
      },
      "atsIssues": [
        "<string>"
      ],
      "qualityStatus": "<string>"
    }
  ],
  "averageScore": "<null>"
}
```



## Application store

Server-side master of the application tracker (Phase 3, [TRACKER_PLAN.md](TRACKER_PLAN.md)). Written only by
`scripts/application-store.js`; git-ignored like all of `data/`. It holds recruiter contacts, so it never goes into
an AI payload. Nothing in discovery, scoring or the ledger reads or writes it.

| Path | Content |
|---|---|
| `data/applications/applications.json` | Every application: frozen snapshot, frozen attempt, append-only events |
| `data/applications/settings.json` | Tracker switches and the stage registry. Separate from the store, written under the same lock |
| `data/applications/files/<appId>/` | Frozen copies of what was sent: the CV, the cover letter, and every CV recorded later |
| `data/backups/applications-<YYYYMMDD-HHMMSS>[-n]/` | Copy of `applications.json` and `settings.json` made before a backup restore merges into them |

Both JSON files are written atomically (temp file, fsync, rename). An unreadable or malformed file is an error: every
write that needs it is refused (500) and the file is never touched. A missing `applications.json` is an empty store; a
missing `settings.json` is the defaults, and it is first written by the first change, never at startup.

### applications.json

```json
{
  "version": 1,
  "updatedAt": "<ISO timestamp>|null",
  "requests": { "<requestId>": "<appId>" },
  "applications": {
    "<appId>": {
      "id": "<appId>",
      "createdAt": "<ISO timestamp>",
      "origin": "manual|migration",
      "posting": {
        "jobId": "<string>|null", "postingKey": "job:<jobId> | url:<url> | tcl:<company>|<title>|<location>",
        "title": "<string>", "company": "<string>", "location": "<string>", "url": "<string>",
        "source": "<string>", "provider": "<string>", "datePosted": "<string>", "salary": "<string>",
        "employmentType": "<string>", "workMode": "<string>", "isRemote": "<boolean>|null",
        "description": "<string>", "descriptionMissing": "<boolean>",
        "capturedFrom": "scored_jobs|job_history|browser|manual", "capturedAt": "<ISO timestamp>",
        "capturedAfterApply": "<boolean>", "snapshotSha256": "<hex>"
      },
      "attempt": {
        "channel": "company_site|job_board|email|referral|recruiter_inbound|agency|other",
        "channelDetail": "<string>", "applicationUrl": "<string>", "appliedDate": "<YYYY-MM-DD>",
        "cv": { "kind": "library|tailored|external|unknown", "cvLibraryId": "<16 hex>|null",
                "label": "<string>", "fileName": "<string>|null", "sha256": "<hex>|null" },
        "coverLetter": { "fileName": "<string>|null", "sha256": "<hex>|null" },
        "previousApplicationId": "<appId>|null",
        "distinctReason": "reapply_after_outcome|different_channel|resubmitted_new_cv|null"
      },
      "legacy": "<null>|<the old applicationTracking object>",
      "events": [
        { "id": "<appId>:<seq>", "seq": 1, "type": "applied", "at": "<ISO timestamp>",
          "date": "<YYYY-MM-DD>", "source": "user|migration", "data": {} }
      ]
    }
  }
}
```

- `appId` is `app-<16 hex>` for an application created in the app and `mig-<jobId>` for a migrated one (`csv-` ids are
  for the CSV import, not built). `requests` keeps the last 200 create `requestId`s, so a retry returns the first result.
- `posting`, `attempt`, `id`, `createdAt`, `origin` and `legacy` are frozen at creation. `events` only grows at the
  end; `seq` runs 1..n with no gap and the first event is `applied`. `assertAppendOnly` checks all of this before
  every write.
- The current state is never stored. `foldApplication(app)` computes it from the events.

### Events

Every event: `{ id, seq, type, at, date, source, data }`. `at` is when it was recorded, `date` the day it happened (never
later than today). The client sends only `{ type, date?, data }`; the server assigns the rest.

| Type | `data` | Notes |
|---|---|---|
| `applied` | `{}` | Event 1 only, written by create |
| `stage_changed` | `{ stage }` | `stage` is `applied` or an active work stage key. Refused on a closed application. No label: the name shown is the registry's current label |
| `outcome_set` | `{ outcome }` | `offer_accepted`, `offer_declined`, `rejected`, `withdrawn`, `ghosted`, `position_closed`. Refused while an outcome is set |
| `outcome_cleared` | `{ reason }` | Reopens. Refused when no outcome is set, or when reopening would leave two competing open applications (409 with `conflictingId`) |
| `note_added` | `{ text }` | |
| `contact_added` | `{ contactId, role?, name?, email?, linkedin? }` | `contactId` (`c<n>`) is assigned by the server |
| `contact_updated` | `{ contactId, ...changed }` | |
| `message_sent`, `reply_received` | `{ via, contactId?, summary? }` | |
| `follow_up_set`, `follow_up_done` | `{ dueDate }` / `{ how? }` | |
| `nudge_snoozed` | `{ rule, until }` | |
| `assignment_due`, `offer_deadline` | `{ dueDate }` | |
| `event_voided` | `{ eventId, reason }` | The only correction. Cannot target `applied`, `event_voided`, `application_voided` or `application_restored` |
| `application_voided`, `application_restored` | `{ reason }` | A restore that brings the application back open is refused (409) when it would compete with another open one |
| `applied_date_corrected` | `{ appliedDate }` | `attempt.appliedDate` stays frozen; the fold reads the latest non-voided correction. Not in the future |
| `cv_recorded` | `{ kind, cvLibraryId, label, fileName, sha256, reason? }` | The first record when `attempt.cv.kind` is `unknown`, otherwise a correction (`reason` required). The server copies the file into `files/<appId>/` under a name nobody has used (`<name>-2.pdf`, ...), never over an existing one, and sets `fileName` and `sha256` itself. `attempt.cv` and every earlier copy stay as they are |

`note_added`, `nudge_snoozed`, `event_voided`, `application_voided`, `application_restored`, `applied_date_corrected`
and `cv_recorded` are not activity: they never reset a follow-up clock.

Two applications **compete** when both are open and not voided, share the `postingKey` and the `attempt.channel`, and
their CVs are not both known and different with one of them claiming `resubmitted_new_cv`. No two ever compete.
Restore (to open), reopen and a CV correction check it. Create applies the stricter rule of TRACKER_PLAN 6c: an open
application at the key refuses a new one unless a distinct reason is claimed and verified. Voided applications are
ignored by every check.

### Folded state

`foldApplication(app)` (`src/modules/applications/foldApplication.js`, pure, registry-free) returns:
`voided`; `stage` (the key of the latest non-voided `stage_changed`, else `applied`; kept under an outcome);
`stageSince` (the `date` of the latest `stage_changed`, else the folded applied date; not time in stage, a reopen
into the same stage does not move it); `stageHistory`
(`[{ stage, from, to }]`, one entry per spell in a stage, `to: null` while it runs, a reopen starts a new entry;
`daysInStage(entry, today)` gives the time in one entry, `daysInCurrentStage(folded, today)` the time in the newest); `outcome`, `outcomeDate`; `appliedDate` (latest non-voided
`applied_date_corrected`, else `attempt.appliedDate`); `cv` (latest non-voided `cv_recorded` without its `reason`,
else `attempt.cv`); `notes`, `contacts`, `followUpDate`, `assignmentDue`, `offerDeadline`, `snoozed`,
`lastActivityDate`, `eventCount`.

`boardColumn(folded, settings)` (`stageRegistry.js`) gives the column: `null` when voided; `rejected` or `ghosted`;
`closed` for the other outcomes (the Closed panel, grouped by outcome); the stage key; or `unfiled` for a retired
or unknown key. A closed application keeps the stage it reached.

### settings.json

```json
{
  "version": 1,
  "updatedAt": "<ISO timestamp>|null",
  "trackingEnabled": true,
  "followUpReminders": true,
  "stages": {
    "work": [
      { "key": "screen", "label": "Screen", "retired": false, "interview": false },
      { "key": "tech", "label": "Tech", "retired": false, "interview": true },
      { "key": "onsite", "label": "Onsite", "retired": false, "interview": true },
      { "key": "offer", "label": "Offer", "retired": false, "interview": false }
    ]
  },
  "changes": [
    { "at": "<ISO timestamp>", "action": "rename", "key": "tech", "old": "Tech", "new": "Technical" }
  ]
}
```

- **Fixed stages** are not stored: `applied` (first), and `rejected` and `ghosted` (closed columns). `unfiled` is a
  reserved column. None of the four can be a work key, be renamed, moved or retired. The defaults above apply when
  the file does not exist.
- **Keys** match `^[a-z0-9_]{1,40}$`, are slugged from the label once (`_`, suffixed `_2`, `_3` on a collision with
  any key, retired ones included) and never change. Events store only the key.
- **Labels** are unique, case-insensitively, among active stages; at most 10 active work stages. Renaming changes the
  label only, so no event is touched.
- **Operations** (`POST /api/applications/settings/stages`): `add`, `rename` (label and/or `interview`), `move`
  (`up`/`down` among active stages), `retire`, `unretire`. A stage is never deleted. `retire` is refused (409 with
  `count`) while an open, non-voided application's folded stage is the key, and for the last active stage. `unretire`
  puts the key back at the end with its last label. `add` with the label of a retired stage is refused (409 with
  `retiredKey`).
- **`interview`** marks the stages that count as interviews for the later reminder rules. It creates no interview and
  no calendar entry.
- **`trackingEnabled` false:** create, `/events`, `/move` and `settings/stages` answer 409 with `code:
  "tracking_disabled"`. `GET`, `POST /settings`, backup export and restore keep working. Nothing is deleted.
- **`changes`** keeps the last 50 settings changes (`switch`, `add`, `rename`, `interview`, `move`, `retire`,
  `unretire`, `restore`), so a rename can be traced. They are not events.
- **Backup restore:** with no current file the backup's file is written as it is. Otherwise the current switches,
  labels and order win, and a key found only in the backup is appended retired with its label. A stage is never
  dropped. Unreadable or invalid settings on either side are reported as a conflict and left alone.

### Routes

`GET /api/applications` (the store), `POST /api/applications` (create), `POST /api/applications/:id/events` (one
event), `POST /api/applications/:id/move` (`{ toStage, date? }`, the server writes `stage_changed`, or
`outcome_set` / `outcome_cleared`, in one save; moving to the current column writes nothing),
`GET /api/applications/:id/files/:name`, `GET` and `POST /api/applications/settings`,
`POST /api/applications/settings/stages`, and the migration: `POST /api/applications/migrate/preview` and
`POST /api/applications/migrate` (below). There is no PUT, PATCH or DELETE.

### migration.json

`data/applications/migration.json`, written by every `POST /api/applications/migrate`, including a run that creates
nothing: `{ "version": 1, "runs": [ { "ranAt", "previewSha", "counts", "backupPath", "unmappable": [ ... ], "legacyChanged": [ { "jobId", "appId", "fields" } ] } ] }`, the
last 50 runs. `counts` is `{ scanned, ignored, candidates, created, alreadyMigrated, alreadyTracked, unmappable }`,
with `candidates = created + alreadyMigrated + alreadyTracked + unmappable` and `scanned = ignored + candidates`.
The response also carries `legacyChanged`, the number of `alreadyMigrated` jobs whose old `applicationTracking` differs
from the migrated one (each such entry lists the fields and has a warning). It is not part of `counts`.
Body of both routes: `{ jobs: [ <browser job records> ] }`; the apply adds `"confirm": true` and the `previewSha`
the dry run returned (sha256 of the canonical JSON of `jobs`). The backup is
`data/backups/applications-<YYYYMMDD-HHMMSS>/` with `legacy-jobs.json` (the posted `jobs`, re-serialised) and, when a
store existed, its `applications.json`. Migrated records have `origin: "migration"`, id `mig-<jobId>`, the original
`applicationTracking` object in `legacy`, and events with `source: "migration"`.

## Source switches

`data/config/sources.json`, the owner's switches for opt-in job boards ([SOURCES_SPEC.md](SOURCES_SPEC.md), first slice). A
missing file, a missing entry or an unreadable file means off.

```json
{
  "version": 1,
  "updatedAt": "<ISO timestamp>|null",
  "boards": {
    "<source name>": {
      "active": "<boolean>",
      "consentAcceptedAt": "<ISO timestamp>|null",
      "disabledAt": "<ISO timestamp>|null",
      "migratedFrom": "<string>, only on an entry moved from the old browser checkbox",
      "history": [ { "at": "<ISO timestamp>", "event": "enabled|disabled", "consentAcceptedAt": "<ISO timestamp>, on enabled", "note": "<string>, on a migrated entry" } ]
    }
  },
  "migrations": { "job-dashboard-discovery-options": "<ISO timestamp>" }
}
```

A source counts as on only with `active: true` and a consent time. `history` keeps the last 50 events.

- **Writer:** only `python/job_discovery/source_settings.py`, under a lock, through `GET` / `PUT /api/sources` and `POST /api/sources/migrate-legacy` (`scripts/sources-handler.js` runs its CLI). `run_discovery.py` reads it. A file with a newer `version` or another shape is an error: it is left as it is and every opt-in source counts as off.
- **Modes:** the file is set to 600 on every write, also when it already existed. New folder 700. Lock file `.sources.json.lock`, 600.
- Not in the backup export.

## AI provider selection

`data/config/ai-settings.json`, the one selection the browser path and the Python pipeline both read. There is no default: a missing file means nothing is selected, and an unreadable or invalid file refuses every call. It never holds a key.

```json
{
  "provider": "claude-code|mock|ollama|openai|openrouter|claude|gemini|deepseek|groq",
  "model": "<string>",
  "temperature": "<number, 0 to 2>",
  "maxTokens": "<number, 1 to 200000>",
  "baseUrl": "<string>, empty except for ollama",
  "features": { "jobAnalysis": "<boolean>", "resumeEnhancement": "<boolean>", "coverLetter": "<boolean>", "interviewPrep": "<boolean>", "outreach": "<boolean>", "careerStrategy": "<boolean>", "skillGap": "<boolean>", "applicationStrategy": "<boolean>", "companyIntelligence": "<boolean>" }
}
```

- **Writer:** only `python/llm/ai_selection.py`, under the AI gate's lock, through `GET` / `PUT /api/ai/selection` (`scripts/ai-settings-handler.js`, then `ai_gate.py selection-get` / `selection-put`). Unknown keys are refused.
- **Modes:** a new file 600 (an existing file keeps its mode, atomic write). New folder 700.
- Not in the backup export.

## AI budget gate

`data/ai/`, the files of `python/llm/ai_gate.py`. It is the only writer; Node reaches it through its CLI (`scripts/ai-gate.js`), so there is one lock and one ledger.

| Path | Content | Modes |
|---|---|---|
| `data/ai/` | Folder | new 700 |
| `data/ai/settings.json` | Budget, limits, automation switch. Missing = budget 0, automation off | new 600, an existing file keeps its mode |
| `data/ai/pricing-overrides.json` | The owner's price edits, merged over `src/data/aiPricing.json` by provider and model | new 600, an existing file keeps its mode |
| `data/ai/usage-ledger.jsonl` | Append-only, one JSON object per line. No route writes or deletes a row | new 600 |
| `data/ai/.ledger.lock` | Lock for all of the above and for `data/config/ai-settings.json` | new 600 |
| `data/ai/findings/` | AI findings store (below) | below |

`settings.json` (`PUT /api/ai/settings`; raising what the gate allows needs `"confirm": true`):

```json
{
  "currency": "<string, three letters>",
  "dailyLimit": "<number>",
  "monthlyLimit": "<number>",
  "maxCallsDaily": "<number>|null",
  "maxCallsMonthly": "<number>|null",
  "estimatedOutputTokens": "<number>",
  "timezone": "<IANA name>",
  "automation": { "enabled": "<boolean>" },
  "claudeCodeSubscription": { "enabled": "<boolean>", "maxCallsDaily": "<number>", "features": [ "<feature name>" ] }
}
```

`pricing-overrides.json` (`PUT /api/ai/pricing`; the request replaces the whole list, at most 200 entries):

```json
{
  "entries": [
    { "provider": "<string>", "model": "<string>|*", "class": "free|local|paid|unknown", "inputPerMTok": "<number>|null", "outputPerMTok": "<number>|null", "source": "<string>|null", "checkedAt": "<YYYY-MM-DD>|null" }
  ]
}
```

`usage-ledger.jsonl` has two row types, read with `GET /api/ai/usage`. A call that goes ahead has a `call` row before it and a `result` row with the same `id` after it; a refusal or a findings hit has the `call` row only. Costs are estimates.

```json
{
  "v": 1, "type": "call", "id": "<string>", "ts": "<ISO timestamp>",
  "feature": "<string>", "trigger": "manual|automation", "provider": "<string>", "model": "<string>|null",
  "class": "free|local|paid|unknown|subscription", "jobId": "<string>|null", "cache": "miss|hit",
  "decision": "allowed|refused|cache-hit", "reason": "<string>|null", "skipped": "<number>, on a refusal found before a batch",
  "inputTokens": "<number>", "outputTokens": "<number>", "tokensAreEstimate": "<boolean>",
  "cost": "<number>|null", "currency": "<string>|null", "costIsEstimate": true, "priceKnown": "<boolean>, not on a findings hit"
}
```

```json
{
  "v": 1, "type": "result", "id": "<id of the call row>", "ts": "<ISO timestamp>", "ok": "<boolean>", "error": "<string>|null",
  "inputTokens": "<number>", "outputTokens": "<number>", "tokensAreEstimate": "<boolean>",
  "cost": "<number>|null", "currency": "<string>|null", "costIsEstimate": true,
  "attempts": "<number>, if given", "providerReportedCostUsd": "<number>, if given"
}
```

None of `data/ai/` is in the backup export.

### AI findings store

`data/ai/findings/<job|company>/<entityKey>.json`, stored model answers for `jobAnalysis` (entity `job`) and `companyIntelligence` (entity `company`). The entity key is the first 16 hex of a sha256, of the job id or of the normalized company name; the file name holds no title or company.

```json
{
  "version": 1,
  "entity": { "type": "job|company", "key": "<entityKey>" },
  "findings": [
    {
      "id": "<entityKey>:<seq>", "seq": "<number, 1..n>", "at": "<ISO timestamp>", "feature": "<string>",
      "provider": "<string>", "model": "<string>", "promptVersion": "<string>", "inputHash": "<sha256>",
      "cacheKey": "<model>|<promptVersion>|<inputHash>", "finding": "<the parsed answer>", "source": "model"
    }
  ]
}
```

- **Writer:** only the Node server (`scripts/ai-findings-store.js`, called from `run-ai.js`), not `ai_gate.py`. Append-only: a finding is never edited or removed, and a file that cannot be read is never overwritten. The prompt is not stored, and neither is an answer with credential-like text.
- **Modes:** every write is 600, also over an existing file; folders are forced to 700 (`chmod` when another mode is found).

## Secret store

`data/secrets/`, AI keys and the LinkedIn cookie. No route returns a value: `GET /api/secrets` gives set / not set, source, the last 4 characters and the base URL.

```json
{ "<openai|openrouter|claude|gemini>": { "key": "<string>", "baseUrl": "<string>, only if one was set", "setAt": "<ISO timestamp>" } }
```

`data/secrets/ai.json`, above. `data/secrets/linkedin.json`:

```json
{ "li_at": "<string>", "setAt": "<ISO timestamp>" }
```

- **Writer:** only `scripts/secret-store.js`, through `PUT` / `DELETE /api/secrets/ai/<provider>` and `/api/secrets/linkedin` (`scripts/secrets-handler.js`). Removing the last AI key, or the cookie, deletes the file. `python/llm/secret_store.py` reads `ai.json` read-only, and refuses the call if the file is not a private regular file or not valid JSON.
- **Modes:** every write is 600, also over an existing file; the folder is forced to 700 on every write.
- Never in a backup, export or restore (`scripts/secret-paths.js`); git-ignored like all of `data/`.

## Examples and fixtures (tracked)

- `data/examples/candidate-profile.example.json`, `candidate-intelligence.example.json`, `scored_jobs.example.json` - fictional data in the shapes above, used only in an explicit demo mode.
- `tests/fixtures/postings/<source>-<n>.json` - ten real public postings, posting fields only (see below).

Posting fixture shape:

```json
{
  "jobId": "<string>", "provider": "<string>", "source": "<string>", "title": "<string>",
  "company": "<string>", "location": "<string>", "description": "<string>", "jobUrl": "<string>",
  "datePosted": "<string>", "scrapedAt": "<string>", "salary": "<string>", "employmentType": "<string>", "isRemote": "<boolean>"
}
```

## Not stored by the app

- AI keys and the LinkedIn cookie are never in the browser: Secret store above, with `.env` as the fallback. Browser AI usage, chat and memory stay in the browser until step 5 (browser keys above).
- The `claude-config/` folder holds the Claude Code CLI login used for tailoring; git-ignored.
