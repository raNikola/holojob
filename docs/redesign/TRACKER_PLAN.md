# Holojob - Application tracker plan (Phase 3, A2)

Status: APPROVED and PARTLY BUILT. The plan was revised 2026-10-29 for ApplyPack v1 alignment and approved by the owner
the same day: decision 13 and O1-O4 decided, O5-O6 deferred (section 9). Decision 5 (fixed stage enum) is superseded there.

- **Built:** S1 store and stages, S2 migration (2.4), the first slice of S3 (2.5), and the board and Settings columns,
  which are the first parts of S4 and S5 (2.6).
- **Not built:** posting snapshot view, Closed panel, "Show voided", removal of the legacy `applicationTracking` field
  (S4), follow-up nudges and the reminders switch's UI (S5), CSV import (S6).

Everything else below is the plan as approved; where it differs from an "As built" note, the note describes the code. The
current status is kept in [../ROADMAP.md](../ROADMAP.md) Phase 3.

Inputs: [DECISIONS.md](DECISIONS.md) principles 13 and 15, [PHASE0_AUDIT.md](PHASE0_AUDIT.md) module F and question 5,
[data-shapes.md](data-shapes.md), [../ROADMAP.md](../ROADMAP.md) Phase 3, the current code listed in section 0, the
owner's requirements document "Application Tracker v1, ApplyPack functional alignment" (2026-10-29), and the ApplyPack
code at commit `5b1edfe9` (github.com/applypack/applypack, MIT), read in sections 0a and 0b.

**Labels used in the revision.** Every new or changed rule carries one of:
- **VERIFIED (ApplyPack):** read in ApplyPack's code at `5b1edfe9`, with the file and line.
- **CAREER OS REQUIREMENT:** stated by the owner's requirements document or an earlier owner decision, with no
  ApplyPack counterpart, or deliberately different from it.
- **PROPOSAL:** this plan's design choice, made where the requirements are silent. The owner approved the revision on
  2026-10-29; the choices behind O1-O4 are decided (section 9). The rest stay open to change in code review.

Text without a label is unchanged from the 2026-10-28 plan.

**A1** (the interim fix from PHASE0_AUDIT question 5): stop `mergeStatusOnImport` from dropping the tracking of an
applied job that is no longer in the incoming discovery list. A2 subsumes it: step S2 (section 7) moves tracking out of
the job record, so there is nothing left on the job for an import to drop. A1 is not built separately.

## 0. Where tracking lives today

- **Record:** `job.applicationTracking` on each job in the browser key `job-dashboard-discovered-jobs`
  (`src/modules/jobs/applicationTracking.js`). It has ten fields: `applied`, `appliedDate`, `applicationUrl`,
  `recruiterName`, `recruiterEmail`, `recruiterLinkedIn`, `notes`, `followUpDate`, `interviewStage` (one value from
  `INTERVIEW_STAGES`) and `lastUpdated`. Each update overwrites the previous one, so there is no history.
- **Job status:** saving with "Applied" ticked also sets `job.status = 'applied_manually'` (`ApplicationTrackerPanel.jsx`).
- **Loss path 1, import:** `mergeStatusOnImport` (`jobStorage.js`) maps over the *incoming* jobs only. An applied job
  missing from a new discovery or scoring import loses its tracking, status, tailored assets, AI insights and outreach.
  Six callers go through `importJobsFromFile`: `JobDiscoveryScreen`, `JobImportPanel`, `PipelineOrchestrator`,
  `SettingsHome`, `autoLoadJobs`, `usePipelineAutoRefresh`.
- **Loss path 2, storage:** `saveJobs` drops `description` when the list overflows localStorage, and failing that keeps
  the list in memory only. So tracking can vanish on reload without any error shown.
- **Loss path 3, ledger:** `job_history.json` drops a job 90 days after it closes, and `discovered_jobs.json` keeps
  closed jobs for 14 days. Neither holds tracking today, but neither can be the anchor of an application.
- **Writers:** `ApplicationHome.jsx`, `JobDiscoveryScreen.jsx`, `OutreachDashboard.jsx` (all through
  `updateApplicationTracking`).
- **Readers:** `followUps.js` (`isFollowUpDue`), `jobStats.js`, `JobTable.jsx`, `FollowUpPanel.jsx`,
  `contactRanking.js` (`appliedDate`), `aiContextBuilder.js` (sends recruiter name, e-mail and LinkedIn into AI
  context), `python/quality_audit/outreach_auditor.py`. The auditor reads `followUpDate` from jobs in
  `scored_jobs.json` (`run_audit.py --jobs`), but that file holds no tracking, so the check never fires today.
  The one exception is a backup export, which writes the browser job list into that file.
- **Tests:** `tests/js/jobStorage.test.js` uses `applicationTracking: { stage: 'applied' }`, a key the current code
  never writes. So stored records may carry keys outside the ten, and the migration must not assume the shape.
- **UI today:** Job Details is the drawer `src/components/jobs/JobDetailDrawer.jsx`, which mounts
  `ApplicationTrackerPanel`. The Applications page is `src/components/applications/ApplicationHome.jsx`, a sortable
  table, not a board. They are separate React trees over the browser job list. Settings is one screen,
  `src/components/settings/SettingsHome.jsx`, with no Applications or Notifications section. Career OS has no
  notification channel (no e-mail, Telegram or digest sender) and no drag-and-drop library.

## 0a. ApplyPack v1 reference (VERIFIED at `5b1edfe9`)

Paths are relative to the ApplyPack repository.

| Topic | What the code does | Where |
|---|---|---|
| Record | Tracking is columns on `Job`: `appliedAt`, `recruiterContact` (one free-text field), `pipelineStage` (string), `applicationNotes` (one text box, overwritten). One application per job; there is no attempt concept and no duplicate rule beyond "Mark applied" being hidden once `status = APPLIED` | `prisma/schema.prisma:324-340`, `src/web/pages/job-detail.tsx:348` |
| Inbox status vs stage | `Job.status` (NEW / ALERTED / SAVED / DISMISSED / APPLIED) is the inbox state and is orthogonal to `pipelineStage` | `prisma/schema.prisma:324-327`, SPEC.md "Application tracking" |
| Stage ledger | `JobStageEvent(jobId, fromStage, toStage, occurredOn DATE, recordedAt, source ui\|backfill\|correction)`, append-only, written in the same transaction as the stage update by one builder. A resubmit that does not change the stage writes nothing | `prisma/schema.prisma:1023`, `src/web/stage-events.ts`, ADR 0024 |
| Stage write sites | Three: Mark applied seeds `applied` (`POST /jobs/:id/status`), the Job Details form (`POST /jobs/:id/application`, any stage, or none), and the board's drag or quick-move (`POST /jobs/:id/stage`, stage only) | `src/web/routes/jobs.tsx:630-697`, `src/web/routes/applications.tsx:178-215, 217-306` |
| Mark applied | Sets `status = APPLIED`. With tracking on and no stage yet, sets `pipelineStage = 'applied'` and writes the ledger row; sets `appliedAt` to now when empty. Records the résumé picked | `src/web/routes/jobs.tsx:654-697` |
| Configurable columns | `AppSettings.pipelineStages` JSON `[{key,label}]`, null = defaults `screen`, `tech`, `onsite`, `offer`. `applied` is the fixed first column; `rejected` and `ghosted` are the fixed Closed panel. Keys match `^[a-z0-9-]+$`, max 40 characters, slugged from the label at creation, immutable; rename changes the label only. Max 10 work columns. Reserved keys: `applied`, `rejected`, `ghosted`, `unfiled`. Add, rename, move up/down, remove | `src/web/stage-config.ts:41-140`, `prisma/schema.prisma:595`, ADR 0025 |
| Invalid stored config | `parseStageConfig` silently falls back to the defaults on invalid JSON | `src/web/stage-config.ts:61-71` |
| Column removal | Refused while `job.count({ pipelineStage: key }) > 0`, counted and written inside `withGlobalWriteLock`; message "move the jobs out first". The last work column cannot be removed (an empty list would read as "defaults") | `src/web/routes/settings.tsx:1019-1048`, `src/web/stage-config.ts:113` |
| Stranded stage | A card whose key no column covers (race during removal) shows under a reserved **Unfiled** column, folded into the Closed panel. Job Details keeps the removed key selectable ("removed column"); a *change* must land on a configured key | `src/web/routes/applications.tsx:43-90, 265-273`, `src/web/stage-config.ts:156`, `src/web/pages/job-detail.tsx:426-431` |
| Board | Server-rendered page. Native HTML5 drag (`board.mjs`) plus a quick-move form on every card for keyboard, mobile and no-JS. A drop moves the card optimistically, posts, then reloads the page on success or puts the card back and shows an error on failure | `src/web/public/board.mjs:100-120`, `src/web/pages/applications.tsx` |
| Moving out of Closed | A move from `rejected`/`ghosted` back into a work column is an ordinary stage move; the quick-move preselect revives a closed card into the first work column | `src/web/stage-config.ts:176` |
| Time in stage | The card line counts from the latest non-backfill ledger event into the current stage, else from `appliedAt`; a non-terminal stage idle for 14 days reads as stale | `src/web/stage-time.ts` |
| Removing an application | No void. The Job Details stage select has "Not in funnel", which sets `pipelineStage = null` and writes a ledger row with `toStage = null`, `source = correction` | `src/web/pages/job-detail.tsx:418`, `src/web/stage-events.ts` |
| Reopen | A Job Details button that posts `status = NEW` to `/jobs/:id/status`. It changes the inbox status only and never touches `pipelineStage` or the ledger. It is not an application operation | `src/web/pages/job-detail.tsx:185-189`, `src/web/routes/jobs.tsx:630-697` |
| Applied date | Editable on Job Details (backdatable). An edit with the stage unchanged writes a `correction` ledger row with the new day | `src/web/stage-events.ts` (`appliedDateCorrection`), `src/web/routes/applications.tsx:277-279` |
| Applied résumé | `appliedResumeId`, `appliedResumeVersion` and `appliedResumeText` (the text, because "Upload a new version" rewrites the same row). No file bytes, except an application pack, whose `.docx`/PDF bytes are kept on `ApplicationPack` once marked sent. Preselect: the résumé of the comparison on screen, else the search-linked résumé, else the best skill overlap. A card dragged into Applied records no résumé, and Job Details then asks for one, never preselecting a guess | `src/web/applied-resume.ts`, `src/resume/pick.ts:50-56`, `src/web/routes/jobs.tsx:515-537`, `prisma/schema.prisma` `ApplicationPack` |
| Résumé snapshot can change | After Reopen the "Mark applied" button reappears, and pressing it again rewrites all three résumé columns (the APPLIED branch sets them unconditionally). The Job Details form can also swap the recorded résumé | `src/web/routes/jobs.tsx:654-689`, `src/web/routes/applications.tsx:250-256` |
| Tracking switch | `AppSettings.applicationTrackingEnabled`, default true, on Settings → Applications. Off: the board shows "Application tracking is off" with a link to Settings, the Job Details tracking card is hidden, the stage routes redirect without writing, the stale digest is skipped. Nothing is deleted. Mark applied still sets the inbox status but seeds no stage | `prisma/schema.prisma:522`, `src/web/routes/settings.tsx:975`, `src/web/pages/applications.tsx:197-207`, `src/web/routes/applications.tsx:182, 221` |
| Follow-up reminder | One daily "stale applications" message: stage `applied`, `appliedAt` older than 14 days, no `recruiterContact`. Toggle `staleApplicationsDigestEnabled` (default true) on Settings → Notifications, sent through the configured channels, skipped when tracking is off. It never changes a stage | `src/jobs/stale-applications-job.ts:10-72`, `src/web/routes/settings.tsx:1167` |
| Re-apply window | `AppSettings.reapplyDays`: off by default, or 30 / 60 / 90 / 180. In the fetch tick, before any AI call, a *new* posting whose employer key has a job with `appliedAt` inside the window is turned away: no row, no classification, no alert, counted in the funnel. Any `appliedAt` counts, whatever the stage. Exempt: a watched company set to "every posting", and a posting the user added by hand. Stored postings are not touched. A separate company *mute* (ADR 0056) hides a company outright | `src/jobs/employer-store.ts:26-45`, `src/employer.ts:172-209`, `src/jobs/process-jobs.ts:262-280`, `src/web/routes/settings.tsx:1152` |
| Employer key | NFKD fold, accents and case dropped, `&` read as "and", all punctuation dropped, a leading "the" dropped, then trailing legal forms from a closed list (Inc, LLC, GmbH, d.o.o., Sp. z o.o. ...). Never fuzzy: "Acme Labs" stays apart from "Acme" | `src/employer.ts:21-64` |
| Board export | `/applications/export.csv` and `.md`: every job holding a stage, in column order | `src/web/routes/applications.tsx:157-171` |

## 0b. Functional comparison with this plan (section 11 of the requirements)

| # | Requirement | 2026-10-28 plan | ApplyPack | Revised plan |
|---|---|---|---|---|
| 1 | Application exists apart from discovery, survives expiry, refresh, filtering, re-import, removal | Supported (1.1, 6a, 6b) | No: tracking is on `Job`; cleanup skips jobs with a stage, a deleted job takes its ledger with it | Kept. CAREER OS REQUIREMENT |
| 2 | Immutable posting snapshot | Supported (1.2) | No snapshot | Kept |
| 3 | Frozen CV actually sent | Supported, file copy + sha256 (decision 7) | Text snapshot that a re-mark or the form can overwrite | Kept; stricter than ApplyPack, which is deliberate |
| 4 | Several attempts per posting, accidental duplicate refused | Supported (6c) | One record per job | Kept. CAREER OS REQUIREMENT |
| 5 | Void and restore | Supported (6e) | "Not in funnel" clears the stage | Kept; void is the Career OS counterpart of "Not in funnel" |
| 6 | Append-only history | Supported (1.4, 6b) | Ledger of stage moves only | Kept; covers more event types |
| 7 | Mark Applied puts the card on the board at once | Partly: create route exists, no board | Verified | Board in S4 reads the store directly (3.2) |
| 8 | Kanban with drag and drop, persisted, failed save reverts | Missing | Verified | Added (3.2, S4) |
| 9 | Job Details and Kanban show one state | Not addressed: separate React trees | Free in ApplyPack (server pages, reload after each move) | Added: one client module both read (3.2, 6g) |
| 10 | Configurable columns with stable ids, rename, reorder, add, remove with safeguards, counts | **Conflicts:** decision 5 fixed enum + free label | Verified | Decision 5 superseded; stage registry (1.6), retire instead of delete (PROPOSAL) |
| 11 | Fixed Applied, Rejected, Ghosted | Applied is a stage; rejected and ghosted are outcomes | Verified (stages) | Applied is a fixed stage; Rejected and Ghosted are fixed Closed columns that write outcomes (1.6) |
| 12 | Tracking on/off switch, nothing deleted | Missing | Verified | Added (1.7, 6h) |
| 13 | Re-apply window per company | Missing | Verified (fetch tick, before AI) | **Deferred, not in v1** (O5, section 5a) |
| 14 | Configurable follow-up reminders, never infer an outcome | Nudges N0-N5, constants (decision 4), ghosted only suggested (decision 3) | One 14-day digest with a switch | Kept, plus a reminders switch (1.7). No conflict |
| 15 | Edit "Applied on" later | Missing: `attempt.appliedDate` frozen, `applied` not voidable | Verified, with a correction row | PROPOSAL: `applied_date_corrected` event (1.4) |
| 16 | Record the CV later when none was picked | Missing | Verified (asks on Job Details) | PROPOSAL: `cv_recorded` event, once (1.4) |
| 17 | Reopen | Not named | Inbox status → NEW only | Four operations kept apart (3.2, "Reopen") |
| 18 | Time in current stage on the card | Missing | Verified | Added to the fold (`stageSince`) |
| 19 | CSV import, migration with dry run, idempotent | Supported (2, 4, 6d) | Not applicable | Kept; stage mapping updated (1.4, 4) |
| 20 | Preparing an application pack never marks applied | Not stated | ApplyPack's pack is frozen only when the user says it was sent | CAREER OS REQUIREMENT, stated in 8 |

