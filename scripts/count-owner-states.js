#!/usr/bin/env node
/**
 * Where the owner's acted-on ads (Applied, Saved, Rejected, Keep) drop out between the raw files and the list, read only, counts only.
 * Stages, one row per status: the raw file (job-state.json entries; application store, voided or not), the ad exists in scored_jobs.json,
 * the ad is a row of the list's "all" composition, the ad is a row of the Active list. An id is never printed.
 *
 *   scripts/node-sandbox node scripts/count-owner-states.js
 */
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import { loadSettings as loadApplicationSettings, loadStore } from './application-store.js'
import { loadState } from './job-state-store.js'
import { importJobsFromFile } from '../src/modules/jobs/jobStorage.js'
import { queryJobList } from '../src/modules/jobs/jobListQuery.js'
import { isActive } from '../src/modules/applications/foldApplication.js'

const DATA_ROOT = '/srv/holojob'
const read = (rel) => JSON.parse(fs.readFileSync(`${DATA_ROOT}/${rel}`, 'utf-8'))

const run = spawnSync('python3', ['python/job_discovery/all_ads.py', '--root', DATA_ROOT], { encoding: 'utf-8', maxBuffer: 512 * 1024 * 1024 })
const answer = run.status === 0 ? JSON.parse(run.stdout) : null
if (!(answer?.ok === true && Array.isArray(answer.rows))) { console.error('all_ads.py gave no rows'); process.exit(1) }
const scored = read('data/jobs/scored_jobs.json')
const store = loadStore(DATA_ROOT)
const state = loadState(DATA_ROOT).doc
const query = (mode) => queryJobList({
  stored: importJobsFromFile({ meta: scored.meta, jobs: scored.jobs }, null).jobs,
  server: answer.rows,
  jobStateDoc: state,
  applications: { status: 'ready', store, settings: loadApplicationSettings(DATA_ROOT) },
  reference: Date.now(), mode, filters: {}, classes: [], recent: false, sort: null, offset: 0, limit: 1000000, withIds: false, withCounts: false,
  activeWindowDays: read('data/ai/settings.json').activeWindowDays ?? 14,
}).rows
const inScored = new Set(scored.jobs.map((job) => String(job.jobId)))
const inAll = new Set(query('all').map((row) => row.jobId))
const inActive = new Set(query('active').map((row) => row.jobId))

const sets = { Applied: new Set(), 'Applied (incl. voided)': new Set(), Saved: new Set(), Rejected: new Set(), Keep: new Set() }
let withoutJobId = 0
for (const app of Object.values(store?.applications ?? {})) {
  const id = app?.posting?.jobId
  if (typeof id !== 'string' || !id) { withoutJobId += 1; continue }
  sets['Applied (incl. voided)'].add(id)
  if (isActive(app)) sets.Applied.add(id)
}
for (const entry of Object.values(state?.jobs ?? {})) {
  if (typeof entry.jobId !== 'string') continue
  if (entry.status === 'saved') sets.Saved.add(entry.jobId)
  if (entry.status === 'rejected') sets.Rejected.add(entry.jobId)
  if (entry.keep === true) sets.Keep.add(entry.jobId)
}
console.log(`applications in the store: ${Object.keys(store?.applications ?? {}).length}, without a job id: ${withoutJobId}`)
console.log('status                 | raw file | in scored_jobs | in the "all" list | in Active')
for (const [label, ids] of Object.entries(sets)) {
  const count = (where) => [...ids].filter((id) => where.has(id)).length
  console.log(`${label.padEnd(22)} | ${String(ids.size).padStart(8)} | ${String(count(inScored)).padStart(14)} | ${String(count(inAll)).padStart(17)} | ${String(count(inActive)).padStart(9)}`)
}
