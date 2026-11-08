---
paths:
  - "python/job_discovery/**"
  - "python/job_scoring/**"
  - "python/profile_import/**"
  - "scripts/run-discovery.js"
  - "scripts/run-scoring.js"
  - "scripts/run-pipeline.js"
  - "scripts/save-profile.js"
  - "scripts/save-intelligence.js"
  - "src/modules/profile/**"
  - "src/modules/intelligence/**"
  - "src/modules/sources/**"
---

# No hard-coded markets, no borrowed data

- The country to search comes from `--country`, else the candidate intelligence; with
  neither, discovery stops. No provider, script or UI has a default country.
- Target roles drive search terms only; seniority is read from the current role.
- Europe and the US are search locations only when relocation is `abroad` or `anywhere`;
  a job needing a visa the candidate lacks is capped by scoring, not removed.
- A missing profile, intelligence or scored-jobs file is an empty state; never fill it
  from `data/examples/` outside an explicit demo mode.
- The server is the master for profile, intelligence, jobs and applications (DECISIONS.md, 2026-10-29); the browser
  keeps UI state only (`docs/redesign/BROWSER_STORAGE_POLICY.md`). **Until migration step 5 ships**, the profile,
  intelligence and jobs still live in `localStorage` and are mirrored to `data/` on sync, so fix profile data in the
  profile form, not in the disk file. After it, the browser copy is removed per key, only after a preview, an owner
  confirmation and a verified server write. No secret (AI key, `li_at`) is stored in or sent from the browser once
  steps 2-3 ship; the server's `data/secrets/` (600 / 700) is the only holder. **Steps 2 (AI keys) and 3 (`li_at`) shipped.**