Data shape, API, UI, sequence and migration changes follow in 1.4-1.7, 3, 7 and 2.

## 1. Data shape

### 1.1 Files

| Path | Content |
|---|---|
| `data/applications/applications.json` | The store: every application with its frozen snapshot, attempt and events |
| `data/applications/files/<appId>/` | Frozen copies of what was sent: the CV (and cover letter), named as sent |
| `data/backups/applications-<YYYYMMDD-HHMMSS>/` | Backups written before a migration, CSV import or restore (same naming as the existing `data/backups/competency-*`) |

- **Master:** the server file, behind one module `scripts/application-store.js` (decision 1). The browser
  keeps a read cache only.
- **Writes are atomic:** write `applications.json.tmp`, fsync, rename. This differs from `saveProfileToDisk`, which
  writes in place, and an append-only log must not be left half-written.
- **Server-side by design:** principle 15 is met because the browser never owns the data.
- **Privacy:** the store is git-ignored, like all of `data/`. It holds third-party personal data (recruiter
  contacts) and never goes into an AI payload (section 3.4).
- **Tracker settings** (PROPOSAL): `data/applications/settings.json`, the stage registry and switches of section 1.7,
  behind the same module. It sits under `data/applications/`, not `data/config/`, for three reasons:
  - **Backup:** `data/config/` is not in `backup-handler.js` `DATA_DIRS`, so it would not be exported.
  - **Validation:** the registry must be read under the same lock as every append that validates a stage.
  - **Isolation:** the 6a static test already confines `data/applications` to one module.

### 1.2 Schema

```
{
  "version": 1,
  "updatedAt": "<ISO timestamp>",              // bumped only when content changes
  "requests": { "<requestId>": "<appId>" },    // last 200 create requests, for retry safety (6c)
  "applications": {
    "<appId>": {
      "id": "<appId>",
      "createdAt": "<ISO timestamp>",
      "origin": "manual" | "migration" | "csv",
      "posting": {                             // FROZEN at creation, never rewritten
        "jobId": "<string>|null",              // weak link to discovery, may point to nothing
        "postingKey": "<string>",              // section 6c
        "title": "<string>", "company": "<string>", "location": "<string>",
        "url": "<string>", "source": "<string>", "provider": "<string>",
        "datePosted": "<string>", "salary": "<string>", "employmentType": "<string>",
        "workMode": "<string>", "isRemote": "<boolean>|null",
        "description": "<string>",
        "descriptionMissing": "<boolean>",    // true when no full description was available
        "capturedFrom": "scored_jobs" | "job_history" | "browser" | "csv" | "manual",
        "capturedAt": "<ISO timestamp>",
        "capturedAfterApply": "<boolean>",    // true for migration/CSV: taken later than the application, the ad may have changed
        "snapshotSha256": "<hex>"             // over the canonical JSON of the fields above
      },
      "attempt": {                             // FROZEN at creation
        "channel": "<channel enum>",
        "channelDetail": "<string>",           // e.g. board name, referrer's role
        "applicationUrl": "<string>",          // where the form was, may differ from posting.url
        "appliedDate": "<YYYY-MM-DD>|null",    // null only for migrated/CSV records without a date
        "cv": {
          "kind": "library" | "tailored" | "external" | "unknown",
          "cvLibraryId": "<16 hex>|null",
          "label": "<string>",
          "fileName": "<string>|null",         // file under files/<appId>/
          "sha256": "<hex>|null"
        },
        "coverLetter": { "fileName": "<string>|null", "sha256": "<hex>|null" },
        "previousApplicationId": "<appId>|null",
        "distinctReason": "<distinct reason enum>|null"   // section 6c
      },
      "legacy": { ... } | null,                // migration only: the original applicationTracking object, verbatim
      "events": [ <event>, ... ]               // APPEND-ONLY
    }
  }
}
```

The fold orders events by `seq` (the order they were recorded), not by `date`. `date` may be earlier than `at`, for a
backfilled event, but never later than `at`'s day. A planned date belongs in a `*_due` or `follow_up_set` event,
not in `date`.

The current state (stage, outcome, notes, contacts, follow-up date, nudges) is not stored. It is computed by one pure
function, `foldApplication(app, today)`. So there are no derived fields that could drift from the history.

### 1.3 Ids

- **`appId`:** set by the server. It takes one of three forms:
  - **Created by the user:** `app-<16 hex random>`.
  - **Migrated:** `mig-<jobId>`. It is deterministic, which is what makes the migration idempotent.
  - **Imported from CSV:** `csv-<first 16 hex of sha256(CSV row key)>`. Also deterministic, so re-importing the same
    CSV adds nothing.

  The ids are checked against `^(app|mig|csv)-[0-9a-f]{16}$` before any path is built from them, as `cv-store.js`
  checks `isCvId`.
- **Event `id`:** `<appId>:<seq>`, where `seq` starts at 1 and has no gaps. The server assigns it; the client never sends one.

### 1.4 Events

Every event: `{ "id", "seq", "type", "at": "<ISO timestamp, when recorded>", "date": "<YYYY-MM-DD, when it happened>",
"source": "user" | "migration" | "csv" | "system", "data": { ... } }`.

| Type | `data` | Notes |
|---|---|---|
| `applied` | `{}` | Always event 1, `date` = `attempt.appliedDate` |
| `stage_changed` | `{ stage, legacyStage? }` | `stage` is a key of the stage registry (1.6) that is active when the event is appended: `applied` or a work stage, never `rejected`/`ghosted`. Revised: the free `label` is dropped (PROPOSAL); the name shown is the registry's current label for the key |
| `outcome_set` | `{ outcome, legacyStage? }` | Ends the application; nudges stop. Revised (PROPOSAL): refused (400) while an outcome is already set, and `stage_changed` is refused (400) on a closed application until it is reopened, so a change between closed columns is always `outcome_cleared` then `outcome_set` (the move route, 3.1, writes both) |
| `outcome_cleared` | `{ reason }` | Refused (400) when no outcome is set. Reopens, e.g. a "ghosted" company replies. Revised (PROPOSAL): checked like a restore (6c). Refused with 409 and the conflicting id when reopening would leave two open attempts that 6c would not allow, e.g. a rejected application whose `reapply_after_outcome` attempt is open |
| `note_added` | `{ text }` | Notes are a list, never one overwritten text box |
| `contact_added` | `{ contactId, role, name, email, linkedin }` | `contactId` = `c<n>` within the application |
| `contact_updated` | `{ contactId, ...changed fields }` | |
| `message_sent` | `{ via: email\|linkedin\|phone\|other, contactId?, summary? }` | Resets the follow-up clock |
| `reply_received` | `{ via, contactId?, summary? }` | Resets the follow-up clock |
| `follow_up_set` | `{ dueDate }` | Explicit reminder, overrides the computed nudge (section 5) |
| `follow_up_done` | `{ how? }` | |
| `nudge_snoozed` | `{ rule, until }` | |
| `assignment_due` | `{ dueDate }` | Take-home task deadline |
| `offer_deadline` | `{ dueDate }` | |
| `event_voided` | `{ eventId, reason }` | The only way to correct a mistake; the voided event stays in the file |
| `application_voided` | `{ reason }` | Created by mistake; kept on disk with its events, excluded from lists, nudges and statistics (decision 2, 6e). Refused when the application is already voided |
| `application_restored` | `{ reason }` | Undoes the latest `application_voided` (decision 11, 6e). Refused when the application is not voided, or when restoring it would break a 6c duplicate rule |
| `applied_date_corrected` | `{ appliedDate }` | Decided (O4). The counterpart of ApplyPack's backdatable "Applied on" (0a). `attempt.appliedDate` stays frozen; the fold reads the latest non-voided correction. `appliedDate` follows the `attempt.appliedDate` rules (valid, not in the future). Nudges and CSV rule 3 read the folded date |
| `cv_recorded` | `{ kind, cvLibraryId, label, fileName, sha256, reason? }` | Decided (O4). Records the CV sent, as a new event: either the first record when none was made at creation (`attempt.cv.kind === 'unknown'`: a migrated or CSV record, or a create without a pick), or a correction of a recorded one (`reason` required then). The server copies the file into `files/<appId>/` as on create, under a new name when the name is taken (`<name>-2.pdf`), never over an existing file. `attempt.cv` and every earlier copy stay as they are; the fold's `cv` is the latest non-voided `cv_recorded`, else `attempt.cv`, and the history shows every record. ApplyPack can overwrite its résumé snapshot (0a); this cannot |

Void and restore events are never activity and never reset the follow-up clock (section 5); neither does
`applied_date_corrected` or `cv_recorded`.

**Enums** (code constants in one module, `src/modules/applications/applicationEnums.js`):

- **Stage:** no longer an enum. Superseded by the stage registry (1.6, decision 13). The module keeps only the fixed
  keys `applied`, `rejected`, `ghosted`, the reserved `unfiled`, and the default work stages used when no registry
  exists.
- **Outcome:** `offer_accepted`, `offer_declined`, `rejected`, `withdrawn`, `ghosted`, `position_closed`. No outcome
  means the application is open. `rejected` records the stage reached, which comes from the fold, so it is not
  duplicated in the outcome. The outcome enum stays fixed and separate from the stage registry (requirements 4.3).
- **Channel:** `company_site` (ATS or careers form), `job_board` (`channelDetail` = board, e.g. LinkedIn Easy Apply,
  Infostud), `email`, `referral`, `recruiter_inbound`, `agency`, `other`.
- **Distinct reason:** `reapply_after_outcome`, `different_channel`, `resubmitted_new_cv`.

Legacy `INTERVIEW_STAGES` mapping, revised to the default work stages (PROPOSAL):

| Legacy value | New event | Data |
|---|---|---|
| Applied | none | Covered by `applied` |
| HR Screen | `stage_changed` | `screen` |
| Technical Round 1 / 2 | `stage_changed` | `tech` |
| Assignment | `stage_changed` | `tech` (the defaults have no assignment column; a take-home deadline is `assignment_due`) |
| Hiring Manager | `stage_changed` | `onsite` |
| Final Round | `stage_changed` | `onsite` |
| Offer | `stage_changed` | `offer` (outcome stays open until accepted or declined) |
| Rejected | `outcome_set` | `rejected` |
| Withdrawn | `outcome_set` | `withdrawn` |

Every mapped event keeps `legacyStage` with the original string, so "Technical Round 2" stays readable in the
history although it shares the `tech` column with round 1.
- **Edited registry:** the mapping targets the default keys. If the owner has retired one of them before migrating,
  the event still records that key, which is history. The application then shows under Unfiled (1.6) until it is
  moved, and the dry run warns "target stage not on the board".
- **Unknown legacy value:** no stage event. The value stays in `legacy` and `legacyStage` is not invented; the dry run
  lists it as a warning. (The old rule wrote it into the dropped `label`.)

### 1.5 Worked example

A posting found by discovery: applied on 3 Nov, HR screen on 10 Nov, the recruiter added, then a rejection. Fictional data.

```json
{
  "version": 1,
  "updatedAt": "2026-11-21T09:12:00.000Z",
  "applications": {
    "app-3f9c0a1b2c3d4e5f": {
      "id": "app-3f9c0a1b2c3d4e5f",
      "createdAt": "2026-11-03T10:02:11.000Z",
      "origin": "manual",
      "posting": {
        "jobId": "a1b2c3d4e5f60718",
        "postingKey": "job:a1b2c3d4e5f60718",
        "title": "Senior Product Manager, Payments",
        "company": "Acme Payments",
        "location": "Remote (EU)",
        "url": "https://boards.greenhouse.io/acme/jobs/123",
        "source": "greenhouse", "provider": "greenhouse",
        "datePosted": "2026-10-30", "salary": "", "employmentType": "full-time",
        "workMode": "remote", "isRemote": true,
        "description": "We are looking for ... (full ad text)",
        "descriptionMissing": false,
        "capturedFrom": "scored_jobs",
        "capturedAt": "2026-11-03T10:02:11.000Z",
        "capturedAfterApply": false,
        "snapshotSha256": "9e1f...c4"
      },
      "attempt": {
        "channel": "company_site", "channelDetail": "Greenhouse form",
        "applicationUrl": "https://boards.greenhouse.io/acme/jobs/123#app",
        "appliedDate": "2026-11-03",
        "cv": { "kind": "tailored", "cvLibraryId": null, "label": "Tailored for Acme",
                "fileName": "Acme_Resume.pdf", "sha256": "51ab...0e" },
        "coverLetter": { "fileName": null, "sha256": null },
        "previousApplicationId": null, "distinctReason": null
      },
      "legacy": null,
      "events": [
        { "id": "app-3f9c0a1b2c3d4e5f:1", "seq": 1, "type": "applied", "at": "2026-11-03T10:02:11.000Z",
          "date": "2026-11-03", "source": "user", "data": {} },
        { "id": "app-3f9c0a1b2c3d4e5f:2", "seq": 2, "type": "stage_changed", "at": "2026-11-10T16:40:00.000Z",
          "date": "2026-11-10", "source": "user", "data": { "stage": "screen" } },
        { "id": "app-3f9c0a1b2c3d4e5f:3", "seq": 3, "type": "contact_added", "at": "2026-11-10T16:41:00.000Z",
          "date": "2026-11-10", "source": "user",
          "data": { "contactId": "c1", "role": "recruiter", "name": "Ana Example",
                    "email": "ana@example.com", "linkedin": "" } },
        { "id": "app-3f9c0a1b2c3d4e5f:4", "seq": 4, "type": "outcome_set", "at": "2026-11-21T09:12:00.000Z",
          "date": "2026-11-20", "source": "user", "data": { "outcome": "rejected" } }
      ]
    }
  }
}
```

