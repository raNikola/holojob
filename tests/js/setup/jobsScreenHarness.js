// The real Jobs screen in jsdom, with the server answered by a stub: for the tests that need real clicks. Only a test file with
// `// @vitest-environment jsdom` can use it. Nothing here reaches a server or the real data.
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { vi } from 'vitest'
import { listAnswer, parseListBody } from '../../../scripts/job-list.js'
import { MAX_JSON_BODY_BYTES } from '../../../scripts/read-body.js'
import { JOBS_STORAGE_KEY } from '../../../src/modules/jobs/jobStorage.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

export const DAY = 86400000
export const ago = (days) => new Date(Date.now() - days * DAY).toISOString()

/** A row of GET /api/jobs/all. */
export function routeRow(jobId, cls = 'found', extra = {}) {
  return {
    jobId, title: `T ${jobId}`, company: 'Acme', location: 'Remote', jobUrl: `https://x.example/${jobId}`, provider: 'jobspy', site: 'linkedin', isRemote: true, datePosted: null,
    firstSeen: ago(30), lastSeen: ago(1), closedAt: null, absentSince: null, class: cls, reason: `why ${cls}`, reasonCode: null, from: 'ledger', copyGroup: null, matchScore: null, ...extra,
  }
}

export const storedJob = (jobId, extra = {}) => ({ jobId, title: `Stored ${jobId}`, company: 'Acme', location: 'Remote', jobUrl: `https://x.example/${jobId}`, provider: 'jobspy', status: 'new', matchScore: 60, matchLabel: 'Good', ...extra })

/** An application as the store holds one. */
export const makeApplication = (id, jobId) => ({
  id, schemaVersion: 1, createdAt: '2026-11-03T10:00:00.000Z',
  posting: { jobId, title: `T ${jobId}`, company: 'Acme', capturedAt: '2026-11-03T10:00:00.000Z' },
  attempt: { channel: 'company_site', channelDetail: '', applicationUrl: '', appliedDate: '2026-11-03', cv: null },
  events: [],
})

export const routeAnswer = (rows, filteredFile = 'ok') => ({ status: 200, body: { ok: true, rows, meta: { filteredFile, counts: {} } } })

const SETTINGS = { stages: { work: [{ key: 'applied', label: 'Applied' }, { key: 'interview', label: 'Interview' }] } }

const reply = (status, body) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body), headers: { get: () => null } })

// What the real scored file would not hold: the owner's own work, which only the browser has.
const OWNER_ONLY = ['status', 'keptByUser', 'tailoredAssets', 'aiInsights', 'outreach', 'notes', 'extraLinks', 'sourceUrl', 'sourceChoice', 'applicationTracking', 'keptRescoredAt', 'offList', 'manualEntry']

/**
 * The server's list for the screen tests (POST /api/jobs/list), made by the route's own `listAnswer` over what this stub server holds: the rows of the browser's stored
 * list that the server would hold (everything but the browser-only rows, without the owner's work), the route's rows from `route`, the job state and the applications.
 */
function answerList(server, rawBody, allBody, pageSize) {
  let local = []
  try { local = JSON.parse(localStorage.getItem(JOBS_STORAGE_KEY))?.jobs ?? [] } catch { /* nothing stored */ }
  const stored = local.filter((job) => !job.offList && !job.manualEntry).map((job) => Object.fromEntries(Object.entries(job).filter(([key]) => !OWNER_ONLY.includes(key))))
  const revision = `r${server.stateWrites.length}.${server.posts.length}`
  const request = parseListBody(rawBody)
  if (request.revision && request.revision !== revision) return { ok: true, changed: true, revision }
  const index = { revision, stored, server: allBody.rows, meta: allBody.meta ?? null, jobStateDoc: server.jobState, applications: { status: 'ready', store: { applications: server.applications }, settings: SETTINGS } }
  return listAnswer(index, request, pageSize, Date.now())
}

