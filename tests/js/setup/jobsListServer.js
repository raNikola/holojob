// A real HTTP server around the list route over a temp data dir, for tests that need a request body and a response, not a fake res. The Python step
// (all_ads.py) is a fake child process that answers with `routeRows`, as in jobsListRoute.test.js.
import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { handleApplicationsRequest } from '../../../scripts/application-store.js'
import { clearListIndex, handleJobsListRequest } from '../../../scripts/job-list.js'

export const NOW = Date.parse('2026-11-20T12:00:00Z')
const DAY = 86400000
const iso = (ms) => new Date(NOW - ms).toISOString()

export const scoredRow = (i, extra = {}) => ({
  jobId: `j${String(i).padStart(2, '0')}`, title: ['Senior Product Manager', 'Product Owner', 'Delivery Lead'][i % 3], company: `Co ${i % 4}`, location: i % 2 ? 'Remote' : 'Niš, Serbia',
  site: 'linkedin', provider: i % 5 === 0 ? 'greenhouse' : 'jobspy', jobUrl: `https://x.example/${i}`, description: `The long ad text number ${i}. `.repeat(20), isRemote: i % 2 === 1,
  matchScore: 30 + ((i * 17) % 60), matchLabel: 'Good', priority: ['P1', 'P2', 'P3'][i % 3], applyRecommendation: 'Maybe', blockedBy: [], dataStatus: 'ok',
  datePosted: iso((i % 9) * DAY), firstSeen: iso(20 * DAY), llmFacts: { _fingerprint: `f${i}`, big: 'x'.repeat(200) }, ...extra,
})
export const SCORED = Array.from({ length: 12 }, (_, i) => scoredRow(i))

export const routeRow = (row, cls = 'found') => ({
  jobId: row.jobId, title: row.title, company: row.company, location: row.location, jobUrl: row.jobUrl, provider: row.provider, site: row.site, isRemote: row.isRemote,
  datePosted: row.datePosted, salary: null, expiresAt: null, firstSeen: row.firstSeen, lastSeen: iso(DAY), closedAt: null, absentSince: null, class: cls, reason: cls, reasonCode: null,
  from: 'ledger', copyGroup: null, matchScore: null,
})
export const ROUTE_ROWS = [...SCORED.map((row, i) => routeRow(row, i % 4 === 3 ? 'absent' : 'found')), { ...routeRow(scoredRow(90)), jobId: 'ledger-only-1', title: 'Only in the ledger' }]

/** `withApplications` also serves /api/applications over the same temp dir (the tracker's own handler). @returns {Promise<{ base: string, root: string, fetchFn: Function, spawnCalls: unknown[], writeScored: Function, close: Function }>} */
export async function startListServer({ scored = SCORED, routeRows = ROUTE_ROWS, pageSize = 4, withApplications = false, windowDays = 14 } = {}) {
  clearListIndex()
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'jobs-list-http-'))
  const writeScored = (rows) => {
    fs.mkdirSync(path.join(root, 'data/jobs'), { recursive: true })
    fs.writeFileSync(path.join(root, 'data/jobs/scored_jobs.json'), JSON.stringify({ meta: { generatedAt: iso(0) }, jobs: rows }))
  }
  writeScored(scored)
  const spawnCalls = []
  const spawnFn = (python, args) => {
    spawnCalls.push(args)
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    setImmediate(() => { child.stdout.emit('data', Buffer.from(JSON.stringify({ ok: true, meta: { filteredFile: 'ok', counts: {} }, rows: routeRows }))); child.emit('close', 0) })
    return child
  }
  const server = http.createServer((req, res) => {
    const url = req.url.split('?')[0]
    if (withApplications && (url === '/api/applications' || url.startsWith('/api/applications/'))) {
      handleApplicationsRequest(req, res, url, { root }).catch(() => { res.statusCode = 500; res.end('{}') })
      return
    }
    handleJobsListRequest(req, res, url, { root, spawnFn, ensureView: async () => {}, readPageSize: async () => pageSize, readWindowDays: async () => windowDays, now: () => NOW })
      .then((done) => { if (!done) { res.statusCode = 404; res.end('{}') } }, () => { res.statusCode = 500; res.end('{}') })
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const base = `http://127.0.0.1:${server.address().port}`
  return {
    base, root, spawnCalls, spawnFn, writeScored,
    fetchFn: (url, options) => fetch(`${base}${url}`, options),
    close: async () => {
      await new Promise((resolve) => server.close(resolve))
      fs.rmSync(root, { recursive: true, force: true })
      clearListIndex()
    },
  }
}

/** The files under a data dir with their sizes, to show that a request wrote nothing. */
export function treeOf(dir) {
  const out = {}
  const walk = (current) => {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name)
      if (entry.isDirectory()) walk(full)
      else out[path.relative(dir, full)] = `${fs.statSync(full).size}:${fs.statSync(full).mtimeMs}`
    }
  }
  walk(dir)
  return out
}