`foldApplication` gives:
- stage `screen` (the stage reached), outcome `rejected`, one contact, no nudge;
- `stageSince` 2026-11-10, and `appliedDate` 2026-11-03.

The board shows the card in the Closed panel under Rejected, with "reached Screen". If the owner later renames
`screen` to "Recruiter call", the card and the history read "Recruiter call", and no event changes. The file
`data/applications/files/app-3f9c0a1b2c3d4e5f/Acme_Resume.pdf` is the CV exactly as sent. If Acme's ad is deleted from
Greenhouse, discovery drops it, and the ledger prunes it 90 days later, nothing above changes.

### 1.6 Stage registry (decision 13, superseding decision 5)

**Shape**, in `data/applications/settings.json` (PROPOSAL for the location; the shape follows ApplyPack's
`pipelineStages` with the additions marked):

```
"stages": {
  "work": [                                          // ordered; the board's columns between Applied and Closed
    { "key": "screen", "label": "Screen", "retired": false, "interview": false },
    { "key": "tech",   "label": "Tech",   "retired": false, "interview": true  },
    { "key": "onsite", "label": "Onsite", "retired": false, "interview": true  },
    { "key": "offer",  "label": "Offer",  "retired": false, "interview": false }
  ]
}
```

Rules, each with its source label:

| Rule | Label |
|---|---|
| **Fixed stages.** `applied` is the fixed first column; `rejected` and `ghosted` are the fixed closed columns. None of them is stored in `work`, renamed or removed | VERIFIED (ApplyPack), CAREER OS REQUIREMENT (requirements 3.1, 4.2) |
| **Defaults.** `screen`, `tech`, `onsite`, `offer`, used when `settings.json` does not exist | VERIFIED (ApplyPack); matches requirements 3.1 |
| **Keys.** A key is created once from the label and never changes. Rename changes `label` only, so every event that names the key stays valid. Labels are unique (case-insensitive) among active stages; at most 10 active work stages | VERIFIED (ApplyPack) |
| **Key format.** `^[a-z0-9_]{1,40}$`, slugged from the label with `_`, suffixed `_2`, `_3` ... on collision. ApplyPack uses `-`; `_` matches the store's other enums and the requirements example `technical_interview`. Keys of retired stages are never reused | PROPOSAL |
| **Reserved keys.** `applied`, `rejected`, `ghosted`, `unfiled` | VERIFIED (ApplyPack) |
| **Reorder.** Move up or down one place; at an edge it changes nothing. Order is display order and the order used by nudge N5 ("a later stage") | VERIFIED (ApplyPack) for the move; PROPOSAL for N5 |
| **Remove = retire.** A work stage is never deleted from the registry. Removing sets `retired: true`, which hides it from the board columns and the pickers but keeps its label for history. Refused (409, with the count) while any **open, non-voided** application's folded stage is that key, and refused for the last active work stage. A retired stage can be restored. Details in 1.6.1 | Decided (O1), adapted from VERIFIED (ApplyPack) |
| **Refusals** (as built). `add` of a label that belongs to a retired stage → 409 with `{ retiredKey }`, and the owner restores that key instead. The `interview` flag of an existing stage is set through `rename` (`{ op: 'rename', key, interview }`, with or without a new `label`); `add` also accepts it for a new stage | Built (S1) |
| **`interview` flag.** Marks the work stages that count as interviews for nudges N3 and N4 and for the "Interviewing" count. Defaults: `tech` and `onsite` true. Not in ApplyPack. The flag only drives those deterministic rules. It never creates an interview record, a calendar entry or a Google Calendar event. Real interviews, with date, time and an optional Google Calendar event, belong to the future Interviews / Calendar modules and are scheduled there, separately from stage moves | Decided (O2) |
| **Invalid file.** An unreadable or malformed `settings.json` is an error: every write that needs the registry is refused, nothing is written over it. This is the store's rule (1.1), and it deliberately differs from ApplyPack, whose `parseStageConfig` silently falls back to the defaults, which could put cards in the wrong columns without notice | PROPOSAL |

**Where the stage and the column come from.**
- **The fold** stays pure and registry-free. It returns the key of the latest non-voided `stage_changed`, else
  `applied`, plus `stageSince`: that event's `date`, else the folded `appliedDate`.
- **`stageSince` and `daysInStage`, exactly** (2026-10-29):
  - `stageSince` is the `date` of the latest non-voided `stage_changed`, else the folded `appliedDate`. It is **not**
    "time in stage". A reopen into the same stage (`outcome_cleared`, no `stage_changed`) does not move it, so after
    a reopen it can be earlier than the day the application came back.
  - `stageHistory` holds one `{ stage, from, to }` entry per spell: `applied` from the folded `appliedDate`, each
    `stage_changed` and each `outcome_cleared` start a new one, and `to` is the day the spell ended (a stage change or
    an outcome), `null` while it runs.
  - `daysInStage(entry, today)` is whole days from `entry.from` to `entry.to`, or to `today` while `to` is `null`.
    The time in the current stage is `daysInCurrentStage(folded, today)`, which reads the **newest** `stageHistory`
    entry. For a closed application that entry ends on the closing day, so the count stops there.
  - A move to another column straight after a reopen leaves a 0-day entry of the old stage in the history.
  - Display code (the board card, "stale" after 14 days) uses `daysInCurrentStage`, never `stageSince`.
- **The column** comes from one pure function, `boardColumn(folded, registry)`:
  - voided → no column (only the "Show voided" view);
  - outcome `rejected` or `ghosted` → that board column;
  - any other outcome (withdrawn, offer accepted, offer declined, position closed) → the Closed panel only, grouped by
    outcome (O3);
  - open, on `applied` or an active work stage → that column;
  - open, on a retired or unknown key → `unfiled`.
- **Unfiled** is a reserved column, shown only when it holds a card, as ApplyPack does. A card lands there through:
  - the race of 1.6.1;
  - a backup restored from another registry;
  - a migration mapped to a retired key.

  Moving the card out works like any other move.
- **Labels:** `labelFor(key, registry)` resolves fixed, active and retired keys, and falls back to the raw key.

#### 1.6.1 Removing a column with applications in it (requirements 4.4)

ApplyPack refuses the removal while any job holds the key (0a). A literal port fails here. In ApplyPack a rejected
job's stage *becomes* `rejected`, so the count only sees open jobs. Career OS keeps the stage reached under an outcome
(1.4), so closed and voided applications reference work keys forever, and a literal count would make every column
that was ever used undeletable.

The adaptation (decided, O1):
- **Count:** only open, non-voided applications whose folded stage is the key. While any exist, the removal is
  refused with the count, and the UI says "Move the N applications out first", as ApplyPack does.
- **Retire, never delete:** closed and voided applications keep naming the key, and keep its label, because the
  registry entry stays with `retired: true`.
- **Atomic:** the count and the write run under the store lock, the same lock every move takes. Unlike ApplyPack,
  whose drag takes no lock, a card cannot land in a column while it is being retired. Unfiled stays as the fallback
  for the other two paths above.
- **Restore a retired stage:** Settings lists retired stages with Restore (`unretire`), which puts the key back at
  the end of the order with its last label. Adding a column whose label equals a retired stage's label offers that
  restore instead of minting a new key, so "remove, then add again" does not split one stage's history into two keys.

### 1.7 Tracker settings

`data/applications/settings.json`, a separate file from `applications.json` (the switches are VERIFIED in ApplyPack
unless marked):

```
{
  "version": 1,
  "updatedAt": "<ISO timestamp>",
  "trackingEnabled": true,             // ApplyPack applicationTrackingEnabled, default true
  "followUpReminders": true,           // ApplyPack staleApplicationsDigestEnabled; here it switches nudges (section 5)
  "stages": { "work": [ ... ] }        // 1.6
}
```

- **Missing file:** the defaults above. The file is written on the first settings change, never at startup.
- **Writes:** atomic like the store. Settings changes are not events. They are not part of the append-only log,
  because they change no application's history. The file keeps a small `changes` list (last 50: date, action, key,
  old and new label) so a rename can be traced (PROPOSAL).
- **Tracking off** (CAREER OS REQUIREMENT 4.1, behaviour from ApplyPack 0a):
  - **Hidden:** the Applications page shows "Application tracking is off" with a link to Settings. The Job Details
    tracking section and the Mark Applied action are hidden. Nudges are not computed.
  - **Refused:** create, `/events`, `/move` and `settings/stages` return 409 `tracking_disabled`. The settings route
    itself stays open, or tracking could never be switched back on.
  - **Still working:** `GET`, backup export and restore, and the migration and CSV previews and applies. Those
    protect data and must not depend on the switch.
  - **Nothing is deleted.** Turning tracking back on shows everything as it was.

### 1.8 What the S1 code needed (historical; S1 is committed as `5e549a4`)

S1 work exists uncommitted in the working tree (section 7, S1). Against this revision:
- **Stays:**
  - `scripts/application-store.js`: load, atomic save, lock, the append-only guard, ids, `requestId`, the duplicate
    rules, frozen files, the routes, the backup merge;
  - `foldApplication` / `isActive`;
  - the backup and isolation tests.
- **Must change:**
  - `STAGES` and `ENUM_FIELDS.stage` validate against the registry;
  - the `label` on `stage_changed` goes;
  - `outcome_set` is refused over an outcome;
  - the fold gains `stageSince`, `appliedDate` and `cv` from the new events;
  - `settings.json` with its read, atomic write and backup merge (3.1);
  - the move and stage-edit routes;
  - the tracking switch on the write routes;
  - the tests that use `screening`, `interview` or `final` move to the registry fixture;
  - (2026-10-29) the restore check, and the new reopen check, use the competing-attempt rule of 1.9. Today
    `findConflict` blocks a restore whenever the restored record's stored `distinctReason` is null, on any channel,
    and also checks a restored record that is closed. 1.9 checks only an application that becomes open, against
    competitors on the same channel;
  - (2026-10-29) `cv_recorded` corrections are allowed, under a new file name (O4);
  - the archiver import fix in `backup-handler.js` is split out into its own commit (S1 list, section 7).

None of it is edited by this revision.

### 1.9 Closed applications and the way back (rules, 2026-10-29)

**States.** An application is in exactly one of three states. The board shows each as follows.

| State | Means | Board |
|---|---|---|
| **Open** | not voided, no outcome | Applied, a work stage column, or Unfiled |
| **Closed** | not voided, an outcome is set | Rejected or Ghosted column; the four other outcomes only in the Closed panel (O3) |
| **Voided** | `application_voided` is the latest of void/restore, whatever the outcome | Nowhere; only "Show voided" |

Closing never forgets the stage reached: the fold keeps it under the outcome.

**Competing attempts.** Two applications **compete** when all of these hold:
- both are open and not voided;
- they have the same `postingKey`;
- they have the same `attempt.channel`;
- and it is *not* the case that their CV sha256 values are both known and different while one of them carries
  `distinctReason: resubmitted_new_cv`.

**The one invariant:** no two applications ever compete. Every operation that makes an application open checks it
first. When it fails, the operation is refused with 409 and the id of the latest competitor, and nothing is written.

**The four ways back, never merged:**

| Operation | Applies to | Same `appId`? | Events | Check |
|---|---|---|---|---|
| **Move** | an open application | yes | `stage_changed` | none: nothing new becomes open |
| **Reopen** | a closed application | yes | `outcome_cleared`, plus `stage_changed` when the target column differs from the stage reached (one `/move`, 3.1) | competing-attempt check |
| **Restore** | a voided application | yes | `application_restored` | if it comes back *open*: the competing-attempt check. If it comes back *closed*: none (it stays closed; reopening it later is checked) |
| **New attempt** | any posting, typically after a closed one | no: a new `app-` id | `applied`, with `previousApplicationId` and `distinctReason` | 6c create rules: with an open application at the key, a reason must be claimed and verified; with none open, `reapply_after_outcome` is set automatically |

**Moves between closed columns** (Rejected ↔ Ghosted) are `outcome_cleared` then `outcome_set` in one save. The
application never becomes open, so there is no check. `outcome_set` is refused while an outcome is set (1.4). The
four Closed-panel outcomes change only from Job Details, by the same two events.

**Examples** (posting P, channel `company_site` unless said otherwise):
1. **Reopen:** A was rejected. The owner drags A from Rejected to Tech. A gets `outcome_cleared` and
   `stage_changed tech`, and is open again with its full history. 200.
2. **Reopen refused:** A was rejected; then B was created for P (`reapply_after_outcome`, still open). Dragging A to
   Tech competes with B: 409 naming B, A stays in Rejected. The owner closes or voids B first, or adds the news to B
   instead.
3. **Reopen next to another channel:** A (`company_site`) was rejected; B (`referral`) is open. Reopening A is
   allowed: different channels do not compete. Both are open, as 6c rule 2 allows.
4. **Restore refused:** A was voided while open; then B was created for P. Restoring A competes with B: 409 naming
   B, A stays voided.
5. **Restore of a closed one:** A was rejected, then voided by mistake; B is open. Restoring A is allowed, and A
   returns to the Rejected column. Example 2 applies if the owner then tries to reopen it.
6. **Ghosted company replies:** A is in Ghosted, no other attempt. Dragging A to Screen reopens it (example 1). It is
   not a restore and not a new attempt.
7. **New attempt:** A was rejected. Mark Applied on P creates B with `previousApplicationId = A` and
   `reapply_after_outcome`. A stays in Rejected; both count as applications.
8. **Accidental duplicate:** A is open. Mark Applied on P again with the same channel and no reason: 409 naming A.
   The dialog offers "add an event to A".

## 2. Migration from `applicationTracking`, and what happens to `mergeStatusOnImport`

### 2.1 Where it runs

The source exists only in the browser (`job-dashboard-discovered-jobs`). The `data/jobs/*.json` files have no
`applicationTracking`, as checked on 2026-10-28. The migration runs in five steps:

1. **Browser:** collects every job that is a candidate (rule in 2.2) and posts their raw records, unchanged, to the
   server.
2. **Server:** `planMigration(legacyJobs, store, serverJobs, ledger)` is a pure function. It returns the plan: one
   entry per candidate with its action and mapping, plus the counts.
