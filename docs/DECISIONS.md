# Holojob - Decisions

Short entries for decisions that were not yet written down. Planned work is in [ROADMAP.md](ROADMAP.md). The product
principles and the older owner decisions stay in [redesign/DECISIONS.md](redesign/DECISIONS.md) and are not repeated here.

The date is the day the entry was recorded (2026-11-02), unless the entry names the day of the decision. "Code check" says
what the code did on 2026-11-02. Where it differs from the decision, the entry says so and nothing has been changed yet.

## Activity screen (approved 2026-11-02)

- **New screen:** named Activity, in the nav group System, built in holojob. No Runs screen exists here.
- **Design reference only:** "Runs", "Search funnel", "By source", "Run history" and "Fetching is paused" come from ApplyPack, a
  separate third-party app on the same server. No code is copied. "Fetching is paused" is ApplyPack's text, not holojob's, so
  it is not a holojob task.
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
`HOLOJOB_ANALYTICS_DIR` moves the folder (tests set it). Records that started more than 90 days ago are removed when a record is
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

**Lock (owner correction A):** one flock, `data/jobs/.pipeline.lock` (`python/job_scoring/pipeline_lock.py`; `HOLOJOB_PIPELINE_LOCK` moves it, and the tests always do), held across both steps.
`run_discovery.py`, `run_scoring.py` (not `--judge-preview`, which writes nothing), `enrich_jobs.py`, `run_pipeline.py` and `import_job_url.py` take it when run alone and exit 75 when it is held; Node answers 409.
A parent hands the lock to its step with `pass_fds` and `HOLOJOB_PIPELINE_LOCK_FD`, not a bare skip flag. The child checks the descriptor is that file and flock agrees, so a stale variable opens nothing.
Consequence: `kill -9` of the orchestrator alone does **not** free the lock while its orphaned step still writes; the kernel frees it when the last holder ends. The orchestrator's output goes nowhere (`stdio: 'ignore'`, its own session) and a step's output goes to an unnamed temp file, so no closed pipe can kill a run.

**Node and the lock:** Node cannot flock, so `run_rescrape.py reconcile` answers "is a run alive" and `hold` keeps the lock until its stdin closes. `/api/discovery/run`, `/api/pipeline/run` and `/api/rescrape` ask before they write the mirrors, because a refused request must not change an active run's input.
A tiny window remains between that question and the spawn: a run starting in it could read a just-rewritten mirror, and the second request still gets 409 from the lock. Node never signals a process.

**Event log and record:** `data/analytics/runs/<stamp>-<runId>.events.jsonl`, 600, `O_APPEND`, one `os.write` per event: `run_start`, `run_end`, `step_start`, `step_end`, `source_start`, `source_end`, `commit_start`, `commit_end`, `commit_incomplete`, `interrupted`, `error`.
A writer ends a torn last line before appending, so a torn line never swallows an event; the reader (`readEventsFile`, Node) skips unparsable lines and does not count a last line with no newline. The JSON record stays the summary: written at the start with status `running`, updated after each source, and with a Re-scrape it has `steps`. One run id runs from the record to `discovered_jobs.json meta.sourceRunId`.
Under the orchestrator discovery fills the record and does not finish it (`--run-id`). A direct run and a pipeline run finish their own record at the end of discovery, as in slice 1. `prune()` removes event logs with their records.

**Interrupted:** a record says `running` and the lock is free, decided while holding the lock, so a run starting that instant cannot be mistaken for a dead one. Checked at server start, when the child exits, on a status read of a running record, and at the start of any run. It becomes `interrupted`, with `finishedAt` left null because nobody saw it end.

**(Superseded by S4a, see "S4a as built": the marker is no longer written and a stop between the two writes is rebuilt by the next reader.)** **Partial writes (owner correction B), smallest mechanism:** each output file is atomic, the set of four (`job_history`, `raw_jobs`, `normalized_jobs`, `discovered_jobs`) is not, and `raw_jobs.csv` is not even atomic itself. `data/analytics/runs/.commit-in-progress.json` (600; not in a backup, and a restore skips it, so a restore cannot bring back a false alarm) is written atomically before the first file, rewritten after each with the list of files done, and removed after the last.
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
- **No automatic ledger deletion.** The 90-day prune of closed entries (`PRUNE_AFTER_DAYS`) is switched off in S4a (done: the importer calls `apply_run(prune=False)`); no other prune is added until a retention policy exists.
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
- **Kept:** every run until S4a, which prunes by status (the keep-3 pruning of 1a was removed in S3, owner correction; see S3 and S4a as built). **Not in backups:** export skips `data/jobs/staging` and restore refuses to write into it.
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

**Open points:** staging grows until S4a deletes by status; a source's staged ads are kept in the order the provider returned them and are not de-duplicated (the existing dedupe still runs on the returned lists).

### S2 as built: discard reasons and externalId

**Behaviour change for readers: none.** No filter rule or result changed; the old commit path writes the same files (`tests/python/test_discards.py` runs a discovery with and without staging and compares them).
`tests/python/test_discards.py` also holds the old `is_relevant_role` and `filter_jobs` answers against the new reason-returning functions over a table of titles, positions, places and search terms.

- **`staging/<runId>/discards.jsonl`:** one line for every ad a provider drops at source stage, written while it collects, with the same rules as the ad files (exclusive create, one whole line per write, fsync, 700 / 600; a torn last line is ignored by `staging.read_discards`).
  A line is `{t, source, externalId, reason, jobId, title, company, location, url, counted, part}`. **Never a description.** `jobId` is the id the ad would have had (the same function as the canonical job), when it can be computed.
