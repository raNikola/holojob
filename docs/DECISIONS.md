# Holojob - Decisions

Short entries for decisions that were not yet written down. Planned work is in [ROADMAP.md](ROADMAP.md). The product
principles and the older owner decisions stay in [redesign/DECISIONS.md](redesign/DECISIONS.md) and are not repeated here.

The date is the day the entry was recorded (2026-11-02), unless the entry names the day of the decision. "Code check" says
what the code did on 2026-11-02. Where it differs from the decision, the entry says so and nothing has been changed yet.

## Activity screen (approved 2026-11-02)

- **New screen:** named Activity, in the nav group System, built in career-os. No Runs screen exists here.
- **Design reference only:** "Runs", "Search funnel", "By source", "Run history" and "Fetching is paused" come from ApplyPack, a
  separate third-party app on the same server. No code is copied. "Fetching is paused" is ApplyPack's text, not career-os's, so
  it is not a career-os task.
- **Not ours:** the legacy "Search history" screen (openai gpt-4o-mini) belongs to the separate jobapply app.
- **Slices, in order (renumbered 2026-11-03):** (1) per-source outcome and run log, including a fix so a failed board cannot close its existing ads;
  (2a / 2b / 2c) the background Re-scrape: job, lock and event log; cancel; source order and timeouts; (3) `GET /api/runs` read API (the 90-day pruning at write
  time was built in slice 1) and the Activity screen, one row per run, Details with per-site stats plus errors and warnings with their level; (4) ad lifecycle changes, last.
- **Run log:** one record per run, written by `python/job_discovery/run_discovery.py`, so a manual Re-scrape and a pipeline run
  each log once.
- **Storage:** `data/analytics/`, private (0600 files, 0700 folders), atomic through `write_text_atomic`.
- **Trigger field:** allows `manual`, `pipeline` and `scheduled` (`pipeline` added in slice 1). No scheduler exists yet, so there are
  no paused rows, and nothing writes `scheduled`.
- **No AI.**

**Known gaps, none of this exists yet:**

- A miss counter, a last successful fetch per source, and per-source id snapshots.

**The bug slice 1 fixed:** the Greenhouse, Lever and Ashby providers caught each board's exception, logged it and went on, and
`run_discovery.py` counted jobs per provider, not per board, so one failed board among working ones could close that board's ads.

## Activity slice 1, as built (2026-11-02)

**Where:** `python/job_discovery/run_log.py`, called once from `run_discovery.py` `main()`. One file per run:
`data/analytics/runs/<startedAt, UTC, YYYYMMDDTHHMMSSZ>-<runId>.json`, 0600 in 0700 folders, atomic through `write_text_atomic`.
`CAREER_OS_ANALYTICS_DIR` moves the folder (tests set it). Records that started more than 90 days ago are removed when a record is
written. One file per run, not one shared file. The reason given then, that a Re-scrape took no pipeline lock so two runs could overlap, ended with
[slice 2a](#activity-slice-2a-background-re-scrape-2026-11-03); the one-file layout stays.

**Record, version 1:**

```json
{
  "version": 1,
  "runId": "<discovered_jobs.json meta.sourceRunId>",
  "trigger": "manual | pipeline | scheduled",
  "startedAt": "<ISO>",
  "finishedAt": "<ISO>",
  "status": "ok | partial | failed | skipped",
  "sources": [
    {
      "name": "greenhouse",
      "status": "ok | partial | failed | skipped",
      "read": 120,
      "kept": 8,
      "new": 1,
      "error": "<string or null>",
      "boardsFailed": ["<board or feed>"],
      "skipReason": "<string or null>"
    }
  ],
  "issues": [
    { "level": "error | warning", "source": "<name or null>", "message": "<string>" }
  ]
}
```

- **read:** ads parsed before the search, role and location filters. **kept:** past them, before dedupe. **new:** ads no earlier run
  recorded, counted after dedupe under the provider of the copy that won, so `new` is not a share of `kept`. Summed, it equals
  `meta.history.new`.
- **Extensible:** scored, closed, missing and expired are left out, because discovery does not know them yet. A later slice adds
  fields; a reader ignores what it does not know and treats a missing field as unknown. A breaking change raises `version`.
- **Run status:** `failed` when the exit code is not 0, no source ran, or every source that searched failed. `partial` when some
  searching source is not `ok`. A `skipped` source does not count, and warnings alone leave it `ok`. **`skipped` (owner correction,
  done):** every source was skipped, so nothing was searched; the record carries one run-level issue saying so. A non-zero exit
  still makes it `failed`.
- **Providers:** `fetch_jobs` still returns a list. The outcome is `provider.last_outcome` (`ProviderOutcome`, `base_provider.py`).

**Decisions made while building, beyond the brief:**

- **A failed board's open ads stay in `discovered_jobs.json`,** unchanged and open (`meta.history.keptFailedBoard` counts them), under
  the same conditions closing has: same search, role not listed under another copy. Not closing them alone would have dropped them
  out of the scored list. A board that fails every run therefore keeps its ads open until it is fixed or removed from
  `companies/*.json`; its error shows on every record.
- **What counts as a failed board:** an exception, an error status, an answer with no jobs list, and Lever's 404 on both hosts (that
  last one used to count as empty).
