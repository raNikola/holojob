#!/usr/bin/env node
/**
 * List-cleanup brief B3: where the owner's must-keep ads sit in the default Jobs order.
 *
 * Runs the server's own list code (`queryJobList`, the same inputs `scripts/job-list.js` builds its index from) over the real data, read only,
 * and prints rank and percentile of each must-keep id. Output: ids, statuses, ranks and counts. No title, company, note or text.
 * The must-keep ids are Saved / Rejected from job-state.json and Applied from the job ids of the applications store.
 *
 *   scripts/node-sandbox node scripts/measure-list-cleanup-order.js
 *
 * The sandbox mounts /srv/holojob/data read-only at its own path, so nothing can be written. `server` rows come from python/job_discovery/all_ads.py
 * (the same file the route runs) with the sandbox's python3; if that fails the script says so and ranks over the scored rows only.
 */
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import { loadSettings as loadApplicationSettings, loadStore } from './application-store.js'
import { loadState } from './job-state-store.js'
import { importJobsFromFile } from '../src/modules/jobs/jobStorage.js'
import { queryJobList } from '../src/modules/jobs/jobListQuery.js'

const DATA_ROOT = '/srv/holojob'
const read = (rel) => JSON.parse(fs.readFileSync(`${DATA_ROOT}/${rel}`, 'utf-8'))

function mustKeep() {
  const out = new Map()
  const add = (id, status) => out.set(id, [...(out.get(id) ?? []), status])
  for (const [key, value] of Object.entries(read('data/jobs/job-state.json').jobs ?? {})) {
    if (value.status === 'saved' || value.status === 'rejected') add(String(value.jobId ?? key), value.status)
  }
  // Applied = the applications' own job ids, read from the store (the exported ids file is older and shorter)
  const seen = new Set()
  for (const app of Object.values(loadStore(DATA_ROOT)?.applications ?? {})) {
    const id = app?.posting?.jobId
    if (typeof id === 'string' && id && !seen.has(id)) { seen.add(id); add(id, 'applied') }
  }
  return out
}

function serverRows() {
  const run = spawnSync('python3', ['python/job_discovery/all_ads.py', '--root', DATA_ROOT], { encoding: 'utf-8', maxBuffer: 512 * 1024 * 1024 })
  if (run.status !== 0) return { rows: null, note: `all_ads.py failed (exit ${run.status}): ranks are over the scored rows only` }
  const answer = JSON.parse(run.stdout)
  return answer?.ok === true && Array.isArray(answer.rows) ? { rows: answer.rows, note: 'server rows from all_ads.py' } : { rows: null, note: 'all_ads.py gave no rows' }
}

const scored = read('data/jobs/scored_jobs.json')
const settings = read('data/ai/settings.json')
const windowDays = settings.activeWindowDays ?? 14 // the default of ai_gate.DEFAULT_SETTINGS when Settings holds none
const { rows: server, note } = serverRows()
const index = {
  stored: importJobsFromFile({ meta: scored.meta, jobs: scored.jobs }, null).jobs,
  server,
  jobStateDoc: loadState(DATA_ROOT).doc,
  applications: { status: 'ready', store: loadStore(DATA_ROOT), settings: loadApplicationSettings(DATA_ROOT) },
}
const keep = mustKeep()
console.log(`must-keep ids: ${keep.size}; ${note}; activeWindowDays ${windowDays}`)

for (const mode of ['active', 'all']) {
  const result = queryJobList({
    stored: index.stored, server: index.server, applications: index.applications, jobStateDoc: index.jobStateDoc,
    reference: Date.now(), mode, filters: {}, classes: [], recent: false, sort: null, offset: 0, limit: 1, withIds: true,
    withCounts: false, activeWindowDays: windowDays,
  })
  const rank = new Map(result.ids.map((id, i) => [id, i + 1]))
  const total = result.total
  const byStatus = {}
  const missing = []
  for (const [id, statuses] of keep) {
    const r = rank.get(id)
    if (r === undefined) { missing.push(`${id} (${statuses.join("/")})`); continue }
    for (const status of statuses) (byStatus[status] ??= []).push({ id, rank: r, pct: Math.round((r / total) * 1000) / 10 })
  }
  console.log(`\n== mode ${mode}: ${total} ads in the list; must-keep present ${keep.size - missing.length}, not in this list ${missing.length}`)
  for (const [status, list] of Object.entries(byStatus)) {
    list.sort((a, b) => a.rank - b.rank)
    const pcts = list.map((x) => x.pct)
    const median = pcts.length ? pcts[Math.floor((pcts.length - 1) / 2)] : null
    console.log(`  ${status}: n=${list.length}, best rank ${list[0].rank}, worst rank ${list[list.length - 1].rank}, median percentile ${median}`)
    console.log(`    ranks: ${list.map((x) => `${x.rank} (${x.pct}%)`).join(', ')}`)
  }
  if (missing.length) console.log(`  not in the list: ${missing.join(', ')}`)
}
