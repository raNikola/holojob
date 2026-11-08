---
paths:
  - "src/modules/jobs/**"
  - "src/modules/applications/**"
  - "src/**/JobDetail*.jsx"
  - "src/**/ApplicationTrack*.jsx"
  - "src/App.jsx"
---

# Job Details page

The drawer (`JobDetailDrawer.jsx`) stays the quick view on the Jobs list, Board, Statistics and Outreach. Its "Open full details" button
goes to `#/jobs/<jobId>` (`JobDetailsPage.jsx`): the drawer body (`JobDetailBody.jsx`) in the main column and `ApplicationTrackerPanel` as a
sticky sidebar. There is no router: `modules/jobs/jobRoute.js` pushes the hash, `useJobRoute` (in `App.jsx`) reads it, so the hash wins over the saved
view on load and Back returns to the previous view. The page and the drawer read the stored record and write through the jobs store (`modules/jobs/jobsStore.js`): `patchJob(jobId, patch)`
reads the latest stored record at write time and applies only the given fields (`useJobPatcher` diffs what a component hands back against the copy it
rendered), so a stale copy cannot revert another view's change; `baseUpdatedAt` gives a `conflict` result instead of an overwrite, the shape for a
later server store. `useJobs` / `useStoredJob` re-render after any write, a `storage` event covers other tabs, and `useJobsSync` lets the Jobs,
Applications and Outreach screens take store writes in. **Still whole-object / whole-list:** those three screens save their whole list from memory
(`saveJobs(state)` effects), and their own handlers (`handleJobUpdated` for the table's `JobTailorActions`, `ContactDetailDrawer`, `FollowUpPanel`,
`RelatedContactsPanel` in the contact drawer, and `updateJobOutreach` / `updateJobStatus` on in-memory state) still merge whole objects. Step 2 moves them to the store.
Across tabs, `useBackgroundRefresh` (`App.jsx`) refetches the tracker cache and re-reads the job list when the tab becomes visible or focused and every 60 s while visible (`modules/applications/refreshPolicy.js`); an edited tracker field that changed elsewhere keeps the typed value and shows "Reload fields".
The drawer's tracking block is a read-only summary (`ApplicationTrackingSummary.jsx`, values from `modules/applications/trackingSummary.js`, the same application cache and `panelMode` as the page): stage badge, applied on, next follow-up, CV used, recruiter, history and note counts, empty fields as "Not recorded" / "Not scheduled". With no active application it offers "Mark Applied", which calls `markApplied` with `newApplicationDefaults` (today, the form's preselected CV, channel `company_site`; the full form starts from the same function) and has no separate-attempt choice, so a 409 points to Job Details. All tracking edits stay on the page. "Open full details" is disabled (tooltip "This posting is no longer in your jobs list") when the stored list lacks the job (`canOpenJobPage`). An unknown id shows "Job not found". Unsaved input: forms that call `useDraftDirty` (the tracker's three forms) make the button ask first
(`modules/jobs/draftGuard.js`); other drafts (AI tools, contacts) are not covered yet. Not built: more tabs, AI spent, "Is it real?".