- **A provider that raises** is one failed source; the others still run and its board ads are held. Before, it stopped the whole run
  with nothing written.
- **A run that cannot start or that crashes** also writes a record, `failed`, with the reason as an error issue. `run_pipeline.py
  --skip-discovery` and a pipeline refused by its lock or setup write none: discovery did not run.
- **`--trigger` is passed by the caller:** `run_pipeline.py` passes `pipeline`, everything else defaults to `manual`. Cron goes through
  `run_pipeline.py`, so cron runs log as `pipeline` until a scheduler passes `scheduled`.
- **Status `skipped` (owner correction, done):** a source that did not search because it does not apply (Infostud or Joberty on an
  unsupported country, Wellfound not built) is `skipped`, not `ok`, with `skipReason` saying why and no warning. `skipReason` is an
  addition to the requested shape, so the reason is not lost. A failed Joberty `fetch_cities` can be told apart, because the board
  always lists places: an empty list is `failed`, not `skipped`.
- **An empty board holds (owner correction, done):** a Greenhouse, Lever or Ashby board that answers 200 with no jobs does not close
  its ads, even when other boards return jobs. They stay open in `discovered_jobs.json`, counted in `meta.history.keptEmptyBoard`, and
  the record gets a warning naming the board. A board that lists at least one posting closes its absent ads as before, even if the
  filters kept none of them. A board that really has emptied therefore keeps its ads open, with the warning, on every run.
- **A source that did not run keeps its ads (owner correction, done):** the open ads of a source with status `skipped` or `failed`
  stay in `discovered_jobs.json`, with no change to the ledger entry: no `closedAt`, no new `lastSeen`. `meta.history.keptSourceNotRun`
  counts them. This covers search-based sources too, and it ignores the "same search" condition: a source skipped for an unsupported
  country is by definition on a different search from the one that found its ads. A role now listed under another copy is still not
  carried. So after a permanent country change, Infostud's Serbian ads stay active until slice 4 decides otherwise.
