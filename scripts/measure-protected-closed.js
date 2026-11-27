#!/usr/bin/env node
/**
 * List-cleanup brief item 2: protected (Saved, applied, Keep) ads that the ledger marks closed must stay in Active with the Expired badge.
 *
 * Runs the server's own list code (`queryJobList`) over the real data, read only, and prints: the Active total, how many Active rows carry
 * the Expired badge, and for each id given (default: the three ids of the 2026-11-27 report) whether it is in Active and its history state.
 * Output: counts, ids and states. No title, company, note or text.
 *
 *   scripts/node-sandbox node scripts/measure-protected-closed.js [ID...]
 */
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import { loadSettings as loadApplicationSettings, loadStore } from './application-store.js'
import { loadState } from './job-state-store.js'
import { importJobsFromFile } from '../src/modules/jobs/jobStorage.js'
import { queryJobList } from '../src/modules/jobs/jobListQuery.js'

const DATA_ROOT = '/srv/holojob'
const read = (rel) => JSON.parse(fs.readFileSync(`${DATA_ROOT}/${rel}`, 'utf-8'))
const watched = process.argv.slice(2).length ? process.argv.slice(2) : ['a7fd432ff2874215', '0c346d0d52357fc6', 'e08801f9a1f88500']

const run = spawnSync('python3', ['python/job_discovery/all_ads.py', '--root', DATA_ROOT], { encoding: 'utf-8', maxBuffer: 512 * 1024 * 1024 })
if (run.status !== 0) { console.log(`all_ads.py failed (exit ${run.status})`); process.exit(1) }
const answer = JSON.parse(run.stdout)
if (!(answer?.ok === true && Array.isArray(answer.rows))) { console.log('all_ads.py gave no rows'); process.exit(1) }

const scored = read('data/jobs/scored_jobs.json')
const windowDays = read('data/ai/settings.json').activeWindowDays ?? 14
const input = {
  stored: importJobsFromFile({ meta: scored.meta, jobs: scored.jobs }, null).jobs,
  server: answer.rows,
  jobStateDoc: loadState(DATA_ROOT).doc,
  applications: { status: 'ready', store: loadStore(DATA_ROOT), settings: loadApplicationSettings(DATA_ROOT) },
}
const list = (mode) => queryJobList({
  ...input, reference: Date.now(), mode, filters: {}, classes: [], recent: false, sort: null, offset: 0, limit: 100000, withIds: true, withCounts: false, activeWindowDays: windowDays,
})
const all = new Map(list('all').rows.map((row) => [row.jobId, row]))
const active = list('active')
const activeRows = new Map(active.rows.map((row) => [row.jobId, row]))
const expiredInActive = active.rows.filter((row) => row.historyState === 'expired').length
console.log(`Active: ${active.total} ads; with the Expired badge: ${expiredInActive}; All: ${all.size}`)
for (const id of watched) {
  const row = all.get(id)
  console.log(`  ${id}: in Active ${activeRows.has(id)}; class ${row?.class ?? 'no row'}; historyState ${row?.historyState ?? 'none'}`)
}