3. **Dry run (`POST /api/applications/migrate/preview`):** returns the plan and writes nothing. The Settings screen
   shows it. **It is required, even when the browser holds zero tracked records** (decision 8). The response
   carries `previewSha`, the sha256 of the payload it planned.
4. **Apply (`POST /api/applications/migrate` with `"confirm": true` and `previewSha`):** it is refused with 409
   unless `previewSha` matches the sha256 of the payload sent now. So there is no apply without a dry run of the
   same input. It runs in this order and stops at the first failure.
   1. Writes the backup `data/backups/applications-<ts>/`. This holds `legacy-jobs.json` (the raw payload, byte for
      byte as received) and a copy of `applications.json` if one exists.
   2. Applies the plan in memory.
   3. Runs the verification (section 6d).
   4. Writes the store atomically.

   If the backup write fails, or the verification fails, nothing is written.
5. **Afterwards:** the server writes `data/applications/migration.json`, holding the date, the counts and the
   backup path. The browser keeps the legacy field until step S4 (section 7), so the old data stays as a second copy
   until the owner has checked the result.

### 2.2 Mapping

**Which jobs are candidates:** any job with `status === 'applied_manually'`, or with an `applicationTracking` that
has any non-default value. So a job with `applied: false` but notes or a recruiter is migrated too. It becomes an
application with `appliedDate: null` and a dry-run warning, "tracked but not marked applied". Nothing a user typed is
dropped.

| Legacy | New |
|---|---|
| `applied`, `status: applied_manually` | Decides that the record is migrated; `applied` event |
| `appliedDate` | `attempt.appliedDate` and the `date` of the `applied` event (empty → `null`, dry-run warning) |
| `applicationUrl` | `attempt.applicationUrl` |
| `recruiterName`, `recruiterEmail`, `recruiterLinkedIn` | One `contact_added` (`role: recruiter`) when any of the three is set |
| `notes` | One `note_added` when not empty |
| `followUpDate` | `follow_up_set` when set |
| `interviewStage` | Per the mapping table in 1.4, with `legacyStage` |
| `lastUpdated` | The `at` of every migration event (or `appliedDate`, else the epoch), so a re-run produces the same bytes |
| any other key (e.g. `stage`) | Kept only in `legacy`; listed in the dry run as "unmapped keys" |
| the whole object | `legacy`, verbatim |

Other fields on migrated records:
- **Channel and CV:** `channel: other` and `cv.kind: unknown`, because the old record never held either.
- **Snapshot:** taken from the server's `scored_jobs.json` by `jobId`; else from the ledger entry
  `job_history.json` `.jobs[<jobId>].job`; else from the browser record. The browser record may be a slim one with
  no description, so in that case the record gets `descriptionMissing: true` and a dry-run warning.
- **The snapshot is taken at migration time, not apply time.** No snapshot was kept when the owner applied, so the
  ad may have changed since. The record gets `capturedAfterApply: true`, and the UI labels the snapshot "captured
  on <date>, after applying". From then on it is frozen like any other.
- **Already tracked in the store:** this rule is narrow on purpose, so it never merges two real attempts. A legacy
  record is **skipped: already tracked** only when both hold:
  - the legacy record is open (its `interviewStage` is not `Rejected` or `Withdrawn`);
  - a non-voided, open application that is not a migrated one already exists for the same `postingKey`.

  That case can only be one attempt recorded twice: the legacy channel is unknown, so 6c rule 1 would refuse it
  anyway. The legacy object stays in the backup, and the dry run lists it.

  A legacy record with a terminal stage is always migrated, as a separate earlier attempt, even if an `app-`
  application for the same posting exists. The `app-` record is frozen, so the two are not linked.
- **One per job is exact:** the legacy shape holds one tracking object per job, so `mig-<jobId>` (one per job) loses
  no attempt.

### 2.3 What happens to `mergeStatusOnImport`

- **S2:** unchanged. The legacy field is still carried as a fallback copy.
- **S4** (unchanged slice number; S4 is now "Kanban and legacy removal", section 7): it stops carrying `applicationTracking`. It still preserves `status`, `tailoredAssets`, `aiInsights` and
  `outreach` for jobs still in the list. Those fields have the same loss path, but they are outside A2 (decision 6).
- **`applied_manually`:** removed from `JOB_STATUSES` in S4 (decision 10). "Applied" on a job row becomes derived:
  at least one non-voided application exists with `posting.jobId === job.jobId`, or with the same `postingKey`.
  The legacy status value is read once by the migration and then ignored.
- **Several attempts on one job:** the derivation returns all of them, never only the first. The job row shows the
  latest non-voided attempt (highest `createdAt`) and an "N attempts" count when N > 1. Stats count attempts, not
  postings, so a re-application after a rejection counts as two applications with two outcomes.
- **Job records:** `applicationTracking` is deleted from them in S4. This happens only after `migration.json`
  exists and a re-run of the dry run reports `toCreate: 0`.

### 2.4 As built in S2 (2026-10-29)

The migration core is built as 2.1 to 2.2 describe it: `planMigration`, `verifyMigration`,
`POST /api/applications/migrate/preview` and `/migrate` in `scripts/application-store.js`, the mapping in
`src/modules/applications/legacyTracking.js`, and a Settings panel (`ApplicationMigrationPanel`) with a dry run and a
confirm button. Where the build differs from, or narrows, the text above:
- **Unmappable is a fifth bucket.** `candidates = created + alreadyMigrated + alreadyTracked + unmappable`. A candidate
  is unmappable when its `jobId` is not 16 hex characters, appears twice in the payload, no source has a title and a
  company, or `applicationTracking` is not an object. The run goes on with the others; the cases are listed in the
  dry run and in `migration.json`. The S4 removal of the legacy field must wait until `unmappable` is 0.
- **Bad dates do not make a record unmappable.** An `appliedDate` that is not a date (or an ISO timestamp, whose
  date part is used) leaves `attempt.appliedDate` empty; a bad `followUpDate` writes no `follow_up_set`. Both stay
  in `legacy` and are warned about.
- **Candidate rule:** `lastUpdated` does not count as a non-default value, so a record that was opened and saved
  empty is ignored.
- **Event dates:** `date` of every event but `applied` is the Belgrade day of `lastUpdated`, else the applied date.
- **`previewSha`** is the sha256 of the canonical JSON of `jobs`, not of the whole body. `legacy-jobs.json` is
  `jobs` re-serialised, so it is equal as JSON, not as bytes, to the request body (which also carries `confirm`).
- **Verification covers the records one run creates**, not every `mig-` record, because an older one may have gained
  user events since. Records from earlier runs are checked by the append-only guard instead.
- **`migration.json`** keeps a list of runs, not one entry, so a re-run does not erase the first run's counts.
- **Tracking switch:** the migration is not refused while tracking is off (1.7 lists only create, `/events`, `/move`
  and `settings/stages`).
- **`mergeStatusOnImport` is unchanged in S2**, as 2.3 says. The legacy field stays a second copy until S4.

**The panel and its writers, as built (S2 second half, 2026-10-29).** The tracker panel and the three screens that wrote
the legacy field now work through the application store:
- **`ApplicationTrackerPanel`** reads and writes only through `applicationsClient.js` (the cache, `useApplications()`)
  and `trackerController.js` (the decisions, testable without a browser). Nothing writes `job.applicationTracking`
  any more; `updateApplicationTracking` is deleted and `updateJobRecord` ignores an `applicationTracking` in its patch,
  so a row carrying tracking derived from the store cannot be saved into the job.
- **Which mode the panel is in** (`panelMode`): `loading` or `error` show no form (an empty cache would make every
  old job look new); `migrate-first` for a job with old tracking and no application at all, with a "Run the migration
  first (Settings)" block and no way to create (`markApplied` refuses before any request); `new`; `tracked`. The
  test for "old tracking" is `legacyKind` in `legacyTracking.js`, the same function `planMigration` uses, so the panel
  never blocks a job the migration ignores and never lets through a job the migration would create a record for.
  A job whose old tracking cannot be mapped (a `jobId` that is not 16 hex) stays blocked and says why.
- **Writes:** create (`POST /api/applications`, with a `requestId` made when the form opens), stage through `/move`,
  the applied date as `applied_date_corrected`, the follow-up date as `follow_up_set` or `follow_up_done`, the recruiter
  as `contact_added` / `contact_updated`, a note as `note_added`, void and restore as their events. A save sends only
  the difference from the application as the server last returned it, so a save that failed half way and is repeated
  does not repeat what landed. Notes are an "add a note" box, never a text area that is posted again.
- **Several attempts:** the panel lists every attempt of the job and shows the latest one that is not voided. A
  second application is refused (409) while one is open, unless the user says it is a separate attempt through
  another channel; after a close, "Apply to this job again" creates a `reapply_after_outcome` attempt.
- **Readers:** `trackingView.js` derives the old `applicationTracking` shape from the latest non-voided application
  (`trackingFromApplication`). `ApplicationHome`, `JobDiscoveryScreen` and `OutreachDashboard` use it for display
  and statistics only (`overlayTracking`); `state.jobs` is what gets saved and never holds the derived value. The
  closed outcomes show as `Rejected`, `Withdrawn`, `Ghosted`, `Position closed`, `Offer` and `Offer declined`
  (`TERMINAL_STAGES` gained the last three). `buildApplicationContext` also reads the overlay.
- **Dry run:** an `alreadyMigrated` job whose old object now differs from the one that was migrated gets
  `legacyChanged` (the fields) and a warning; the response has a top-level `legacyChanged` count and each
  `migration.json` run lists them. `lastUpdated` alone is not a change, and a job that arrives without the object
  (an import dropped it) is not a change. `counts` is unchanged.
- **Privacy:** `ai-redact.js` now also removes every recruiter name, e-mail and LinkedIn link recorded in the store
  (`knownContactIdentity`, voided applications and earlier values included), so a contact entered after the
  migration is still a known identifier. It fails closed when the store is unreadable.

Deviations and limits of this part:
- **`channel` and `applicationUrl` are read-only after creation.** They are part of the frozen attempt and the plan
  has no correction event for them. The panel shows them; an edit needs a new event type, which is a plan change.
- **The other outcomes** (withdrawn, position closed, offer accepted, offer declined) can be set only on an open
  application, with one `outcome_set`. Changing between them, or from them to Rejected or Ghosted, is a reopen
  (`/move`). `/move` does not take them, and two separate POSTs would run the reopen check for an application that
  never reopens.
- **No attempt switcher beyond a select, no CV picker, no timeline, no snapshot view:** those are S3.
- **`status: applied_manually`** is still set on the job when an application is created, because several readers use
  it until S4.
- **Statistics still count jobs, not attempts**, through the overlay, until S4.
- **An application whose job has left the browser list** is safe in the store but appears on no screen until the S4 board.
- **Still reading the old field:** `contactRanking.js` and the single-job `safeTracking` in `aiContextBuilder.js`.
  The first only ranks contacts; the second sends nothing identifying (the AI redaction step runs after it).
- **Nothing here was run in a browser**: the panel, the screens and the Settings panel are covered by lint, the
  build and tests of the logic they call.

The legacy field is deleted from the job records in S4, after `migration.json` shows `unmappable: 0` and the dry run
shows `toCreate: 0` and `legacyChanged: 0`.

### 2.5 As built in S3, first slice (2026-10-29)

Job Details gained the CV and the history; the rest of S3 is still open.
- **CV picker** (`CvPicker`, `cvOptions`, `defaultCvOption` in `trackerController.js`): tailored for this job (bare name of
  `job.tailoredAssets.resumePdf`), each library CV that has a stored file (16-hex id and `filePath`), "a CV outside the
  app" (kind `external`, typed name) and "Not recorded yet" (`unknown`). Preselect: tailored, else the default library CV,
  else not recorded. A library CV with no stored file is not offered, because the store freezes a copy and refuses what
  it cannot read.
- **CV used on a tracked application:** a link to the frozen copy (`GET /api/applications/:id/files/:name`, which already
  served only names recorded on the application; no server change), "Record the CV" when none, "Correct the CV" with a
  reason otherwise (`cv_recorded`), earlier copies listed. The correction picker has no "tailored" option yet.
- **History:** a read-only list of every event, newest first (`ApplicationTimeline`).
- **Not in this slice:** snapshot view, several contacts, a full attempt switcher, cover letter attach, the 409 dialog
  beyond the existing button, component tests (tests cover the controller and the routes). Not run in a browser.
- **AI context:** unchanged; `safeTracking` already passes stage and dates only. `tests/js/trackerCv.test.js` asserts it.

### 2.6 As built: Jobs filter, Board and Statistics, Settings columns (2026-10-29)

Owner scope change of 2026-10-29. Browser work only; no API change, no `data/` change beyond what the existing routes write.
It pulls the first parts of S4 (board) and S5 (Settings) forward; the legacy removal of S4 and the rest of S5 stay open.
- **Jobs status filter:** one new value `applied` in the existing Status select (`appliedFilter.js`): the job has a
  non-voided application in the store. It is a filter value, not a job status (`JOB_STATUSES` and `updateJobStatus` do
  not know it). `applied_manually` stays in the select only while some job has that status and no application. While the
  store is not loaded, "applied" shows nothing and says so.
- **Applications screen, two tabs:** Board (default) and Statistics.
  - **Board** (`boardModel.js`, `ApplicationBoard.jsx`): columns Applied, the active registry stages, Rejected, Ghosted;
    cards (company, title, days in stage from `daysInCurrentStage`, "stale" after 14 days) read the store, not the Jobs
    list. Dragging a card to a column (`dropDecision`) and a "Move to" select, the touch and keyboard fallback, both call
    `/move`. The move is not optimistic: the cache changes only on success; a refusal (for example the
    competing-attempt 409) shows on the card. Closed (other outcomes) and unfiled are one line of counts. A card whose
    job left the Jobs list says so instead of opening Job Details (the snapshot view is not built).
  - **Statistics** (`applicationStatistics.js`): the earlier stat cards and tracker table unchanged, a stage filter on the
    table, and counts per stage, channel and CV used, applications per week (Monday weeks, zero weeks filled), median days
    per stage (every spell, running ones to today), outcomes. Voided applications count nowhere; an unrecorded applied
    date, channel, CV or stage date is counted as missing and shown, never guessed.
- **Settings > Applications** (`ApplicationSettingsPanel.jsx`): the tracking switch and the board columns: rename,
  reorder by dragging (`reorderDecision` in `stageRegistry.js`) or up / down, add, remove (= retire, refused with the count while open applications sit there), restore. Applied, Rejected
  and Ghosted are shown locked. The `interview` flag, the reminders switch, "avoid duplicate applications" and CSV
  import are not built here. Counts come from the cached store; the server still decides a retire.