- **Unchanged on purpose:** a source that ran successfully and did not return an ad. A search-based ad then leaves
  `discovered_jobs.json`, `scored_jobs.json` and the browser list with no badge, while the ledger keeps it open; a Greenhouse, Lever or
  Ashby ad closes and shows the badge for 14 days. A source that was not asked to run at all (not in `--providers`, or an opt-in source
  switched off) has no status, so its ads leave the file too. **For slice 4.** A row that left no longer loses the owner's data in
  the browser: see [offList](#offlist-rows-keep-the-owners-data-2026-11-03).
- **Scoring:** `scored_jobs.json` meta gains `discoveryRunId`; `sourceRunId` stays scoring's own. No scored counts are attached: a
  Re-score runs on its own, several times per discovery run, so it would overwrite an older record's counts.
- **Backups:** `data/analytics/` is not in `DATA_DIRS` in `scripts/backup-handler.js`, so run history is not backed up (nor is
  `skill_gap.json`, already there), though `PRIVATE_RESTORE` accepts the folder. Left as it is: a 90-day report is not clearly worth
  backing up.

**Known limitations (none of these closes an ad):**

- **`jobspy_adapter` can report a blocked LinkedIn search as a successful fetch with 0 ads,** because `jobspy_adapter.fetch_jobs` never
  raises. The source then shows `ok` with the 0-ads warning, so run statistics for `jobspy` are unreliable. It never closes ads
  automatically.
- `joberty_client.fetch_listing` keeps the pages it read and drops the rest, so a listing cut short still shows `ok`.

## Activity slice 2a: background Re-scrape (2026-11-03)

**What changed:** the Re-scrape button used to chain two HTTP calls from the browser, so closing the tab between them skipped scoring. Now `POST /api/rescrape` starts one
detached process, `python/run_rescrape.py` (discovery, then scoring, the same arguments and order as before; no enrichment, no judge, no model call, no cost), and the browser only
polls `GET /api/rescrape/status?after=N` every 2.5 s. A reload reattaches. `usePipelineAutoRefresh` is unchanged. There is no auto-resume, no cancel (2b) and no source order or timeout policy (2c).

**Lock (owner correction A):** one flock, `data/jobs/.pipeline.lock` (`python/job_scoring/pipeline_lock.py`; `CAREER_OS_PIPELINE_LOCK` moves it, and the tests always do), held across both steps.
`run_discovery.py`, `run_scoring.py` (not `--judge-preview`, which writes nothing), `enrich_jobs.py`, `run_pipeline.py` and `import_job_url.py` take it when run alone and exit 75 when it is held; Node answers 409.
A parent hands the lock to its step with `pass_fds` and `CAREER_OS_PIPELINE_LOCK_FD`, not a bare skip flag. The child checks the descriptor is that file and flock agrees, so a stale variable opens nothing.
Consequence: `kill -9` of the orchestrator alone does **not** free the lock while its orphaned step still writes; the kernel frees it when the last holder ends. The orchestrator's output goes nowhere (`stdio: 'ignore'`, its own session) and a step's output goes to an unnamed temp file, so no closed pipe can kill a run.

**Node and the lock:** Node cannot flock, so `run_rescrape.py reconcile` answers "is a run alive" and `hold` keeps the lock until its stdin closes. `/api/discovery/run`, `/api/pipeline/run` and `/api/rescrape` ask before they write the mirrors, because a refused request must not change an active run's input.
A tiny window remains between that question and the spawn: a run starting in it could read a just-rewritten mirror, and the second request still gets 409 from the lock. Node never signals a process.

**Event log and record:** `data/analytics/runs/<stamp>-<runId>.events.jsonl`, 600, `O_APPEND`, one `os.write` per event: `run_start`, `run_end`, `step_start`, `step_end`, `source_start`, `source_end`, `commit_start`, `commit_end`, `commit_incomplete`, `interrupted`, `error`.
A writer ends a torn last line before appending, so a torn line never swallows an event; the reader (`readEventsFile`, Node) skips unparsable lines and does not count a last line with no newline. The JSON record stays the summary: written at the start with status `running`, updated after each source, and with a Re-scrape it has `steps`. One run id runs from the record to `discovered_jobs.json meta.sourceRunId`.
Under the orchestrator discovery fills the record and does not finish it (`--run-id`). A direct run and a pipeline run finish their own record at the end of discovery, as in slice 1. `prune()` removes event logs with their records.

**Interrupted:** a record says `running` and the lock is free, decided while holding the lock, so a run starting that instant cannot be mistaken for a dead one. Checked at server start, when the child exits, on a status read of a running record, and at the start of any run. It becomes `interrupted`, with `finishedAt` left null because nobody saw it end.

**Partial writes (owner correction B), smallest mechanism:** each output file is atomic, the set of four (`job_history`, `raw_jobs`, `normalized_jobs`, `discovered_jobs`) is not, and `raw_jobs.csv` is not even atomic itself. `data/analytics/runs/.commit-in-progress.json` (600; not in a backup, and a restore skips it, so a restore cannot bring back a false alarm) is written atomically before the first file, rewritten after each with the list of files done, and removed after the last.
A marker on disk with the lock free means an incomplete commit. It is reported by `reconcile`, by the status endpoint (`incompleteCommit`, shown on the Jobs screen), in the dead run's record, and as an `error` issue and `commit_incomplete` event in every later run until a commit finishes. **Nothing is repaired.** Reporting does not clear it; only a later finished commit does, because all four files then come from one run.
**It does not heal everything:** the ledger keeps what the killed run recorded (first-seen dates, closures), which is why the later run's record carries the report for good. A second signal: the status endpoint sets `scoringBehind` when `scored_jobs.json meta.discoveryRunId` differs from `discovered_jobs.json meta.sourceRunId`, that is, discovery finished and scoring did not.

**Manual add (owner correction C): blocked, not serialised.** `import_job_url.py` takes the pipeline lock for `--job-json` (except `--check-only`, which writes nothing) and for URL import; `/api/jobs/manual/score` and `/sync` answer 409 `run_active`.
A short separate lock would not be enough: `run_scoring.py` reads `manual_jobs.json` at its start and replaces `scored_jobs.json` whole at its end, so a job added in between would still lose its scored row, and a merge at commit would be needed. Blocking costs no data, because the browser already saves the job unscored with its "Score now" retry; the message says a Re-scrape is running. The cost: no job is scored while a run is active, and a run can take over 20 minutes.

**Also 409 while a run is active:** Re-score, judge, old discovery and pipeline routes, URL import, backup restore. A restore holds the lock while it writes (`withRunLock`), refuses when the lock cannot be checked (503), and never replaces the lock file from an archive, since flock holds the inode.

**Killing the orchestrator:** killing the whole run (its process group, or the container) frees the lock at once. Killing the orchestrator alone keeps it until the orphaned step exits, so no second run can start mid-commit. That run's scoring never happens, and it is marked `interrupted` even if its discovery finished.

**Known gaps, not closed by this slice:**

- **Profile reset is not locked.** It moves the candidate intelligence away; a run past discovery then fails at scoring with "Missing intelligence". No job file is touched, and the reset's own copy is kept.
- **`competency_backup.py restore` is not locked.** It is a command the owner runs by hand and it replaces job files: run it only with no run active.
- **A pipeline run's enrichment and scoring have no events,** and a direct Re-score has no record, so the status endpoint does not show them as active; a start during one still gets 409.
- **The other screens still use the old blocking routes** (Pipeline screen, Re-score, judge). They are safe under the lock but not background jobs.

**Tests:** `tests/python/test_rescrape.py`, `tests/python/test_tailor_merge.py`, `tests/js/rescrape.test.js`, `tests/js/rescrapeRoutes.test.js`.

**Closed after the slice (2026-11-03):**

- **Tailoring can no longer revert a run's scores.** `run_tailor.py` used to write back the whole file it read minutes earlier. `save_tailored` now re-reads `scored_jobs.json` at write time and sets `tailoredAssets` on the rows it tailored, nothing else, under the pipeline lock. The lock is not held while it tailors, so tailoring does not block a run.
  If a run holds the lock at write time, tailoring waits for the run to end (it says so) rather than getting a 409 that would throw the finished work away; a row the run removed does not come back, and its documents stay in `data/resumes/`. Under the pipeline it uses the lock it was handed.
  Unchanged direction: a later full scoring rebuilds the file from the discovered jobs and leaves `tailoredAssets` out of it, as it always has. The browser keeps its copy and the documents stay on disk.
- **Backup export refuses instead of mixing runs.** `/api/backup/export` holds the lock until the last byte (a run starting meanwhile gets 409), answers 409 `run_active` during a run, 409 `commit_incomplete` when a commit marker is left over, and 503 when the lock cannot be checked. The marker stays until a commit finishes, so after a killed commit **no backup can be made until a Re-scrape has run to the end**. That is the owner's rule: such files may not match each other. A `.pipeline.lock` in an archive is harmless, because a restore skips it.

## Scrape, import, scoring (approved 2026-11-03)

**Why:** one process fetched, merged into the ledger, wrote four files and scored. A stop at any point either lost what was collected or left the files
disagreeing, and "an ad was not in this search" was allowed to read as "the ad is gone". The run becomes three steps, each safe to repeat:
**scrape** (collect, write staging only) -> **import** (the one commit) -> **scoring** (reads the committed data). Slice names: **S1 to S7**
([ROADMAP.md](ROADMAP.md#activity-screen---planned)); "slice 2b / 3 / 4" in older entries mean S6 / S7 / S5.

**Approved decisions (owner, 2026-11-03):**

- **Cancel and Interrupted import every validly written ad.** Ads already written to staging are imported; an unfinished source (no footer) never closes or
  changes an existing ad. A cancelled run is its own outcome, "scraping cancelled, collected ads imported", and is **not** a failed run. It skips scoring:
  `scoringBehind` shows and Re-score is one click.
- **Import is independent of scoring.** If import succeeds and scoring fails, the imported data stays saved and Re-score needs neither a scrape nor an import.
  A failed import does not start scoring.
- **The ledger (`job_history.json`) is the single source of truth; `discovered_jobs.json` is a view derived from it.** A generation mismatch is detected
  before any reader uses the data, the view is regenerated automatically, and if recovery fails the reader gets an explicit error, never the old results.
  The interruption between the ledger write and the view write is tested, and the same for `enrich_jobs.py` (which will write the ledger first).
- **No automatic ledger deletion.** The 90-day prune of closed entries (`PRUNE_AFTER_DAYS`) is switched off in S4a; no other prune is added until a retention policy exists.
- **Stale is a flag only, never a deletion.** Temporary values: 30 days and 3 successful runs of the same source and search key. `offList` logic is unchanged.
  5,000 rows in `discovered_jobs.json` is a warning, not a limit.
- **Source classes.** Greenhouse, Lever and Ashby are snapshot-based (a complete fetch may define the active set). Everything else is search-based (`lastSeen`;
  absence never removes an ad from discovery results). **Joberty stays search-based. Infostud is not classified snapshot-based** until its completeness is measured
  (the reported total matches the rows read, no page cap or guard fired, the categories cover the relevant set, stable over several runs, vanished ads confirmed closed); that measurement is last.
- **`raw_jobs.csv` and `normalized_jobs.json` are debug output**, best-effort and outside the commit set (S4a), then no longer written (S4b). Confirmed 2026-11-03: nothing reads them (no script, module, route, UI or backup list).

**Slices, each small and shippable:** S1 staging and ad records, then streaming (no behaviour change) -> S2 discard reasons and `externalId` -> S3 import `--dry-run`
and report, compared with the current commit on real runs -> S4a the switch (manual backup of `job_history.json` and the files beside it first) -> S4b mirror files ->
S5 lifecycle by source class -> S6 Cancel -> S7 Activity screen and `GET /api/runs`. Source order and timeouts (old 2c) come later.

### S1 as built (1a: store; 1b: streaming)

**Behaviour change for readers: none.** The old commit path (ledger, `discovered_jobs.json`, `raw_jobs.csv`, `normalized_jobs.json`, marker) is exactly as before;
`tests/python/test_staging.py` runs a discovery with and without staging and compares what the old path wrote. Nothing reads staging yet.

- **Where:** `python/job_discovery/staging.py`, `data/jobs/staging/<runId>/<source>.jsonl` and `run.json` (the run's search and ledger link). Folders 700, files 600, atomic where a file is
  replaced. One line is one record: `header` (source, search key, terms, locations, country), `batch` (a search, board, feed, page or ad: `part`, `read`, the canonical ads), `footer`
  (`status`, `complete`, `read`, `kept`, `total`, `staged`, `invalid`, `mismatch`, ...). Every append is one `os.write` and an fsync.
- **Unfinished means no footer.** A footer with `complete: true` is the only sign a source ran to its end; `partial`, `failed` and `skipped` footers have `complete: false`. An import may take the ads of any source, and may use absence only from a complete one.
- **Validation:** the same `problems()` check when writing and when reading (a canonical ad needs `jobId`, `provider`, `title`, text fields as text, strict JSON). An ad that fails is left out and counted in the footer; slice S2 gives reasons.
- **Torn writes:** the reader ignores a last line with no newline and any line that does not parse; whole lines before it are kept.
- **Never stops a run:** a writer that cannot write disables itself, logs once, and the run carries on; the run record gets a warning.
- **The ledger as the run found it:** `data/jobs/staging/<runId>.ledger-before.json`, a hard link made before any source runs. The ledger is replaced by rename, so the link keeps the old bytes (a copy where hard links are impossible). Its mode is the ledger's own (a link is the same file); the folder around it is 700.
- **Kept:** the newest 3 runs, whatever their state (slice S1 has no notion of "imported" yet; see the open point below). **Not in backups:** export skips `data/jobs/staging` and restore refuses to write into it.
- **Joberty:** `job_history.load(path, read_only=True)` returns an empty ledger for an unreadable file and renames nothing; `known_ids` uses it. A scrape must never rename a ledger.
- **Infostud's reported total** (`totalPrimaryItems`) is in its footer as `total`. Nothing compares it with the rows read yet.

**1b: when each provider stages.** A provider calls `self.stage(ads, part=..., read=...)` as soon as a part is complete, and returns the same ads in the same order to the old commit
path. `run_discovery.fetch_source` writes the footer when the fetch ends and stages the whole list of a provider that staged nothing; `mismatch` in the footer is `true` if what a
provider staged is not what it returned (tested for every provider below). `tests/python/test_staging_streaming.py`.

| Source | Stages | Granule | Not staged / limits |
|---|---|---|---|
| JobSpy (LinkedIn) | during collection | one search (term x place), after the title filter; an empty search is a part with 0 ads | a failed search is no part. The raw DataFrame (`raw_jobs.csv`) is not staged |
| Greenhouse, Lever, Ashby | during collection | one board, filtered as the whole list is | a failed board is no part; an empty board is a part with 0 ads |
| We Work Remotely | during collection | one feed (a repeat across feeds once) | a failed feed is no part |
| Infostud | during collection | one ad, after its full description is read (one slow request per ad) | the listing phase (up to 40 pages, about a minute) stages nothing: an ad is final only after its description is read. An ad outside the place filter is neither staged nor returned |
| Workable | during collection | one search term: the ads that term added | none twice |
| Joberty | during collection | one ad, as its detail arrives (or at once for an ad the ledger holds) | the listing pages (at most 3) stage nothing; an ad the ledger holds is staged with the empty description it is returned with, the commit restores the stored one; ads past the 25-detail cap are not returned, so not staged |
| Remote OK, Y Combinator | when the fetch returns, as `part: "all"` | the whole list | a single HTTP response: nothing to stream |
| Wellfound | nothing | - | skipped, not built |

**Open points:** pruning to 3 runs can remove a run's staging that was never imported, once import exists (S3/S4a must stop pruning an unimported run); a source's staged ads are kept in the order the provider returned them and are not de-duplicated (the existing dedupe still runs on the returned lists).

## offList rows keep the owner's data (2026-11-03)

**Rule:** discovery finds ads and never deletes what the owner did. Re-running discovery must not remove a status, AI insights,
tailored assets, outreach or legacy `applicationTracking`.

- **What is kept:** `importJobsFromFile` keeps a stored row the imported file lacks if it holds any of those: a status other than
  `new` (`rejected` included, so a rediscovered ad does not come back as new), or a non-empty `aiInsights`, `tailoredAssets`, `outreach`
  or `applicationTracking`. It is marked `offList: true`. A row with none of them is dropped as before, so old ads do not pile up.
  Timestamps alone, `applied: false` and an outreach with status `none` and empty lists do not count as data.
- **When it returns:** matched on `jobId`, then lowercased URL, as before. It loses the mark and keeps all its data.
- **Where it is hidden:** the Jobs list (`filterJobs`), its totals, filter options and exports, `computeJobStats`, `computeOutreachMetrics`,
  the Dashboard's tailored count, the pipeline counts, and the AI features that read the whole list (`topJobs`, skill gap). The "Show
  jobs absent from current results" filter lists them.
- **Where it stays visible, on purpose:** Job Details and the drawer by id, Resume Library, the tracker table, and the Outreach contact
  list and exports, because each of those is the owner's own record. The backup, the tracker migration and the AI redaction hints still read
  these rows.
- **Scoring and discovery never see it:** the browser sends only hand-entered jobs to the server, and `run_scoring.py` reads only the
  discovered and manual files (`tests/python/test_scoring_input.py`). The file contents did not change.

**Terms, two different states:**

- **offList** = absent from current results. A browser mark on a row. It says nothing about whether the ad closed.
- **orphan** (Step 5) = a user record with no matching active discovery record.

**Temporary:** `offList` is a protection until the Step 5 job-state overlay (`data/jobs/job-state.json`). The Step 5 migration must treat
`offList` rows as orphans, not as active records. Its plan turns a browser-only job into a `record` entry, which is an active job, so this
is an exception to that rule ([plan, section 2.3](redesign/STEP5_SERVER_MASTER_PLAN.md)).

**Limits of this step:**

- Data lost before this change is not restored; only rows still in the browser are protected.
- A row kept under another browser or profile is not shared: the data still lives in one browser's `localStorage`.
- When the list does not fit `localStorage`, `saveJobs` stores it without `description`, `llmFacts` and `engineShadow` (`slimJob`). A
  scored row gets them back from the file; an `offList` row gets its ad text from the ledger or its application's posting when Job Details opens.
- Carry-over still matches on `jobId` or URL only. A status on one copy of a role is not moved to another copy with a different URL; the
  old copy is kept `offList` instead.
- Job Details saying a job is absent from current results, opening an ad whose row was dropped, and counting an application whose ad is
  `offList` are solved by [the next decision](#applications-open-without-the-ad-history-read-path-2026-11-03).

## Applications open without the ad; history read path (2026-11-03)

**Rule:** an application is an independent record. It opens, and its notes, follow-ups and history work, from its own frozen posting,
whatever discovery returns.

- **Read path:** `GET /api/jobs/history/<jobId>` (`scripts/job-history-read.js`) returns one job's snapshot from `job_history.json` with
  `firstSeen`, `lastSeen` and `closedAt`, and never another job, `llmFacts`, `roleKey` or `seenUnder`. It is read-only: it writes, renames and creates nothing,
  so even a corrupt ledger stays where it is (503). The file is parsed once into a `Map`, and again when its inode, size or mtime changes. The id must match the
  store's job id rule. An unknown id, a missing ledger and an entry with no snapshot are 404 `{ found: false }`.
- **Job Details order** (`modules/jobs/jobResolve.js`): stored row, scored or discovered file, ledger, the application's frozen posting (latest non-voided attempt, else the
  latest). Missing ad text on a stored row is filled from the ledger, then the posting, except on a hand-entered job.
- **Notice "Not in the latest run":** shown for an `offList` row or a job the read file lacks, with the last-seen date. A posting's capture date is reported as such, never as last seen.
  When no file could be read the page says nothing unless the row is already marked. It says nothing about the ad being closed. Hand-entered jobs never show it.
- **Fallbacks are display only:** a ledger or posting record is never written to the browser's list. A saved row would count as an active job in stats, exports and AI
  contexts, and Step 5 would migrate it as one. A job with no stored row therefore hides tailoring, AI tools and contacts, which write to a row; the tracker panel
  writes to the application store and needs none.
- **Opening:** a board card or tracker table row uses the drawer when a row exists, otherwise Job Details by job id. The drawer's "Open full details" is enabled by a stored row, an application
  or a ledger entry.
- **Counting:** the tracker stat cards (Applications, Dashboard, Jobs screen) and the AI `jobStats` count from the store (`trackerStats`): one per non-voided application, as the board and
  Application Statistics do, so two attempts at one job count twice. `computeJobStats` keeps counting rows. Until the store loads, the Dashboard shows "…"; the other screens and the AI context use the row count.
- **AI:** the application context holds an application with no row through the same `summarizeJob` whitelist. `topJobs` and the skill gap read only rows in current results. Nothing in
  `aiContextBuilder.js` reads the ledger, so an ad known only to the ledger reaches no context. Scoring and exports are unchanged.
- **Not the long-term source:** `localStorage` still holds the job list, and this path works around that rather than replacing it. Step 5 follows
  ([plan](redesign/STEP5_SERVER_MASTER_PLAN.md)).

**Limits of this step:**

- A voided application stays out of the board, the table and the counts (TRACKER S4 is unchanged). Its Job Details opens only by link, showing Restore; its notes and follow-ups are editable after a restore.
- An application saved with no job id has no route, so its card shows a notice. The UI always sends a job id, so none is known to exist.
- A row with legacy `applicationTracking` that was never migrated no longer counts in the tracker stat cards once the store has loaded. It stays in the tracker table, and the migration moves it into the store.
- Per-job AI tools on a stored `offList` row are unchanged: they run only when the owner opens that job and asks.

## Ad lifecycle rules (narrowed 2026-11-02)

- **Closed:** the source explicitly says the ad is closed.
- **Missing:** absent in a successful fetch of the same source.
- **Expired:** only Greenhouse, Lever and Ashby can reach it, after two consecutive successful and complete fetches of the same
  board.
- **Search-based sources** (LinkedIn / JobSpy, Infostud, Workable, Joberty) show Missing and never become Expired automatically.
- **What is not a miss:** a failed or partial fetch, and a changed search.
- **0 ads** is a warning and never closes everything.
- **A source that did not run** (`skipped` or `failed`) keeps its ads as they were (slice 1 correction).
- **`expiresAt`** (Infostud, Joberty) is a deadline: displayed only, never used as Closed or Expired.

**Code check, differs, built last (slice 4):** `python/job_scoring/job_history.py` has one state, `closedAt` / `isClosed`, and no
Missing or Expired.

- One absence closes a job, not two.
- No provider reads an explicit "closed" from the source.
- A provider that returned 0 jobs closes nothing, and neither does a Greenhouse, Lever or Ashby board that answered with no jobs,
  which matches the rule. The run log gives each a warning (slice 1).
- The UI's "Closed" badge means "No longer listed since ...", which under these rules would be Missing or Expired.

## AI in scraping - pending, needs separate approval with cost

- AI only as a second stage after the deterministic parser and filter, only on ads that passed the filter, and only for
  missing or uncertain fields and translation.
- First measure how many ads have empty or uncertain fields.
- The Activity screen itself has no AI.

**Code check:** enrichment (`enrich_jobs.py`, `llmFacts`) already sends ads to a model after discovery, and skips ads the board
already places outside `allowedLocations`. This decision does not say how it relates to that step.

## Location cap rule - approved

| Case | Result |
|---|---|
| Outside allowed, no remote signal | Cap 40 |
| Remote with an explicit disallowed geography | Cap 40 |
| Remote, Worldwide or EU with no confirmed restriction | UNKNOWN, no cap, flag "Verify location" |
| Confirmed from Serbia | PASS |

UNKNOWN gets no matching priority. Richer location extraction is later and needs AI cost plus explicit approval. The geo
audit is parked.

**Code check, matches:** `scorer.py` (`OUTSIDE_ALLOWED: 40`), `location_text.py`, and `match_engine/shadow.py` (a passed
location goes before an unknown one). One addition in the code: an ad stating the Balkans, or stating worldwide availability, is also
`pass`. The fix-scoring task in [ROADMAP.md](ROADMAP.md) must not change this rule.

## Matcher (decided 2026-10-28)

- **Cache key:** a hash of the requirement ids and texts.
- **`requirement-remap`:** applied on read.
- **Top 50 tie-break, deterministic:** score, location passed, provisional ratio ascending, newer, fingerprint.
- **Plan:** the matcher plans on the local Layer 1 score, without the judge.
- **Duplicate canonical ids:** not merged.
- **Relocation:** `abroad` stays.

**Code check:**

- Tie-break, plan and remap match (`match_engine/shadow.py` `plan`, `matcher.py` `posting_from_job`).
- `requirements_hash` also covers each requirement's kind, importance and quote, and it is one part of a key with the ad
  fingerprint, profile version and prompt version. That is wider than this entry.
- `abroad` is still a relocation option (`dimensions/location_match.py`).
- Not verified: "duplicate canonical ids". `competencies.py` refuses a repeated id within a list, but nothing states this
  decision in the code.

Earlier related decision: top 50 per run ([redesign/DECISIONS.md](redesign/DECISIONS.md), 2026-10-25).

## AI budget and the subscription exception

- Paid steps need separate approval.
- The owner set `dailyLimit` 10 and `monthlyLimit` 25.
- `claude-code` under the owner's flat subscription is class `subscription`: cost 0, default off, allowlist `jobAnalysis`
  only, daily cap 5, with ledger rows. Rules: AI budget gate in [../CLAUDE.md](../CLAUDE.md).
- Ollama is not installed.

**Code check:**

- `data/ai/settings.json` holds those limits, and the subscription switch is on there with `jobAnalysis` only. Off is the
  code's default, not the current state. The same file also caps calls at `maxCallsDaily` 5 and `maxCallsMonthly` 25.
- Ollama: no binary on the host or in the container, and no running service. It remains a provider in the code and the price table.

## Import redesign

**Approved sources:** PDF, DOCX, TXT / MD, pasted text, LinkedIn data ZIP, JSON Resume, LinkedIn PDF, manual form.
**Rejected:** PDF URL, LinkedIn profile URL.

**Design:**

- A transient `ImportDraft`, from a stateless `POST /api/profile/import/parse`, in `python/profile_import`.
- No new dependencies and no new AI call.
- A review-and-correct screen before saving.
- Import creates a new "My CVs" entry that is not automatically active.
- Unplaced text goes only into `rawText`.
- A DOCX original is not stored.

Slice order and status: [ROADMAP.md](ROADMAP.md). Draft shape: [redesign/data-shapes.md](redesign/data-shapes.md).

**Code check, differs in one place:** the first CV imported becomes the active one (`willBeActive` in `importDraft.js`); any
later import does not. The rest of what is built matches.

## Product principles

- **Other users:** Holojob will be used by other users, so no personal data is hard-coded.
- **English only:** no Serbian, Cyrillic or multilingual parsing. AI translates non-English ads and CVs. English
  section-header synonyms live in one data file.
- **Access:** no login and no basic auth; home LAN plus Tailscale. Already recorded:
  [redesign/DECISIONS.md](redesign/DECISIONS.md), 2026-10-29.

**Code check, differs:**

- **Single user:** principle 15 in [redesign/DECISIONS.md](redesign/DECISIONS.md) and [../CLAUDE.md](../CLAUDE.md) still say
  "single user for now".
- **Hard-coded market:** the `serbia` provider group ([ROADMAP.md](ROADMAP.md), Tech debt leftovers) and Serbian place names in
  `location_text.py`, which is also how "Confirmed from Serbia" above is read.
- **Serbian parsing exists:** `src/data/sectionHeadings.json` has `en` and `sr` blocks and a Cyrillic transliteration, used by
  `python/profile_import/vocabulary.py` and `src/utils/headingVocabulary.js` (commit `10bf5d3`, 2026-11-01). Its removal is
  not scheduled.
- **Serbian sites:** [redesign/DECISIONS.md](redesign/DECISIONS.md) keeps "job sources incl. Serbian sites" in scope. This
  entry is about parsing, and does not say whether those sources change.
- **No AI translation exists:** the prompts in `job_import/ad_ai.py` and `cv_analysis/analysis.py` tell the model not to translate.
- **One data file:** `sectionHeadings.json` is that file for the import parser and the PDF extractor, but
  `resume_generator/resume_parser.py` has its own English list (`SECTION_STEMS`).

## Jobs table - open discussion, not final

Meaning today, confirmed in the code: the New badge is `job.isNew` (3 days or less, `NEW_WINDOW_DAYS`), and Status is
`job.status`.

| Agreed direction | Status on 2026-11-02 |
|---|---|
| Display names "Just found" and "Unreviewed", data unchanged | Done (`jobHistory.js`, `jobStatusLabel`) |
| Warnings in the Location cell | Done (`AuthorizationBadge`, `33e5a18`) |
| Icon actions with tooltips | Done (`JobActions`, `63f216c`) |
| Compact rows | Done (`63f216c`) |
| Remove the shadow badge from the table, keep it on Details | Not done: `EngineShadowBadge` is still in `JobTable.jsx` (table and cards), and is on Details |
| Applied button goes to the tracker (a separate task) | Not done: the table button only sets `job.status` to `applied_manually` through `updateJobStatus` and writes no application |
