# Holojob - Data shapes (DS9)

Structure of every data file the app reads or writes. Only shapes: `<string>`, `<number>`, `<boolean>`, `<null>` and `<x>|<y>` for mixed values, `[...]` for lists, `<id>` for a map keyed by ids, a trailing `?` on a key where some records omit it. No value is copied from candidate or profile data. Generated from the files on DS9 on 2026-10-25, plus the code for data that lives only in the browser.

Where data lives: the **browser `localStorage` is the master** for the profile, intelligence, job list and application tracking; the files under `data/` are mirrors written by sync actions and read by the Python pipeline. Everything under `data/` except `data/examples/` is git-ignored and private.

Browser keys: `job-dashboard-candidate-profile`, `job-dashboard-candidate-intelligence`, `job-dashboard-discovered-jobs`, `job-dashboard-pipeline-state`, `job-dashboard-outreach-index`, `job-dashboard-jobs-tab`, `job-dashboard-sidebar-collapsed`, `job-dashboard-ai-settings`, `job-dashboard-ai-cache`, `job-dashboard-ai-chat`, `job-dashboard-ai-memory`, `job-dashboard-ai-usage`.

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
    "positioningStatement": "<string>"
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
    "relocation": "<string>"
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
      ]
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
        "answer": "<string>"
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
    "completedAt": "<string>"
  }
}
```

Fields that exist in the browser profile and appear in the disk mirror only after the next sync (this mirror pre-dates them):

```json
{
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
        "analyzedAt": "<string>",
        "applied?": ["<string>"],
        "lastApply?": { "at": "<string>", "count": "<number>", "state": "<string>", "error?": "<string>" }
      }
    }
  ],
  "resume.parsedData.experienceDetail?": [{ "title": "<string>", "company": "<string>", "start": "<string>", "end": "<string>", "bullets": ["<string>"] }],
  "resume.parsedData.competencyGroups?": [{ "label": "<string>", "items": ["<string>"] }],
  "resume.parsedData.toolGroups?": [{ "label": "<string>", "items": ["<string>"] }]
}
```

`profile.resume` is always a copy of the default `cvLibrary` entry. List-type questionnaire answers are stored one entry per line with a trailing newline.


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
      "ashby": "<number>"
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
      "keptFullerDescription": "<number>"
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
      ]
    }
  ]
}
```



## Scored jobs

- **Path:** `data/jobs/scored_jobs.json`
- **Purpose:** Everything in discovered jobs plus scores, label, priority, reasons, work-authorization status, salary parse. What the UI job list loads (copy in browser key `job-dashboard-discovered-jobs`).
- **Written by:** `run_scoring.py` (`--judge` adds `llmFit`; with `HOLOJOB_ENGINE_SHADOW` on, every job with an
  engine output gets `engineShadow` and `meta.engineShadow` counts them, see "Engine shadow output").

```json
{
  "meta": {
    "generatedAt": "<string>",
    "sourceRunId": "<string>",
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
      "limit": "<null>",
      "threshold": "<number>"
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
        "reason": "<string>"
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
      "workMode?": "<string>",
      "expiresAt?": "<string>",
      "category?": "<string>",
      "standardizedPosition?": "<string>",
      "tags?": [
        "<string>"
      ]
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
        ]
      },
      "seeded?": "<boolean>"
    }
  }
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
      "ashby": "<number>"
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
      "keptFullerDescription": "<number>"
    }
  },
  "enrichment": {
    "enrichedShare": "<number>",
    "extracted": "<number>",
    "cached": "<number>",
    "failed": "<number>"
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

- **On:** each scored job as `engineShadow`, when `HOLOJOB_ENGINE_SHADOW` is on (`match_engine/shadow.py`).
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

- AI provider keys live only in `.env` / container environment. Browser AI settings (provider, model, usage, chat, memory) are in `localStorage` only.
- The `claude-config/` folder holds the Claude Code CLI login used for tailoring; git-ignored.