- **Not built:** optimistic moves, Closed panel, Unfiled column, "Show voided", snapshot view, several contacts,
  nudges, CSV, component tests (the tests cover the pure modules and the routes through the client).
- **Tests:** `appliedFilter.test.js`, `applicationBoard.test.js`, `applicationSettings.test.js`, `stageRegistry.test.js` (`reorderDecision`).

## 3. API and UI surface

### 3.1 Server (`scripts/api-handler.js` → `scripts/application-store.js`)

| Route | Purpose |
|---|---|
| `GET /api/applications` | The whole store (single user, small) |
| `POST /api/applications` | Create. Body: `{ requestId, jobId? \| posting?, attempt, newAttempt?: { distinctReason } }`. The server builds the snapshot itself (2.2 order), copies the CV file, and runs the duplicate check (6c). Returns the application, or 409 with the conflicting id |
| `POST /api/applications/:id/events` | Append ONE event `{ type, date, data }`. The server assigns `id`, `seq`, `at` and `source`, and validates the type and data against the enums and, for `stage`, against the registry (1.6) |
| `POST /api/applications/:id/move` | Revised, PROPOSAL. The board's drag and quick-move, and the Job Details stage select. Body `{ toStage, date? }`, where `toStage` is `applied`, an active work key, `rejected` or `ghosted`. The server builds the events itself (table below) and appends them in **one** locked save, checked by `assertAppendOnly`, as ApplyPack writes its stage and ledger row in one transaction. Moving to the current column writes nothing and returns 200. Refused: voided application (400), retired or unknown key (400), tracking off (409) |
| `GET /api/applications/settings` | Revised, PROPOSAL. Settings and the stage registry, with per-column counts (open, non-voided applications) for Settings → Applications, as ApplyPack shows them |
| `POST /api/applications/settings` | Revised, PROPOSAL. Body: any of `trackingEnabled`, `followUpReminders` |
| `POST /api/applications/settings/stages` | Revised, PROPOSAL. Body `{ op: add \| rename \| move \| retire \| unretire, key?, label?, dir?, interview? }`, the operations of 1.6. `retire` runs the 1.6.1 count and write under the store lock, and is refused with 409 and `{ count }` while open applications sit in the column |
| `GET /api/applications/:id/files/:name` | Serve a frozen file (name checked against the record) |
| `POST /api/applications/migrate/preview`, `/migrate` | Section 2 |
| `POST /api/applications/import-csv/preview`, `/import-csv` | Section 4 |

**The move route's events** (PROPOSAL):

| From | To | Events appended |
|---|---|---|
| Open, any stage | `applied` or a work stage | `stage_changed` |
| Open | `rejected` / `ghosted` | `outcome_set` (the stage reached stays) |
| Closed, any outcome | `applied` or a work stage | `outcome_cleared { reason: "moved on the board" }`, then `stage_changed` unless the stage reached already equals `toStage` |
| Closed | the other of `rejected` / `ghosted` | `outcome_cleared`, then `outcome_set` |

Every row that writes `outcome_cleared` *and leaves the application open* runs the competing-attempt check of 1.9
first, on `/move` and on `/events` alike. A rejected application dragged back to Tech while its reapply is open is refused with 409 and the
reapply's id. Nothing is written, and the card goes back.

`/events` stays one event per request (6b). `/move` is the only route that writes two, and it never takes event
bodies from the client.

**Tracking off:** create, `/events`, `/move` and `settings/stages` return 409 `tracking_disabled` (1.7). Still open:
`GET`, `POST /api/applications/settings` (so tracking can be switched back on), `migrate*`, `import-csv*` and the
backup routes.

There is no `PUT`, `PATCH` or `DELETE`. Corrections go through `event_voided`, removal through
`application_voided`, and its undo through `application_restored`. All three are ordinary appends to the
`/events` route. `event_voided` cannot target an `application_voided` or `application_restored` event (400), so
there is exactly one way to undo a void. `backup-handler.js` adds `applications` to `DATA_DIRS`, so export includes the store and its
frozen files.

**Restore from a backup zip** is the one other path that touches the store. Today `importBackupZip` writes every
`data/` entry over the file on disk, so for `data/applications/` it changes to a merge:
1. Back up the current store to `data/backups/applications-<ts>/`.
2. Add applications whose `appId` is not in the store.
3. For an `appId` in both, keep the record with the longer event log, and only if the shorter log is its prefix
   (`assertAppendOnly`). Otherwise keep the current one and report a conflict.
4. Add frozen files that are missing; never overwrite an existing one.
5. Revised, PROPOSAL. **`settings.json`:**
   - **No current file:** the backup's file is written.
   - **Both exist:** the current switches and order win. Stages are merged by key: a key only in the backup is
     appended as `retired: true` with its label, so the restored applications' history keeps its names. Labels of
     keys in both stay the current ones.
   - **Never lost:** a stage is never dropped by a restore. Open applications on a key the current board does not
     show appear under Unfiled.

A restore can therefore add history but never remove or rewrite it.

### 3.2 Browser

- **Data module:** `src/modules/applications/` holds:
  - `applicationsClient.js`, the fetch plus read cache;
  - `foldApplication.js`, `applicationEnums.js` and `nudges.js`;
  - (revised) `stageRegistry.js`, with `boardColumn`, `labelFor` and the registry operations of 1.6.

  The folding, column and nudge code is pure and shared with the server tests.
- **One state for every view** (CAREER OS REQUIREMENT 2.3 and 2.4, PROPOSAL for the mechanism):
  - **The gap:** ApplyPack gets this for free, because its pages are rendered on the server and the board reloads
    after each move (0a). In Career OS, `JobDetailDrawer` and `ApplicationHome` are separate React trees.
  - **One source:** `applicationsClient.js` is the only source both read, through one hook (`useApplications()`). It
    holds the last store the server returned, with no copy of the stage anywhere else.
  - **Writes:** every write (create, event, move, settings) replaces the cached application, or the settings, with
    the server's response, then notifies every subscriber.
  - **Failure:** nothing changes in the cache, and the view that started the write shows the error.
  - **Optimistic drag:** the board may move a card at once, as ApplyPack does. It then shows the server's state on
    success and puts the card back on failure.
  - **After a reload:** the cache is refetched from `GET /api/applications`.
- **Legacy adapter:** `trackingFromApplication(app, registry)` returns the old ten-field shape, so the current readers
  (`jobStats`, `JobTable`, `FollowUpPanel`, `contactRanking`, `outreach_auditor.py` via the scored file) keep working
  through S2-S3. It is deleted in S4.
  - **Revised, PROPOSAL:** `interviewStage` is:
    - `Applied` on `applied`;
    - `Offer` on the `offer` key;
    - `Rejected` and `Withdrawn` for those outcomes;
    - otherwise the registry label (so `jobStats` counts any other work stage as "Interviewing", as it counts
      "HR Screen" today).
  - **Other outcomes:** ghosted, position closed and the two offer outcomes give `Ghosted`, `Position closed`,
    `Offer accepted` and `Offer declined`. `jobStats` `TERMINAL_STAGES` gains these four in S2, so they are not
    counted as interviewing.
  - **Interim counting:** this keeps today's counting through S2-S3. From S4 `jobStats` reads the fold, and "Interviewing"
    counts open applications on a stage with `interview: true` (O2).

