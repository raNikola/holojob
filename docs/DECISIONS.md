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
- **Backups:** `data/analytics/` was left out of `DATA_DIRS` here; Wave 0 (2026-11-08) put it in, see "Wave 0: verified backup and restore check".

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

## Testing and commit policy (owner decision, 2026-11-04)

Docs only; no code changed. The short form is in `CLAUDE.md`. It extends item 4 of "Owner decisions: baseline score, role filter, Infostud, testing (2026-11-03)" (no merge and no production before the real-container integration check).

**Rules**

1. **During development:** run only the targeted tests relevant to the changed code, plus the relevant lint. Mutation tests only for changed logic, when necessary.
2. **Before each commit:** the targeted tests and the relevant lint must pass. The full suite is not run solely to create a commit.
3. **Before a push or merge:** once, after the feature is complete, run the full Python pytest, the full Vitest, the JS lint, the production build, the mutation checks, the required integration tests, and the data-integrity fingerprint verification (the method used so far: a sha256 over `data/` leaving out `data/ai` and `data/analytics`, compared before and after).
4. **If the full gate fails:** fix, and rerun the failed checks. Repeat the full gate only when later changes could affect previously verified areas.
5. **Never** bypass a failing test (no `--no-verify`, no skipping or `xfail` to turn a test green, no loosened assertion), and **never** modify production data to make a test pass. **Never** push, merge or deploy without the owner's explicit approval.
6. **Explicit task-specific testing requirements override this policy.**

**Where it meets what exists.** The pre-push hook (`scripts/git-hooks/pre-push`) already runs the lint, the JS tests, pytest `-m "not network"` and the build on the pushed commit; it covers that part of rule 3. Mutation checks, integration tests and the fingerprint are not in the hook and are done by hand. A search of `CLAUDE.md`, `.claude/rules/`, `docs/` and `README.md` found **no earlier rule that required the full gate before every commit**, so nothing was replaced. Slices S4 to S7 ran the full gate before each slice commit because their task briefs said so; that was a task requirement, never a rule in these files.

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

- **A run counts once.** `appliedRuns` holds the id of every counted run, so A, B, A counts A once, which `lastRunId` alone could not say. The list only grows, ids only (changed by S5e2b; it first kept the newest 500).
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

## S5e2 as built: `GET /api/jobs/all`, the read-only list of all ads (2026-11-03)

**Owner decisions (2026-11-03):**

- "All" comes from a separate server route, not from more rows in `discovered_jobs.json`.
- Active (S5e3) will be found, held, manual, and absent seen within 14 days. All is everything known: closed, absent, older search key, stale (S5f), filtered.
- A filtered ad shows only with a valid title and web address. Others stay in `filtered_ads.json` as diagnostics.
- `detail_cap` and `no_detail_text` ads with a valid title and address show, marked incomplete.
- Hidden rows have no score: "Not scored", no model call, no last-score file.
- "Read-only" means no job data changes. The existing view recovery may still rebuild a view behind the ledger.
- Found, held, absent and older_key must come from ledger marks, never from `meta.generatedAt` or the time a view was regenerated. A missing mark gets a documented fallback, never a guess.

**The route:** `scripts/job-all-read.js` makes the same `ensureViewCurrent` check as the other job routes, then runs `python/job_discovery/all_ads.py`. The rules are in Python because the marks are written there and the tests can then use the real import, view rebuild and enrichment. The script uses only the standard library and takes about 0.15 s on the real files. A view that cannot be rebuilt, and a ledger that cannot be read, are both 503 `view_unrecoverable` with no list. The second check matters: a cut ledger whose generation can still be peeked passes the view check.

**Classes, first match wins (`all_ads.classify`):**

| Class | Mark | Note |
|---|---|---|
| `found` | `lastRunId == lastImport.runId` | |
| `closed` | `closedAt` | Its own mark |
| `stale` | `staleSince` | Nothing writes it until S5f |
| `absent` | `absentSince` | Its own mark: a proven miss |
| `unclassified` | no `lastImport.runId` | Fallback |
| `held` | `heldRunId == lastImport.runId` | |
| `unclassified` | no `seenUnder`, or no current search | Fallback |
| `older_key` | `seenUnder` differs from the current search | |
| `absent` | `seenUnder` equals the current search | The search ran and did not return it |

`filtered` and `filtered_incomplete` come from `filtered_ads.json`.

- **`unclassified` is a ninth class, added here.** The "never guess" rule needs somewhere to put a row none of the eight describes. Real data has none.
- **`lastImport.searchKey` is not added.** The current search is the one `seenUnder` on the rows the last import found, because `apply_run` writes it on each. So the ledger and the importer do not change, and an older ledger works. If that import found no row, or rows under two keys, there is no current search and the fallback applies.
- **`lastImport.marksNotFound` is not read.** `heldRunId` is older than that flag, so a ledger from before it gives the same classes.
- **`lastSeen` does not decide a class.** It is only shown in the reason. S5e3 uses it for the 14-day rule.

**One row per ad:** an ad in both files shows once, from the ledger, by the ledger's real ids rather than the `inLedger` mark, which may be behind. A cross-post whose other copy was found is `absent` with the reason "Still listed under another copy" (44 on real data).

