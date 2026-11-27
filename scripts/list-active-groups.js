#!/usr/bin/env node
/**
 * The Active list of the Jobs screen as the server builds it (`queryJobList`, default filters), read only, one pair per ad: [jobId, group].
 * The group is `listGroupOf` of the row (strong, possible, weak, notRead, blocked, closed, unscored), so the tier code is the screen's own.
 * Output: JSON on stdout, ids and group names only. Used by `scripts/measure_list_tiers.py`.
 *
 *   scripts/node-sandbox node scripts/list-active-groups.js
 */
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import { loadSettings as loadApplicationSettings, loadStore } from './application-store.js'
import { loadState } from './job-state-store.js'
import { importJobsFromFile } from '../src/modules/jobs/jobStorage.js'
import { queryJobList } from '../src/modules/jobs/jobListQuery.js'
import { listGroupOf } from '../src/modules/jobs/fitTier.js'

const DATA_ROOT = '/srv/holojob'
const read = (rel) => JSON.parse(fs.readFileSync(`${DATA_ROOT}/${rel}`, 'utf-8'))

const run = spawnSync('python3', ['python/job_discovery/all_ads.py', '--root', DATA_ROOT], { encoding: 'utf-8', maxBuffer: 512 * 1024 * 1024 })
const answer = run.status === 0 ? JSON.parse(run.stdout) : null
if (!(answer?.ok === true && Array.isArray(answer.rows))) { console.error('all_ads.py gave no rows'); process.exit(1) }
const scored = read('data/jobs/scored_jobs.json')
const result = queryJobList({
  stored: importJobsFromFile({ meta: scored.meta, jobs: scored.jobs }, null).jobs,
  server: answer.rows,
  jobStateDoc: loadState(DATA_ROOT).doc,
  applications: { status: 'ready', store: loadStore(DATA_ROOT), settings: loadApplicationSettings(DATA_ROOT) },
  reference: Date.now(), mode: 'active', filters: {}, classes: [], recent: false, sort: null, offset: 0, limit: 100000, withIds: true, withCounts: false,
  activeWindowDays: read('data/ai/settings.json').activeWindowDays ?? 14,
})
console.log(JSON.stringify(result.rows.map((row) => [row.jobId, listGroupOf(row)])))
