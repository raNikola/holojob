// @vitest-environment jsdom
// S8a: the list stored in its minimal shape, a fresh page load, and every reader of the ad text.
// The single place where the text comes back is jobTexts.js (filled by JobTextGate at start, merged by loadJobs for every reader).
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, describe, expect, it, vi } from 'vitest'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const AD = {
  listed: 'Listed ad: we need a Product Manager, contact: Recruiter: Jane Doe for questions. LISTEDWORD',
  kept: 'Kept ad body KEPTWORD',
  off: 'Off list ad body OFFWORD',
}
const stored = [
  { jobId: 'listed', title: 'Listed PM', company: 'Acme', status: 'new', notes: 'my note', description: AD.listed },
  { jobId: 'kept', title: 'Kept PM', company: 'Acme', status: 'saved', keptByUser: true, description: AD.kept },
  { jobId: 'off', title: 'Off PM', company: 'Acme', status: 'saved', offList: true, description: AD.off },
  { jobId: 'mine', title: 'Mine', company: 'Acme', status: 'new', manualEntry: true, description: 'Mine ad MINEWORD' },
]

const reply = (status, body) => ({ ok: status < 400, status, json: async () => body })
let calls

/** A fresh page: new modules, localStorage holding the minimal shape, a server whose ledger holds `ledgerTexts`. */
async function freshPage({ ledgerTexts = AD, serverDown = false } = {}) {
  vi.resetModules()
  localStorage.clear()
  calls = []
  const storage = await import('../../src/modules/jobs/jobStorage.js')
  // Store it with a limit so small that only the minimal shape fits.
  const minimalSize = JSON.stringify({ meta: null, jobs: stored.map(({ description, ...r }) => (r.manualEntry ? { ...r, description } : r)), filters: storage.getDefaultJobsState().filters, importedAt: null, slim: true, degraded: 'minimal' }).length
  const real = Storage.prototype.setItem
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function limited(k, v) {
    if (k === storage.JOBS_STORAGE_KEY && v.length > minimalSize + 40) throw new DOMException('quota', 'QuotaExceededError')
    return real.call(this, k, v)
  })
  storage.saveJobs({ meta: null, jobs: stored, filters: storage.getDefaultJobsState().filters, importedAt: null })
  vi.restoreAllMocks()
  const onDisk = JSON.parse(localStorage.getItem(storage.JOBS_STORAGE_KEY))
  expect(onDisk.degraded).toBe('minimal')
  expect(onDisk.jobs.find((j) => j.jobId === 'kept').description).toBeUndefined()
  // The page load: modules are new again, nothing in memory.
  vi.resetModules()
  vi.stubGlobal('fetch', async (url, options) => {
    calls.push(String(url))
    if (serverDown) throw new Error('offline')
    const ids = JSON.parse(options.body).jobIds
    const texts = Object.fromEntries(ids.filter((id) => ledgerTexts[id]).map((id) => [id, ledgerTexts[id]]))
    return reply(200, { ok: true, texts, missing: ids.filter((id) => !texts[id]) })
  })
  return {
    store: await import('../../src/modules/jobs/jobsStore.js'),
    storage: await import('../../src/modules/jobs/jobStorage.js'),
    health: await import('../../src/modules/jobs/storageHealth.js'),
    texts: await import('../../src/modules/jobs/jobTexts.js'),
  }
}

async function mountGate(child = () => createElement('div', { id: 'app' }, 'APP')) {
  const { default: JobTextGate } = await import('../../src/components/jobs/JobTextGate.jsx')
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  await act(async () => { root.render(createElement(JobTextGate, null, createElement(child))) })
  await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
  return container
}

beforeEach(() => { document.body.innerHTML = ''; vi.unstubAllGlobals(); Element.prototype.scrollIntoView = () => {} })

