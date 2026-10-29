# Holojob - Data shapes (DS9)

Structure of every data file the app reads or writes. Only shapes: `<string>`, `<number>`, `<boolean>`, `<null>` and `<x>|<y>` for mixed values, `[...]` for lists, `<id>` for a map keyed by ids, a trailing `?` on a key where some records omit it. No value is copied from candidate or profile data. Generated from the files on DS9 on 2026-10-25, plus the code for data that lives only in the browser.

Where data lives: the **browser `localStorage` is the master** for the profile, intelligence, job list and (until the tracker migration) application tracking, whose server-side successor is the [Application store](#application-store); the files under `data/` are mirrors written by sync actions and read by the Python pipeline. Everything under `data/` except `data/examples/` is git-ignored and private.

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
- **Written by:** `run_scoring.py` (`--judge` adds `llmFit`; with `CAREER_OS_ENGINE_SHADOW` on, every job with an
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
      "origin": "manual",
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
      "legacy": "<null>",
      "events": [
        { "id": "<appId>:<seq>", "seq": 1, "type": "applied", "at": "<ISO timestamp>",
          "date": "<YYYY-MM-DD>", "source": "user", "data": {} }
      ]
    }
  }
}
```

- `appId` is `app-<16 hex>` for an application created in the app. (`mig-` and `csv-` ids come with the migration and
  the CSV import, later steps.) `requests` keeps the last 200 create `requestId`s, so a retry returns the first result.
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
nothing: `{ "version": 1, "runs": [ { "ranAt", "previewSha", "counts", "backupPath", "unmappable": [ ... ] } ] }`, the
last 50 runs. `counts` is `{ scanned, ignored, candidates, created, alreadyMigrated, alreadyTracked, unmappable }`,
with `candidates = created + alreadyMigrated + alreadyTracked + unmappable` and `scanned = ignored + candidates`.
Body of both routes: `{ jobs: [ <browser job records> ] }`; the apply adds `"confirm": true` and the `previewSha`
the dry run returned (sha256 of the canonical JSON of `jobs`). The backup is
`data/backups/applications-<YYYYMMDD-HHMMSS>/` with `legacy-jobs.json` (the posted `jobs`, re-serialised) and, when a
store existed, its `applications.json`. Migrated records have `origin: "migration"`, id `mig-<jobId>`, the original
`applicationTracking` object in `legacy`, and events with `source: "migration"`.

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
