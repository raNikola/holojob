// The real Jobs screen in jsdom, with the server answered by a stub: for the tests that need real clicks. Only a test file with
// `// @vitest-environment jsdom` can use it. Nothing here reaches a server or the real data.
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { vi } from 'vitest'

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

/** `route(call)` answers /api/jobs/all; `ledger(jobId)` answers /api/jobs/history; `applications` is the store the server holds. */
export function stubServer({ route = () => routeAnswer([]), health = true, scored = null, ledger = () => null, applications = {} } = {}) {
  const server = { allCalls: 0, posts: [], applications }
  vi.stubGlobal('fetch', async (url, options = {}) => {
    const path = String(url).split('?')[0]
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
export async function mountScreen({ stored = [], file = '../../../src/components/jobs/JobDiscoveryScreen.jsx', props = {}, keepStorage = false, filters = {} } = {}) {
  vi.resetModules()
  const storage = await import('../../../src/modules/jobs/jobStorage.js')
  if (!keepStorage) {
    localStorage.clear()
    sessionStorage.clear() // the screen's open tab
    storage.saveJobs({ meta: {}, jobs: stored, filters: { ...storage.getDefaultJobsState().filters, ...filters }, importedAt: 'first' }, localStorage)
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
    rows: () => [...container.querySelectorAll('tbody tr')],
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