describe('minimal list, fresh page load', () => {
  it('before the gate runs, the rows have no text; the app is not shown until the texts are in', async () => {
    const page = await freshPage()
    expect(page.storage.loadJobs().jobs.find((j) => j.jobId === 'kept').description).toBeUndefined()
    const { default: JobTextGate } = await import('../../src/components/jobs/JobTextGate.jsx')
    const container = document.createElement('div')
    document.body.appendChild(container)
    let release
    vi.stubGlobal('fetch', () => new Promise((r) => { release = () => r(reply(200, { ok: true, texts: AD, missing: [] })) }))
    const root = createRoot(container)
    await act(async () => { root.render(createElement(JobTextGate, null, createElement('div', null, 'APP'))) })
    expect(container.textContent).not.toContain('APP')
    expect(container.textContent).toContain('Loading the text of 3 ads')
    await act(async () => { release(); await new Promise((r) => setTimeout(r, 10)) })
    expect(container.textContent).toContain('APP')
  })

  it('asks only for the rows stored without text, never for a hand-entered job', async () => {
    await freshPage()
    await mountGate()
    expect(calls).toEqual(['/api/jobs/texts'])
  })

  it('search finds a kept and an off-list ad by a word that is only in its text', async () => {
    const page = await freshPage()
    await mountGate()
    const { filterJobs } = await import('../../src/modules/jobs/jobFilters.js')
    const jobs = page.storage.loadJobs().jobs
    const find = (q) => filterJobs(jobs, { ...page.storage.getDefaultJobsState().filters, searchText: q, showOffList: true }).map((j) => j.jobId)
    expect(find('KEPTWORD')).toEqual(['kept'])
    expect(find('OFFWORD')).toEqual(['off'])
    expect(find('LISTEDWORD')).toEqual(['listed'])
    expect(find('MINEWORD')).toEqual(['mine'])
  })

  it('outreach reads the contact from the text of the stored row', async () => {
    const page = await freshPage()
    await mountGate()
    const { discover } = await import('../../src/modules/outreach/providers/greenhouseProvider.js')
    const job = page.store.getStoredJob('listed')
    const result = await discover({ job })
    expect(JSON.stringify(result)).toContain('Jane Doe')
  })

  it('the AI context carries the text of the stored row', async () => {
    const page = await freshPage()
    await mountGate()
    const { buildAiContext } = await import('../../src/modules/ai/aiContextBuilder.js')
    const ctx = buildAiContext({ featureId: 'jobAnalysis', job: page.store.getStoredJob('kept') })
    expect(JSON.stringify(ctx)).toContain('KEPTWORD')
  })

  it('a job action (patch) keeps the text for every reader, and a later save keeps the user fields', async () => {
    const page = await freshPage()
    await mountGate()
    expect(page.store.patchJob('off', { notes: 'edited' }).ok).toBe(true)
    const after = page.store.getStoredJob('off')
    expect(after.description).toBe(AD.off)
    expect(after.notes).toBe('edited')
    expect(JSON.parse(localStorage.getItem(page.storage.JOBS_STORAGE_KEY)).jobs.find((j) => j.jobId === 'off').notes).toBe('edited')
  })

  it('tailoring a kept or off-list ad says it cannot be done, and does not start', async () => {
    const page = await freshPage()
    await mountGate()
    const { default: JobTailorActions, NOT_IN_SCORED_LIST } = await import('../../src/components/jobs/JobTailorActions.jsx')
    const { ProfileProvider } = await import('../../src/context/ProfileContext.jsx')
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    await act(async () => { root.render(createElement(ProfileProvider, null, createElement(JobTailorActions, { job: page.store.getStoredJob('kept'), apiAvailable: true, onJobUpdated: () => {} }))) })
    const generate = [...container.querySelectorAll('button')].find((b) => /generate resume/i.test(b.textContent))
    expect(generate).toBeTruthy()
    const before = calls.length
    await act(async () => { generate.click() })
    expect(container.textContent).toContain(NOT_IN_SCORED_LIST)
    expect(calls.length).toBe(before)
  })
})

describe('the server cannot give a text', () => {
  it('the app still opens, and the notice names how many ads have no text', async () => {
    const page = await freshPage({ serverDown: true })
    const container = await mountGate()
    expect(container.textContent).toContain('APP')
    expect(page.health.getStorageHealth().textsMissing).toBe(3)
    const { default: StorageNotice } = await import('../../src/components/layout/StorageNotice.jsx')
    const host = document.createElement('div')
    document.body.appendChild(host)
    await act(async () => { createRoot(host).render(createElement(StorageNotice)) })
    expect(host.textContent).toMatch(/3 ads could not be loaded with their text/)
    expect(host.textContent).toMatch(/Search, outreach and AI tools cannot read those ads/)
  })

  it('a text the ledger lacks is counted as missing, not invented', async () => {
    const page = await freshPage({ ledgerTexts: { kept: AD.kept } })
    await mountGate()
    expect(page.health.getStorageHealth().textsMissing).toBe(2)
    expect(page.store.getStoredJob('listed').description).toBeUndefined()
    expect(page.store.getStoredJob('kept').description).toBe(AD.kept)
  })
})
