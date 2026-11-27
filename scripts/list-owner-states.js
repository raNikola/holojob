#!/usr/bin/env node
/**
 * The owner's state of every ad the list can show (mode "all"), read only, one record per ad: [jobId, status, keep, applied].
 * status is new | saved | rejected | applied_manually (job-state.json); keep is the Keep flag; applied is true when the application store
 * holds a non-voided application for the ad. Ids and flags only. Used by `scripts/measure_strong_reliability.py`.
 *
 *   scripts/node-sandbox node scripts/list-owner-states.js
 */
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import { loadSettings as loadApplicationSettings, loadStore } from './application-store.js'
import { loadState } from './job-state-store.js'
import { importJobsFromFile } from '../src/modules/jobs/jobStorage.js'
import { queryJobList } from '../src/modules/jobs/jobListQuery.js'
import { appliedJobIds } from '../src/modules/applications/appliedFilter.js'

const DATA_ROOT = '/srv/holojob'
const read = (rel) => JSON.parse(fs.readFileSync(`${DATA_ROOT}/${rel}`, 'utf-8'))

const run = spawnSync('python3', ['python/job_discovery/all_ads.py', '--root', DATA_ROOT], { encoding: 'utf-8', maxBuffer: 512 * 1024 * 1024 })
const answer = run.status === 0 ? JSON.parse(run.stdout) : null
if (!(answer?.ok === true && Array.isArray(answer.rows))) { console.error('all_ads.py gave no rows'); process.exit(1) }
const scored = read('data/jobs/scored_jobs.json')
const store = loadStore(DATA_ROOT)
const result = queryJobList({
  stored: importJobsFromFile({ meta: scored.meta, jobs: scored.jobs }, null).jobs,
  server: answer.rows,
  jobStateDoc: loadState(DATA_ROOT).doc,
  applications: { status: 'ready', store, settings: loadApplicationSettings(DATA_ROOT) },
  reference: Date.now(), mode: 'all', filters: {}, classes: [], recent: false, sort: null, offset: 0, limit: 1000000, withIds: false, withCounts: false,
  activeWindowDays: read('data/ai/settings.json').activeWindowDays ?? 14,
})
const applied = appliedJobIds(store)
console.log(JSON.stringify(result.rows.map((row) => [row.jobId, row.status || 'new', row.keptByUser === true, applied.has(row.jobId)])))
