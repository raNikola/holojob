# Holojob - Application tracker plan (Phase 3, A2)

Status: PLAN, decisions recorded 2026-10-28 (section 9, and the DECISIONS.md log). No code, no `data/` change.

Inputs: [DECISIONS.md](DECISIONS.md) principles 13 and 15, [PHASE0_AUDIT.md](PHASE0_AUDIT.md) module F and question 5,
[data-shapes.md](data-shapes.md), [../ROADMAP.md](../ROADMAP.md) Phase 3, and the current code listed in section 0.

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
| `stage_changed` | `{ stage, label?, legacyStage? }` | `stage` from the stage enum, `label` free text ("Technical round 2") |
| `outcome_set` | `{ outcome, legacyStage? }` | Ends the application; nudges stop |
| `outcome_cleared` | `{ reason }` | Reopens, e.g. a "ghosted" company replies |
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

**Enums** (code constants in one module, `src/modules/applications/applicationEnums.js`):

- **Stage:** `applied`, `screening`, `interview`, `assignment`, `final`, `offer`.
- **Outcome:** `offer_accepted`, `offer_declined`, `rejected`, `withdrawn`, `ghosted`, `position_closed`. No outcome
  means the application is open. `rejected` records the stage reached, which comes from the fold, so it is not
  duplicated in the outcome.
- **Channel:** `company_site` (ATS or careers form), `job_board` (`channelDetail` = board, e.g. LinkedIn Easy Apply,
  Infostud), `email`, `referral`, `recruiter_inbound`, `agency`, `other`.
- **Distinct reason:** `reapply_after_outcome`, `different_channel`, `resubmitted_new_cv`.

Legacy `INTERVIEW_STAGES` mapping:

| Legacy value | New event | Data |
|---|---|---|
| Applied | none | Covered by `applied` |
| HR Screen | `stage_changed` | `screening` |
| Technical Round 1 / 2 | `stage_changed` | `interview`, `label` = the legacy value |
| Assignment | `stage_changed` | `assignment` |
| Hiring Manager | `stage_changed` | `interview`, `label` = the legacy value |
| Final Round | `stage_changed` | `final` |
| Offer | `stage_changed` | `offer` (outcome stays open until accepted or declined) |
| Rejected | `outcome_set` | `rejected` |
| Withdrawn | `outcome_set` | `withdrawn` |

Every mapped event keeps `legacyStage` with the original string.

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
          "date": "2026-11-10", "source": "user", "data": { "stage": "screening" } },
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

`foldApplication` gives: stage `screening` (the stage reached), outcome `rejected`, one contact, no nudge. The file
`data/applications/files/app-3f9c0a1b2c3d4e5f/Acme_Resume.pdf` is the CV exactly as sent. If Acme's ad is deleted
from Greenhouse, discovery drops it, and the ledger prunes it 90 days later, nothing above changes.

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
- **S4:** it stops carrying `applicationTracking`. It still preserves `status`, `tailoredAssets`, `aiInsights` and
  `outreach` for jobs still in the list. Those fields have the same loss path, but they are outside A2 (decision 6).
- **`applied_manually`:** removed from `JOB_STATUSES` in S4 (decision 10). "Applied" on a job row becomes derived:
  at least one non-voided application exists with `posting.jobId === job.jobId`, or with the same `postingKey`.
  The legacy status value is read once by the migration and then ignored.
- **Several attempts on one job:** the derivation returns all of them, never only the first. The job row shows the
  latest non-voided attempt (highest `createdAt`) and an "N attempts" count when N > 1. Stats count attempts, not
  postings, so a re-application after a rejection counts as two applications with two outcomes.
- **Job records:** `applicationTracking` is deleted from them in S4. This happens only after `migration.json`
  exists and a re-run of the dry run reports `toCreate: 0`.

## 3. API and UI surface

### 3.1 Server (`scripts/api-handler.js` → `scripts/application-store.js`)