- **Reason codes (stable):** `title_excluded:<phrase>` (the first excluded phrase in the title; it beats a board's own position), `title_not_matched`, `search_terms_not_matched` (none of the search terms in title or description: the `filter_jobs` test), `location_not_matched`,
  `country_not_matched`, `no_title`, `no_url` (Workable), `unparsable_row` (a row that is not an ad: RemoteOK's legal notice, a Joberty row with no numeric id), `not_listed` (Ashby), `no_detail_text` and `detail_cap` (Joberty).
  The rules are `role_filter.role_drop_reason` and `base_provider.filter_drop_reason` / `place_drop_reason` / `split_by_filter`; `is_relevant_role` now answers `role_drop_reason(...) is None`, and `filter_jobs` is untouched.
  Infostud, Workable and Joberty keep their strict place check (location AND country, no forgiveness for a place the search names); they use `place_drop_reason`, and so does the list they return.
- **Invariant, per source:** `read == kept + discarded`. `counted` is true for an ad that was part of the source's `read` count; a row dropped before it was counted (no title, no id, an address-less Workable row after the first) is `counted: false` and is not in the sum.
  The footer holds `discarded`, `discardedUncounted`, `discardReasons` and `discardMismatch` (true when the sum fails; null for a failed source, whose reading stopped half way, or when staging itself failed). A repeat of an ad already seen in the same fetch (Infostud pages, WWR feeds, Workable terms, Joberty ids) is a copy, not a drop, and is not recorded.
- **`externalId`:** the id the source itself gives an ad (Infostud's row `id`, Workable's `id`, Greenhouse / Lever / Ashby `id`, Remote OK / YC `id`, LinkedIn's `id` from JobSpy, the RSS `guid` of We Work Remotely, Joberty's `joberty:<id>`). It is kept **beside** the canonical job: in the batch line (`externalIds`: jobId -> id) and in the discard line; the canonical job, `jobId` and every live file are unchanged
  (Joberty's canonical job has carried an `externalId` field since it was built; that is unchanged). A source that gives no id (some JobSpy boards, RSS items without a guid) leaves it null; nothing is invented. `normalize()` of Infostud and Workable now keeps the id in their raw row; their canonical ads are built from named fields and do not carry it.
  `staging.SourceStage.external_ids` reads it.

| Source | Reasons recorded (counted) | Not counted (before `read`) | Not recorded |
|---|---|---|---|
| JobSpy | `title_excluded:*`, `title_not_matched` | `no_title` (rows `normalize_jobs` drops) | - |
| Greenhouse, Lever | `search_terms_not_matched`, `location_not_matched`, `country_not_matched` | `no_title` | a board that failed (no ads known) |
| Ashby | the same | `no_title`, `not_listed` | the same |
| We Work Remotely | `search_terms_not_matched`, `location_not_matched`, `country_not_matched` | `no_title` | a repeat in another feed |
| Remote OK | the same | `no_title`, `unparsable_row` | - |
| Y Combinator | the same | `no_title` | - |
| Infostud | `title_excluded:*`, `title_not_matched`, `location_not_matched`, `country_not_matched` | - | a repeated row (a later page) |
| Workable | `title_excluded:*`, `title_not_matched`, `location_not_matched`, `country_not_matched`, `no_url` | further rows with no address | an ad seen again under another term |
| Joberty | `title_excluded:*`, `title_not_matched`, `location_not_matched`, `country_not_matched`, `no_detail_text`, `detail_cap` | `unparsable_row` | a repeated id |
| Wellfound | none (skipped) | - | - |

Limits: Infostud's role drops are known after the listing and are written then (`part: "listing"`), before any description is read; a source killed before its footer has discards for what it had finished, and no `discardMismatch`.
`staging.problems` still only requires `jobId`, `provider` and `title`: the import needs full validation (ROADMAP, review requirements for S3 / S4a).

### S3 as built: the importer, `import --dry-run` and the import report

**Boundary (owner correction 4):** S3 changes **no discovery, ledger, `discovered_jobs.json` or scoring result.** What it adds to the live path is diagnostics only: the run record gets a `staging` field, staging gets a `status.json`, `staging/<runId>.discovered-before.json` is one more hard link, and
`apply_run` takes an optional `run_id` that only the importer passes. `tests/python/test_import.py` runs a discovery with a staging failure of three kinds and compares every output file with a run without one: byte-identical apart from timestamps and run ids.
Nothing is imported for real in S3: `import_run.py` refuses without `--dry-run` (the real import is S4a).

- **No new rule.** `python/job_discovery/importer.py::plan_import(run, ledger, previous, now=None)` calls the code the old commit calls (`_collapse` twice = `dedupe_jobs`, `job_history.apply_run`, `export_jobs.discovered_payload`). It is a pure function of the staging run, the ledger as it stands and the discovered file the run replaced; it reads and writes no file and changes none of its arguments. `now` is the end of the run's last source (its footer), so the same run always gives the same bytes; the dry run passes the time the old commit used instead.
- **Full validation before any ledger change** (`validate_ad`, stable codes): every canonical field present and text, `isRemote` boolean, `jobId` / `provider` / `title` not empty, lengths bounded, `jobId` without whitespace, `provider` equal to the source it came from, `jobUrl` empty or `http(s)://host...`, `scrapedAt` an ISO time, strictly storable as JSON. A rejected ad is left out and listed with its code (counted in full, first 50 named); the rest of the import goes on. Never silent. Staging's own check (`jobId`, `provider`, `title`) stays as it is.
- **A source that lost an ad cannot say another is gone.** A source with no footer (killed, cancelled), a footer of `failed` or `skipped`, a footer with `mismatch` or `invalid` ads, or with rejected ads is held like a source that did not run: the ads it wrote are imported, no ad it did not write is closed or changed. A `partial` source keeps the old per-board rule (the ads of its failed boards are held, its other boards count as read). A provider named in the manifest with no file is unfinished.
- **Refused, nothing planned:** a run whose staging failed (`status.json` says `ok: false`), a missing or foreign `run.json`, a run with no usable time. A run with no `status.json` (never reached its end) is planned and marked `unfinished`.
- **Idempotent:** a ledger whose `lastImport` is this run is returned as it is (`alreadyImported`), the same run twice gives identical bytes of the ledger and the view. That is the importer's only memory. `force=True` applies the run again anyway: the ledger data is then identical (apply_run alone is idempotent), only the counts of what that application changed differ.
- **Order is not controlled, and it matters (owner correction 1).** `apply_run` stamps `lastSeen` with the run's own time and closes or reopens by what that run lists, so applying an older run after a newer one moves `lastSeen` back and can reopen an ad the newer run closed. The importer does exactly that and nothing more: A then B and B then A give different ledgers, and the test (`test_import_order_changes_the_result_exactly_as_apply_run_does`) pins the actual behaviour.
  **Decided for S4a (owner): a real import refuses a run older than `lastImport.startedAt`**, with an override for recovery; see "S4a as built". S3 itself adds no such rule.
- **Dedupe is here.** Staged ads are not deduplicated (S1); the import runs the two existing passes (same address, then same title and company) and reports `duplicatesRemoved` and `crosspostsMerged`.
- **The report** (`plan_import(...).report`, printed by the CLI, written only with `--report-file`): per source its state (`complete`, `partial`, `failed`, `skipped`, `unfinished`), staged / imported / rejected, whether it was held as not run and why; `duplicatesRemoved`, `crosspostsMerged`, `rejected` with codes and examples, `thinDescriptionReplaced`, `heldFailedBoard`, `heldEmptyBoard`, `heldSourceNotRun`, the ledger counts, `incompleteSources` and `complete`.
- **The view from the ledger alone.** With `run_id`, `apply_run` stamps each entry `lastRunId` / `lastRunPos` (found) or `heldRunId` (kept open), and the importer writes `lastImport` (run id, time, the view's meta) into the ledger. `derive_view(ledger)` rebuilds `discovered_jobs.json` from those: same ads, same order, same `isNew` / `isClosed`. It reads only the ledger, changes nothing and returns a copy (tests: deep-copy comparison, two runs give the same bytes). It raises `ViewError` for a ledger no import produced. These stamps exist only in an imported ledger, never in the one the old path writes.
- **`import_run.py --run RUNID | --latest --dry-run [--limit N] [--report-file]`.** It takes the pipeline lock (exit 2 when a run is active), replays the staged run on `staging/<runId>.ledger-before.json` and `...discovered-before.json` (a run staged before the second link existed is replayed but marked `NOT exact`), and compares with `job_history.json` and `discovered_jobs.json` **only if they are this run's** (`meta.sourceRunId`): four counts, ledger and view each replay vs committed, and `derive_view` vs replay and vs committed. Each difference is a path with both values. **Excluded and listed in the output:** `ledger.updatedAt`, `ledger.lastImport`, the importer's per-entry stamps, `meta.generatedAt`, `meta.sourceRunId`. Timestamps are not excluded: the time the old commit used is read back from the committed ledger (the latest `lastSeen` / `closedAt`).
  Exit codes: **0** compared, zero differences; **1** differences; **2** error, refused run, a run active, or no `--dry-run`; **3** nothing to compare with (the committed files belong to another run). A later run, or an enrichment that rewrote the files, makes a dry run of an older run exit 3 or show differences: dry-run right after the Re-scrape you want to check.
- **Default writes nothing** (tests: tree and hash snapshot before and after, with every writer under the root patched to raise). `--report-file` writes `staging/<runId>/import-report.json` (600, atomic) and nothing else.
- **Staging failure (owner correction 4).** `staging.StagingRun.finish()` runs after the sources: not ok when the run folder could not be made, a source or the discards log stopped writing, a source's staged ads are not what it returned, or ads were left out for not being whole. The run record gets `staging: {ok, problems}`, an `error` issue, and a run that would be `ok` is `partial`; the folder gets `status.json`. An import refuses such a run (`staging_failed`). Discovery's output is the same (tested for a source that stops writing, a folder that cannot be made, a provider that stages less than it returns).
- **Retention (owner correction 3).** There is no "imported" marker and the keep-3 pruning is gone: **nothing removes a staging run** until S4a, which will delete by status (never a run waiting for import or recovery). `staging.usage()` and the CLI summary say how much room staging takes, each hard-linked file once. Expect about the size of the ledger plus the discovered file per run (the links keep the old bytes alive), plus the ad files: roughly 25 to 30 MB a run at today's sizes; look at the CLI line and clean old runs by hand if needed until S4a.

## Owner decisions: baseline score, role filter, Infostud, testing (2026-11-03)

Recorded from the owner's addendum. Docs only; no code changed. Backlog entries: [ROADMAP.md](ROADMAP.md#activity-screen---planned).

1. **Scoring baseline.** A made-up manual job with a junk description scored 44 (Weak, P3, Maybe; Role 45, Skill 20, Industry 55, Experience 65, Location 50, Culture 58).
   The owner expects at most about 5 and an "insufficient data" label. **Deferred** to the end of the current Activity work and solved with the scoring fix
   ([ROADMAP.md](ROADMAP.md#fix-scoring-skill-extraction-scope-requirement-weighting-domain-transferability---todo)). Any fix stays in `scorer.py`, not in a prompt (architectural rule).
2. **Role filter too strict.** `python/job_discovery/providers/role_filter.py` checks `TITLE_EXCLUDE` ("project manager", ...) first, and an ad with no include term is dropped
   silently with the reason `title_not_matched` (Infostud: 392 of 409 dropped, for example ad 765172 "Medior Dev Project Manager Niš", position "IT Project Manager").
   Idea: three tiers (clear no / clear yes / borderline kept with a "for review" flag; AI only on a borderline title plus a short description, which needs its own approval with cost, see
   "AI in scraping"). Depends on the scoring fix and on the discard-reason data from S2. **Deferred.**
   **Code check on whether the exclude was deliberate:** `.claude/rules/scoring.md` and this file say nothing about it. The only mentions are the module docstring (one shared term list so clients do not drift)
   and `docs/ARCHITECTURE.md` open problem 8, which says `role_filter.py` "would tighten" providers that match the whole ad. So the exclude of "project manager" was a deliberate noise cut at the time (commit `c346ad3`),
   not an owner decision recorded anywhere; the owner now finds it too strict.
3. **Infostud stays unclassified** (not snapshot-based) until its fetch coverage is confirmed; the six checks are postponed to the end. Consistent with the entry under "Scrape, import, scoring".
4. **Process rule.** Every decision is recorded in the md files, not only in chat. The owner tests everything at the end; no merge and no production before the real-container integration check.

## S4a as built: the switch (2026-11-03)

**Owner decisions recorded first:**

- **The S3 dry-run gate** was reduced by the owner from 3 real runs to 2. In fact **3** real Re-scrapes were compared with **zero differences** (runs `4ceb98880ded`, `307c5e408af3`, `bb94862330c0`). **None of them contained a closed or a reopened ad.** Closing and reopening are covered by tests and by the five historical runs the S3 tests replay, not by real data.
- **Order guard.** A real import **refuses** a run whose start is older than `ledger.lastImport.startedAt`, with an explicit message (`older_run: ... would move lastSeen backwards ...`); there is no silent skip and `lastSeen` never goes backwards. The override is explicit and off by default: `importer.plan_import(..., allow_older=True)`, on the command line `import_run.py --run RUNID --import --allow-older`. Nothing in the live path passes it. Tested (refusal changes no byte; the override works and is recorded as the last import).
- **Before the switch:** the owner made a manual backup of the ledger (`data/jobs/job_history.json.bak-pre-s4a`). Nothing here deletes or rewrites it.

**The live path.** collect to staging (streaming, S1) -> `importer.import_staged_run` (the S3 code, no new rule) -> the ledger `job_history.json` is the single source of truth -> `discovered_jobs.json` is **derived** from it (`view_guard.derive_view`), carrying `meta.ledgerGeneration`. `run_discovery.py` no longer dedupes, applies history or writes `discovered_jobs.json` itself; it fetches, stages, imports.
Commit order: **ledger first, then the view**, both inside the view lock (`view_guard.commit`). The old commit marker is no longer written. A marker left on disk by the old protocol is cleared by the first finished commit (`run_log.clear_commit_marker`); `run_rescrape.reconcile`, the status route and the backup export still report one that is there.

**Generation.** The ledger gets `generation` (its first key, bumped by every import and every enrichment that changes it) and the view `meta.ledgerGeneration` (first key of its meta), so a check reads 4 KB of each file, not 19 MB. Consistent = equal; a ledger and a view that both have none are the pre-S4a pair and are left alone, so the existing ledger loads and migrates with no manual step and no conversion (checked read-only on a copy of the real 1,820-entry, 19 MB ledger and the real 335 ads: all valid, import 0.4 s, nothing lost, rebuild 0.1 s). The first import makes it generation 1.

**Every reader checks first** (`view_guard.ensure`, `scripts/view-guard.js`): `run_scoring.py`, `enrich_jobs.py`, `import_job_url.py`, `run_pipeline.py`, a Re-scrape's own start (so the discovered file it keeps beside its staging is the ledger's), Node's `GET /api/discovery/jobs`, `GET /api/discovery/status`, the Re-scrape status (`scoringBehind`) and the **backup export** (inside the pipeline lock, before the archive is built). A mismatch is rebuilt from the ledger and then used. If it cannot be rebuilt the reader stops with the reason (Python: exit 1 and a message on stderr; Node: **503** `view_unrecoverable` with the message): **a stale view is never served.** Tailoring reads `scored_jobs.json`, not the view, and needs no check.
The Node and Python checks are the same function written twice; `tests/fixtures/view-generation.json` holds the cases both run.

**Lock rules (deadlock-safe).**
- Recovery and the commit take **one short lock of their own**, `data/jobs/.view.lock` (flock, polled, 60 s then an explicit error). **They never take the pipeline lock.** So it does not matter whether the caller holds it: a run's scoring step holds it (handed down), a backup export holds it (`run_rescrape.py hold`), a status route does not. No re-entrancy is needed.
- **Order: pipeline lock, then view lock. Never the other way round.** Nothing waits for the pipeline lock while holding the view lock.
- The commit (ledger write, view write) is inside the view lock, so a recoverer never sees the moment between them. **Parallel readers** that find a mismatch queue on the view lock; the first rebuilds, the others re-check when their turn comes, find it consistent and do nothing. The view is replaced by rename, so nobody reads half a file.
- A rebuild during a running Re-scrape is safe: the run only writes the ledger and the view at its commit, under the same lock. During a **backup export** the pipeline lock is held, so no commit can happen; the rebuild (view lock only) runs under it, before the archive.
- Tests: (a) recovery while the caller holds the pipeline lock (in the holder, in a step it was handed to, in a process that does not hold it); (b) eight processes and eight threads hitting one mismatch (exactly one rebuilds, a watcher never reads a torn view); (c) unreadable ledger, disk error, a ledger no import produced and an old ledger restored beside a newer view each give an explicit error and leave the stale file untouched, and scoring stops; (d) recovery while `run_rescrape.py hold` holds the lock, while commits go on in another thread, and (Node) under the export's lock before the archive. Mutation check: with the mismatch detection disabled 24 of these tests fail.

**Enrichment** writes the ledger first (generation bumped, only when a fact changed), then the view derived from it; an enrichment that finds nothing new writes nothing. A ledger no import has produced (pre-S4a) is enriched as before but ledger first. Tests: a crash between the two writes of a commit and of an enrichment is recovered by the next reader and the facts are in the rebuilt view.

**Import is final and independent of scoring.** *Rule: once the import has committed, its data stays saved whatever scoring does; Re-score needs neither a scrape nor an import.* A failed scoring changes no byte of the ledger or the view and leaves the run marked imported; `run_scoring.py` alone, with every provider, the importer and staging patched to fail the test if touched, scores from the view. The run record keeps its status (`scoringBehind` shows when scoring did not finish).

**Staging failure.** The run record says `staging: {ok: false}`, an `error` issue, and the run **fails** (exit 1, status `failed`): it is never reported as saved. **Nothing is imported**: the ledger and the view are byte-identical to before, and the importer refuses such a run (`staging_failed`) if asked later. Tested for a source that stops writing, a folder that cannot be made, a provider that stages less than it returned.
Accepted consequence: the ads of that run are lost (they were only in memory); the next Re-scrape finds them again.

**Retention is by status** (`staging.prune`, called after an import): a run gets `imported.json` only from a real import (a dry run never writes it); only imported runs are pruned, and only beyond the newest 3 of them, with their two hard links. **Never** a run that is awaiting import or recovery, a run with no marker (every run staged before S4a, including the three the owner dry-ran), or a run whose staging failed (evidence). The disk use is logged after every run and kept in the run record (`staging.runs`, `staging.bytes`); the CLI prints it.

**Ledger prune off.** `job_history.apply_run(prune=False)` for the importer: no entry is deleted automatically, whatever its age (it stops showing in the view 14 days after it closed). The default of `apply_run` is unchanged for its other callers and tests. More than 5,000 rows in the view is a **warning** (log and run record), never a limit. `offList` logic is unchanged (browser only).

**Debug files.** (Superseded by S4b: no longer written.) `raw_jobs.csv` and `normalized_jobs.json` were written after the commit, best effort, outside the commit set.

**Unfinished, failed and skipped sources** import what they wrote and never close or change another ad (the S3 importer rules), tested through the live path. **Live path = old path:** `test_a_full_discovery_through_staging_and_import_gives_what_the_old_path_gave_from_the_same_inputs` runs four discoveries (a seeded install, a cross-post, a duplicate, a thin description, a failed board, an empty board, a failed and a skipped source) and compares the ledger and the view with the old commit reproduced from its code on the same inputs: no difference.

**Recovery tool.** `import_run.py --run RUNID --import [--allow-older]` imports a staged run whose import did not happen (a run that stopped after staging). A second time changes nothing.

**Other changes:** `.view.lock` is neither exported in a backup nor restored; `data/jobs/staging/`, `data/jobs/*.bak-*` and `.view.lock` are git-ignored. Superseded: the 2a "Partial writes" mechanism (marker, nothing repaired, no backup until a Re-scrape finished) and the S1 / S3 statements that nothing prunes staging.

**Known limits / risks:**
- A run whose staging fails loses its ads (see above); a disk too full for staging is a disk too full for the ledger anyway.
- `copy.deepcopy` of the whole ledger in `plan_import` costs about 0.4 s and a few hundred MB of memory at 19 MB; fine today, watch it if the ledger grows tenfold.
- Staging keeps about 25 to 30 MB per run until it is imported; imported runs beyond 3 go. The three runs the owner dry-ran have no marker and stay until deleted by hand.
- Order is guarded only against the last import (`lastImport.startedAt`), not against a history of imports.

## S4b as built: the debug mirror files are no longer written (2026-11-03)

`raw_jobs.csv` and `normalized_jobs.json` are not written by a run any more. `export_raw_csv` and `export_normalized_json` are removed from `export_jobs.py`, and the best-effort block after the commit is removed from `run_discovery.py` (with the now unused `raw_df`, `pandas` and `JobSpyProvider` imports there). Re-confirmed by search before removing: nothing reads them (no Python module, Node script or route, `src/` component, backup or restore list, `.gitignore` entry; the backup copies whole folders, so an absent file cannot fail it). Files left by earlier runs stay on disk, untouched and not deleted; they are stale and nothing uses them, so the owner may delete them by hand. No change to discovery, import, ledger, view, scoring or the run record (the "debug output was not written" warning no longer exists). `JobSpyProvider.last_raw_df` stays (a test and the provider use it). Test: `test_a_run_no_longer_writes_the_debug_mirror_files_and_leaves_existing_ones_alone` (`tests/python/test_view_guard.py`); the failed-export test in `test_atomic_writers.py` now covers `discovered_jobs.json` only. `docs/redesign/data-shapes.md` marks both files as no longer written.

## S5: owner decisions so far, and S5a as built: the lifecycle report (2026-11-03)

**Owner decisions:**

- **D1:** the 14-day default list window is temporary, to be confirmed after this report.
- **D2:** Stale rows may leave `discovered_jobs.json`, but "Include stale" must bring them back from the ledger. A row missing from the file must never mean the owner cannot find it. Application tracking stays independent of the discovery list.
- **D3:** no automatic removal of rows under an old search key after 30 days (decided in S5b: they stay in the ledger).
- **D4:** snapshot closing ignores the search key, and only for a board proven completely read.
- **D5:** no minimum gap between the two fetches.
- **D6, naming:** in the rules of 2026-11-02 below, **Missing = Absent and Expired = Closed**. An explicit close by the source stays unbuilt, no provider reads one.
- **D7:** per board, but only for boards with reliable proof of a complete read. `read == kept + dropped` alone is not enough, a provider may have stopped early. The evidence per provider is decided and built in S5b.

**S5a, no behaviour change.** `python/job_discovery/lifecycle_report.py` and `import_run.py --latest --lifecycle-report [--report-file]`: pure functions (`simulate`, `build_report`) replay the staged runs under the S5 rules. `apply_run`, the importer, the ledger and the view are not touched, and these rules are not live until S5c to S5f. It writes nothing, except `staging/<runId>/lifecycle-report.json` with `--report-file`; it takes the pipeline lock like `--dry-run`. Scoring is timed in a child process with no model call. Closing is shown twice: strict (today: no board has proof, so nothing closes) and if proven. User data is what the backend can see; the browser's status, insights and outreach state cannot be seen. One live GET per provider on 2026-11-03 checked the answer shapes (Greenhouse `meta.total`, Lever `skip`/`limit`, Ashby only `jobs` and `apiVersion`). **The application store stays closed to Python** (`test_no_python_code_names_the_application_store`, TRACKER_PLAN 6a). The report does not read it: application job ids come through `--application-job-ids FILE`, and without it the report prints that applications were not joined. The file citations live in `python/job_discovery/lifecycle_storage_map.json`, a data file. Tests: `tests/python/test_lifecycle_report.py`.

## S5b as built: board completeness evidence (2026-11-03)

**Owner decisions:** D1, 14 days, stays temporary. D3, older-key rows stay in the ledger with no automatic removal. D7, closing is per board and only with proof of a complete read; `read == kept + dropped` alone is not proof, and **Ashby has no right to close an ad until reliable proof exists**. These replace "D3 not decided" and "not decided" for D7 in the S5a section.

**Staged only; nothing reads it.** The footer of a snapshot source now has `boardsRead`, one line per board: `board`, `read` (ads with a title), `postings` (what the answer held), `complete`, `reason` (why not; none when complete). `apply_run`, the importer's closing, the ledger, the view, scoring and the UI are unchanged.

| Provider | Complete when | Extra fields |
|---|---|---|
| Greenhouse | `meta.total` equals the postings in the answer (a boolean or text total is no total) | `reportedTotal` |
| Lever | `skip=<postings>&limit=1` on the host that answered returns an empty list. One extra request per non-empty board; a check that fails leaves the board unproven and fails nothing | `endChecked` |
| Ashby | Never: `no completeness proof available` | `anomalies`: a top-level field that looks like paging, also a run warning |

`parts_outcome` is the one place that forces a failed or empty board to `complete: false` and gives it a line, whatever its provider said. Limit: Greenhouse's total comes from the same answer, so it catches a list cut short of its own total, not a server that lies about both. `lifecycle_report` still does not read the field; only its wording changed. Tests: `tests/python/test_board_completeness.py`, through the real staging writer.

## S5c as built: two-fetch closing for snapshot sources (2026-11-03)

**Behaviour change, snapshot sources only.** `job_history.apply_run` closes an ad only on `board_evidence`, which the importer builds (`importer.board_evidence`). With none, nothing closes and no miss is counted, so every run staged before S5b is no evidence. Search-based and unclassified sources are not touched: absence closes nothing, and their rows stay shown or hidden as before until S5e. `SOURCE_CLASS` in `job_history.py` names the classes; a source it does not name is search-based.

| What a run says about an open snapshot ad | Result |
|---|---|
| Found | Active. Clears `absentRuns`, `absentSince`, `lastAbsentRunId`; a closed ad reopens, with `firstSeen` and facts kept |
| Complete board, not listed, first time | `absentRuns` 1, `absentSince`. Stays shown, marked `isAbsent`; `lastSeen` unchanged |
| Complete board, not listed, second in a row | `closedAt`. Row carries `closedAfterChecks`, shown for 14 days as before |
| Listed, dropped by a filter | No miss, not found, not shown. On a complete board it clears an earlier miss; a closed ad stays closed |
| Listed under another copy (`roleKey`) | No miss, as before |
| Failed, empty, unproven, board not read, source did not run | Neither raises nor clears. Shown if it was of this search or already absent |

- **Complete** means the provider's proof (`boardsRead`, S5b) AND this run's files accounting for the board: `read` is the same in the line and the batches, equals kept plus counted discards, every counted discard has an id, `discards.jsonl` is whole, no `discardMismatch`. Without the second part a lost discard would make a filtered ad look gone. **This goes beyond the owner's wording and only closes less.**
- **A listed ad clearing an earlier miss on a complete board** is how "stays as it is" and "consecutive" were reconciled: a board that shows the ad means the two misses were not consecutive.
- **An unproven board keeps an ad shown with no mark**, so an Ashby ad that leaves its board stays in the list as an ordinary row, with an old `lastSeen`, for good. Accepted result of "Ashby never closes"; only a later proof or rule changes it.
- **`closedAfterChecks`** lets the badge say "Not on the company's board in 2 complete checks since DATE" only for an ad that really had them. An ad closed before S5c keeps "No longer listed since DATE".
- **`lastAbsentRunId`** makes one run count once, so a run applied twice gives the same ledger. A board removed from the config is unread and closes nothing, which fixes the old bug. D4 and D5 as decided: the key plays no part on a proven board, and there is no gap between the two fetches.
- **Dry-run comparison:** a run imported before S5c may now differ from what its old commit wrote, by design. Fields are additive, version stays 1, nothing migrates.
- **Limit until S5d:** first-miss rows are in the scoring corpus, like the held rows already are.

Tests: `tests/python/test_snapshot_closing.py` (rules, evidence, real providers, the five-step replay through `run_discovery`), rewritten tests in `test_job_history.py`, `test_import.py`, `test_run_log.py`. The 2026-11-02 "code check" list below is now partly out of date: one absence no longer closes a snapshot ad.

## S5d as built: readers ready for rows a run did not find (2026-11-03)

**No visible change.** A row a run did not find (absent, held, or Stale when S5f comes) now costs nothing and moves nothing. `python/job_scoring/row_state.py` is the one definition; how a row is told was replaced in S5d2 (below).

- **Corpus:** `scorer.score_jobs` builds term rarity without these rows, so an active ad scores byte-identically with or without them. They are still scored, with that corpus. The mark `notFoundThisRun` stays on those rows in `scored_jobs.json`, unread by the UI. Closed rows stay in the corpus as before.
- **Enrichment:** no model call for them, also under `--force`. Facts they already have are kept. They do not lower the enriched share in `run_pipeline.py`.
- **Fit judge and shadow engine:** no new call, and no place under the limit. A judgement already paid for still applies, so a row's score does not jump the run it stops being found.
- **Summaries:** `run_pipeline.py` prints found, kept open and closed on one line and absent on its own; `run_discovery.py` adds an absent line.

**Reuse of stored scores: not built, not clearly safe.** A stored score is valid only for the same ad, profile, weights, scoring code and term rarity. Rarity moves every run: on real data, the same 428 rows scored against the corpus of an earlier run moved on 188 to 262 rows, by at most 2 points (mean 0.4 to 0.6). So reuse would freeze a row at an older corpus, and a profile or code change would need a key over all of those to invalidate it. Time is `score_job` at 0.034 s a row; building rarity is 0.7 s. For S5e: reuse for absent rows only, with a key of ad fingerprint, intelligence hash, weights and a scoring version, saves about 0.034 s per absent row (about 45 s of 61 s with today's rows), accepts up to about 2 points of difference from what a rescore would give, and needs a file or field for the key. **No scoring cache for now: decided after the S5e measurements** (owner, S5d2).

Tests: `tests/python/test_readers_not_found.py`.

## S5d2 as built: a durable "not found this run" mark (2026-11-03)

**Replaces the date test of S5d** (`lastSeen == meta.generatedAt`), which a later regeneration or enrichment could break. Readers behave as before; only how a row is told has changed.

**Field chosen: the entry's existing `heldRunId`.** The importer already stamps it on every row a run keeps without finding, and `derive_view` already uses `heldRunId == lastImport.runId` to decide which rows those are. So the mark is that fact and no new state: `notFoundThisRun: true` on the row, written by `apply_run` (for its output) and by `derive_view` (from the ledger), on those rows only. `lastRunId` could not do it alone: a row with neither stamp for this run is not in the view at all. `meta.generatedAt` plays no part any more. Enrichment writes through the same derive or keeps the row as it stands, so the mark survives both. It is in `HISTORY_FIELDS`, so it never reaches a stored ad.

**`lastImport.marksNotFound: true`** says the import knew about the mark. `derive_view` adds marks only then, so a ledger from before gives the very bytes it always gave, and nothing in it counts as held until proven. `isAbsent` is a mark of its own. Such a row is treated as it was before S5d until the next import, which sets the flag. `importer.compare_views` ignores the mark, as it does the other import stamps, so a dry-run against an older commit does not count it.

**Closed rows in the corpus, measured, not changed** (read-only, copy of real data, local score): with today's one closed row, leaving it out moves 3 of 428 active scores by 1 point. What-if runs, treating other ledger rows as closed: 50 rows move 12 of 428, 200 rows move 18 of 428, never more than 1 point. The owner decides.

Tests: `tests/python/test_readers_not_found.py`.

### S4a follow-up (2026-11-03): the older-run override is confirmed by a human; Node view recovery has a safe live check

- **`import_run.py --allow-older` needs an explicit confirmation.** It prints a warning first (the import may overwrite newer ledger data with older data: `lastSeen` moves back, ads the newer run closed can reopen) and then needs either `--confirm-overwrite-newer` or, at a terminal, the word `OVERWRITE` typed at the prompt. Without either it refuses, exit 2, and changes nothing. `--confirm-overwrite-newer` alone is not the override. Only this command line passes `allow_older`: the live run, the recovery in `run_discovery` and the Node routes never do. Code check: `tests/python/test_view_guard.py` (`test_the_older_run_override_is_never_reachable_from_an_automatic_path` scans `python/` and `scripts/` for every use; the order-guard test covers the refusals).
- **The Node recovery was tested only with a mocked spawn; now it has a real check that touches no live data.** The server has no data-folder setting (every module derives `ROOT` from its own place), and none was added. `scripts/check-view-recovery.js` builds a temp root with a COPY of the code and of `job_history.json` / `discovered_jobs.json`, runs the real `handleApiRoutes` from that copy on a local port, raises the copy's ledger generation (view stale), and shows (a) `GET /api/discovery/jobs` answers 200 with the view regenerated, (b) both generations match afterwards, (c) with the ledger cut so it cannot be parsed the route answers 503 `view_unrecoverable` and sends no job list (so does `/api/discovery/status`). It prints sha256 of the two live files before and after. Run in the container: `podman exec holojob node_modules/.bin/tsx scripts/check-view-recovery.js` (tsx, as the server is started). Test: `tests/js/viewRecoveryCheck.test.js` (synthetic root, skipped when no Python 3 is available). The copied code is dereferenced on purpose: a symlinked source would make the handler read the real data.

### Fix to the Node view-recovery check: the host guard (2026-11-03)

In the real container every request of `scripts/check-view-recovery.js` answered 403 "Host not allowed": the container's `.env` sets `HOLOJOB_ALLOWED_ORIGINS`, and `request-guard.js` then accepts only those Host values, while the script called `127.0.0.1:<port>`. The guard is unchanged. The script now sends the Host the guard allows (the first entry of `HOLOJOB_ALLOWED_ORIGINS`, as the reverse proxy does; none configured = the local address passes). A 403 is reported as `ENVIRONMENT: the request guard refused ...`, the recovery steps are not run or reported, the result line says `ENVIRONMENT FAILURE (not a recovery failure)` and the exit code is 2 (1 stays for a recovery failure). Tests: `tests/js/viewRecoveryCheck.test.js` runs the check with the guard configured (passes) and with a wrong Host (environment failure, no `(a)/(b)/(c)` failure line). Reproduced in a throwaway container with the guard config set and the live data mounted read-only: all steps pass, live ledger and view sha256 identical before and after.

## S5e1 as built: dropped ads kept in `filtered_ads.json` (2026-11-03)

**Why:** the owner must be able to see every ad, including the ones a role or location filter dropped at scrape time (Infostud keeps 3 of 441). Those exist only in `staging/<runId>/discards.jsonl`, and a run is pruned after three newer imports. No screen or route reads the file yet; `GET /api/jobs/all` is S5e2.

**Owner decisions (2026-11-03):**

- A separate file, not the ledger: every ledger reader assumes an entry holds a full ad.
- The backfill covers all 5 staged runs, including the 3 never imported, for this file only. Those runs stay not imported.
- No last-score file. Hidden rows show no score.
- What "Active" and "All" hold is decided at S5e3.
- Archiving at 20 MB is a future idea and is not built.

**The file:** one record per `jobId`, updated in place: `source, title, company, location, url, externalId, reason, firstSeen, lastSeen, lastRunId, timesSeen, searchKey, inLedger`. Never a description. Atomic write, `version` 1, no link to the ledger's generation. Written as ASCII, so an odd character in a title cannot stop the write. Shape: [data-shapes.md](redesign/data-shapes.md#filtered-ads).

**Rules, in `python/job_discovery/filtered_ads.py`:**

- **A run counts once.** `appliedRuns` holds the id of every counted run, so A, B, A counts A once, which `lastRunId` alone could not say. The list keeps the newest 500 ids (about 8 KB) and never drops an id whose run is still in staging, the only runs that could be applied again.
- **Time is the run's own** (`importer.import_time`), so a run gives the same record whenever it is applied. An older run moves `firstSeen` back and adds to the count; it never moves `lastSeen`, the reason or the shown fields. The final record does not depend on the order runs are applied in.
- **One ad under several searches** is one sighting, with the first line's reason.
- **Skipped:** a torn last line, an unparsable line, a line that fails `discard_problems`, a line with no `jobId` (counted as `noId`).
- **Kept later:** the record stays, and `inLedger` is set from the ledger at every write. Readers show the ad once, from the ledger. Being kept is not a sighting, so `lastSeen` and `timesSeen` do not move.

**Import order: ledger, view, this file, `imported.json`, prune.** The S5e plan said "before the ledger"; after it is cleaner, because `inLedger` then describes a ledger that was really written and a run killed earlier leaves no record of a run that was not imported.

| Stopped or failed at | State | What finishes it |
|---|---|---|
| Between the ledger and this file | Run not marked and not in `appliedRuns` | Importing the run again (`alreadyImported`) records it, once |
| Between this file and `imported.json` | Counted, not marked | Importing again changes no counter and writes the marker |
| Inside the rename | Old file whole | Importing again |
| Later run imported first (order guard refuses the old one) | Old run stays staged, not counted | `--backfill-filtered` |
| Write fails (disk full, bad store) | The import stands, the marker is written, a warning goes to the log | The run stays out of pruning until it is counted |
| Store unreadable or another version | Never overwritten. Nothing is pruned, since nothing can say what was counted | The owner moves it aside, then backfills what staging still holds |

**Pruning guard:** `staging.prune(root, protect=filtered_ads.unrecorded(root))`. A run that is staged, has a discards file and is not in `appliedRuns` is never pruned. So until the first backfill, deployed code keeps every imported run, and the log says so at each import. This also means a late backfill loses nothing.

**Backfill:** `import_run.py --backfill-filtered [--dry-run]`. Takes the pipeline lock, reads staging and the ledger, writes only this file. No import, scoring, marker, ledger or view change; it reads the ledger directly, so a bad ledger stops it and is not set aside as `job_history.load` would. Twice gives the same bytes, and the second pass does not rewrite the file. It prints counts only.

**Same id, kept or dropped (checked 2026-11-03):** no mismatch.

- **Rule:** `jobId` is `sha256(url)[:16]`, or a hash of title, company and location when there is no address.
- **Real data (read-only, counts only):** all 7,778 dropped lines and 4,292 kept ads of the 5 staged runs, and all 1,981 ledger entries, reproduce from their own fields, for every provider present.
- **Tests:** an ad kept in one run and dropped in another has one id for all 10 providers.
- **Infostud separately:** both of its drop paths give the canonical id, not the sha1 its raw row carries.
- **Joberty:** the address holds a slug of the title, so a retitled ad gets a new id. Both paths do this, so it is not a mismatch, but it is one more way a Joberty ad can look new.

**Measured on a copy of the real data:** 7,778 lines become 1,508 ads, 0 in the ledger, in a file of 814 KB. The earlier estimate of 581 KB left out indentation and ASCII escapes.

**DEFERRED: ledger growth.** At about 10 KB per entry and about 150 new ads a day, `job_history.json` grows about 1.5 MB a day, about 550 MB a year, and every import reads and rewrites all of it. D3 removes nothing. The likely fix is moving descriptions out of the main file (they are about 6.3 KB of each entry). Not scheduled; this will hurt long before `filtered_ads.json` does.

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

**Naming (owner, D6, 2026-11-03):** Missing is now called Absent, and Expired is now called Closed.

- **Closed:** the source explicitly says the ad is closed.
- **Missing:** absent in a successful fetch of the same source.
- **Expired:** only Greenhouse, Lever and Ashby can reach it, after two consecutive successful and complete fetches of the same
  board.
- **Search-based sources** (LinkedIn / JobSpy, Infostud, Workable, Joberty) show Missing and never become Expired automatically.
- **What is not a miss:** a failed or partial fetch, and a changed search.
- **0 ads** is a warning and never closes everything.
- **A source that did not run** (`skipped` or `failed`) keeps its ads as they were (slice 1 correction).
- **`expiresAt`** (Infostud, Joberty) is a deadline: displayed only, never used as Closed or Expired.

**Code check, partly out of date since S5c (2026-11-03): a snapshot ad now closes after two proven misses; see S5c as built. The rest still holds for search-based sources.** **Code check, differs, built last (slice 4):** `python/job_scoring/job_history.py` has one state, `closedAt` / `isClosed`, and no
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