**Slim rows:** a whitelist, so no description, facts or salary can be in them. Every row has the same fields and `matchScore: null`. `meta` holds the counts per class, `filteredFile` (`ok`, `missing`, `unreadable`; the ledger's rows do not depend on it) and diagnostics. Hand-entered jobs are not in the route: they are not in the ledger, and S5e3 takes them from the browser's list.

**Measured on a copy of the real data:** 3,489 rows, 2.0 MB (the plan's 1.1 MB estimate was low). Counts: found 455, absent 856, closed 1, older_key 669, filtered 1,508; held, stale, filtered_incomplete and unclassified 0. The view's 463 rows are exactly the 455 found, the 7 proven absent and the 1 closed.

**`appliedRuns` bound, tested as asked (fixed by S5e2b, below).** Through the code a repeat never counts twice: `_trim` never drops an id whose run is in staging, even past the bound. An id missing from the list with its run on disk is counted again; that test is a strict xfail. The code cannot reach that state alone. Only a run folder restored after its id was dropped, or a hand-edited file, can. **Smallest fix, not applied (scope):** remove `_trim`. The list then only grows, by about 15 bytes a run (about 27 KB a year at 5 runs a day), and a restored folder is covered; only a hand-edited file is left.

## S5e2b as built: two fixes after S5e2 (2026-11-03)

**A source left out of the run is not "absent" (owner, 2026-11-03).** The search key does not hold the list of sources, so turning a source off leaves its rows under the current key, and S5e2 called them "not returned by the latest search" though nothing searched for them. `all_ads.classify` now also needs the row's source in `lastImport.meta.providers`. If it is not there, the row is `unclassified` with the reason "Its source was not part of the latest run". `searchKey` and the importer did not change.

- **Unchanged:** a failed or skipped source is in that list and its rows are held, as before. A class the row's own mark or its older key proves stays.
- **No list in the ledger:** nothing can say the source ran, so the row is `unclassified`, "Not enough information to say". Real ledgers have the list.
- **Real data:** 0 rows change, because all 7 sources ran.

**`appliedRuns` only grows (owner, 2026-11-03).** The trim step and its bound of 500 are gone. It costs about 15 bytes a run. A run folder restored from a copy now counts once, and the code has no way left to remove an id. The protection of staged runs (`filtered_ads.unrecorded`, the pruning guard) is unchanged.

**Not fixed by this: an id taken out of the list by hand.** With its run on disk, that run is counted again, so that test stays a strict xfail. A guard on `lastRunId` would pass the one-run case only and still double count after a later run, so it is not used. A true fix needs a list of runs on each ad, about 1,500 ads times the runs that saw them, which is not worth it for a hand edit.

## S5e3a as built: the merge and the two lists, wired to nothing (2026-11-03)

**Final owner decisions (2026-11-03). These replace the S5e3 plan where they differ:**

- **Active** is class found or held, hand-entered, and absent seen within 14 days, plus any row the owner already works on (`hasUserData` or any application on that `jobId`), whatever its class. A closed row with no work is only in All.
- **The 14 days** run from the row's `lastSeen` to the current date, not from the last import. They affect what is shown, never the lifecycle. No `lastImportAt` field; that plan item is dropped.
- **Cross-post copies:** one representative per `copyGroup`, and every copy with work stays visible. With no worked copy: by class (found, held, absent), then newest `lastSeen`, then smallest `jobId`, never by API order. While the application store is loading, or if it failed, copies are not collapsed, and a failure is flagged. When its data arrives, the list is worked out again from the same inputs and nothing stored changes.
- **Merge per field**, as in the table below. A stored score on an absent row stays shown.
- **Server-only rows** never reach `saveJobs` or `importJobsFromFile`.

**Built:**

- `copyGroup` on the rows of `all_ads.py` (the entry's `roleKey`; null on a filtered ad). Additive.
- `src/modules/jobs/allAds.js`: `mergeRow`, `composeJobList({ stored, server, applications, reference })`, the copy choice, `classLabel`.
- `src/modules/jobs/useAllAds.js`: `fetchAllAds`, `createAllAdsLoader` (`loading`, `ready`, `error`; in memory only; the last good rows survive a later failure; the newest request wins), `useAllAds`.
- `jobMatchKey` exported from `jobStorage.js`.
- Nothing imports the two modules yet except tests, so nothing visible changes.

| Fields | Source when a route row and a stored row share a `jobId` |
|---|---|
| `status`, `aiInsights`, `tailoredAssets`, `outreach`, `notes`, `extraLinks`, `sourceUrl`, `sourceChoice`, `createdAt` | Stored always |
| Tracking | Not part of the merge; the application store, derived |
| `class`, `reason`, `reasonCode`, `from`, `copyGroup`, `firstSeen`, `lastSeen`, `closedAt`, `absentSince` | Route always, null included. Display only, never stored |
| `title`, `company`, `location`, `jobUrl`, `provider`, `site`, `isRemote`, `datePosted` | Route when not null, else stored |
| `description`, `llmFacts`, `engineShadow`, `matchScore`, `matchLabel`, `priority`, salary and authorization fields | Stored only, so the route's `matchScore: null` cannot remove a score |
| A hand-entered row | Entirely stored |

**Choices made while building:**

- **A dead copy does not hide a live ad.** If the only worked copy of an ad is outside Active's own classes (closed, older key, or past the 14 days), it stays and the best unworked copy shows too. The decision above says a pick is made with no worked copy, and this keeps the rule from the plan for that one case, because otherwise a live ad would leave Active. It shows one extra row at most. Removing it is a one-line change in `copiesToShow`.
- **A stored row the route does not hold** stays in Active unless it is `offList` with no work, whether the route failed, answered empty or simply lacks it. It has no class, and `classLabel` calls it "Saved in this browser".
- **An application whose store failed does not count as work,** even if a last copy of the store is held: only what is known counts, and the copies are not collapsed anyway.
- **A row with no usable `lastSeen`** is out of the 14 days. A date ahead of the clock is in.
- **Rows match as the import does:** by id, then by `jobMatchKey`. The stored `jobId` stays, since later writes go to it. A route row at a hand-entered job's `identityJobUrl` is dropped.
- **No usable `reference`** throws, rather than guessing a date.

**Measured on a copy of the real data (compose takes about 50 ms):** Active 1,238 (found 455, absent 781, hand-entered 2), 774 of them with no score. All 3,491. 75 copies hidden. All 4 applications are visible, including the one on a copy the deterministic choice would not have picked. With the store loading, Active is 1,313 with nothing collapsed. With the route failed, the 465 stored rows stay. Moved 14 days ahead with no import, Active is 459.

## S5e3b as built: the Jobs table on a long list (2026-11-03)

**Why first:** Active will hold about 1,200 rows and All about 3,500, and the table mounted every row twice. This slice applies to today's list and uses neither `useAllAds` nor `composeJobList`.

**Owner rules (2026-11-03):**

- Show more, paging and selection never touch `localStorage`.
- Existing filters keep their current persistence.
- `state.jobs` and stored user data stay byte-identical.
- A filter change resets the selection. A sort change and Show more do not.
- A sort change or a filter change goes back to the first batch.

**Built:**

- **One layout:** `JobTable` mounts the table or the cards, by `useMediaQuery('(min-width: 768px)')`, Tailwind's `md`, the width they always switched at. With no `matchMedia`, the table.
- **Paging:** the whole list is sorted first, then the first 100 are shown, with "Show 100 more" and "Showing N of M". The Score and Provider columns are still judged on the whole list.
- **Selection** is a Set of `jobId`s. State for both lives in `modules/jobs/jobTableModel.js`, in memory only.
- **Select all** means every filtered row. A line above the list says so ("Select all 350 filtered jobs"), as do the header checkbox's label and tooltip, and it also counts selected rows not on screen. The line also gives narrow windows a select-all, which they never had. Selecting all replaces the selection, and with all selected it clears.
- **Bulk actions** read the Set and still act on `state.jobs`.
- **`FitScore`** has an optional `emptyLabel`. The default stays "—" and nothing sets it yet.

**How a reset works:** each state keeps the key it was made under, and a state from another key reads as the starting one. So there is no effect to forget, and only a real change of filters or sort resets. The list being rebuilt does not: changing a row's status on row 350 keeps the rows loaded and the selection.

**Numbers. All SYNTHETIC: React in jsdom in a test container, with a made-up list. Not a browser benchmark.** jsdom does no layout or paint, so a real browser spends its time differently and the old table would suffer more there.

| At 3,500 rows | Before | After, table | After, cards |
|---|---|---|---|
| DOM nodes | 269,544 | 3,248 | 4,506 |
| Mount | 10.9 s | 0.3 s | 0.5 s |
| Re-render on a list change | 3.1 s | 0.13 s | 0.17 s |
| Click on a sort header | 7.2 s | 0.2 s | not applicable |

| At today's size (465 rows) | Before | After |
|---|---|---|
| DOM nodes | 35,849 | 3,248 |
| Mount | 1.6 s | 0.15 s |

- **Sort time alone** (`sortRows` on 3,500 rows, unchanged): about 1.5 ms. Sorting the whole list was never the cost.
- **Search, on the real Jobs screen, per keystroke:** at 465 stored rows, 415 ms before and 56 ms after. `saveJobs` alone takes about 11 ms of that (3.3M characters).

**Search and the re-save:** the save on every state change was not the cause of the lag; rendering the table was. Storage is not changed. jsdom's `localStorage` is not a browser's, so if typing still lags in the browser, the fix to try first is writing only `filters` less often (debouncing the save effect), not changing what is stored.

**Testing:** the repo has no DOM for tests, and adding one was out of scope. Committed tests use the pure state functions and server-rendered markup. Real clicks on the real screen ran once in the same throwaway jsdom setup, outside the repo: Show more, sort, select all, a filter change, a status change. Two of the mutations are caught only there: the Score column judged on the whole list after a re-sort, and focus moving when the last Show more button goes.

**Visible changes:** today's list starts at 100 rows, not all of them, so the browser's own find sees only what is loaded. A filter change now clears the selection; before, it stayed.

## S5e3c as built: the visible Active/All view (2026-11-03)

**Owner decisions (2026-11-03):**

- The Jobs screen gets an Active/All toggle, default Active, using the composed lists of S5e3a. Inside All: a class filter (nine classes plus "Saved in this browser", a display label) and "Seen in the last 14 days".
- Server-only rows live in memory only. The new controls never write to storage. Existing filters keep their persistence. `state.jobs` stays byte-identical.
- Only the list count and the filter counts and options read the composed list. KPIs, AI statistics and application tracking keep their logic and inputs, so a server-only row with no score cannot move the average fit score or any other metric. Export stays stored rows only and says so.
- Until S5e3d, actions on server-only rows are disabled and say why: "Keep this ad is coming in the next update". No button is clickable and does nothing.
- Filtered rows are read-only, with a link and an "Add job" form prefilled with title, company and URL. Nothing is saved until Save.

**States:**

| Situation | Active | All |
|---|---|---|
| Route not answered yet | Today's list, exactly | Stored rows; "Loading the full list. This list is incomplete until it arrives." |
| Route failed or 503, first time | Today's list, an error and "Try again" | Stored rows, the error and "This list is incomplete: the full list could not be loaded…" |
| Route failed later | The last list loaded, and the error | The same |
| Answer with no rows | Stored rows stay | Stored rows stay |
| `filteredFile` not `ok` | Unchanged | "This list is incomplete: filtered ads could not be read" |
| No API, or demo data | Today's list, no toggle, the route is never asked | Not offered |
| Application store loading or failed | Copies not collapsed, with a note | Unchanged |

**The two old filters while a composed list shows:** "Show jobs absent from current results" is off and disabled, with the tooltip "Active and All already include these rows", since the two lists decide that. "Hide jobs no longer listed" still works, reading the route's class when a row has one. On today's list (route not answered, failed, no API) both behave exactly as before.

**Choices made while building:**

- **The reason line shows on every row of a composed list,** found ones too ("Found by the latest run"), as asked. It is one line to hide it on found rows if that turns out noisy.
- **Select all covers stored rows only,** since bulk actions act on those, and says so ("Select all 2 filtered jobs saved in this browser"). Server-only rows have a disabled checkbox with the note; filtered rows have none.
- **The drawer of a server-only row** shows the ad, reads its text from the ledger and stores nothing. It hides "Mark Applied" until S5e3d, unless the job already has an application. The tailoring tools in cards are for stored rows only.
- **Job Details for a server-only row is unchanged:** it already opens from the ledger, stores nothing and shows no section that writes job fields, and its tracker writes to the application store, so "Mark Applied" works there. This is the one action on such a row that is not disabled; S5e3d should make the two places agree.
- **The route is asked each time the screen opens,** after every import (`importedAt` moving covers Re-scrape, Re-score, auto-refresh and URL import), and after a Re-scrape however it ended, since the ledger may have moved. `useAllAds` keeps what it holds until the answer comes.
- **The current date** for the 14 days refreshes hourly while the screen is open.
- **A selection or page resets** on a change of mode, class or the 14-day filter too, as for any filter.
- **"Not scored" now shows in the Jobs table** in both layouts, for any row without a score. Other screens keep "—".

**Testing:** first with pure functions, server-rendered markup and source checks; real clicks ran once in throwaway jsdom. Since S5e3d commit 1 those clicks are permanent tests.

## S5e3d, commit 1: jsdom and permanent click tests (2026-11-03)

**Owner decision:** `jsdom` is approved as a dev dependency, with the existing Vitest and no new test framework.

- **Added:** `jsdom` to `devDependencies`. Test files opt in with `// @vitest-environment jsdom`; every other test keeps the `node` environment.
- **Production is not affected:** the build output is byte-identical with and without it (sha256 of every file in `dist`). The image's final stage runs `npm ci --omit=dev`, so it does not ship.
- **Tests:** `tests/js/jobsScreen.dom.test.js` runs real clicks on the real Jobs screen, with the server stubbed by `tests/js/setup/jobsScreenHarness.js`. This covers the checks that until now ran only once, outside the repo. No production code changed for them.

## S5e3d, commit 2: "Keep this ad" and promotion (2026-11-03)

**Owner decisions (2026-11-03):**

- An explicit "Keep this ad" button on server-only rows (table, cards, drawer, Job Details) is the only way such a row becomes a stored row. Opening details never stores it. Filtered rows stay read-only with Add job.
- AI, outreach, tailoring and status changes need Keep first, and say so. Status stays disabled until then, rather than promoting on the same click.
- Keep is a lasting intent. The row is marked `keptByUser`, so it survives re-import and stays in Active even when off-list, with no status, note or AI on it.
- Mark Applied works on both the drawer and Job Details, the same way, and does not promote the ad. The application store holds it, so it stays after refresh and re-import.
- The reason line "Found by the latest run" is hidden on found rows. Other classes keep theirs.
- Bulk selection covers stored rows only, stated clearly. The per-field merge stays as decided.

**Built:** `keepAd.js` reads the ad from the ledger through `resolveJob`, the path Job Details already uses, and calls `promoteRow` in `jobsStore.js`. That is built on `addJobIfAbsent`, and is the one explicit exception to "only rows from the file are added". `KeepAdButton.jsx` is the only caller.

**A stored kept row:** the ledger's ad plus `status: 'new'`, `keptByUser: true`, `keptAt`. It never holds `class`, `reason`, `reasonCode`, `from`, `copyGroup` or `serverOnly`, and it does not take the route's empty `matchScore`, `closedAt` or `absentSince`.

| When Keep runs | What happens |
|---|---|
| Ledger answers with the ad | Stored whole |
| Ledger cannot answer | Nothing stored; "The ad could not be read from the job history, so nothing was kept. Try again." |
| Ledger answers with no ad text | Stored with `descriptionIncomplete: true`; the details say the copy is incomplete. The mark goes away when a later scored file brings the text |
| Another tab already stored it | Its data stays and it gets the mark |

**Changes this needed outside the button:**

- `hasUserData` counts `keptByUser`, which is what keeps the row through an import.
- `mergeStatusOnImport` carries `keptByUser` and `keptAt` over when the ad returns to the file. Otherwise a kept ad that came back would lose the mark, and be dropped at its next absence.
- `listedJobs` and `filterJobs` keep a kept off-list row on today's list, so it stays visible when the route has not answered. `onListJobs` is unchanged, so AI context and the numbers still leave it out while it is off the list.
- `JobDetailBody` offers AI tools on a kept row with no score, or Keep would promise something it did not give.
- **A leak fixed:** `handleJobUpdated` in the screen merged a whole row into the stored one, and in a composed list that row carried display fields, so the tailoring tools in cards would have stored `class` and `reason`. It now strips them. The drawer strips them from what Mark Applied posts too.
- A server-only row with an application shows "applied manually", for display only, as Job Details does.

**Known limit:** a kept ad with no score stays "Not scored" unless a later run finds it. Re-score reads the view, which does not hold it, and the tailoring tools still need a score.

## S5f as built: the Stale flag (2026-11-04)

**Owner rule (2026-11-04):** an ad is Stale after no sighting for 30 days and at least 3 successful runs of the same source and search key since its last sighting. It is a flag only: nothing is deleted and no ledger history changes. "Successful" means finished and proven by the same evidence rules as S5b and S5c. Snapshot ads keep their closed and absent rules, and a closed ad is not Stale. An ad with the owner's work can be Stale but never leaves Active for it. Scoring, the IDF corpus and the closed-row treatment are untouched.

**The rule is in one place:** `python/job_scoring/stale_rule.py`, stdlib only and pure, used by the importer, the view and the route.

**The evidence is in the ledger, additive:**

- `ledger.sourceRuns`: `{provider: {bucket: [{runId, at}]}}`, oldest first, the newest 100 kept per bucket. The rule needs only 3; the rest give the count in the reason line, shown as "100 or more" past the bound.
- A bucket is the search key for a search-based source. For a snapshot source it is `board:<name>`, with no key (D4).
- `lastListedAt` on an entry: when a run last returned the ad and a filter dropped it. That counts as a sighting, since the source plainly still has the ad. `lastSeen` does not move.
- A ledger with no `sourceRuns` has no Stale ad and derives the same bytes as before. Runs before this slice are not counted, so the count starts at the first import after deploy.

**What counts as a proven run:**

| Run | Counts? |
|---|---|
| Search-based source: status ok, ads read, nothing lost, files add up | Yes, under its key |
| Failed, partial, skipped or unfinished | No |
| Status ok but nothing read (a throttled source can do this) | No (single rule, 2026-11-04: ok with 0 read is not automatically proof; see [Roadmap v2](#roadmap-v2-and-the-single-discovery-safety-rule-2026-11-04)) |
| A lost ad, staged ads that differ, `discardMismatch`, a failed part, or a damaged discards file | No |
| A disabled source (not in the run) | No: it has no run |
| A board proven complete by S5b/S5c | Yes, under the board |
| Any other board, and every Ashby board | No, so Ashby ads never go Stale, as they never close |

**Choices made while building:**

- **The 30 days are measured from the last sighting to the newest proven run, not to today.** So a pause in scraping proves nothing and flags nothing, and one ledger always gives one class. With regular runs the two readings differ only by the time since the last run. This also keeps the rule that classes do not depend on when they are read. Measuring to today instead is a small change in `stale_rule.evidence`.
- **A snapshot ad a proven board stops listing closes first** (2 misses), so in practice only a search-based ad goes Stale.
- **An older-key row is not Stale** while its key does not run again, so it stays `older_key`.
- **Order:** found, closed, stale, then absent and held. A held ad can be Stale: its source failing now does not undo the runs that already did not find it.

**Screen:** the class, badge and filter already existed, and the reason line now gives the counts: "No sighting for 40 days and 3 successful runs of this search. Last seen 2026-09-25". `composeJobList` already kept Stale out of Active unless worked; tests now hold that. `isActionable` is false for Stale, on a stored row (`isStale`) or a composed one (`class`).

**`isActionable` has two callers:** the action buckets in `computeJobStats` (Apply, Maybe, P1, P2) and the top jobs in the AI context. Both read stored rows, which never hold a class, so `view_guard.derive_view` writes `isStale` on a held row that is Stale, the only way a Stale row is in the file. The average score and other numbers still count such a row, as they count a closed one.

**Measured on a copy of the real data (2026-11-04):**

| | Stale | Active | All |
|---|---|---|---|
| Before this slice | 0 | 1,238 | 3,491 |
| After, today | 0 | 1,238 | 3,491 |
| What-if, 3 proven runs by 2026-11-15, same rows | 0 | 696 | 3,491 |
| What-if, 3 proven runs by 2026-12-04, same rows | 846 | 459 | 3,491 |

Nothing can be Stale yet: the ledger has no proven runs and its oldest sighting is under 30 days old. **Stale barely changes Active.** An unworked absent row leaves Active after 14 days anyway, well before it can be Stale at 30. The two what-if Active counts above come from the 14 days. What Stale adds is the label and reason in All, and leaving the action buckets for a held row.

## S6 as built: cancel a running Re-scrape (2026-11-04)

**Owner decision, final (2026-11-04, option D; it replaces the first S6 choice, "import held", and the line "Cancel and Interrupted import every validly written ad" of 2026-11-03 for a cancel):** a cancelled run **saves what it validly collected, and never rebuilds the existing list from an incomplete run.**

1. No validly collected ad: nothing is imported, not even a generation.
2. Valid ads: only those are saved. A new ad is added; a known ad is refreshed as any sighting refreshes it (`lastSeen`, its snapshot, its facts), and a closed ad it sees again reopens, as ever.
3. Every other entry is not looked at. None becomes held, absent, closed or Stale, and no miss is counted.
4. The list is not rebuilt: `lastImport` stays the last complete run's, and the collected ads join that run's list.
5. Scoring is skipped. The scored file and the IDF corpus are untouched; the corpus can only grow, by the saved ads, at the next scoring.
6. `sourceRuns` and `appliedRuns` do not change, and no lifecycle conclusion comes from a cancelled run's absence.
7. The run's dropped ads are saved once, under `partialRuns` in `filtered_ads.json`, never in `appliedRuns`.

**Which parts of `plan_import` assume a complete run** (why this is its own path, `importer._plan_partial`, and not a status on the old one): the second half of `apply_run`, where every entry not found is kept, marked absent, missed or closed and the output is the whole list; the rewrite of `lastImport`, from which the view is derived (found = `lastRunId == lastImport.runId`), which would make the partial list *the* list; `_record_stale_evidence` (proven runs, `lastListedAt`); `filtered_ads.appliedRuns`, which is both the counted-runs list and the idempotence guard; and "already imported" keyed on `lastImport.runId`. What it can share is the validation, the dedupe, the refusals and the order guard, and the half of `apply_run` that sees an ad, now `job_history.found_ad`, used by both so they cannot disagree.

**The partial path.** `job_history.apply_partial` runs `found_ad` for each collected ad with `lastRunId` set to the last complete run's id, in the place the ad already had or after the last one. The ledger gains `generation + 1`, `updatedAt` and `partialRuns` (the idempotence memory, newest 200). The view is `derive_view` of that ledger, so the rows that were there keep their order and nothing else moves. Nothing is saved (and nothing written) when no valid ad was collected, when there is no complete run to add to, or when the run searched something other than the list's own search (`seenUnder` of the last run's rows); `imported.json` then says `committed: false, saved: 0` and staging is pruned like any run. The order guard applies as ever. **One rule for every cancelled run, including one cancelled after all sources finished:** the code shows no reason to treat it differently, except that its complete read is not used for closing or Stale. The next ordinary run does that.

**Where a run can stop** (unchanged from the first S6 build; the handshake is untouched): scrape (staging only, stops at once), after the scrape before the commit claim (staging only), **commit never interrupted** once claimed, scoring (one atomic write). **How:** `POST /api/rescrape/cancel {runId}` writes `<record>.cancel` and one event; it takes no lock, writes no data file and does not touch the record. Node never signals. The orchestrator polls for the file and sends SIGTERM to the step's own process group and every descendant found through `/proc`; discovery turns it into `RunCancelled` (a `BaseException`) only inside the source loop, and checks the file between sources. **Handshake:** two O_EXCL claims on `<record>.decision`: discovery claims `commit` before it imports, the orchestrator claims `kill` before any SIGKILL (after `HOLOJOB_CANCEL_GRACE_SECONDS`, default 20); exactly one wins, a run that holds `commit` is never killed, and discovery re-reads the cancel file after the claim.

**What a user can see:**

| State | Run status | `cancel.outcome` | Saved | Scoring |
|---|---|---|---|---|
| Cancelled while scraping or before the claim | `cancelled` (step exit 76) | `collected_ads_saved`, `saved: N` (N may be 0) | the N ads, nothing else changed | skipped |
| Step had to be killed | `cancelled` (step exit -9) | `stopped_nothing_imported` | nothing | skipped |
| Cancelled before the scrape began | `cancelled` | `stopped_nothing_imported` | nothing | skipped |
| Request after the commit was claimed | the run's own | `imported_before_cancel` | an ordinary import, it counts | skipped (or stopped) |
| Request on a run that failed anyway | `failed` | none | as it was | as it was |

Texts: progress line and Re-scrape message, "The last run was cancelled. N collected ads were saved. Nothing else changed. Scoring was skipped." (or "No ads were saved."); event "Cancelled: N collected ads saved" / "Cancelled: nothing was saved"; after the commit claim, "The cancel came after the jobs were saved, so the scrape counts. Scoring was skipped." No cancel text mentions held rows, because a cancel makes none. The held-row reason line ("Its source or board could not say in the latest run") belongs to failed or skipped sources and is unchanged. `scoringBehind` does not turn on after a cancel, since the list's run id did not change; the saved ads show as not scored until the next scoring.

**Idempotent answers** (all but a new request change nothing): `cancel_requested` 202; `cancel_already_requested`, `already_cancelled`, `already_finished`, `not_running` 200; `not_cancellable` (pipeline or direct discovery) 409; `unknown_run` 404; a bad run id 422. Liveness is read from `/proc/locks` on the inode alone, taking no lock. Requests are keyed by run id; `run_log.prune` removes `.cancel` and `.decision` with their record.

**Staging rule (one):** a cancelled run's staging is marked imported (`imported.json`: `cancelled`, `saved`) and pruned like any imported run, hard links included. A run that was killed carries `cancelled.json`, stays like any run awaiting an import, and is never counted: `import_run.py --import` of it takes the same partial path, the lifecycle report leaves every cancelled run out, and `--backfill-filtered` / `filtered_ads.unrecorded` treat a cancelled run only through `partialRuns` and only if it saved ads.

**Measured on the real ledger, read-only (2026-11-04, `data/` byte-identical):** list 463 rows, corpus 456, generation 2.

| Cancel | Saved | Rows | Corpus | Other ledger entries changed | `lastImport`, `sourceRuns` |
|---|---|---|---|---|---|
| Before staging | 0 | 463 | 456 | 0 | same |
| After the first source | 3 | 463 | 456 | 0 | same |
| After all 7 sources | 455 | 463 | 456 | 0 | same |
| After the first source, plus 3 new ads | 6 | 466 | 459 | 0 | same |
| After all 7 sources, plus 3 new ads | 458 | 466 | 459 | 0 | same |

"Saved" counts refreshed ads too: the real staging holds ads the ledger already knew. The 7 not-found rows are the existing ones. The first S6 design (held) would have shown 1,919 to 1,981 rows and, after an early cancel, a corpus of 1 to 4.

**Not covered:** no container is started anywhere in the repo. Playwright's Chromium was not run; the descendants sweep is tested against a child in its own session that ignores SIGTERM. A source stuck in an uninterruptible kernel call ends only by the SIGKILL after the grace. Changed outside the new code: `tests/python/test_rescrape.py::test_sigkill_of_the_whole_run...` kills the step's group too, because the step now has its own session.

**Tests:** `tests/python/test_cancel.py` (what a cancelled run may change, offline, 22), `tests/python/test_cancel_run.py` (the request, the signal, the claim, the kill, the process tree, and a real slow run in a scratch copy of the code), `tests/js/rescrape.test.js`, `tests/js/rescrapeRoutes.test.js`. Mutation-checked: a cancelled run taking the full path, marking other ads absent, joining its own list (corpus shrinks), writing `appliedRuns`, recording a proven run, rewriting `lastImport`, writing when nothing was collected, adding another search, saving filtered ads twice, the backfill and `unrecorded` and lifecycle report reading it; and the earlier S6 checks (pre-scrape, between-source and after-claim cancel checks, kill without the claim, commit without it, the descendants sweep, the step's own group).

**S5f follow-ups, same day:** `isStale` surviving the real `run_scoring.main()` is a permanent test, and a Stale ad seen again is tested through real imports and on a held row.

## S7a as built: run evidence in the record, and `GET /api/runs` (2026-11-04)

**Scope:** the data and the read API for the Activity screen. No screen, no polling and no Cancel button (S7b, S7c). No change to scoring, the IDF corpus, lifecycle rules or the cancel semantics; no existing importer test was edited, and one (`test_run_log.py`, the exact record shape) was extended for the new fields.

**Owner decisions (2026-11-04):** "collected" means ads that passed the owner's rules and were written to staging. The `import` block and per-source times go into **new** run records only; older records stay as they are and the screen shows them as "Not recorded". The reason codes are one shared file used by Python (emit) and JS (show).

**The words** (one meaning each, never merged): **Returned** = `read`, what a source gave and the code could read. **Filtered out** = returned minus collected, dropped by the owner's rules, with reason counts. **Collected** = `kept`, passed the rules and written to staging (the S6 word). **Saved** = written to the list: collected, whole, not a duplicate; a cancelled run's saved **includes refreshed ads it already knew**. **New** = saved ads the ledger had never seen. **Refreshed** = saved minus new. Per-source `new` is counted after dedupe under the winning copy's source, so source columns do not add up to the run's `new`.

**The record gains (additive, version stays 1):**
- `sources[].startedAt`, `finishedAt`.
- `import`: `{kind: complete | partial | nothing | refused, complete, saved, new, refreshed, duplicatesRemoved, crosspostsMerged, rejected, ledger {closed, absent, reopened, changed, known} (complete only), nothingSaved?, sources: [{name, proof, filterReasons}]}`. Counts and codes only; no ad, title, link or description. 2 to 4 KB a run.
- `proof`: `{proven, why: [codes], boards: [{board, proven, why, detail}]}`. A search source is Proven only if `why == ["proven"]`; a board source only if it has boards and every one is complete.

**The importer only reports.** `_search_proof_reasons` is the S5f rule with every clause named instead of OR-ed; `_search_run_proven` is now `not reasons`, and `test_the_rule_is_what_it_always_was` compares it with a copy of the old function over a grid of footers and damage. `board_evidence` computes `complete = not why` from the same clauses it had; the importer's other tests pass unchanged. The report gained `proof`, `filterReasons` and `saved`, in keys of their own, so no existing report entry changed.

**Reason codes** (`python/job_discovery/proof_reasons.py`, texts in `src/data/proofReasons.json`; a pytest and a vitest fail when the two differ). Search sources: `proven`, `not_finished`, `source_failed`, `source_partial`, `source_skipped`, `nothing_read`, `ads_not_whole`, `staged_differs`, `files_torn`, `discards_mismatch`, `discards_damaged`, `parts_failed`, `no_search_key`, `run_cancelled`. Boards: `board_complete`, `board_unreadable`, `board_empty`, `no_total`, `total_differs`, `end_not_checked`, `end_check_failed`, `end_check_not_a_list`, `postings_past_end`, `no_proof_available` (Ashby, always), `board_anomalies`, `files_dont_add_up`, `source_in_doubt`, `board_not_complete` (a provider text this table does not know; a test fails if a provider text maps to it), `no_board_evidence`, `boards_not_proven`. "Proven" means the run may count towards Stale and, for a board, may support closing; it does not mean the run was good.

**Three states, never mixed:** `proven`, `not_proven` (with codes), and `not_recorded` (an old record, no `import` block, or a source the block has no row for). Not recorded is never shown as not proven.

**`GET /api/runs?limit=30&before=<recordName>`** (`scripts/run-history.js`): newest first; `limit` default 30, above 100 is 100, below 1 or not a number is 422; `before` must be a record file name (422 otherwise) and pages by name, so only that page's files are read. Envelope `{ok, runs, next, skipped, retentionDays: 90, activeRunId}`. It reads the names in `data/analytics/runs/` and up to `limit` record files (over 256 KB: skipped). It takes no lock, starts no process, repairs and writes nothing, and reads no ledger, staging, event log or ad. For a record that says running it reads the lock file's inode and `/proc/locks` (no lock is taken): nobody holding it shows the record as `interrupted` with `inferred: true`, unknown counts as alive, and nothing is marked on disk (`reconcile` stays the only thing that does). `cancelRequested` comes from the file name `<record>.cancel` in the same listing. `canCancel` is true only for a running Re-scrape.

**The allow-list:** `project()` builds every run, source, issue, step, proof and import field one by one, with type, enum, regex and size checks; the raw record is never returned, and a field a later slice adds does not appear until it is added there. Free text is the hard part: a record's messages end in text from outside the app (an exception, a step's output, a provider's error), and no pattern can promise an ad title is not in it. So **a message is shown whole only if it is one of the app's own fixed texts**; a known beginning keeps the app's words and summarises the rest; any other text becomes "details withheld" plus only exception class names, an HTTP status and snake_case codes. A step's failure keeps "discovery failed with exit code N" and drops the output tail. A source `error` is summarised part by part with the board names kept. Everything also passes `maskSecrets`, and links, e-mail addresses and phone-like numbers are replaced. `issues` are capped at 10 per run (the full count is `issuesCount`). The cost is that a provider's own error wording is not visible on the screen; the reason codes and the exception name are. A canary test seeds ad text, title, company, link, contact, a fake key and unlisted fields at every level and checks none arrives.

**Cost of one request, measured 2026-11-04 in a throwaway node container on this host, warm file cache, `listRuns` plus `JSON.stringify` (no HTTP):**

| Folder | Runs returned | Response | CPU per request |
|---|---|---|---|
| The real history, 7 records, `limit=30` | 7 | 19.5 KB | 0.56 ms |
| Synthetic, 100 records of 7 sources each (3.0 KB on disk), `limit=30` | 30 | 96.7 KB | 2.4 ms |
| Same, `limit=100` | 100 | 322 KB | 7.1 ms |

So a run with seven sources is about 3.2 KB in the response, more than the 1 to 1.5 KB the plan assumed; the default page is about 100 KB at worst. The screen (S7b) can ask for fewer, or the sources can move to a per-run request, if that matters. Cold-cache disk time is not included. There is no polling in S7a.

**Not covered:** records written before this slice have no `import` block, so their counts of saved, new and refreshed and all proof stay null / Not recorded. The cancelled run's in-flight source has no `sources[]` row (it never reported), so it is shown as `unfinished` from the import block. A real deployed server was not called; the numbers above are the same code on the real records.

**Tests:** `tests/python/test_proof_reasons.py` (52), `tests/js/runHistory.test.js` (34), route tests in `tests/js/rescrapeRoutes.test.js`. Mutation-checked: each of nothing_read, files_dont_add_up, run_cancelled and no_search_key dropped; a board always complete, every search source proven, an empty read still proving; the list reading outside the runs folder, an unbounded or no default limit; the raw staging field, messages, source errors, board details and unknown codes leaking; Not recorded shown as Not proven; a running record never inferred dead.

## S7b as built: the Activity screen, read-only (2026-11-04)

**Scope:** the screen and nothing more. No Cancel button, no live view, no polling (S7c). No change to the API, the importer, scoring, the IDF corpus, lifecycle rules or the cancel semantics. One server-side wording fix: a source error with no board name now starts "Details withheld (...)" instead of "Error details withheld (...)", because the screen already labels it "Error:".

**Where:** view id `activity`, label "Activity", first item of the System group (above Quality Audit), in the sidebar and in the mobile "More" menu; `src/components/activity/ActivityScreen.jsx` and `RunDetails.jsx`, wording in `src/modules/activity/runView.js` (pure), the request in `activityClient.js`, the loading rule in `useRunHistory.js`.

**When it asks the server:** when the screen opens, on Refresh, and on Show more; at no other time. There is no timer anywhere in the code that fetches (a test greps for it and another advances an hour of fake time). A tab that is hidden when the screen opens asks nothing, and asks once when it is shown. Default request `GET /api/runs?limit=30`; Show more sends the previous answer's `next` as `before` and adds the runs, a run seen twice is shown once. Details need no request: the list already holds the per-source data. **Nothing is stored in the browser**, not even the open/closed state of a row (a test spies on `setItem`).

**What a user sees:**
- **Loading:** "Loading the run history…" with a spinner; Refresh is disabled while it loads.
- **Empty:** "No runs yet. A run appears here once a Re-scrape or a pipeline run has started."
- **Error:** an alert "The run history could not be loaded" with the reason ("The server could not be reached." or "The run history is not available (status 503).") and a "Try again" button. An answer that is not a list is an error, not an empty history. A failed Show more keeps the list and says so beside the button.
- **List:** one card per run, newest first: start time, a status badge with a word (OK, Partial, Failed, Skipped, Running, Interrupted, Cancelled, Unknown), trigger (Manual, Pipeline, Scheduled), duration ("In progress" while running), issue count ("No issues" / "3 issues"), then four figures: Returned, Collected, Saved (new), Filtered out. Cancelled, interrupted, skipped, failed, partial and running runs add a sentence; a cancelled run says "The last run was cancelled. N collected ads were saved. Nothing else changed. Scoring was skipped." (or "No ads were saved."). An interrupted run that the API inferred from the lock says the record and the lock disagree. A cancel that came after the jobs were saved is not shown as cancelled: the badge is the run's own and the sentence says the scrape counts.
- **Footer of the list:** "Records older than 90 days are removed, and the run history is not part of a backup."
- **Details (a button on each card, `aria-expanded`):** the six numbers apart, each with its one-line help (Returned, Filtered out, Collected, Saved, New, Refreshed), then "Saved 455 (3 new, 452 already known and refreshed)" and, for a cancelled run, "Nothing else changed."; duplicates merged, cross-posts merged, ads rejected as not whole; a per-source table (status, returned, filtered out with the top three reasons and a count of the rest, collected, new, proof with its reason texts, error or skip reason, start time and duration), with the note that per-source "New" does not add up to the run's; boards that failed or are not proven, with their reason; ledger effect ("1 closed, 2 marked absent, 0 reopened", or "Nothing else changed" for a cancelled run); scoring ("Finished", "Skipped because the run was cancelled", "Not run, because discovery did not finish"); staging; issues with Error or Warning and "The first 10 of N issues are shown." (no link, because the rest is not available).
- **"What the numbers mean"** at the top, collapsed, with the same six helps and what "Proven" means.

**Honesty rules, each tested:** a value the API says is null is "Not recorded", never 0 (a real 0 is 0). Proof has three states only: **Proven** (the reason text from `src/data/proofReasons.json`), **Not proven** (one line per reason code), and **Not recorded** (an old record, no import block, a source the block has no row for, or any state the screen does not know); Not recorded is never shown as Not proven. A source that had not finished when the run was cancelled is **Unfinished**, never Failed, and has its own tone. A reason code the build has no text for is shown as "Reason code: x", never blank; a test requires a text for every code in the file. Nothing is calculated that the API did not give, except Filtered out per source and per run, which the API itself computes.

**Not done, by design:** no Cancel (S7c), no live updates of a running run (the card says "Refresh to see where it is"), no per-run fetch, no filter or search of the history, no export. The 100 KB default page measured in S7a was accepted as it is.

**Tests:** `tests/js/runView.test.js` (the wording, 19), `tests/js/activityScreen.dom.test.js` (the real screen in jsdom, 20: list, states, Show more, Refresh, hidden tab, no storage, Details, old records, Unfinished, every reason code), `tests/js/navGroups.test.js`. Fixtures are built with the real `project()` from S7a. Mutation-checked: Not recorded shown as Not proven, no data treated as a claim, null shown as 0 (a count, the short Saved, a duration), Saved without its parts, a cancelled run without "Nothing else changed", a reason code without text (in the code and in the file), Unfinished shown as Failed or in the failed tone, a timer, a hidden tab asking, the history written to storage, a wrong default limit, Show more ignoring the cursor, the per-source note missing, an error shown as an empty history, and boards that are not proven hidden. One equivalent mutant: dropping the `!loaded` guard when a hidden tab is shown, since no other path can have loaded it first.

## S7c as built: the live view and Cancel on Activity (2026-11-04)

**Scope:** `GET /api/runs/<runId>?after=N`, the live panel and polling hook on Activity, the Cancel control there and on the Jobs screen's progress line, and a "Details" link from Jobs to Activity. Cancel semantics (S6), the importer, scoring, lifecycle rules and the Jobs screen's own 2.5 s poll are unchanged. No new browser storage key; nothing is stored.

**The endpoint** (`getRun` in `scripts/run-history.js`): Node only, no Python, no lock, no recovery, no write. One record through the same allow-list as the list, and its events from line `after` on (a complete line only; a torn last line waits; a bad line is skipped but counted; at most 200 per answer; a log over 1 MB is not read). Each event goes through `projectEvent`, an allow-list of its own: the type is one of 17 known, step/source/status are checked, counts are numbers, an `error` is summarised like a source error, and a `message` is shown whole only if it is one of the app's fixed texts, else "details withheld" (the rule of S7a). Event fields such as file lists are never returned. 404 for an unknown run or an unreadable record, 422 for a malformed id or cursor. A running record is alive unless the inode-only `/proc/locks` test says nobody holds the lock; unknown reads as alive; a dead one is returned as `interrupted` with `inferred: true` and nothing is marked on disk. `canCancel` is true only for a running Re-scrape; `cancelRequested` comes from the `.cancel` file name.

**Polling** (`src/modules/activity/useLiveRun.js`): one request at once, then every **3 s**, only while the screen is mounted (Activity is the visible view), the tab is visible (`document.visibilityState`) and the last answer said the run is active. A hidden tab clears the timer; showing it asks at once and starts again; a request already on its way is never doubled. After an error it waits 3, 6, 12 and then 30 s and stays at 30; the first good answer resets it. The first answer that says the run is not active is the last request: `onFinished` is called once, with that final record, and nothing is asked again. A 404 ends it the same way. **A run that ends while the tab is hidden** is found on return: one immediate request, one `onFinished`, the history list read once, then nothing. With nothing running there is no live request at all. An answer that arrives after the screen is gone is dropped. The history list itself still never polls; it is read once more when a watched run ends.

**The panel** (`LiveRunPanel.jsx`): "A run is in progress" with a Running badge, when it started, "Running for 2 min 10 s (as of the last update)" (computed from the time of the last answer, so it moves only when the page hears from the server and needs no timer of its own), the step ("Reading the sources", "Scoring the jobs"), a table of sources as they report (the record's rows, plus "Reading…" for a source an event says has started and a row from `source_end` before the record has it; an unreported number is "–", never 0), and a collapsible list of every event in the words of the Jobs screen (`eventText`). A failure of the live request says "The live view could not be updated (…). Trying again in N s. The run itself is not affected." A run that was not started by a Re-scrape says it cannot be cancelled here.

**Cancel** (`CancelRun.jsx`, shared by Activity and Jobs): a "Cancel run" button, only where `canCancel` is true; it asks first ("Cancel this run? The ads it has already collected are saved and nothing else changes. Scoring is skipped.") with "Yes, cancel the run" and "Keep running"; it sends one `POST /api/rescrape/cancel {runId}` however many times it is clicked (a ref guards the window before the button disables). **"Cancel requested" is not "Cancelled":** a 202, or a 200 `cancel_already_requested`, only shows "Cancel requested. The run stops at its next safe point." and hides the button. Until the record itself says `cancelled`, the panel keeps saying Running, and no text says the run has stopped or how many ads were saved (a test polls three times in that state). When the record says so, the run's card says the S6 outcome once, by `statusSentence`/`cancelledText` (no string is repeated, and no second notice repeats it): "The last run was cancelled. N collected ads were saved. Nothing else changed. Scoring was skipped.", "...No ads were saved...", or, when the cancel came after the jobs were saved, "The cancel came after the jobs were saved, so the scrape counts. Scoring was skipped." The other answers are said in the server's own words: 200 `already_cancelled`, `already_finished`, `not_running` (nothing was requested, the live view refreshes), 409 `not_cancellable` (a pipeline or direct run), 404 `unknown_run`, 422; a request that cannot be sent says so, changes nothing and can be tried again. The server's own reply wording for a 202 no longer says "imported, held" (left over from before option D).

**Jobs screen:** its progress line gains "Details" (opens Activity through an `holojob:open-activity` event that App listens for) and the same Cancel for a running Re-scrape; the existing "Cancel requested" line stays for the server's flag, and this control stays silent when that flag is set so the sentence appears once.

**Wording:** the issues line now reads "The first 10 of N issues are shown." with no link or button, because the rest is not available.

**Real check on a scratch copy** (the real orchestrator, discovery and importer, a slow provider, a browser stand-in in its own session; the live endpoint and the Cancel route code ran in a node container; `data/` untouched). Run A (3 ads) finished. Run B (ads 2, 3, 4, 5; ad 4 and 5 new) was watched:

| t | poll | `after` | run | cancelRequested | new events | `next` | response | CPU |
|---|---|---|---|---|---|---|---|---|
| 0 s | 1 | 0 | running | no | 3 | 3 | 1,268 B | 3.69 ms |
| 3 s | 2 | 3 | running | no | 0 | 3 | 595 B | 0.66 ms |
| 6 s | 3 | 3 | running | no | 0 | 3 | 595 B | 2.14 ms |
| 9 s | 4 | 3 | running | no | 0 | 3 | 595 B | 2.53 ms |
| 12 s | Cancel via the S6 route: HTTP 202 `cancel_requested` | | | | | | | 7.9 ms (a one-off that starts the Python cancel command) |
| 12 s | 5 | 3 | **running** | **yes** | 1 | 4 | 819 B | 0.48 ms |
| 15 s | 6 | 4 | **cancelled** | n/a | 7 | 11 | 2,859 B | 10.8 ms |

The cursor moved 0→3→3→3→3→4→11 with no event repeated or lost; polling stopped at the first inactive answer (6 polls). The in-between state was observed for real (poll 5: a cancel on file, the record still running). Outcome: status `cancelled`, step discovery `cancelled` (exit 76), `cancel.outcome` `collected_ads_saved`, saved 4 (2 new, 2 refreshed); ledger generation 1→2, `lastImport` still run A, `partialRuns` [B], `sourceRuns` unchanged (only A), `appliedRuns` [A], entries 3→5 with the one ad B did not return unchanged. The scratch lock was free, the browser stand-in was dead, no process of the scratch tree remained, and the next run started at once (exit 0, generation 3). **Cost of a poll:** 0.5 to 2.5 ms of CPU while the run goes and 595 B of response when nothing is new; the first poll (3.7 ms) and the last (10.8 ms, a finished record with 11 events) were the first time those code paths ran in a cold Node process. The earlier warm measurement of the list (S7a) was 0.3 to 0.6 ms. These runs read `/proc/locks` with the host's whole lock table (about 70 rows, `--pid=host`); the container server reads its own, shorter table.

**A limit found by that check, and the cause of the first failed attempt:** `/proc/locks` lists only the locks held by processes in the reader's PID namespace. A reader in another container (or the host) sees no row and reports "nobody holds the lock", so a live run looks interrupted, Cancel disappears, and the live view stops. "Unknown reads as alive" does not cover this, because the file is readable and simply empty of that lock. In the deployed arrangement the Node server and the Python orchestrator it starts are in the same container (`holojob`), and a lock held inside a container is seen inside it (checked on a scratch lock: the row is there and `lockIsHeld` is true). The scratch check first failed because its watcher ran in a second container; it now shares the host PID namespace. **Not run:** the same probe inside the real `holojob` container. If the API server is ever run outside the container that runs the jobs, a live run will be shown as interrupted.

**Only verified in jsdom, never in a real browser** (S7b and S7c): the layout of the cards, the per-source table and the live table (wrapping, horizontal scroll at phone width, dark mode colours); focus and keyboard behaviour of Details, Cancel, the confirm and the Dismiss; the `<details>` expander; how the Running badge and the spinner look; the sidebar item and the mobile "More" entry (rendered, not clicked); the real page-visibility events when a tab is switched, minimised or the laptop sleeps (jsdom only simulates the event); that a hidden tab really stops the requests (checked in the network panel); the behaviour of the polling timers in a throttled background tab; the Jobs screen "Details" link moving to Activity in the real app shell; and the look of the notice that carries the cancel outcome.

**Tests:** `tests/js/runLive.test.js` (17: the endpoint, cursor, canaries in the record and the event log, nothing written or spawned), `useLiveRun.dom.test.js` (16: the poll, hide/show, the run that ends hidden, the back-off), `activityLive.dom.test.js` (26: the panel, Cancel and its answers, the in-between state, the end), `liveView.test.js` (9), `rescrapeProgress.dom.test.js` (11), route tests in `rescrapeRoutes.test.js`. Mutation-checked (31, run against a clean baseline): polling while hidden, after the run finished (with its three guards removed together), faster than 3 s, a back-off with no cap or that never grows, a hidden-then-shown tab that does not ask, a 404 retried forever, the cursor ignored, finish called twice; a Cancel button on a pipeline run (server flag and Jobs screen) or on a finished run, a double click that sends two, "requested" claiming the run stopped, Cancel still offered once requested, a settled answer that does not refresh, a request without JSON, the list read twice at the end or never, the outcome sentence repeated in a notice; a live response leaking the raw record, an event leaking its raw fields or copying its message or error, an unknown lock read as dead, an inferred run marked on disk, a process started, an unknown run answered 200, a malformed id accepted, an uncapped event log; no Details link on Jobs.

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

## S8a: the job list never silently loses data to the browser's storage limit (2026-11-04)

`saveJobs` (`jobStorage.js`) stores the list in the first shape that fits, and `storageHealth.js` tells the user which one:

| Shape | Stored | Dropped, and where it comes from instead |
|---|---|---|
| full | every row | nothing (a "near the limit" note from 85% of the assumed 5,242,880 characters) |
| lean | as full | `llmFacts`, `engineShadow`, and the text of rows the scored file carries (reloaded from the server). A kept ad, a no-longer-listed row and a hand-entered job keep their text |
| minimal | as lean | also the text of kept and no-longer-listed rows. A hand-entered job always keeps its text |
| error | nothing is written | the last saved copy stays; a permanent warning says the change is not saved |

Always kept in every shape: notes, statuses, outreach, tracking, tailored assets, AI insights.

- **Single place for the text:** `jobTexts.js`. `JobTextGate` (wraps the app in `App.jsx`) asks `POST /api/jobs/texts` (read-only, from the
  ledger index, 100 ids a request, ad text only) before any screen is shown; `loadJobs()` merges the cache into every row it returns, so search,
  outreach providers, `buildAiContext`, `patchJob` and the screens all read the same rows. `saveJobs` also remembers the texts it leaves out.
  Tests per consumer: `tests/js/jobTextsConsumers.test.js`.
- **Cannot be made reliable:** if the ledger is unreachable or holds no text for an id, the app still opens and the notice names how many ads
  have no text ("search, outreach and AI tools cannot read those ads"). Tailoring a kept or no-longer-listed ad is refused with a visible message:
  the server reads only the scored file (functional gap, see DEFERRED).
- The error shape never clears by reading the older copy, and nothing in the browser says "saved" for it.

## S8b: a run with no usable source imports nothing (2026-11-04)

Evidence: on the real-data copy, a run whose sources were all skipped changed 1,982 of 1,990 ledger entries (each got `heldRunId`), grew the
list from 56 to 1,990 rows, cut the corpus from 55 to 8 and moved the generation. That was the 2026-11-02 design and it is replaced.

- **Rule:** with `require_usable`, a run that is not cancelled, asked at least one source to run and has no usable source (usable: state
  `complete` and not held as not run) is a no-op: `importer.plan_import` returns the ledger as it went in with `report.nothingSaved =
  no_usable_source`; `import_staged_run` writes nothing, not even a generation. After it the proof harness shows the same bytes for the
  ledger, the view and `filtered_ads.json`, and 56 rows / corpus 55 / generation 3 for skipped, failed and partial runs alike.
- **Opt-in:** the plain importer behaves as before. The live run (`run_discovery.py`) and `import_run.py --import` pass `require_usable=True`
  (`tests/python/test_no_usable_source.py` checks that these are the only two callers). Cancelled runs keep the S6 partial semantics.
- **Marker:** `imported.json` gets `nothing: "no_usable_source"`. Such a run adds nothing to `appliedRuns` and its dropped ads are not counted
  (`filtered_ads.unrecorded` / `backfill` skip it), and `lifecycle_report` does not read it as evidence.
- **Exit code:** attempted and unusable (a failed or partial source) exits 1: the record is `failed`, with the error "No source gave a usable
  result, so nothing was imported and the job list was not changed." (fixed text in the `run-history.js` allow-list). All skipped exits 0:
  skipped is not failed, so the record stays `skipped` (warning, same text), and the Re-scrape orchestrator skips scoring because the list did not change
  (`step_skipped`, reason `nothing_imported`). Exit 1 would have turned a skipped run into a failed one in the record, in Activity and in the Re-scrape message.
- **Screens:** Activity shows the sentence and the ledger effect; the Jobs screen says "Re-scrape found nothing usable: no source gave a usable result, so the list was not changed. Details in Activity."
- **Tests edited (11), each decided separately:** see the S8b report. Tests of the new rule were updated to exit codes and unchanged bytes;
  tests of something else kept their scenario and got a usable (whole) source.

## Roadmap v2 and the single discovery safety rule (2026-11-04)

Owner-approved, GPT-reviewed. Documentation only: no code, test or data changed. History above is not rewritten; where an earlier entry conflicts with this section, this section wins. The wave table is in [ROADMAP.md](ROADMAP.md#roadmap-v2-recorded-2026-11-04). Goal: Scoring -> Matching -> Application Tracking.

**State:** S1 to S8b are built, deployed from a clean build and merged to main at `d44d9cd`. The "Built, not deployed" statuses in ROADMAP.md were stale and are corrected.

**Execution order:**

- **Wave 0 (P0, minimal):** verified backup plus restore check covering server data and browser state (Keep, statuses, applications), with integrity hashes and a tested restore; include `data/analytics` if not reconstructable; rotate the OpenAI key and `li_at` (the owner does this); align the rules in ROADMAP.md and DECISIONS.md.
- **Wave 1 (P0):** (k)+(q) discovery safety, the one rule below.
- **Wave 2 (P0):** (a1) scoring correctness (junk baseline at most about 5 plus a distinct Insufficient Data state, hard/soft requirements, low-confidence reasons); (e) manual Re-score and tailoring for kept ads; (g) exclude closed ads from the IDF corpus (approved; measured effect at most 1 point); (i) `scoringBehind` after a cancel.
- **Wave 3 (P0):** (a2) scoring quality (skills from the whole candidate history, domain transferability) after basic validation, then (b) the three-level role filter.
- **Wave 4 (P1):** (h) `older_key` policy; (c) Infostud coverage; (n) `lastImport.meta` for partial imports.
- **Wave 5 (P1):** (j) Application Tracking: all records including history-only and voided, snapshots, applied sync, the Applied button opens the tracker, fix history-only showing "Unreviewed", remove the shadow badge.
- **Wave 6 (P2, release blockers):** profile import slices; Phase 4 protections (fact gate, identifier redaction, confirm) are release blockers for AI and application workflows; review the 11 of 17 resume docs with stale unverified-degree findings before use for applications.
- **Wave 7 (P2):** UX, Settings, (d). (d) is likely not a bug: the toggle exists only for Joberty, other boards follow group `serbia`. Treat it as a missing feature and confirm the UX first.
- **Wave 8 (P3):** Step 5 server master (TRACKER_PLAN.md); a verified backup is mandatory before bigger changes.
- **Wave 9 (P3):** (f) ledger growth; (m) hand-edited `appliedRuns` double-count; (o) truncated ledger with unchanged generation; (p) never run the old `import_run --backfill-filtered` below S6; Step 6; tech debt.

**The single discovery safety rule (Wave 1).** A throttled source never proves an ad disappeared. "Ok with 0 read" is not automatically proof of closure; a confirmed-empty source is distinguished from an incomplete or failed read. Successful sources import independently: a partial source must not block the import. Failed sources never affect closing.

**Conflicts resolved (both files now use this rule):**

- ROADMAP.md, DEFERRED: "a source that is `ok` with zero reads counts as usable" and "a sole `partial` source counts as not usable" are replaced by a pointer to this rule. Code still behaves as those lines described until Wave 1 ships; the S8b `require_usable` definition (state `complete`, not held as not run) is to be revisited there.
- DECISIONS.md, S5f "What counts as a proven run": the row "Status ok but nothing read" already said No (for Stale). Under this rule that applies to closing as well, and the row now points here. The Stale rule (30 days, 3 proven runs) and the closure rule (two proven complete board checks, S5c) are both read through the same proof: a source that is throttled, empty-unconfirmed, partial or failed proves nothing.

**Backlog added:** rotate the OpenAI key and `li_at`; resume findings (11 of 17 docs, stale unverified-degree findings).

**Open decisions:** (1) whether the four "Fix scoring" items in ROADMAP.md belong to a1/a2 as split above (hard/soft and low-confidence reasons to a1; whole-history skills and domain transferability to a2); (2) the `older_key` retention window; (3) the Infostud coverage check.

## Design System and UI redesign planning (2026-11-04)

Planning only. No application code, dependency, test or data changed, and the redesign has not started. Documents: [design-system/](design-system/README.md). Roadmap: one row before Wave 0, marked planning only; the other waves are not reordered.

**Owner decisions:**

1. **Name:** keep the current app name until the owner decides otherwise. "HolyJobs" is only the epic's title; the repo says Holojob and `index.html` says Holojob.
2. **Preset:** apply the complete preset `b7CScIWmG`, colours and fonts.
3. **Body font:** from the real CLI output, never guessed. Result: **Lora**, through `html { @apply font-serif }`, so the whole interface is serif.
4. **Primitives:** Base UI accepted (the preset's choice, not Radix).
5. **Sequence:** planning comes before Wave 0; implementation comes after the minimal Wave 0 backup.
6. **Branching:** no long-lived redesign branch. After the docs are reviewed and approved, implementation goes through small independent branches and PRs, so it does not collide with the scoring and matching roadmap.
7. **Design System = the preset plus a central semantic extension:** tokens for fit score, job status, priority, success, warning and error, defined once in the token layer and documented in `TOKENS.md` as "extension, not defined by the preset", with proposed values marked for PO approval. No arbitrary colours inside components.
8. **Testing and browser policy (permanent).** Text in [design-system/README.md](design-system/README.md#testing-and-browser-policy-permanent). Claude Code owns unit, integration, functional regression, build, lint and existing tests. The owner owns visual look and aesthetics, responsive look and UX acceptance, and final design approval. Default: no browser tests. A browser only when a function cannot be reliably verified without it. No crawling, mass screenshots, visual regression, pixel comparison or screenshot baseline. At most one targeted browser smoke test per slice, with a justified need; more only with the owner's approval. Claude states what it could not verify without a browser; visually unverified UI is never presented as visually approved.

**Removed from the plan at the owner's request:** the Playwright dependency, the demo-mode screenshot baseline, all visual regression tooling, browser-based visual tests, any duty for Claude to confirm aesthetics or layout, and the long-lived branch with its rebase rhythm.

**Constraints kept:** no behaviour change, no backend or API change, no new routing framework, no overwriting of existing UI components, no colours or fonts outside the Design System, no secrets or env files in Git. Proposed CLAUDE.md lines are in the README; CLAUDE.md itself is not edited.

**Verified while planning (`shadcn@4.23.0`, in an isolated container with only an empty scratch folder mounted):**

- Preset: `base-mira`, Base UI, `mist`, lucide, Lora, radius `0.625rem`. Snapshot in [design-system/preset/](design-system/preset/README.md).
- `template=react-router` does not matter: tokens are identical to the `vite` scaffold. The app keeps having no router.
- `tsx: false` and `aliases.ui` set to `@/components/ds` give `.jsx` files in `ds/`, so the existing `src/components/ui/` is not touched.
- `ds/sidebar` as supplied writes a `sidebar_state` cookie and binds a keyboard shortcut, and `theme-provider` writes a `localStorage` key; both conflict with the browser storage policy. `theme-provider`, `next-themes` and `sonner` are left out, and the cookie write is removed from `ds/sidebar`.
- `--color-accent`, `--color-accent-hover` and `--color-border` have no consumers, so the preset's same-named tokens do not collide in practice.
- Preset controls default to `h-7`; the current `Button` has `min-h-[44px]`.
- Computed contrast of `muted-foreground` on `muted` in light mode is 4.15:1, below AA. It is a preset value and is left unchanged.

**Implementation choices (standard, not owner decisions):** `src/components/ds/` for registry files; exact version pins; `shadcn` and `tw-animate-css` as dev dependencies; `native-select` before `select`; the repo's dark variant kept until the `dark:` colour uses are gone; `window.confirm` kept in MVP; a ratchet test for palette classes.

**Open PO decisions** (details in [REDESIGN_BACKLOG.md](design-system/REDESIGN_BACKLOG.md#open-po-decisions)):

- O1: approval of the extension token values and aliases.
- O2: sequencing of slices against Waves 2 to 5.
- O3: control size, preset `h-7` or today's 44 px minimum.
- O4: serif everywhere, confirmed once seen.
- O5: whether a mixed look may be deployed between slices.
- O6: whether Wave 7's Settings and UX work merges into Task H.
- O7: colours with no meaning today (`violet`, `indigo`, `green` stat cards) go to neutral.
- O8: `muted-foreground` on `muted` at 4.15:1.
- O9: the registry's sidebar keyboard shortcut.

**Not approved:** any application code change, installing dependencies into the frontend, or starting the redesign.

## Design System preset changed to b1a1cZcRs (2026-11-04)

Owner decision. Still planning only: no application code, dependency, test or data changed. This entry supersedes the preset named in [the planning section](#design-system-and-ui-redesign-planning-2026-11-04); the other decisions there stand.

**What changes in the decisions above:** decision 2 now means the complete preset `b1a1cZcRs`. Decision 3 now gives **Geist**, a sans-serif, so "the whole interface is serif" no longer applies. The snapshot in [design-system/preset/](design-system/preset/README.md) is replaced, and now also holds the component source so the preset can be rebuilt from Git without the website.

**Verified from generated output (`shadcn@4.23.0`, isolated container, only an empty scratch folder mounted, never against the application):**

- **Same:** style `base-mira`, Base UI, base colour `mist`, lucide, radius `0.625rem`, `menuColor: default`, `menuAccent: subtle`; neutral, surface, border, ring and destructive tokens; all 38 component files, byte-identical; every dependency except the font.
- **Changed:** `--primary`, `--primary-foreground`, `--chart-1` to `--chart-5`, `--sidebar-primary`, `--sidebar-primary-foreground` (cyan-based or neutral, now Tailwind `blue` values); `@fontsource-variable/lora` to `@fontsource-variable/geist`; `--font-heading` and the `html` rule from serif to sans.
- **Re-checked, unchanged:** `ds/sidebar` still writes the `sidebar_state` cookie and binds the shortcut; `theme-provider` still writes `localStorage` key `theme`; controls are still `h-7`; `muted-foreground` on `muted` is still 4.15:1; `tsx: false` still gives `.jsx` in `ds/`.
- **New:** `--font-sans` collides by name with the repo's DM Sans, and `body` reads it, so it moves only in the global cutover. Dark `--primary` as text fell from 2.72:1 to 2.23:1. `shadcn apply` over an existing preset leaves the old font import and dependency behind.
- **Closed assumptions:** Geist has Serbian Latin and Cyrillic glyphs and a working `tnum`, read from the font files.

**Open decisions re-evaluated** ([details](design-system/REDESIGN_BACKLOG.md#open-po-decisions)): O4 closed, as serif is gone. O1 changed and still open: values are the same, and `--info` now sits near the blue primary. O10 is new: what replaces `text-teal-*` given dark `--primary` as text. O2, O3, O5, O6, O7, O8 and O9 are unchanged.

**Constraints kept:** React and Vite, no React Router, `src/components/ds/` isolated until migration, no change to business logic, APIs, routing or state, no new browser storage keys, current sidebar and Settings draft behaviour preserved, semantic colours centralized as extension tokens, no invented token values without approval, small independent branches and PRs later.

**Not verified:** nothing was looked at in a browser, so nothing is visually approved. The preset's CSS was built only in the scratch project (Vite 8.3.5, Tailwind 4.3.4), not with the repo's versions. Base UI under the repo's jsdom is still untried.

## Design System final PO decisions (2026-11-04)

Owner decisions. Approved preset: `b1a1cZcRs` (Blue / Mist / Geist / Base UI / Lucide). Documentation only. **Not authorized:** application code changes, Design System installation, UI migration, dependency changes, deployment, push or merge. Implementation does not start until a separate approval is given.

- **O1, semantic extension tokens: approved in principle, NOT closed.** Centralized semantic tokens for success, warning, danger, information, fit scores and application states. No arbitrary colours in components. Concrete values and aliases are pending, presented with measured ratios in [TOKENS.md](design-system/TOKENS.md#part-2-extension-not-defined-by-the-preset). The earlier `--error` name is now `--danger`, to match this wording.
- **O2, sequencing: approved.** Foundations may be prepared first. Jobs and Scoring UI migration aligns with the scoring roadmap. Application Tracker redesign aligns with the tracker changes. Small independent slices and PRs; avoid conflicts with parallel work.
- **O3, control sizes: approved.** Minimum 44 x 44 px interactive target on mobile; compact desktop controls allowed where appropriate.
- **O4, typography: approved.** Geist for headings, body, tables, forms and numerical data. Not activated globally in the initial foundations slice. The global font migration is a separate controlled step, with functional regression verification and PO visual approval.
- **O5, mixed UI: approved.** Temporary coexistence of the old custom UI and the new shadcn UI during development is allowed. The final release must be visually consistent.
- **O6, Settings: approved.** Coordinated with the existing Settings roadmap (Wave 7) to avoid duplicate work.
- **O7, stat cards: approved.** Neutral cards and surfaces by default. Semantic colours only where they carry meaning (fit, status, priority, errors).
- **O8, accessibility and contrast: approved with clarification.** The PO's original Cyan preset was not the source of the reported dark-mode contrast regressions; the Blue/Geist configuration was recommended in the design discussion and then selected. The new preset introduced or exposed contrast problems in specific combinations, and the original is not characterized as defective without evidence. Requirements: preserve Blue/Mist/Geist; identify the exact failing light and dark combinations; propose the smallest token or usage corrections; meet WCAG AA (4.5:1 normal text, 3:1 applicable non-text UI); do not redesign the palette or replace the preset; document original and proposed values with measured ratios; keep corrections centralized. Results: [TOKENS.md](design-system/TOKENS.md#part-3-contrast-o8), measured by `design-system/preset/contrast_check.py` from the committed snapshot. The proposed values await PO verification with O1.
- **O9, sidebar keyboard shortcut: approved.** Not introduced during migration. Existing navigation behaviour and the browser storage policy are preserved.
- **O10, teal text: approved.** Decorative `text-teal-*` becomes semantic or neutral text. Accessible link styling, with underlines where appropriate. Primary Blue for actions and fills where contrast is sufficient. Not every teal class is replaced blindly; existing semantic meaning and contrast are preserved.

**Testing responsibilities, replacing the earlier wording of this policy.** Claude Code owns unit, integration, functional regression, lint, build, token consistency checks and programmatic contrast verification. The PO owns visual appearance, aesthetics, UX review, responsive visual acceptance and final design approval. No Playwright, visual regression tooling, screenshot baselines or new browser tests. A browser only when functionally necessary and explicitly authorized; the earlier allowance of one smoke test per slice no longer applies without that authorization.

**Unchanged:** the minimal Wave 0 backup still comes before implementation. O2's "foundations may be prepared first" is read as foundations before screen migration, not as lifting that gate. The PO can correct this reading.

## Design System final planning decisions, Epic postponed (2026-11-04)

Owner decisions. Documentation only. **The redesign is POSTPONED: the Epic "UI Redesign & Design System" and all its work are To Do until the PO explicitly authorizes implementation. All colours are PROVISIONAL.** Roadmap: [the Epic](ROADMAP.md#epic-ui-redesign--design-system---deferred--to-do). Backlog: [REDESIGN_BACKLOG.md](design-system/REDESIGN_BACKLOG.md).

**O1, semantic tokens: the proposed structure, aliases and values are approved FOR PLANNING PURPOSES ONLY.** No current value is permanently approved. All semantic extension values and contrast corrections remain provisional; before implementation, the complete palette is reviewed again, finalized and approved by the PO.

- `--input` follows the original C2 proposal, with no separate input-border token.
- C1, C3 and U1 to U3 stay planning recommendations.
- `--fit-insufficient` uses neutral styling, not the information colour. This replaces the earlier proposal. Since Weak and Reject are neutral too, its label and the absence of a score band tell it apart from a low score.
- `--app-state-offer-accepted` may use the success colour.
- Warning text on muted surfaces gets a better margin: `--warning` in light mode moves from amber 700 to amber 800, a value already in the scale, and warning text on muted rises from 4.54 to 6.41. Measured by `design-system/preset/contrast_check.py`. Provisional like the rest.

**O2 to O10: preserved as approved** in [the previous section](#design-system-final-po-decisions-2026-11-04). No new evidence shows a material conflict, so none is reopened.

**Implementation prerequisites (future gates, not authorization to execute now):** (1) complete and verify the minimal Wave 0 backup; (2) finalize and approve the colour palette; (3) recalculate contrast ratios against the final colours; (4) verify the semantic-token mappings; (5) recheck framework and dependency compatibility; (6) obtain separate PO implementation approval. Prerequisite 1 settles the earlier open reading of O2: the backup comes before foundations.

**Backlog structure:** one Epic with nine Tasks, replacing the earlier tasks A to J. Screens the nine Tasks do not name are placed by a planning choice the PO can move: Dashboard in Task 2; Intelligence in Task 6; Career Strategy, AI Copilot, Outreach and Quality Audit in Task 7; Activity in Task 8.

**Testing responsibilities, kept as recorded.** When implementation begins, Claude Code owns unit, integration, functional regression, lint, build, token consistency checks and programmatic contrast verification. The PO owns visual review, UX validation, responsive appearance and final design approval. No Playwright, screenshot baselines, visual regression tooling or Chrome tests; browser testing needs separate explicit authorization.

**Not done and not authorized:** application code changes, dependency installation, foundations, component migration, GitHub issues, push, merge or deployment.

## Job relevance, lifecycle, salary and deadline (2026-11-08)

Owner decisions after a calibration on a copy of the data (2,537 ads). Code checks in brackets.

1. **Three title tiers for a role family: target, near, unrelated.** Only an unrelated title is capped, at 40, with `hardCapped` and a reason line. Flat caps of 40 or 50 sent every near-PM ad to Weak; 55 left 67 unrelated ads at Good. From 40 to 54 label, priority and recommendation are the same, so 40 only decides the order inside Weak: an unrelated ad sits below a target-role ad held at 45 or 50. [`UNRELATED_TITLE_CAP` in `scorer.py`; `role_tier.title_tier`; `tests/python/test_role_tier.py`]
2. **`program_management` is accepted for the product family; `project_delivery` is not.** A project or delivery title is near only when enrichment read product responsibility in the ad (track `product_management` or `product_ownership` with its quote); otherwise it is unrelated. Discovery is not changed for these titles. [`src/data/roleFamilies.json` `acceptedRoleTracks`, `titleRules`]
3. **A near-target title scores role 65**, like a product role in other words, so removing the fragment credit does not push real program roles down. [`role_match.py`]
4. **Fragment variants do not match.** `expandRoleVariants` no longer writes the opening words of a role, and `role_match` ignores a variant that only opens a longer target, because stored intelligence still holds them. This differs from the proposed "must end in a role noun": it needs no noun list and works for every family. [`_is_leading_fragment`; `tests/js/roleAdjacencyMap.test.js`]
5. **A closed ad leaves Active whatever work it holds**, Keep included. It stays in All Jobs and in the Application Tracker, which marks it "Ad closed". An application never changes because its ad closed. A stale ad with the owner's work stays in Active. [`composeJobList` in `allAds.js`; `isClosedAd`]
6. **Open before closed applies only to the default sort.** Any column the owner clicks, even back to Score, is respected. [`closedLast`, `DEFAULT_SORT` by identity in `JobTable.jsx`]
7. **Salary column: the pay as stated.** The EUR monthly figure is a second line marked approximate, never the offered salary. Lever `salaryRange` and Ashby salary components are read; a structured figure with no currency is left out, because a bare "N - N yearly" reads as USD. [`format_pay_range`; `statedSalary`, `approximateMonthlyEur`]
8. **Apply by is separate from Closed.** `applyDeadline` comes from the board's expiry, else from an unmistakable sentence in the ad; an ambiguous date is unknown. Expiry closes nothing and moves no score. Warnings: 0 to 1 days critical, 2 to 3 warning, 4 to 7 upcoming, past Expired, unknown Not specified. Sortable; the default sort stays the Fit Score. [`deadline.py`, `jobDeadline.js`]

**Left out on purpose:** the "Urgent only" filter (deadlines on 7 of 379 ads), stricter discovery filtering, keyword-bank changes (removing role names took P1 from 434 to 30 without recalibrating `TARGET_COVERAGE`; Wave 3, a2), and Greenhouse per-job fetching.

## Private files are inspected by shape only (2026-11-08)

During the job-relevance analysis a read-only Python one-off printed entries of `atsKeywordBank` filtered by a role-word pattern, to see how role names sat in the bank. Four entries are whole CV paragraphs, so work history (employers, roles, dates, responsibilities, figures) was printed as tool output, reached the model provider as conversation context and was forwarded with later advisor calls. No name, e-mail, phone or link was in them (checked by count). The session transcript under `~/.claude/` holds a local copy; it is outside the repo and was not inspected.

**Checked with 8-word fingerprints, counts and paths only:** nothing in the container log, `data/analytics`, `data/ai`, `data/jobs`, `data/applications`, `data/outreach`, `graphify-out` or `dist`. No file under `data/` is tracked other than the examples. Two tracked test files share short phrases (longest 9 words, no employer named): ordinary CV wording. No code path prints these values and no test reads the real files. `data/cache` holds CV-derived text in files of mode 644, inside `data/` at 700, so other users cannot reach them.

**Decision:** a rule in `CLAUDE.md` against printing values from these files, and `scripts/inspect-private-data.py`, which reports shape, counts and hashes. [`tests/python/test_inspect_private_data.py` plants a canary in values and keys.] A hook blocking such commands was not added: a pattern cannot reliably recognise a one-off script. The CV paragraphs in the bank are a generator problem left to Wave 3, a2.
## Graph tooling: Graphify output, update cycle and backup (2026-11-08)

Owner decisions for Graphify adapter Milestone 1 (B0, S0, S1, S2). The adapter is a planned, minimal, removable stdlib tool that reads `graphify-out/graph.json` and writes derived files only; no services, databases, network access or LLM extraction. S3 to S6 need separate approval. Roadmap: [Graph tooling](ROADMAP.md#graph-tooling-graphify-adapter---in-progress).

- **D1, graphify-out/ is git-ignored; `graph.json` is not committed.** It is about 10 MB and rewritten whole on every build. It holds no personal data (no `data/` nodes, no absolute paths), but its semantic layer (about 830k tokens to build) is the one part that cannot be rebuilt for free; D4 protects it, not Git. The CLAUDE.md line that expected a committed `graph.json` came from the Graphify installer and was removed. Check: `git check-ignore graphify-out/graph.json` matches.
- **D2, graphify-out/ is in `.dockerignore`.** The Dockerfile copies none of it and `docker-compose.yml` mounts none of it; the app needs nothing from it at build or runtime. Check: `grep -n graphify Dockerfile docker-compose.yml` finds nothing; `.dockerignore` ends with `graphify-out`.
- **D3, the normal cycle uses no LLM.** It is `graphify update .` (AST only), then the adapter once S1 ships. `/graphify --update`, `graphify label` and `graphify cluster-only` without `--no-label` can call a model and need owner approval. Volatile docs (ROADMAP, DECISIONS, CLAUDE.md) are not added to `.graphifyignore`, which would evict their existing semantic nodes; their semantic layer may be stale until a separately approved refresh. Check: no `.graphifyignore` lists them.
- **D4, a full backup outside the repo comes before any Graphify configuration change.** Done 2026-11-06: `~/graphify-backups/holojob-graphify-2026-11-06.tar` (all of `graphify-out/`, `.claude/settings.json`, `.claude/skills/graphify/`; 347 files), with `holojob-graphify-2026-11-06.tar.sha256` next to it, directory 700, files 600. Restore test passed: restored `graph.json` sha256 equal to the live one, all 347 files identical, `graphify query --graph` on the copy exit 0. Check: `sha256sum -c holojob-graphify-2026-11-06.tar.sha256` in that folder.

**Not done and not authorized:** S1, S2, S3 to S6, push, merge or deployment.

## Graph tooling: the Graphify adapter, as built (2026-11-08)

Owner-authorized (S1 to S6, autonomous execution, no push or merge). Code: `tools/graphify_adapter/` (README there). It reads `graphify-out/graph.json`, never writes it, and writes `graphify-out/holojob/` (`index.json`, `architecture.json`, `test-deps.json`, `report.md`). Normal cycle: `graphify update .`, then `.venv/bin/python tools/graphify_adapter/adapter.py build`. Measured on the real graph (graph.json sha256 `69b98ca0…` unchanged throughout).

- **D5, derived files only, fail closed.** Standard library only: no network, subprocess, model call or project import in `adapter.py`. Pinned to Graphify 0.9.103, schema 1; another version or an unknown top-level key exits 3 and writes nothing (`built_at_commit` is optional: Graphify omits it outside a git repository). Every edge and node outside the declared changes is checked equal to the input; each changed or added edge has `_origin: "adapter"` and a `provenance`. Two runs are byte-identical. Check: `tests/python/test_graphify_adapter_core.py`.
- **D6, three freshness lines.** Code graph "current" only when every manifest file's md5 matches, no indexable file is new, and HEAD is readable; else "possibly stale" (with the files) or "unknown". Doc links: rebuilt every run. Semantic docs: "possibly stale" whenever an extracted doc changed since the semantic run. Check: the `test_freshness_*` tests.
- **D7, Python imports (S2), temporary.** A stub import is re-pointed only when exactly one module or package of that name exists across every repo folder, `.venv` site-packages and the standard library, so it is the same file in every run context; anything else stays unresolved. Unreviewed `sys.path` or import-hook writes refuse the build (`tools/graphify_adapter/sys_path_review.json`, 42 reviewed); a `sys.modules` injection blocks its name. Result: 104 candidates, 90 re-pointed, 94 submodule edges added, 14 unresolved (all `text_utils`: two files, and pytest and script contexts load different ones). `graphify affected` import dependents: `ai_gate.py` 2 -> 17, `view_guard.py` 2 -> 10, `salary.py` 1 -> 4, `run_scoring.py` 0 -> 7, `shadow.py` 2 -> 11; all 42 new ones backed by an import line. Remove when a fresh `graphify update .` after an upgrade leaves 0 to re-point. Check: `validate.py imports` (isolated `python -I -S` PathFinder lookups, no project code runs: 454 agree, 0 disagree).
- **D8, proven-wrong inferred edges (S3).** An INFERRED Python call edge is removed only when the source has no import edge to the target file, never names it, and every bare occurrence at the line is bound to something else (parameter, local or module variable, def or class in the file, standard-library import, builtin, import from a file that defines it). Aliases, re-exports, star imports, nonlocal, `name.name`, the target's own module and JavaScript are kept. Result: 51 of 751 removed (all 5 production-to-test edges among them), each hand-labelled wrong (`validation/s3_removals.json`); 0 false negatives; the guards keep 4 further wrong edges. Check: `validate.py calls`.
- **D9, views (S4).** Graphify has no filtered views; its `query`, `path`, `explain` and `affected` take `--graph`. `architecture.json`: `python/`, `src/`, `scripts/`, root config and docs; no tests, design-system preset, tools, fixtures or stubs. `test-deps.json`: production and test code, AST and reconstructed edges only. Same community ids (no re-clustering, no labelling). `affected ai_gate.py --graph .../test-deps.json` lists the 8 test files that import it. The report's test-reference list is static, not runtime coverage. Check: `tests/python/test_graphify_adapter_views.py`.
- **D10, doc links (S5).** Only an inline backticked token outside fenced blocks that is exactly the repo- or doc-relative path of one code file; bare names, suffixes, globs, folders and `data/` never link. Rebuilt every run, so ROADMAP, DECISIONS and CLAUDE.md stay linked with no semantic re-extraction. Result: 265 edges from 27 docs; all 266 unique mentions labelled by hand, precision 266/266, Wilson 95% lower bound 0.9858 (bar 0.98, n >= 200). Check: `validate.py doclinks`.
- **D11, zero LLM tokens per cycle (S6).** `tools/graphify_adapter/zero_token_check.sh` runs the cycle in a throwaway copy with an LLM available but unreachable (dummy API keys set, a fake `claude` first on PATH that leaves a marker, no network): no marker, no traceback or connection attempt, Graphify's `cost.json` 829383 / 0 tokens and 1 LLM run before and after, 591 semantic nodes kept, AST and doc links updated, real repo byte-identical. The copy has no `.git`, so the "current" freshness path and a post-update graph that carries `built_at_commit` are covered by unit tests only. The Claude Code session that runs a cycle still spends its own tokens.

- **D12, one set of graph rules (CLAUDE.md).** Agents query `architecture.json` for architecture questions and `test-deps.json` for impact analysis and related tests; the original `graph.json` is used only to verify raw data. Check: the CLAUDE.md "graphify" section has no rule that queries the default graph.

**Not done:** `graphify update .` on the real repo (graph.json kept as built; run the cycle above), the upstream Graphify issue (configurable Python import roots; draft in the S6 report, the owner files it), push or merge.

## Workflow sizes and UI skills (owner decision, 2026-11-08)

Recorded in `CLAUDE.md` ("Workflow sizes", "UI skills"). Docs only; no code changes.

- **Workflow sizes.** S (columns, UI fixes): implement, test, commit. M (role scoring, filters, ad statuses): short self-directed analysis, implement, test, commit, no separate analysis round. L (discovery pipeline, importer, migrations, AI scoring architecture): Plan Mode, one approval, then autonomous implementation; stop only for a blocking product decision or significant risk; one final report. The owner decides product behavior, Code decides the technical approach. Skills and plugins add no ceremony to S and M.
- **UI skills.** `docs/design-system` has priority over any UI plugin guidance (UI UX Pro Max). No external image-generation or logo / icon services from plugins, since they send prompts off the server (principle: personal data and prompts stay on the home server).
- **Code check:** none; these are working rules for the agent, nothing in the code enforces them.

## Wave 0: verified backup and restore check (2026-11-08)

Minimal change in `scripts/backup-handler.js`, `scripts/backup-check.js`, `python/match_engine/competency_backup.py`. Tests: `tests/js/backupIntegrity.test.js`, `tests/python/test_competency_backup.py`.

- **What is reconstructable (technical decision).** In the backup now: everything already there, plus `data/analytics/` (run records, event logs, `skill_gap.json`: nothing else holds them, 168 KB, so the 2026-11-03 "not worth backing up" is reversed; the commit marker stays out). Not in it, on purpose: `data/secrets`, `.env`, `claude-config` (credentials); `data/jobs/staging` and the lock files (working state of one run); `data/ai` (budget ledger and settings) and `data/config` (provider choice): small and not reconstructable, but they hold budget accounting and machine settings, not job-hunt work, and restoring a ledger would hide spending: **owner to decide** whether they join. Reconstructable, so not a reason to add: `data/cache` (included anyway), `data/audits`.
- **Browser state.** Keep, statuses and the hand-entered jobs live only in the browser's job list. The export already replaces the server's `data/jobs/scored_jobs.json` with the list the browser sends (kept as it was, so a restore brings Keep and statuses back); profile and intelligence likewise. Applications are server files (`data/applications`). The manifest now records `browserState: {profile, intelligence, jobs}`: `jobs: false` means the browser sent nothing and Keep and statuses are NOT in that archive.
- **Integrity.** Manifest version 2.0: `files: { name: { sha256, bytes } }` for every file in the zip (each file is read once, so the hash is of the zipped bytes). `importBackupZip` verifies the whole archive first and refuses it, writing nothing, on a changed file, a file the manifest lists but the zip lacks, a file the manifest does not list, a duplicate entry or an unreadable manifest. An archive from before manifests (no `files`) still restores, and the answer says `verified: false`.
- **Restore check.** `checkBackupRestore(zipBuffer)` / `node scripts/backup-check.js <zip>`: verify, restore into a fresh `mkdtemp` directory (never `./data`), compare the sha256 of each restored file with the manifest, delete the directory, print PASS or FAIL with counts and file names only. Application files are merged by the store, not copied, so they are checked in the archive and counted as `merged`. It also FAILS an archive without hashes. Run it outside the server's data: `podman cp` the zip into a throwaway container, or `podman exec holojob node scripts/backup-check.js /tmp/x.zip` (it reads only the zip and `/tmp`).
- **Lock.** The web restore already holds the pipeline lock (`withRunLock`, no run under it or during it). The Python restore had none: `competency_backup.restore` now takes `data/jobs/.pipeline.lock` under its root without waiting and refuses ("nothing restored") while a run holds it. Not covered: a tracker edit in the Node server during a restore; application entries are merged through the store's own lock, and every other restored file is written atomically.
- **Not verified.** No browser was used: the Settings buttons were not clicked, and the download of a real archive from the running server was not made (the server was up and the host must not run jobs against `./data`). The check ran on fictional trees only. The owner should make one real backup and run `backup-check.js` on it.
- **Code check:** `tests/js/backupIntegrity.test.js` (manifest, tamper detection, restore into a temp directory), `test_restore_refuses_while_a_run_holds_the_pipeline_lock_and_works_after`.


## Wave 1 discovery safety built (2026-11-08)

Implements the single discovery safety rule of 2026-11-04. Branch `wave1-discovery-safety`, local, not merged. Owner decisions: an empty board stays held; a partial source with something proven imports; one failing JobSpy site must not fail the ads other sites read; closing needs proof of a complete read of that board, not a read class alone.

- **Read class** (`providers/base_provider.py`, `classify_read`): `ok`, `confirmed_empty` (every part answered and held no ads), `incomplete` (partial, throttled, or a plain `ok` with nothing read), `failed`, `skipped`. Kept in the staging footer (`readClass`), per board in `boardsRead` (`readClass`), in the run record (`sources[].readClass`), the `source_end` event, and projected by `run-history.js` (unknown when absent). Status and counts only.
- **Empty is held, not closing:** a confirmed-empty board is classified and its ads stay open (existing `keptEmptyBoard`). Closing still needs two consecutive misses on a board whose read was complete (`board_evidence`, S5c); a board line whose `readClass` is not `ok` is never complete, whatever `complete` says.
- **JobSpy:** `jobspy_adapter.fetch_jobs` marks `df.attrs["sitesFailed"]`; a search where every site raised is a failed search (provider status `failed`/`partial`), not "0 ads". Ads from the sites that answered are kept, with a warning for the failed site. JobSpy never closes ads (search source); this fixes the run record and the stale proof.
- **Usable gate** (`importer.plan_import`, S8b revisited): usable is state `complete`, or `partial` with a proven board (snapshot sources) or imported ads (search sources), and not held as not run. Its failed boards stay held. A sole `partial` source with nothing proven still changes nothing. `test_no_usable_source.py` updated: the `partial` case now carries no ads; a new test covers a partial source that read ads.
- **Code check:** `tests/python/test_wave1_safety.py` (throttled 429/403/500 closes nothing, confirmed-empty held while a complete board still closes, mixed run, partial sole source, JobSpy), `test_board_completeness.py`, `test_run_log.py`, `tests/js/runHistory.test.js`.

## Wave 2 scoring correctness built (2026-11-08)

Branch `wave2-scoring-correctness`, local, not merged. Owner approved the plan with two corrections (below).

- **(g) Closed ads out of the IDF corpus.** `row_state.in_idf_corpus`: a closed ad and a row a run did not find are scored but are no part of term rarity; a hand-entered job is always in. Lifecycle rules are unchanged (a closed ad is still `isClosed`, still listed and scored). Code check: `test_readers_not_found.py` (`test_a_closed_ad_is_out_of_the_corpus_but_scored`, with a guard that the row would move scores if it were in).
- **(i) `scoringBehind` after a cancel.** The server's answer was right; the page never asked again once no run was active, so the banner survived the Re-score that fixed it. `useRescrapeRun` returns `refresh()`; the Jobs screen calls it after a Re-score. Server and lifecycle untouched. Not covered: a judged run from the pipeline card does not refresh the banner (it reloads with the next status read). Code check: `tests/js/useRescrapeRunRefresh.dom.test.js`.
- **(a1) Insufficient Data is a state, not a band.** `python/job_scoring/data_sufficiency.py`. An ad is insufficient when it has no extracted requirement (`llmFacts.requirements`) AND is neither a full description (>= 80 characters and >= 30 distinct terms) NOR an informative short one (>= 12 distinct terms and >= 2 duty / requirement cues such as "responsib", "requir", "years", "stakeholder"). The numeric thresholds are a first signal only: a short but informative ad, or one with extracted requirements, is scored. Repeated filler does not count (distinct terms). The result carries `dataStatus: "insufficient"`, `insufficientReasons`, `matchLabel: "Insufficient data"`, `priority: "Unrated"`, `applyRecommendation: "Not assessed"`, `hardCapped: true`, and `matchScore` at most 5 (`SCORE_CEILING`), applied last, after the role-tier, off-track, red-flag, work-authorization and location caps, which are unchanged. The number stays in the record only for older readers: the UI shows the state with its reasons, and `fitScoreOf` (sort, minimum-score filter, averages, stats) reads it as no score; it gets no priority or apply badge. The fit judge never sees it. `meta.summary.insufficient` counts it. Tune the constants in `data_sufficiency.py`; recheck against a real run. Code check: `test_data_sufficiency.py`, `test_manual_jobs.py`, `tests/js/insufficientData.test.js`.
- **Hard vs soft requirements: reviewed, not redesigned.** The split is an LLM fact (`enrich_jobs.py`: `must` / `preferred` / `nice`; an unlabelled requirement defaults to `must`); the scorer only reports `mustHaves` (`skill_match.py`), dealbreakers belong to the opt-in judge, and `yearsRequired` is the one requirement that moves a dimension. No scoring change. What was added is visibility: **`confidence`** on every scored job, `{level: "normal" | "low" | "none", reasons}`. Low-confidence reasons: requirements not extracted (so must / nice-to-have are not separated), description under 400 characters, location not stated, seniority not stated, no keyword bank. They never change the score; Job Details shows them next to it.
- **(e) Manual Re-score of kept ads.** Keep is a browser flag, so a kept ad that left the list had no scored row and could not be tailored (`run_tailor.py` reads `scored_jobs.json`). A "Re-score this ad" button on Job Details (kept ads only; user-triggered only) calls `POST /api/jobs/kept/rescore {jobId}` -> `python/job_scoring/rescore_kept.py`: reads the ad from the job-history ledger by id (the browser sends only the id), scores it with the same `score_jobs()` over the list, the hand-entered jobs and the other registered ads, and merges that one row into `scored_jobs.json` (other rows and `tailoredAssets` untouched). It makes **no model call and no network call**, so the AI budget gate has nothing to approve; the judge stays the existing confirmed `--judge` run, which now includes these ads like any other. The browser patches only the scored fields (`scoredPatch`) and sets `keptRescoredAt`; Keep, notes, status, application tracking and tailored assets are owner fields and are not touched. Tailoring is unblocked for a kept ad with `keptRescoredAt` (`tailoringBlocked`). The row is marked `keptRescore` and is no part of the IDF corpus, so it moves no other ad's score. A run active -> 409 `run_active`; an id the ledger lacks -> 404, nothing written.
- **Removal rule for the re-scored set (owner correction).** `data/jobs/rescored_kept.json` (`{ids: {jobId: {rescoredAt}}}`, mode 600) lists the ids `run_scoring.py` adds to every run, so a full Re-score keeps the row. It is pruned: before each Re-score / judged run / pipeline run the browser sends the ids it still keeps (`POST /api/jobs/kept/sync`), and the server drops every id that is neither kept nor has an application (applications read from the application store, never written; an unreadable application store prunes nothing). Pruning removes the id only: the owner's stored copy of the job and its saved score stay in the browser, and applications are never touched. The server's `scored_jobs.json` row for a pruned id disappears at the next scoring run, as any off-list row does. Code check: `test_kept_ads.py`, `tests/js/keptRescore.test.js`.
- **Test fixtures.** Several fixtures used one-line ads (for example "Own the roadmap."); they were genuinely thin and now are Insufficient Data, so the fixtures carry a real ad text. `RARE` in `test_readers_not_found.py` gained distinct terms for the same reason.
- **Not verified without a browser:** how the "Insufficient data" chip and its tooltip, the low-confidence note, the Re-score button and its messages look and behave; the Jobs table, filter and sort with real data; the banner clearing after a real cancelled Re-scrape. These are visually unapproved.
- **Intermittent tests (investigated 2026-11-08).** `test_cancel.py::test_a_cancelled_run_whose_dropped_ads_could_not_be_saved_waits_and_a_backfill_saves_it_once` and `test_view_guard.py::test_recovery_import_of_a_staged_run_whose_import_never_happened` failed in some full runs with "A job run is in progress", the first also with the Wave 2 changes stashed. Re-run: both pass alone on `main` and on this branch, and the full suite passed twice here (2797) and once on `main` (2762). The tests use a temp lock (`conftest.py` sets `HOLOJOB_PIPELINE_LOCK` to `tmp_path`), the real `data/jobs/.pipeline.lock` is held by no process, so it is not a host job and not Wave 2. Cause not pinned down; likely a lock descriptor left by a child process of an earlier test. Treat as known flaky tech debt.

## Wave 3 scoring quality and the three-level role filter built (2026-11-08)

Branch `wave3-scoring-quality`, local, not merged. Owner approved the plan with two corrections, both applied: a search term (`extra_terms`) never turns a title into Target, and the transfer reason always says "assumed".

- **(b) Three tiers in discovery** (`providers/role_filter.py`, `role_tier()`). **Target:** a target phrase (`TITLE_INCLUDE`) or a board position set by hand. **Near:** `project manager`, `delivery manager`, `program(me) manager`, `product operations / ops / management`, `tpm`, Serbian `projekt(ni) menadžer`, `menadžer projekata`, `rukovodilac projekta` (diacritics folded), a board position that names one of these, or a title that only holds a caller's search term. **Excluded:** seniority terms (`junior`, `intern`, `praktikant`, `pripravnik`) and other functions (`account / sales / area sales / brand / category manager`, `product technologist`), checked first and beating a board position, plus `title_not_matched`. Target and Near both go to scoring; `role_drop_reason` and `is_relevant_role` drop only Excluded, so no caller changed. A project title is no longer rejected by name. Scoring is unchanged and stays responsible: `title_tier` calls a project or delivery title Near only when enrichment read product responsibility in the ad, else Unrelated, capped at 40; `project_delivery` is still not an accepted track. The near list is a constant; `test_role_filter_tiers.py` checks it against `roleFamilies.json` `titleRules`. The reason codes in the discard ledger are unchanged; `title_excluded:project manager` and `title_excluded:delivery manager` no longer occur.
- **Dry run** (`scripts/role-tier-dryrun.py`, counts only, reads `filtered_ads.json`, writes nothing): of 1396 ads the role filter dropped, 402 become Near and 4 Target, 990 stay Excluded. By source: Infostud 528 dropped, 5 kept now; JobSpy 817, 390 kept now (140 were `project manager`, 244 `title_not_matched` that are `product management` / `program manager` / `tpm` titles); Workable 50, 11; Joberty 1, 0. The board position and the run's search terms are not in the file, so the numbers are a lower bound. **Finding:** in the stored data Infostud's drops are almost all `title_not_matched` (508 of 528; production, retail and sales roles), not `project manager` (2), so the three tiers do not by themselves recover most of Infostud's ads; its 392 of 409 needs a fresh run to look at (that is slice (c), Infostud coverage). Cost: every Near ad is read in full (Infostud: one request each, 1 s apart) and enriched through the gate.
- **Keyword bank holds keywords** (`keywordShape.js`, `keyword_shape.py`, fixture `tests/fixtures/keyword-shape.json` run by both). Root cause: `cleanKeywordBank` treated any string with a space or hyphen as a phrase, so whole work-experience entries reached `mediumPriority`, `experienceMap.domainsWorkedIn` and `resumeKeywords`. A keyword is at most 6 words and 48 characters, with no comma, semicolon, colon, sentence end, line break or bullet. Applied to every bucket and to `extractMeaningfulPhrases` ("Role at Company" gives the role) and `extractWorkDomains`. Education and certification lines longer than that no longer enter the bank (intended). Python ignores such entries in a bank already stored and says so in the skill reasons ("N keyword-bank entries are CV prose ... regenerate the intelligence"), until the owner regenerates it.
- **Skills from the whole history** (`historySkills.js`, vocabulary `src/data/skillsVocabulary.json`). Every history entry of every CV (`experienceDetail`, `workExperience`, skill / competency / tool lists) is scanned; result `historySkills: [{term, entries, listed}]`, no text stored. Non-technical skills no longer vanish in `classifySkills`; they go to `productBusiness` / `leadership`. Bank: stated by 2+ entries is high, one entry medium, list-only supporting. `_candidate_tokens` reads them for the report of stated requirements; that report is still not scored (unchanged). `_candidate_digest` is unchanged, so the privacy list in CLAUDE.md is unchanged.
- **Domain transfer** (`domain_transfer.py`, data `src/data/domainAdjacency.json`, `historyEntries` in the intelligence: role, period, industry ids, capability ids, no text). **Proven:** an entry of the candidate is in the ad's own industry: +16. **Transferable (assumed):** no entry is, but an entry in an adjacent industry states a capability the ad also asks for, on a documented edge with a `why`: +8 per bridge, at most +16. Inside the industry dimension only (weight 10, so at most about +1.6 on the score); an avoided industry stays 20; an Unrelated title gets none (the 40 cap holds, and the reason says "Industry transfer not applied"). Every reason names the entry (role and period) and the capability, and an assumed one ends "Not proven experience in <industry>". Result field `transferability: {applied, bonus, proven, bridges, skipped}`. Proven credit is new: without it an assumed bridge would out-score the candidate's own industry. The table is small and fixed; structural similarity beyond it (the two-sided marketplace example in ROADMAP) is not judged.
- **Calibration.** `TARGET_COVERAGE` 0.32 to 0.36 (see the comment in `skill_match.py`). Measured on the 436 jobs of `scored_jobs.json` with a regenerated bank: mean score -0.1, >= 80: 9 to 12, P1 (>= 76): 48 to 69 (0.32 would give 102). `P1_MIN_SCORE` left at 76: whether P1 should shrink back to about 48 is the owner's call. With the bank not yet regenerated, the same ads score higher (mean +3.1, P1 207), because the cleaned stale bank is much smaller; regenerate before a Re-score.
- **Not changed:** Wave 1 (read class, closing guard), Wave 2 (Insufficient Data, low-confidence reasons, kept Re-score), location and visa caps, the Unrelated cap of 40, the budget gate (no new AI call).
- **Not verified without a browser:** that Regenerate in the profile screen rebuilds the stored bank and the new fields in `localStorage` and the `data/` mirror; how the transfer reasons look in Job Details (they arrive in `job.reasons`, which the page lists as positive reasons).
- **Code check:** `tests/python/test_role_filter_tiers.py`, `test_discards.py`, `test_keyword_shape.py`, `test_domain_transfer.py` (including an Unrelated title with a valid bridge staying at or under 40), `tests/js/keywordShape.test.js`, `tests/js/historySkills.test.js`.

## CLAUDE.md slimmed to always-needed rules (2026-11-08)

Owner decision, size M, no app code changed. `CLAUDE.md` went from 36386 to 7230 bytes so the fixed token cost per session drops. It keeps only what is wrong in almost every task: privacy and never printing secrets, approvals and git rules (no push, merge or deploy without the owner), owner-runs-commands, the S / M / L workflow, the testing and commit policy, the test commands, graphify rules, one-line pointers, and "never read DECISIONS.md, data-shapes.md or ROADMAP.md whole". Privacy and git rules stay in `CLAUDE.md` on purpose and are never moved into paths-scoped files. Everything else moved verbatim, nothing deleted: reference sections to `.claude/rules/*.md` with `paths:` globs (`settings-screen`, `job-details`, `manual-jobs`, `request-guard`, `secret-store`, `ai-gate-and-selection`, `privacy-inventory`, `markets-and-data-source`, `container`, `private-file-modes`), test and pre-push detail to `docs/ARCHITECTURE.md`. `.claude/settings.json`, plugins, hooks and the graphify skill are untouched. **Code check:** every glob matches at least one tracked path and every pointer in `CLAUDE.md` resolves (checked with a script, 2026-11-08).