| Route | Purpose |
|---|---|
| `GET /api/applications` | The whole store (single user, small) |
| `POST /api/applications` | Create. Body: `{ requestId, jobId? \| posting?, attempt, newAttempt?: { distinctReason } }`. The server builds the snapshot itself (2.2 order), copies the CV file, and runs the duplicate check (6c). Returns the application, or 409 with the conflicting id |
| `POST /api/applications/:id/events` | Append ONE event `{ type, date, data }`. The server assigns `id`, `seq`, `at` and `source`, and validates the type and data against the enums |
| `GET /api/applications/:id/files/:name` | Serve a frozen file (name checked against the record) |
| `POST /api/applications/migrate/preview`, `/migrate` | Section 2 |
| `POST /api/applications/import-csv/preview`, `/import-csv` | Section 4 |

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

A restore can therefore add history but never remove or rewrite it.

### 3.2 Browser

- **Data module:** `src/modules/applications/` holds `applicationsClient.js` (fetch plus read cache),
  `foldApplication.js`, `applicationEnums.js` and `nudges.js`. The folding and nudge code is pure and shared with
  the server tests.
- **Legacy adapter:** `trackingFromApplication(app)` returns the old ten-field shape, so the current readers
  (`jobStats`, `JobTable`, `FollowUpPanel`, `contactRanking`, `outreach_auditor.py` via the scored file) keep working
  through S2-S3. It is deleted in S4.

### 3.3 Smallest first slice (S1 + S2, one release)

The apply flow and the migration go to the store. The tracker panel reads and writes through it, with the same
fields as today plus nothing else.
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
no contacts and no snapshot text. That narrows what is sent today and never widens it (decision 9). The CLAUDE.md privacy list is updated in S4 to record it.

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
| `stage` | no | stage enum, or a legacy `INTERVIEW_STAGES` value (mapped as in 1.4) |
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
| N3 post-interview | `stage_changed` to `interview` or `final`, with no `message_sent` within 1 day | "Send a thank-you" |
| N4 stalled after interview | `interview`/`final`, no activity for 7 days | "Ask about next steps" |
| N5 deadlines | `assignment_due` or `offer_deadline` within 2 days, or past and not followed by a later stage or outcome | "Assignment due ..." / "Offer deadline ..." |

- **Activity:** any event except `note_added`, `nudge_snoozed`, `event_voided`, `application_voided` and `application_restored`. A `message_sent` or
  `reply_received` therefore resets N1, N2 and N4.
- **One nudge per application:** the highest rule in the order N0, N5, N3, N4, N1, N2.
- **No nudges when:** an outcome is set, the application is voided (6e), or there is a `nudge_snoozed` for that rule with
  `until > today`.
- **Nothing automatic:** nudges never write events. "Mark as ghosted" is a button that appends `outcome_set`.
- **Migrated records:** `appliedDate: null` gets N0 only; it never fires N1 or N2 from an unknown date.
- **Where they show:** the follow-up list and the badge (`FollowUpPanel`, `JobTable`, `jobStats`). These read nudges
  from S5 onwards. Outreach follow-ups (`followUpEngine.js`) stay as they are (decision 6).

## 6. Invariants and verification

Every test is named, deterministic, offline and runs in the normal suite (`npm test`). The store tests use a temp
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

**Restoring is checked like a create.** An `application_restored` on X runs rules 1-2 below for X against the
other active applications, as if X were being created now. Its own `distinctReason` counts as the claimed reason.
If another active application has taken X's place in the meantime (same key, same channel, open), the restore is
refused with 409 and the conflicting id. The owner then voids one of the two first. So restoring can never
produce two open copies of one attempt.

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
| `interviewStage` | If set and not `Applied`, exactly one `stage_changed` or `outcome_set` per the 1.4 mapping, with `data.legacyStage === L.interviewStage`. An unknown value → `stage_changed` with `stage: applied`, a `label` equal to the value, and a report warning |
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

## 7. Tests and implementation sequence

Each step ships alone, leaves the app working and passes `npm run lint`, `npm test` and `npm run build`.

