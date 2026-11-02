---
paths:
  - "src/**"
---

# Frontend rules

- The server as master is decided (DECISIONS.md principle 15) but NOT built. Until step 5 (`docs/redesign/STEP5_SERVER_MASTER_PLAN.md`) ships, the profile, intelligence and job list live in the browser's `localStorage`. `data/profile/` and `data/intelligence/` are mirrors written on sync and read by Python, so a disk-only fix is overwritten at the next sync; fix profile data in the profile form. The pipeline files (`discovered_jobs.json`, `scored_jobs.json`, `job_history.json`) are written by the Python pipeline, not by sync. Applications (tracker) are already on the server: `data/applications/` is the master and the browser keeps a read cache.
- Missing profile, intelligence or scored-jobs files are an empty state. Never fill them from `data/examples/` outside the explicit demo mode (`src/modules/demo/`).
- No default country, market or role anywhere in the UI; search country comes from the profile or intelligence.
- Scoring weights default from `src/data/scoringWeights.json` only; saved weights win, and every regenerate goes through `regenerateIntelligence()`.
- Geography and work-authorization data are shared with Python (`src/data/geography.json`); keep both sides in step.
- Judged runs, CV analysis and the Add job form's AI extraction (`/api/jobs/ad/ai-extract`) need their confirm dialog; never call those routes without `"confirm": true`. The extraction's request is the token and field names only.
- Code and comments in English. After changes, run lint and JS tests in a throwaway node container (`node` and `npm` are not on the host's PATH; always `--security-opt label=disable`, never `:Z`). In fish or bash:

      podman run --rm --security-opt label=disable -v /srv/career-os:/work -w /work docker.io/library/node:20-bookworm npm run lint
      podman run --rm --security-opt label=disable -v /srv/career-os:/work -w /work docker.io/library/node:20-bookworm npm run test:js

Data shapes: `docs/redesign/data-shapes.md`. Architecture: `docs/ARCHITECTURE.md`.