/** `route(call)` answers /api/jobs/all (and, with `listServer`, the rows under /api/jobs/list); `ledger(jobId)` answers /api/jobs/history; `applications` is the store the server holds. */
export function stubServer({ route = () => routeAnswer([]), health = true, scored = null, ledger = () => null, applications = {}, listServer = false, pageSize = 100 } = {}) {
  const server = { allCalls: 0, posts: [], applications, jobState: { version: 1, updatedAt: null, jobs: {} }, stateWrites: [], listCalls: [] }
  vi.stubGlobal('fetch', async (url, options = {}) => {
    const path = String(url).split('?')[0]
    if (path === '/api/jobs/list' && options.method === 'POST') {
      if (!listServer) return reply(404, {})
      server.allCalls += 1
      const answer = route(server.allCalls)
      if (answer.status !== 200) return reply(answer.status, answer.body)
      // as the real route: a body over the cap is a 413 in words, before anything is read
      if (String(options.body).length > MAX_JSON_BODY_BYTES) return reply(413, { ok: false, limitBytes: MAX_JSON_BODY_BYTES, error: "The browser's own ads are too many to send with one list request. Nothing was cut: no list was made." })
      const body = JSON.parse(options.body)
      server.listCalls.push(body)
      try { return reply(200, await answerList(server, body, answer.body, pageSize)) } catch (error) { return reply(400, { ok: false, error: error.message }) }
    }
    if (path === '/api/pipeline/health') return health ? reply(200, { available: true, scoring: {}, discovery: {} }) : reply(503, {})
    if (path === '/api/jobs/all') {
      server.allCalls += 1
      const answer = route(server.allCalls)
      return reply(answer.status, answer.body)
    }
    if (path === '/api/scoring/jobs') return scored ? reply(200, scored()) : reply(404, { error: 'none' })
    if (path === '/api/scoring/run' || path === '/api/jobs/manual/sync') return reply(200, { ok: true })
    if (path.startsWith('/api/jobs/history/')) {
      const found = ledger(decodeURIComponent(path.slice('/api/jobs/history/'.length)))
      return found ? reply(200, { found: true, ...found }) : reply(404, { found: false })
    }
    if (path === '/api/jobs/state' && options.method === 'POST') {
      const { key, jobId, patch } = JSON.parse(options.body)
      const before = server.jobState.jobs[key] ?? { jobId, status: 'new', statusAt: null, keep: false }
      const entry = { ...before, ...patch, statusAt: patch.status ? '2026-11-09T10:00:00.000Z' : before.statusAt }
      server.stateWrites.push({ key, patch })
      server.jobState = { ...server.jobState, jobs: { ...server.jobState.jobs, [key]: entry } }
      return reply(200, { entry, sha256: `sha${server.stateWrites.length}`, changed: true })
    }
    if (path === '/api/jobs/state') return reply(200, { doc: server.jobState, sha256: `sha${server.stateWrites.length}` })
    if (path === '/api/applications' && options.method === 'POST') {
      const body = JSON.parse(options.body)
      server.posts.push(body)
      const app = makeApplication(`app${server.posts.length}`, body.jobId)
      server.applications = { ...server.applications, [app.id]: app }
      return reply(200, { application: app })
    }
    if (path === '/api/applications') return reply(200, { applications: server.applications })
    if (path === '/api/applications/settings') return reply(200, { settings: SETTINGS })
    return reply(404, {})
  })
  return server
}

export function viewport(wide = true) {
  vi.stubGlobal('matchMedia', (query) => ({ matches: /min-width/.test(query) ? wide : false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
}

export const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)) })

/** A fresh mount of `file`'s default export under the profile provider, with `stored` in the browser. Modules are new each time, as after a page load. */
// showNotOnBoard is on by default here: these tests use absent and closed rows as ordinary rows; the default-off behaviour has its own tests.
export async function mountScreen({ stored = [], file = '../../../src/components/jobs/JobDiscoveryScreen.jsx', props = {}, keepStorage = false, filters = {}, server = false } = {}) {
  vi.resetModules()
  // the server's list is off by default; a test turns it on (the module is new after the reset, so it is turned on after it)
  if (server) (await import('../../../src/modules/jobs/serverListSwitch.js')).setServerListActive(true)
  const storage = await import('../../../src/modules/jobs/jobStorage.js')
  if (!keepStorage) {
    localStorage.clear()
    sessionStorage.clear() // the screen's open tab
    storage.saveJobs({ meta: {}, jobs: stored, filters: { ...storage.getDefaultJobsState().filters, showNotOnBoard: true, ...filters }, importedAt: 'first' }, localStorage)
  }
  const { default: Screen } = await import(/* @vite-ignore */ file)
  const { ProfileProvider } = await import('../../../src/context/ProfileContext.jsx')
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  await act(async () => { root.render(createElement(ProfileProvider, null, createElement(Screen, props))) })
  await settle()
  const key = storage.JOBS_STORAGE_KEY
  return {
    container,
    key,
    raw: () => localStorage.getItem(key),
    storedJobs: () => JSON.parse(localStorage.getItem(key)).jobs,
    text: () => container.textContent,
    rows: () => [...container.querySelectorAll('tbody tr')].filter((tr) => !tr.querySelector('th')), // group headings are rows too
    row: (text) => [...container.querySelectorAll('tbody tr')].find((tr) => tr.textContent.includes(text)),
    button: (pattern, within = container) => [...within.querySelectorAll('button')].find((b) => pattern.test(b.textContent)),
    box: (pattern) => [...container.querySelectorAll('label')].find((l) => pattern.test(l.textContent))?.querySelector('input'),
    click: (element) => act(async () => { element.click() }),
    type: (input, value) => act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, value)
      input.dispatchEvent(new window.Event('input', { bubbles: true }))
    }),
    unmount: async () => { await act(async () => root.unmount()); container.remove() },
  }
}

/** Counts writes to the job list's key from here on. */
export function countWrites(key) {
  const real = Storage.prototype.setItem
  let writes = 0
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function counted(name, value) {
    if (name === key) writes += 1
    return real.call(this, name, value)
  })
  return () => writes
}