**Job Details** (S3; CAREER OS REQUIREMENT 2.4 and 5, layout from ApplyPack's tracking card, VERIFIED 0a). An
"Application" section in `JobDetailDrawer`:
- **Mark Applied:**
  - **Fields:** channel, applied date (default today), and "CV used".
  - **CV preselect** (PROPOSAL): the tailored CV for this job when one exists under `data/resumes/<jobId>/`, else the
    profile's default CV (`profile.defaultCvId`).
  - **Not preselected:** Career OS has no per-job résumé comparison record or search-linked CV for ApplyPack's first
    two preselect rules. "None / external" stays available, and the user can override any preselect.
  - **The call:** `POST /api/applications`. On 201 the card is on the board, because the board reads the same cache.
  - **On 409:** the dialog offers "add an event to the existing one", or a new attempt with a reason (6c).
- **When an application exists:**
  - stage (a select over `applied`, the active work stages, Rejected and Ghosted, through `/move`);
  - applied on (correction, O4);
  - CV used (a link to the frozen file; "record the CV" when none is recorded, "correct the CV" with a reason
    otherwise; earlier copies stay listed, O4);
  - contacts; notes as a list;
  - follow-up date; channel; the snapshot;
  - void and restore.
- **Several attempts:**
  - an attempt switcher ("Attempt 2 of 2, latest") lists every non-voided attempt with its date, stage and outcome,
    and the section shows the selected one;
  - "Show voided" adds the voided ones, read-only apart from Restore;
  - Mark Applied on a posting with an open attempt goes through the 409 path, never a silent overwrite.
- **A job that left discovery:** the application opens from the board with its snapshot and a "no longer in
  discovery" label (6a).

**Applications Kanban** (S4; CAREER OS REQUIREMENT 2.3 and 3, behaviour VERIFIED in ApplyPack 0a):
- **Columns:**
  - Applied, then the active work stages in registry order, then Rejected and Ghosted as board columns (O3);
  - Unfiled, only when a card is there;
  - a collapsible Closed panel below the board with the other outcomes (withdrawn, offer accepted, offer declined,
    position closed), grouped. They appear nowhere else on the board and are set from Job Details (O3).
- **Each column header** shows its count.
- **Card:**
  - company, title, stage, applied date, CV used and time in stage (`daysInCurrentStage`, from the newest `stageHistory` entry, not `stageSince`; "stale" after 14 days in a
    non-closed stage, as ApplyPack does, display only);
  - an "attempt N" badge when the posting has more than one;
  - clicking opens Job Details, or the snapshot view when the job is no longer in discovery.
- **Moving a card:**
  - **Drag:** native HTML5, no new dependency.
  - **Fallback:** a quick-move select on every card covers keyboard, touch and no-drag, as ApplyPack's form does.
  - **Optimistic:** the card moves at once and goes back on any non-2xx response, with an error line.
- **Header line:** "N active · M closed". Voided cards are never on the board; a "Show voided" list is reachable from
  the page.

**Settings → Applications** (S5; CAREER OS REQUIREMENT 4.1, 4.2, 4.5, 4.6, ApplyPack layout VERIFIED 0a). A new
section in `SettingsHome`:
- the tracking switch;
- **Board columns:**
  - add, rename, move up/down and retire;
  - each column shows its count; Applied, Rejected and Ghosted are shown locked;
  - the `interview` checkbox per column (O2);
  - retired columns are listed under "Retired", with Restore;
- the follow-up reminders switch.

The re-apply window is not in v1 (O5); neither is the board export (O6).

Career OS has no Notifications tab, so the reminders switch lives here. ApplyPack puts it under Notifications.

**Reopen and its neighbours** (requirements 5.4). Four operations, never merged; the binding rules and examples
are in 1.9:

| Operation | What it does | Career OS event(s) | ApplyPack |
|---|---|---|---|
| Move to another stage | Same application, new current stage | `stage_changed` (via `/move`) | Stage move, ledger row (VERIFIED) |
| Reopen a closed application | A rejected or ghosted application becomes open again, e.g. a "ghosted" company replies | `outcome_cleared`, plus `stage_changed` if moved to another column (via `/move`). 409 when a later open attempt for the same posting would be duplicated (6c) | A move out of Rejected/Ghosted (VERIFIED). ApplyPack's **Reopen button** is something else: it resets the *inbox* status to NEW and never touches the stage (VERIFIED). Career OS has no counterpart, and none is planned |
| Restore a voided application | A record voided by mistake comes back, same id and history | `application_restored`, 409 on a duplicate (6c, 6e) | No void; "Not in funnel" then picking a stage again is the nearest (VERIFIED) |
| New attempt | A separate application to the same posting | New `app-` id with `previousApplicationId` and `distinctReason` (6c) | Not possible: one record per job (VERIFIED) |

### 3.3 Smallest first slice (S1 + S2, one release)

The apply flow and the migration go to the store. The tracker panel reads and writes through it, with the same
fields as today plus nothing else. Revised: the store, registry and settings exist from S1. The panel's stage select
lists the registry's active stages instead of `INTERVIEW_STAGES`.
- **Legacy jobs:** for a job that still has legacy tracking and no `mig-` record, the panel shows "Run the migration
  first (Settings)" instead of an empty form. So no new record can be created next to an unmigrated one.
- **When A1 is closed:** once the migration has run. From then on no import, overflow or ledger prune can lose an
  application, and that is all A1 needed. Until the owner runs it, the legacy data is exposed to the same import
  loss as today, so the release note asks for the migration right after the upgrade. Channel and CV picker, timeline, nudges and CSV come later and are each shippable alone
(section 7).

### 3.4 Privacy

The store contains no candidate data that the existing privacy rules (CLAUDE.md "Privacy rules and exceptions") do not
already cover. No route sends it to a provider. `aiContextBuilder.js` currently puts recruiter name, e-mail and
LinkedIn into AI context. Under this plan, its replacement reader passes outcome, stage and company/title only, with
no contacts and no snapshot text. That narrows what is sent today and never widens it (decision 9). The CLAUDE.md privacy list is updated in the same step to record it.
Revised: that step moves from S4 to S3. S3 is where Job Details starts reading the store, so the narrowed reader is
ready there, and the narrowing comes one slice *earlier*, not later.

Revised (PROPOSAL): stage labels are now free text the owner types, where they were fixed strings before. So the
AI context passes the stage **key**, mapped through a fixed table to the old wording for the default keys (`screen`
→ "Screen" ...), and "other stage" for a custom key. It never passes a label the owner typed. That keeps the
"never widens" promise. The S3 update of the CLAUDE.md privacy list records it.

No tracker route, setting or nudge makes an AI or network call (CAREER OS REQUIREMENT 2.2, 9). Scenario 19 checks
this at the HTTP layer (section 6, acceptance).

## 4. CSV import of past applications

**Format:**
- **Encoding:** UTF-8 (a BOM is accepted).
- **Delimiter:** `,` or `;`, detected from the header line, because Serbian-locale Excel writes `;`.
- **Quoting:** RFC 4180. One header row. Column names are case-insensitive, and unknown columns are reported and
  ignored.

| Column | Required | Rule |
|---|---|---|
| `company` | yes | |
| `title` | yes | |
| `applied_date` | yes | `YYYY-MM-DD` or `DD.MM.YYYY`; anything else makes the row invalid |
| `channel` | no | channel enum, or empty → `other` |
| `channel_detail`, `url`, `location`, `cv_label` | no | `cv_label` → `cv: { kind: external, label }` |
| `stage` | no | Revised (PROPOSAL). Matched in this order: an active registry key; an active label (case-insensitive); a legacy `INTERVIEW_STAGES` value (mapped as in 1.4). `rejected` / `ghosted` in this column are read as the outcome. Anything else makes the row invalid ("unknown stage"), so a typo never creates a stage. The preview names the registry it matched against |
| `outcome`, `outcome_date` | no | outcome enum; `outcome_date` defaults to `applied_date` |
| `contact_name`, `contact_email`, `contact_linkedin` | no | One `contact_added` |
| `notes` | no | One `note_added` |
| `attempt` | no | Integer ≥ 1. Optional (decision 12). When present, it separates two real attempts with the same company, title, date and channel. When the column is absent or the cell is empty, the value is 1. A file without the column therefore gives exactly the ids and dedupe results of rules 1-4 below. Anything else (0, negative, text) makes the row invalid |

**Snapshot:**
- **Default:** `capturedFrom: csv` and `descriptionMissing: true`.
- **When `url` matches a ledger or scored job:** `jobId` and the description are taken from it at import time, then
  frozen like any other snapshot.

**Normalization for keys:** lower-case, trim, collapse whitespace, transliterate Serbian Latin (č ć → c, š → s, ž → z,
đ → dj), drop legal suffixes (`d.o.o.`, `doo`, `ltd`, `gmbh`, `inc`, `llc`, `ag`).

Revised (PROPOSAL), aligned with ApplyPack's `employerKey` (VERIFIED 0a):
- **Punctuation:** dropped, `&` read as "and", and a leading "the" dropped. The uncommitted `norm()` keeps
  punctuation, so "Acme, Inc." gives `acme,` and does not match "Acme".
- **Legal forms:** dropped only at the end, from ApplyPack's closed list. The uncommitted `norm()` drops them anywhere
  in the name.
- **Serbian Cyrillic:** transliterated to Latin first. Infostud ads can name companies in Cyrillic.
- **Never fuzzy:** "Acme Labs" stays apart from "Acme".

One `norm()` serves the CSV keys and the 6c soft warning (and the re-apply window if it is ever built, 5a). It must be fixed before S6 ships,
because it feeds `csv-` ids.

**Dedupe rules**, applied in the preview and again on confirm:
1. **Row key** = `norm(company)|norm(title)|applied_date|channel|attempt`, and `appId = csv-<hash>`. A row whose id
   already exists is **skipped: already imported**, whether that application is voided, restored or active. This is what makes the
   CSV re-import idempotent. Rows that differ in date, channel or `attempt` get different ids, so separate attempts
   at one posting are imported as separate applications.
2. **Same row key twice in one file:** the first row is used and the next ones are **skipped: duplicate row**, with
   their line numbers.
3. **Possible duplicate.** A row is flagged when an existing non-CSV, non-voided application has the same `url`, or the same
   `norm(company)` and `norm(title)` with `appliedDate` within 3 days. Such rows are **excluded by default**, and the
   owner can tick them in.
4. **Invalid** rows (missing required field, bad date or enum) are listed with the reason and never imported.

The preview shows four counts (new, already imported, possible duplicate, invalid) and the rows behind each. Confirm
writes a backup first, as the migration does.

## 5. Follow-up nudges (deterministic, no AI)

`nudges(app, today)` is a pure function over the folded application. `today` is passed in, as a date in the server's
local zone, `Europe/Belgrade`. Thresholds are code constants and are counted in calendar days.

| Rule | Fires when | Nudge |
|---|---|---|
| N0 explicit | an open `follow_up_set` with `dueDate <= today` and no later `follow_up_done` | "Follow-up due" (wins over N1-N5) |
| N1 no response | last activity is `applied`, 7 days ago or more | "No reply in N days: follow up" |
| N2 ghost check | no activity for 21 days in any open stage | "Consider marking as ghosted" (only a suggestion) |
| N3 post-interview | `stage_changed` to a stage with `interview: true` (1.6), with no `message_sent` within 1 day | "Send a thank-you" |
| N4 stalled after interview | current stage has `interview: true`, no activity for 7 days | "Ask about next steps" |
| N5 deadlines | `assignment_due` or `offer_deadline` within 2 days, or past and not followed by a stage later in the registry order or an outcome | "Assignment due ..." / "Offer deadline ..." |

Revised:
- **Inputs:** `nudges(app, today, registry)` takes the registry for N3, N4 and N5. The thresholds, the order and
  "never write an event" are unchanged (decisions 3 and 4).
- **The `interview` flag (O2)** selects the stages N3 and N4 apply to. A nudge is a reminder only; it creates no
  interview and no calendar event.
- **Folded applied date:** N1 counts from the folded `appliedDate` (O4).
- **Reminders switch:** with `followUpReminders` false (1.7) no nudge is computed or shown. Nothing is written, and
  turning it on again shows the same nudges, since they are a pure function.
- **ApplyPack** (VERIFIED 0a): one daily message for applications 14 days in `applied` with no recruiter contact.
  It never changes a stage. Career OS N1 already covers it at 7 days, with "no reply" rather than "no contact". This
  is no conflict: decision 4 stands. Career OS has no message channel, so nudges stay in-app.

- **Activity:** any event except `note_added`, `nudge_snoozed`, `event_voided`, `application_voided`, `application_restored`
  and (revised) `applied_date_corrected` and `cv_recorded`. A `message_sent` or
  `reply_received` therefore resets N1, N2 and N4.
- **One nudge per application:** the highest rule in the order N0, N5, N3, N4, N1, N2.
- **No nudges when:** an outcome is set, the application is voided (6e), or there is a `nudge_snoozed` for that rule with
  `until > today`.
- **Nothing automatic:** nudges never write events. "Mark as ghosted" is a button that appends `outcome_set`.
- **Migrated records:** `appliedDate: null` gets N0 only; it never fires N1 or N2 from an unknown date.
- **Where they show:** the follow-up list and the badge (`FollowUpPanel`, `JobTable`, `jobStats`). These read nudges
  from S5 onwards. Outreach follow-ups (`followUpEngine.js`) stay as they are (decision 6).

## 5a. Company re-apply window: DEFERRED, not in v1 (O5)

The owner deferred the window on 2026-10-29. Nothing in S1-S6 builds it: no `reapplyDays` setting, no Python
reader of the store, no change to discovery or the judge. It stays here only as a future item.

**Constraint for any future design** (owner, 2026-10-29): it must not affect Layer 1, the Top 50, or which postings
go to AI matching. Both placements studied in the 2026-10-29 revision break that rule:
- **At discovery** (ApplyPack's placement) it changes Layer 1's inputs.
- **Before the paid calls** it changes which postings fill the judge's 50 slots, which are the highest local scores
  at or above the threshold (`llm_enhancer.py` `select`).

A future version therefore needs a different shape, for example a label on the posting with no effect on selection.
It comes back to the owner as its own proposal.

What stays valid from the study, for that proposal:
- **ApplyPack** (VERIFIED 0a): the window is off by default and acts on *new* postings only. Any application inside
  the window counts, and postings added by hand are exempt.
- **Four different cases are kept apart.** Only the last one is the window; the first three are v1 behaviour (6c)
  and unchanged:

  | Case | v1 rule |
  |---|---|
  | The same application recorded twice by accident | Refused: `requestId` replay, 409 (6c) |
  | A genuinely separate attempt at the same posting | Allowed with a checked `distinctReason` (6c) |
  | A new application to another position at the same company | Always allowed; only the 6c soft warning for the same normalized title within 30 days |
  | A company-level rest period for new postings | Not in v1 |

The company *mute* of ApplyPack ADR 0056 is a separate feature and is not part of this plan either (section 8).

## 6. Invariants and verification

Every test is named, deterministic, offline and runs in the normal suite (`podman run --rm --security-opt label=disable -v /srv/career-os:/work -w /work docker.io/library/node:20-bookworm npm run test:js` and `.venv/bin/python -m pytest tests/python -q`; `npm test` works on neither side on DS9). The store tests use a temp
directory (`fs.mkdtempSync`), as `cvStore.test.js` does.

### 6a. An application exists independently of any posting in Discovery

**Rule:** an application never depends on a job record, a scored or discovered file, the ledger, a tailored-résumé
folder or a CV library entry. Everything it needs is in `applications.json` and `data/applications/files/<appId>/`.

| Test | How it is checked |
|---|---|
| `application survives the discovered job leaving the list` | Create an application from job J. Run `importJobsFromFile` with a payload that lacks J. Assert the store deep-equals the store before, and that the "Applied" derivation still finds the application by `appId` |
| `application survives deleted job files` | In a temp root: create an application. Delete `data/jobs/*.json` and `data/resumes/<jobId>/`, then delete the library CV through `deleteCvFile`. Assert `GET /api/applications` returns the identical record, and that `GET .../files/<name>` serves bytes whose sha256 equals `attempt.cv.sha256` |
| `application survives ledger prune` | Python test: prune a fixture ledger entry past 90 days with `job_history.py`. Assert the bytes of the temp `applications.json` are unchanged (sha256 before = after) |
| `no discovery code writes the store` (Python side) | The same static check for `python/`: apart from the read-only `outreach_auditor.py` after S4, no Python file names `data/applications` |
| `application without any posting` | Create one with `jobId: null` (manual and CSV). Assert it folds, lists and nudges like any other |
| `no discovery code writes the store` | Static test: in `src/` and `scripts/`, only `scripts/application-store.js` references the path `data/applications`. The backup restore goes through that module's merge function, not its own file writes |

### 6b. Re-importing discovery, or a posting disappearing, never changes an application's history

**Rule:** `posting` and `attempt` are frozen at creation. `events` only grows at the end, and only through the append
route. One guard enforces this on every write: `assertAppendOnly(prev, next)`.

| Test | How it is checked |
|---|---|
| `store has no update or delete path` | The module's exported names are exactly the expected list: no `update*`, `delete*` or `set*` for events, posting or attempt. The route table has no PUT, PATCH or DELETE under `/api/applications` |
| `append keeps the old log as a prefix` | After N random appends, for each step `next.events.slice(0, prev.length)` deep-equals `prev.events`, and `seq` runs 1..n with no gap |
| `assertAppendOnly rejects any rewrite` | Table of mutations: change one byte of an old event, remove an event, reorder events, change `posting.description`, change `attempt.channel`. Each throws, and the file on disk is unchanged |
| `snapshot frozen against a changed ad` | Create from job J. Re-import J with a new description, salary and title. Assert `posting` deep-equals the original and `snapshotSha256` still matches a recomputation |
| `snapshot time is honest` | A manual create has `capturedAfterApply: false` and `capturedAt` equal to the `applied` event's `at`. Every migration and CSV record has `capturedAfterApply: true`. So "frozen at apply time" holds for applications created in the app, and records created later are labelled as such |
| `restore cannot rewrite history` | Store with app X at 5 events. Restore a zip holding X at 3 events (an older backup), plus a new app Y. After the restore X still has 5 events, Y is added, and `data/backups/applications-<ts>/applications.json` is byte-equal to the store before the restore. A zip holding X with an altered event 2 → X unchanged, conflict reported |
| `correction is an event, not a rewrite` | `event_voided` appends an event; the voided event is still in the file; the fold ignores it |
| `append route accepts only one event` | `POST .../events` with a body containing an `events` array, an `id` or a `seq` → 400, and the store is unchanged |

### 6c. Several applications to the same posting only for genuinely different attempts

**Posting key:**
- **When the posting is in discovery:** `job:<jobId>`. `jobId` is sha256 of the URL, else of title|company|location.
- **Otherwise:** `url:<normalized url>`, else `tcl:<norm(company)>|<norm(title)>|<norm(location)>`.

The key is only a link for duplicate checks. It is never the identity: the same role on two boards gets two keys,
and that pair is caught only by the soft warning (rule 4 below).

Voided applications are ignored by every rule below. A mistaken record therefore never blocks the real one.

**Restore and reopen** (revised 2026-10-29) are checked by the competing-attempt rule of 1.9. An application that
becomes open again, by a restore or by `outcome_cleared`, is refused with 409 and the conflicting id while another
open, active application competes with it: same key, same channel, and not a verified new CV. A restore that brings
an application back *closed* needs no check. So neither can ever produce two open copies of one attempt.

**A new attempt is genuinely distinct** when at least one of these holds:
1. **`reapply_after_outcome`:** every earlier application with this key has an outcome (rejected, withdrawn, ghosted,
   position closed).
2. **`different_channel`:** an open earlier one exists, but the new channel differs (e.g. applied on the company
   site, then got a referral).
3. **`resubmitted_new_cv`:** an open earlier one exists with the same channel, the CV sha256 differs, and the user
   picks this reason explicitly.

The new record stores `previousApplicationId` (the latest earlier one) and `distinctReason`.

**What prevents accidental duplicates:**
1. **409 by default.** Create with a key that has an open application and no `newAttempt` → 409 with the existing id.
   The UI then offers "add an event to it" instead.
2. **Reason checked in code.** The claimed `distinctReason` is verified: `different_channel` with the same channel →
   409; `resubmitted_new_cv` with the same sha256 → 409.
3. **`requestId`.** The client sends a `requestId` (a UUID per apply dialog). The server keeps the last 200 in the
   store's `requests` map. A retry or double click returns the first result instead of a second application.
4. **Soft warning.** A different key, but same `norm(company)` + `norm(title)` with an open application in the last
   30 days → the dialog warns ("possibly the same role on another board") without blocking.
5. **Deterministic ids for migration and CSV.** Repeating either cannot add records.

| Test | How it is checked |
|---|---|
| `duplicate open attempt is refused` | Same key, same channel, no reason → 409; store unchanged |
| `reapply after rejection is allowed` | Prior has `outcome_set rejected` → 201 with `previousApplicationId` set |
| `different channel is allowed, same channel claimed as different is refused` | Two cases, 201 and 409 |
| `new CV requires a different file` | Same sha256 → 409; different → 201 |
| `retry with the same requestId is a no-op` | Two identical POSTs → one record, both responses return the same `appId` |
| `cross-board soft warning` | Different `jobId`, same normalized company and title → 201 with `warnings: ['possible_duplicate']` |
| `voided application does not block a new one` | Create X, void it, create again with the same key and channel and no reason → 201 |
| `reopen cannot create a duplicate` | Revised. 1.9 example 2: A rejected, then reapply B open (same key and channel). `/move` A from Rejected to `tech` → 409 naming B, store bytes unchanged. Close B, then the same move → 200 |
| `reopen next to another channel` | 1.9 example 3: A (`company_site`) rejected, B (`referral`) open. Reopen A → 200, both open |
| `restore of a closed application is not checked` | 1.9 example 5: A rejected then voided, B open. Restore A → 200, A in the Rejected column; then reopen A → 409 naming B |
| `closed to closed needs no check` | A in Rejected, B open on the same channel. `/move` A to `ghosted` → 200 (`outcome_cleared`, `outcome_set`) |
| `restore cannot create a duplicate` | Continue the previous test: restore X while the new one is open → 409 naming it, and X stays voided. Void the new one, then restore X → 201, and exactly one active application for the key |
| `distinct attempts are never collapsed` | One posting P, run end to end through the API, migration and CSV. Creates: (1) a migrated legacy record for P with `Rejected`; (2) an `app-` reapply (`reapply_after_outcome`); (3) an `app-` with a different channel (`different_channel`); (4) two CSV rows for P with the same date and channel and `attempt` 1 and 2. Then it re-runs the migration and re-imports the CSV. Asserts: 5 applications with 5 distinct ids for P; the job row derivation returns all 5, shows the latest, and reports "5 attempts"; stats count 5 applications; no `alreadyTracked` and no `already imported` for any of them on the first run; the second run adds nothing |
| `open legacy record next to an open app- is one attempt` | Legacy record for P with no terminal stage, plus an open `app-` for P → the migration reports `alreadyTracked`, not a second application. Same setup with the `app-` voided → it is migrated |

### 6d. Migration is idempotent and lossless

| Check | How it is checked |
|---|---|
| **Dry run writes nothing** | `migrate/preview` on a fixture: the listing and mtimes of `data/applications/` and `data/backups/` are unchanged, and the response carries the full plan and counts |
| **Backup before write** | `migrate` with confirm. `data/backups/applications-<ts>/legacy-jobs.json` is byte-equal to the request body, and its mtime is earlier than the store's. A test that makes the backup directory unwritable gets an error, and `applications.json` does not exist afterwards |
| **Counts balance** | `candidates == created + alreadyMigrated + alreadyTracked`. Each `alreadyTracked` job is listed with the `appId` it matched. Jobs that are not candidates (no non-default value) are counted separately as `ignored`, so `ignored + candidates == jobs scanned`. After the run, the number of applications with `origin: migration` == `created + alreadyMigrated` |
| **Field-level check** | `verifyMigration(legacyJobs, store)` asserts the 10-row table below for every migrated record. It runs inside the apply, and on failure aborts the write. `legacy` deep-equals the original object, and unmapped keys (fixture `stage: 'applied'`) are present in `legacy` and listed in the report |
| **Idempotent** | Run `migrate` twice on the same input. The second run reports `created: 0`, `alreadyMigrated: N`, and the bytes of `applications.json` are identical (sha256), because `updatedAt` is not bumped when nothing changes and migration event `at` values come from the source |
| **Does not overwrite later work** | Migrate, append a user event to `mig-<jobId>`, migrate again. That application is untouched (an existing `mig-` id is never rebuilt) |
| **Fixture coverage** | The fixture holds: a full record; legacy `{ stage: 'applied' }`; `applied: false` with notes only; `applied_manually` with no tracking; each `INTERVIEW_STAGES` value; a slim job without description (→ `descriptionMissing`); a job present only in the ledger; a job already tracked by an `app-` record (→ `alreadyTracked`); a job with all defaults (→ `ignored`) |

The field-level table (`L` = the legacy object, `A` = the migrated application, `E(type)` = its events of that type):

| Legacy field | Assertion |
|---|---|
| `applied` | `L.applied === true` or `job.status === 'applied_manually'` ⇒ `E(applied).length === 1`. `L.applied === false` with other values ⇒ still one `applied` event, plus the warning "tracked but not marked applied" in the report |
| `appliedDate` | `A.attempt.appliedDate === (L.appliedDate \|\| null)` and `E(applied)[0].date === L.appliedDate` when it is set |
| `applicationUrl` | `A.attempt.applicationUrl === L.applicationUrl` |
| `recruiterName` | If set, exactly one `contact_added` with `role: recruiter` and `data.name === L.recruiterName` |
| `recruiterEmail` | Same event, `data.email === L.recruiterEmail` |
| `recruiterLinkedIn` | Same event, `data.linkedin === L.recruiterLinkedIn` |
| `notes` | If not empty, exactly one `note_added` with `data.text === L.notes` (whitespace not trimmed) |
| `followUpDate` | If set, exactly one `follow_up_set` with `data.dueDate === L.followUpDate` |
| `interviewStage` | If set and not `Applied`, exactly one `stage_changed` or `outcome_set` per the 1.4 mapping, with `data.legacyStage === L.interviewStage`. Revised: an unknown value → no stage event, the value present in `legacy`, and a report warning (1.4) |
| `lastUpdated` | Every migration event has `at === L.lastUpdated`, or the fallback named in 2.2, and `source: 'migration'` |

Two more checks for the dry-run requirement (decision 8):

| Check | How it is checked |
|---|---|
| **No apply without a dry run** | `migrate` with no `previewSha`, or with the sha of a different payload → 409, and nothing is written (no backup, no store) |
| **Zero records is a valid run** | A preview of an empty candidate list returns all counts 0. Apply with its `previewSha` writes `migration.json` with zero counts, and writes no `applications.json` if none existed |

### 6e. A voided application stays in the history and counts nowhere; a restore brings it back once

**Rule:** `application_voided` and `application_restored` are appended like any other event. The application and all
its events stay in the file. The fold sets `voided` from the later of the two: true after a void, false after a
restore (decision 11). Void and restore can alternate any number of times, and each one is a new event.
Neither counts as activity for nudges (section 5).

Every consumer then reads through one filter, `isActive(app) = !folded.voided`, which is used in these places:
- the active lists (the Applications screen, and the job-row "Applied" derivation in 2.3);
- nudges (section 5);
- success and outcome statistics (`jobStats`, and the Phase 5 reports);
- the duplicate checks (6c) and the migration's `alreadyTracked` rule.

The only place a voided application shows is a "Show voided" filter on the Applications screen. It is read-only there, apart from the Restore action.

**Restore** (decision 11):
- **Same record:** a restore never creates an application. It is the same `appId`, the same frozen `posting` and
  `attempt`, and the full event log with the void and restore events in it.
- **Counted once:** a restored application counts exactly once, as if it had never been voided. The events from
  before the void count again; those during the void count as normal.
- **Duplicate check:** the restore is checked against 6c ("Restoring is checked like a create").

| Test | How it is checked |
|---|---|
| `voided application is kept with its history` | Fixture: app V with `applied`, `stage_changed interview`, `outcome_set offer_accepted`, `follow_up_set` due yesterday, then `application_voided`. Assert `GET /api/applications` still returns V with all 5 events byte-equal, and `assertAppendOnly` passes |
| `voided application is in no active list` | The Applications screen list and the job-row derivation for V's job both exclude V. With "Show voided" on, the list includes it and marks it voided |
| `voided application fires no nudge` | `nudges(V, today)` is empty even though its `follow_up_set` is due |
| `voided application counts in no statistic` | Stats over store S plus V deep-equal the stats over S alone: application count, per-outcome counts (the voided `offer_accepted` is not an offer), per-stage counts, conversion rates and the follow-ups-due badge |
| `restore keeps the history and adds no application` | V from the first test, then `application_restored`. Assert: the application count in the store is unchanged; V has the same `appId`, `posting` and `attempt` deep-equal; its events are the 5 earlier ones (byte-equal prefix) plus the restore; `assertAppendOnly` passes |
| `restored application counts once` | Stats over S plus restored V deep-equal the stats over S plus a copy of V with the void and restore removed. V is in the active list once, and its due `follow_up_set` fires N0 again |
| `void and restore can repeat` | Void, restore, void, restore: 4 new events, `voided` false; one more void → `voided` true. A void on a voided application, or a restore on an active one → 400, store unchanged |
| `a void is undone only by restore` | `event_voided` targeting an `application_voided` or `application_restored` event → 400 |
| `every consumer uses the filter` | Static test: the modules that list, count or nudge (`nudges.js`, `jobStats.js`, the Applications list, the job-row derivation, the stats builder) import `isActive`. A fixture with only voided applications gives empty lists, zero counts and no nudges in each |

### 6f. Stage configuration never invalidates an application or its history (revised)

**Rule:** a stage key never changes and never leaves the registry. Every event that names a key stays valid, and
every application has exactly one place on the board (1.6).

| Test | How it is checked |
|---|---|
| `rename keeps every reference` | Applications in `tech`, one closed after `tech`. Rename `tech` to "Technical Interview". The bytes of `applications.json` are unchanged (sha256); `boardColumn` and `labelFor` give "Technical Interview" for the card and in the history |
| `add and reorder change no application` | Add "Take-home" and move it before `tech`. Store bytes unchanged, every folded state deep-equal, columns in the new order |
| `retire refuses an occupied column` | One open application in `onsite` → `retire onsite` is 409 with `count: 1`, and the settings bytes are unchanged. Move it out → retire is 200. A closed application that reached `onsite` still shows "reached Onsite" |
| `retire races a move` | A retire and a move into the same column are sent in parallel 50 times. Afterwards no open application sits on a retired key, or, if the move came first, the retire was refused. The lock makes the two exclusive |
| `the last work stage stays` | Retiring the only active work stage → 400 |
| `unretire brings a stage back` | Retire an empty `onsite`, then `unretire`: the key is active again at the end of the order with its label; `applications.json` bytes unchanged; closed applications that reached `onsite` read "Onsite" throughout |
| `reserved and fixed keys` | Adding a stage labelled "Applied", "Rejected", "Ghosted" or "Unfiled" gets a suffixed key, never the reserved one. `applied`, `rejected` and `ghosted` cannot be renamed or retired (400) |
| `stage validated against the active registry` | `stage_changed` and `/move` to an unknown or retired key → 400, store unchanged |
| `unfiled catches the rest` | A store whose open application names a key missing from the registry (a restored backup) folds to `unfiled`; moving it to `screen` works |
| `invalid settings are not overwritten` | A malformed `settings.json` → every write that needs the registry is 500, and the file bytes are unchanged |
| `registry restore merges by key` | Restore a zip whose `settings.json` has a key the current one lacks → it is appended retired with its label; current labels and order are kept |
| `restore without a current settings file writes the backup's` | Empty root, restore a zip with `settings.json` → the file is byte-equal to the backup's |

### 6g. Kanban and Job Details show one state (revised)

| Test | How it is checked |
|---|---|
| `both views read one client state` | Component test: mount the board and `JobDetailDrawer` on one `applicationsClient` with a fake server. A move on the board changes the drawer's stage select without a refetch; a stage change in the drawer moves the card |
| `a failed move is not shown` | The fake server answers 500 to `/move`. The card goes back to its column, the drawer still shows the old stage, and the cache deep-equals the state before |
| `no stage copy outside the store` | Static test: no module under `src/` writes a stage to `localStorage` or to a job record after S4 |

### 6h. The tracking switch never deletes anything (revised)

| Test | How it is checked |
|---|---|
| `switching tracking off and on keeps every byte` | sha256 of `applications.json`, `settings.json` and every file under `files/` before; off; create, `/events`, `/move` and `settings/stages` → 409, `GET` still 200; on; every sha256 equal except `settings.json`, whose only change is `trackingEnabled` and its `changes` entry |
| `backup and migration work with tracking off` | With tracking off, export and restore a backup, and run a migration preview and apply. All succeed |
| `nothing is shown while off` | Component test: with tracking off the board shows the "tracking is off" state, the drawer has no Application section, and `nudges` returns nothing |

### 6i. Acceptance scenarios (requirements section 13)

Each scenario is a named test in the normal suite; "kind" says where it runs.

| # | Scenario | Test | Slice | Kind |
|---|---|---|---|---|
| 1 | Mark Applied puts the job in the Applied column at once | `mark applied appears in Applied` | S4 (store part S1) | component |
| 2 | Moving the card to Tech updates Job Details | 6g `both views read one client state` (board → drawer) | S4 | component |
| 3 | Changing the stage in Job Details updates Kanban | same test (drawer → board) | S4 | component |
| 4 | Renaming Tech keeps applications and history valid | 6f `rename keeps every reference` | S1 | store, fold |
| 5 | Adding and reordering a column changes no application | 6f `add and reorder change no application` | S1 | store |
| 6 | Deleting a non-empty column cannot lose applications | 6f `retire refuses an occupied column`, `retire races a move`, `unfiled catches the rest` | S1 | store |
| 7 | Removing a discovered job keeps its application | 6a `application survives the discovered job leaving the list`, `application survives deleted job files` | S1, S2 | store |
| 8 | Re-importing a job does not overwrite tracking | 6b `snapshot frozen against a changed ad`, 6a import test | S1, S2 | store |
| 9 | Updating the CV library leaves the frozen CV | `the frozen copy is unchanged after the library CV changes or is deleted` (S1 code) | S1 | store |
| 10 | Several attempts at one posting stay separate | 6c `distinct attempts are never collapsed` | S1, S6 | store |
| 11 | An accidental duplicate is refused | 6c `duplicate open attempt is refused`, `retry with the same requestId is a no-op` | S1 | store |
| 12 | Void hides without deleting | 6e `voided application is kept with its history`, `is in no active list` | S1, S4 | store, component |
| 13 | Restore brings back the same application, stats counted once | 6e `restore keeps the history and adds no application`, `restored application counts once` | S1 | store |
| 14 | Rejected and Ghosted stay in history | `closed applications stay reachable`: a move to Rejected keeps all events and the stage reached; the Rejected column lists it; a withdrawn one is listed in the Closed panel only; a move out writes `outcome_cleared` (1.9) | S1, S4 | store, component |
| 15 | Reminders never change an outcome | `nudges never write`: run `nudges` over every fixture and day for 60 days; the store bytes are unchanged and no `outcome_set` is appended | S5 | fold |
| 16 | Tracking off never deletes | 6h `switching tracking off and on keeps every byte` | S1 | store |
| 17 | Migrating twice adds nothing | 6d **Idempotent** | S2 | store |
| 18 | Importing a CSV twice adds nothing | S6 re-import idempotency test | S6 | store |
| 19 | No AI call anywhere in tracking | `tracker makes no network call`: with `fetch`, `http.request` and `https.request` stubbed to throw, run create, move, events, settings, migration, CSV and nudges; nothing is called | S1, S5, S6 | store, static |
| 20 | Restart and backup/restore keep data and history | backup round-trip and 6b `restore cannot rewrite history` (S1 code), plus `restart reloads the same store`: a new module instance over the same root returns byte-equal `GET` output | S1 | store |

## 7. Tests and implementation sequence

Each step ships alone, leaves the app working and passes these checks:

    podman run --rm --security-opt label=disable -v /srv/career-os:/work -w /work docker.io/library/node:20-bookworm npm run lint
    podman run --rm --security-opt label=disable -v /srv/career-os:/work -w /work docker.io/library/node:20-bookworm npm run test:js
    podman run --rm --security-opt label=disable -v /srv/career-os:/work -w /work docker.io/library/node:20-bookworm npm run build
    .venv/bin/python -m pytest tests/python -q

Revised 2026-10-29. The owner's proposed boundaries (requirements section 12) are adopted. The old steps map
onto them as below, and nothing of the old content is dropped:
- **Old S1 to S3:** S1 and S2 keep their content, plus the registry. Old S3 is split: the apply dialog goes to new
  S3 and the Applications screen to new S4.
- **Old S4** is split three ways:
  - the `aiContextBuilder` narrowing and the CLAUDE.md privacy list move *earlier*, to S3 (3.4);
  - the removal of `applicationTracking` and `applied_manually`, and the adapter deletion, go to the end of S4, once
    both views read the store;
  - `outreach_auditor.py` goes to S4 with them.
- **Old S5 to S7:** old S5 (nudges) becomes part of S5; old S6 (CSV) and S7 (docs) become S6.

| Step | Content | Tests |
|---|---|---|
| S0 | Owner decisions (done 2026-10-28, section 9 and DECISIONS.md). data-shapes.md gets the new store section. Revised: DECISIONS.md records decision 13, O1-O4 decided and O5-O6 deferred (done 2026-10-29); data-shapes.md gets `settings.json` with S1 | none |
| S1 | **Application store.** `application-store.js` with everything listed below; no UI. The data shape is complete for configurable stages from here on, although the Settings UI comes in S5 | 6a (all except the import one), 6b, 6c, 6e (store and fold parts), 6f, 6h store part, backup round-trip, acceptance 4-6, 9-11, 13, 16, 19 (store part), 20 |
| S2 | **Migration.** Migration (required preview, backup, apply, verify) from a Settings button, mapping to the registry defaults (1.4). `ApplicationTrackerPanel` and the three writers go through the store, with the "run the migration first" guard (3.3); the panel's stage select lists active registry stages; the readers go through `trackingFromApplication` (revised mapping, 3.2). Backup restore merges as in 3.1. **Closes A1 once the owner has run the migration** | 6d, 6a import test, 6b restore test, a reader test showing the old badges and stats are unchanged on a fixture, acceptance 7, 8, 17 |
| S3 | **Job Details.** `applicationsClient.js` with `useApplications()` (3.2). The Application section of `JobDetailDrawer`: Mark Applied with channel, CV picker (preselect, override, library / tailored / external) and the frozen copy, `requestId`, 409 handling; stage select through `/move`; applied on (O4); CV used, and record it later (O4); contacts; notes as a list; follow-up date; snapshot view; event timeline; attempt switcher; void and restore actions. `aiContextBuilder` narrowed (3.4) and the CLAUDE.md privacy list updated in the same step (decision 9) | Component tests for the dialog's 409 handling, including a refused restore; the CV preselect and override; snapshot view renders a missing job; the AI context test asserts no contact fields |
| S4 | **Applications Kanban.** `ApplicationHome` becomes the board (3.2): columns from the registry, cards, native drag and the quick-move select, optimistic move with revert, Closed panel, Unfiled, counts, time in stage, "Show voided" list. Then the legacy removal: `applicationTracking` leaves job records, `mergeStatusOnImport` and `jobStorage.test.js`; `applied_manually` is replaced by the derivation; readers use the fold directly and the adapter is deleted; `outreach_auditor.py` reads the follow-up date from `data/applications/applications.json` by `jobId` | 6g, 6e list and component parts, a test that `importJobsFromFile` output has no `applicationTracking`, 6e statistics test on `jobStats`, acceptance 1-3, 12, 14 |
| S5 | **Settings and reminders.** Settings → Applications (3.2): tracking switch, board columns editor (add, rename, reorder, retire, restore, counts, `interview` flag per O2), reminders switch. `nudges.js` (section 5) replaces `followUps.js`, with the registry and the switch; snooze and done actions. No re-apply window (O5 deferred) | One table-driven test per rule N0-N5, plus suppression, priority, the switch and a custom registry, with a fixed `today`; 6e nudge test; 6h component part; `the interview flag creates nothing` (N3/N4 fire on flagged stages; the store and `data/` are byte-equal after any number of nudge runs, so no interview or calendar record exists); acceptance 15 |
| S6 | **CSV import and completion.** CSV import with preview (section 4, revised `stage` column and `norm()`). Docs: ARCHITECTURE.md (tracker section), ROADMAP.md Phase 3 status, GLOSSARY (application, attempt, snapshot, nudge, stage registry, retired stage). The acceptance run of 6i end to end | Delimiter and BOM detection, both date forms, each dedupe rule, the `attempt` column, re-import idempotency, invalid row reasons including an unknown stage; the CSV part of the 6c "never collapsed" test; acceptance 10, 18 and the full 6i table |

**What S1 contains** (the S1 row above refers to this list; revised 2026-10-29):
- **Store mechanics:** load, atomic save, `create`, `appendEvent`, `assertAppendOnly`, the duplicate checks, the frozen
  file copy, and the routes of 3.1 except CSV and migration.
- **Configurable stages with stable ids:** the stage registry lives in its own file,
  `data/applications/settings.json`, separate from `applications.json` and written atomically under the same lock.
  - **Ids:** each stage has a key that is created once and never changes; its label is separate and renamable.
  - **Fixed stages:** `applied`, `rejected` and `ghosted` are fixed; the work stages default to `screen`, `tech`,
    `onsite` and `offer`.
  - **Operations:** add, rename, move, retire and unretire (1.6, 1.6.1), through `POST /api/applications/settings/stages`.
  - **Switches:** `trackingEnabled` and `followUpReminders` through `POST /api/applications/settings`.
  - **No UI:** the Settings screen for all of this comes in S5.
- **Revised, validation:** stages are checked against the active registry, and `outcome_set` is refused over an
  outcome.
- **Revised, the move route.**
- **Revised, new events:** `applied_date_corrected` and `cv_recorded` (O4).
- **Revised, the tracking switch** on the write routes.
- **The fold:** pure `foldApplication`, including `voided` from void and restore events and (revised) `stageSince`,
  the folded `appliedDate` and the folded `cv`; `boardColumn` and `labelFor`; `isActive` and enums.
- **Duplicates:** the competing-attempt check of 1.9 on create, restore and reopen.
- **Backup:** `backup-handler.js` includes `applications`. A restore merges `applications.json` as in 3.1 steps 1-4,
  and `settings.json` by the rule in 3.1 step 5:
  - with no current file, the backup's file is written;
  - otherwise the current switches, labels and order win;
  - a key found only in the backup is appended as retired with its label;
  - no stage is ever dropped, and an open application on a key the board does not show appears under Unfiled.
- **S1 tests for the stage settings** (6f), each asserting that `applications.json` is byte-equal before and after:
  - `rename keeps every reference`: the history and the card read the new label;
  - `add and reorder change no application`;
  - `retire refuses an occupied column`, and the history of closed applications keeps the retired label;
  - `retire races a move`;
  - `the last work stage stays`;
  - `unretire brings a stage back`: the key returns with its label, and old events show it again;
  - `stage validated against the active registry`;
  - `unfiled catches the rest`;
  - `invalid settings are not overwritten`;
  - `registry restore merges by key`, plus `restore without a current settings file writes the backup's`.
- **Not in S1:** the archiver import fix in `backup-handler.js` is unrelated to the tracker. It shipped as its own commit,
  `549d42f`.

## 8. What this plan does not do

- No AI in any part of the tracker.
- No changes to discovery, scoring or the ledger beyond the S4 removal from `mergeStatusOnImport`. No re-apply
  window: deferred (O5, 5a). Nothing in the tracker affects Layer 1, gates, Fit, the Top 50 or which postings go to AI
  matching.
- No interviews or calendar entries. A stage marked "interview" (O2) drives reminder rules only. Scheduling real
  interviews, with date, time and an optional Google Calendar event, belongs to the future Interviews / Calendar
  modules.
- No multi-device sync; the server file only makes it possible later.
- Outreach (`job.outreach`) and tailored assets stay on the job record and keep their own loss path (decision 6).
- ~~No custom stages (decision 5).~~ Superseded by decision 13: the work stages are configurable (1.6).
- Revised: **No application created by anything but an explicit user action**, a confirmed migration or a confirmed
  CSV import. Preparing a CV, a cover letter or an application pack never marks a job applied
  (CAREER OS REQUIREMENT 10). No automatic submission to employers.
- Revised: **Not taken from ApplyPack:**
  - ApplyPack's inbox-status Reopen (3.2);
  - its company mute (ADR 0056);
  - its funnel statistics, which ApplyPack itself removed (ADR 0025);
  - its notification channels;
  - its database or framework.
- Revised: **No board export** (CSV/Markdown of the board, VERIFIED in ApplyPack 0a). Deferred (O6); the backup
  export holds the data.
- Revised: no custom outcomes. The outcome enum stays fixed (1.4).

## 9. Decisions

The owner decided these on 2026-10-28. They are also recorded in the [DECISIONS.md](DECISIONS.md) log.

| # | Decision | Where in this plan |
|---|---|---|
| 1 | **Master storage** is the server file `data/applications/applications.json`, not localStorage | 1.1, 3.1 |
| 2 | **A mistaken application is voided only** (`application_voided` event), never physically deleted through the UI | 1.4, 3.1, 6e |
| 3 | **Ghosted is a suggestion only**, never set automatically | 5 (N2) |
| 4 | **Nudge thresholds** 7 / 21 / 1 / 7 / 2 days are accepted as code constants | 5 |
| 5 | ~~**Stages** are a fixed enum plus a free label~~ **SUPERSEDED 2026-10-29 by decision 13.** The owner's requirements document ("Application Tracker v1", section 4.3) states that this decision "must be revised because it does not fully represent ApplyPack's configurable Kanban behavior". Kept here as history; nothing in the plan relies on it any more | 1.4, 1.6 |
| 6 | **Outreach and tailored assets** are out of A2 scope | 2.3, 8 |
| 7 | **CV copies:** an immutable copy of the CV file that was sent is stored, with its sha256 | 1.1, 1.2, 6a |
| 8 | **Migration:** the S2 dry run is required even with zero tracked applications, and the migration code ships anyway | 2.1, 6d |
| 9 | **Recruiter name, e-mail and LinkedIn are removed from the AI context** in S4, and the CLAUDE.md privacy list is updated in that step. Revised 2026-10-29: the step is now S3, one slice earlier (3.4); the decision itself is unchanged | 3.4, 7 (S3) |
| 10 | **`applied_manually` is derived** from the application store, not kept as a separate job status | 2.3, 7 (S4) |
| 11 | **Undo a void: yes**, through an `application_restored` event. The full event history is kept. A restore creates no new application and duplicates no statistic. (Decided in the follow-up review on 2026-10-28) | 1.4, 3.1, 6c, 6e, 7 (S1, S3) |
| 12 | **CSV `attempt` is optional.** When present, it separates attempts at the same position; when absent, the existing dedupe rules apply unchanged (absent = 1). (Decided in the follow-up review on 2026-10-28) | 4 |
| 13 | **Configurable work stages** (2026-10-29, owner requirements document sections 3.1, 4.2, 4.3; supersedes decision 5). `Applied` is the fixed first stage, `Rejected` and `Ghosted` the fixed closed columns; the stages between are added, renamed, reordered and removed by the owner, each with a stable key separate from its label; defaults Screen, Tech, Onsite, Offer. The outcome enum stays separate and fixed | 1.4, 1.6, 3.1, 3.2, 6f |

Additional requirements from the same review:

- **A.** A voided application stays in the event history and never appears in active lists, follow-up nudges or
  success and outcome statistics. See 6e.
- **B.** Several separate applications for the same posting stay possible. The review re-checked every rule and
  changed two:
  - **Migration `alreadyTracked` (2.2):** it now applies only to an open legacy record next to an open, non-voided
    `app-`. A terminal legacy attempt is always migrated as its own application.
  - **CSV row key (4):** it now includes an `attempt` column, so two real attempts on the same day and channel are
    not merged.

  Unchanged:
  - **`mig-<jobId>`:** the legacy shape holds one attempt per job.
  - **`csv-` ids:** they differ by date, channel and attempt.
  - **Duplicate checks (6c):** they ignore voided records.
  - **The job-row derivation (2.3):** it returns all attempts.

  Test: 6c `distinct attempts are never collapsed`.

**DECISIONS.md** records this revision in its entry of 2026-10-29: "Tracker stages are configurable (stable ids),
superseding the fixed stage enum; O1-O4 decided, O5-O6 deferred." Its 2026-10-28 line "Custom stages are not built"
stays as history; the new entry supersedes it.

### Owner decisions (revision of 2026-10-29), resolved the same day

| # | Question | Status | Decision |
|---|---|---|---|
| O1 | What "remove a column" means | **Decided** | Columns are retired, never deleted. Retiring is refused while any open, non-voided application is in the column. History keeps the key and label, and a retired column can be restored (1.6, 1.6.1) |
| O2 | An `interview` mark per work stage | **Decided** | Stages can be marked "interview", on by default for Tech and Onsite. The mark only drives the deterministic reminder rules N3 (thank-you) and N4 (next steps). It never creates an interview or a calendar event; real interviews are scheduled in the future Interviews / Calendar modules, with date, time and an optional Google Calendar event (1.6, 5, 8) |
| O3 | Outcomes on the board | **Decided** | Rejected and Ghosted are Kanban columns. Withdrawn, offer accepted, offer declined and position closed are reachable only through the Closed panel (1.6, 1.9, 3.2) |
| O4 | Applied-date and CV corrections | **Decided** | Recorded as new events, `applied_date_corrected` and `cv_recorded`. The original CV snapshot and every earlier copy are never replaced (1.4) |
| O5 | Company re-apply window | **Deferred, not v1** | It must not affect Layer 1, the Top 50 or which postings go to AI matching. Removed from v1 and kept only as a future item (5a) |
| O6 | Board export | **Deferred, not v1** | Not built in v1 (8) |

### Remaining open questions

**No open questions block S1.** Every rule S1 implements is decided:
- the store and events (1.2-1.4), with the O4 events;
- the stage registry and its file (1.6, 1.7, O1, O2);
- the closed-application rules (1.9);
- the routes (3.1) and the backup merge (3.1);
- the tests (6a-6f, 6h).

Two follow-ups were listed here, and both are closed:
- **The S1 code** is committed as `5e549a4` (section 1.8).
- **The data-shapes.md update** is done: Application store in [data-shapes.md](data-shapes.md).
