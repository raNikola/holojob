---
paths:
  - "src/**"
---

# Frontend rules

- The browser's `localStorage` is the master for profile, intelligence, job list and tracking. `data/` files are mirrors written on sync and read by Python; a disk-only fix is overwritten at the next sync. Fix profile data in the profile form.
- Missing profile, intelligence or scored-jobs files are an empty state. Never fill them from `data/examples/` outside the explicit demo mode (`src/modules/demo/`).
- No default country, market or role anywhere in the UI; search country comes from the profile or intelligence.
- Scoring weights default from `src/data/scoringWeights.json` only; saved weights win, and every regenerate goes through `regenerateIntelligence()`.
- Geography and work-authorization data are shared with Python (`src/data/geography.json`); keep both sides in step.
- Judged runs, CV analysis and the Add job form's AI extraction (`/api/jobs/ad/ai-extract`) need their confirm dialog; never call those routes without `"confirm": true`. The extraction's request is the token and field names only.
- Code and comments in English. Run `npm run lint` and `npm run test:js` after changes.

Data shapes: `docs/redesign/data-shapes.md`. Architecture: `docs/ARCHITECTURE.md`.