| Step | Content | Tests |
|---|---|---|
| S0 | Owner decisions (done 2026-10-28, section 9 and DECISIONS.md). data-shapes.md gets the new store section | none |
| S1 | `application-store.js`: load, atomic save, `create`, `appendEvent`, `assertAppendOnly`, duplicate checks, frozen file copy, routes from 3.1 except CSV. Pure `foldApplication` (including `voided` from void and restore events), `isActive` and enums. The restore duplicate check. `backup-handler.js` includes `applications`. No UI | 6a (all except the import one), 6b, 6c, 6e (store and fold parts), backup round-trip |
| S2 | Migration (required preview, backup, apply, verify) from a Settings button. `ApplicationTrackerPanel` and the three writers go through the store, with the "run the migration first" guard (3.3); the readers go through `trackingFromApplication`. Backup restore merges as in 3.1. **Closes A1 once the owner has run the migration** | 6d, 6a import test, 6b restore test, a reader test showing the old badges and stats are unchanged on a fixture |
| S3 | Apply dialog: channel, CV picker (library, tailored for this job, external) with the frozen copy, `requestId`. Applications screen lists from the store, including postings no longer in discovery; snapshot view; event timeline; notes as a list; void and restore actions, and the "Show voided" filter | Component tests for the dialog's 409 handling, including a refused restore; snapshot view renders a missing job |
| S4 | Remove `applicationTracking` from job records, from `mergeStatusOnImport` and from `jobStorage.test.js`. `applied_manually` replaced by derivation. Readers use the fold directly; the adapter is deleted. `aiContextBuilder` narrowed (3.4), and the CLAUDE.md privacy list updated in the same step (decision 9). `outreach_auditor.py` reads the follow-up date from `data/applications/applications.json` by `jobId` | Existing tests updated; a test that `importJobsFromFile` output has no `applicationTracking`; the AI context test asserts no contact fields; 6e statistics test on `jobStats` |
| S5 | `nudges.js` (section 5) replaces `followUps.js`; snooze and done actions | One table-driven test per rule N0-N5, plus suppression and priority, with a fixed `today`; 6e nudge test |
| S6 | CSV import with preview (section 4) | Delimiter and BOM detection, both date forms, each dedupe rule, the `attempt` column, re-import idempotency, invalid row reasons; the CSV part of the 6c "never collapsed" test |
| S7 | Docs: ARCHITECTURE.md (tracker section), ROADMAP.md Phase 3 status, GLOSSARY (application, attempt, snapshot, nudge) | none |

## 8. What this plan does not do

- No AI in any part of the tracker.
- No changes to discovery, scoring or the ledger beyond the S4 removal from `mergeStatusOnImport`.
- No multi-device sync; the server file only makes it possible later.
- Outreach (`job.outreach`) and tailored assets stay on the job record and keep their own loss path (decision 6).
- No custom stages (decision 5).

## 9. Decisions

The owner decided these on 2026-10-28. They are also recorded in the [DECISIONS.md](DECISIONS.md) log.

| # | Decision | Where in this plan |
|---|---|---|
| 1 | **Master storage** is the server file `data/applications/applications.json`, not localStorage | 1.1, 3.1 |
| 2 | **A mistaken application is voided only** (`application_voided` event), never physically deleted through the UI | 1.4, 3.1, 6e |
| 3 | **Ghosted is a suggestion only**, never set automatically | 5 (N2) |
| 4 | **Nudge thresholds** 7 / 21 / 1 / 7 / 2 days are accepted as code constants | 5 |
| 5 | **Stages** are a fixed enum plus a free label | 1.4 |
| 6 | **Outreach and tailored assets** are out of A2 scope | 2.3, 8 |
| 7 | **CV copies:** an immutable copy of the CV file that was sent is stored, with its sha256 | 1.1, 1.2, 6a |
| 8 | **Migration:** the S2 dry run is required even with zero tracked applications, and the migration code ships anyway | 2.1, 6d |
| 9 | **Recruiter name, e-mail and LinkedIn are removed from the AI context** in S4, and the CLAUDE.md privacy list is updated in that step | 3.4, 7 (S4) |
| 10 | **`applied_manually` is derived** from the application store, not kept as a separate job status | 2.3, 7 (S4) |
| 11 | **Undo a void: yes**, through an `application_restored` event. The full event history is kept. A restore creates no new application and duplicates no statistic. (Decided in the follow-up review on 2026-10-28) | 1.4, 3.1, 6c, 6e, 7 (S1, S3) |
| 12 | **CSV `attempt` is optional.** When present, it separates attempts at the same position; when absent, the existing dedupe rules apply unchanged (absent = 1). (Decided in the follow-up review on 2026-10-28) | 4 |

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

### Remaining open questions

None. No open questions block S1, and none are left for later steps.
