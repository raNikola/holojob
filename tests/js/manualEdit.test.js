import React, { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { importJobsFromFile, loadJobs, saveJobs } from '../../src/modules/jobs/jobStorage.js'
import { getStoredJob, invalidateJobs } from '../../src/modules/jobs/jobsStore.js'
import { buildManualJob, editChanges, formFromJob, validateEditedJob } from '../../src/modules/jobs/manualJob.js'
import { editManualJob } from '../../src/modules/jobs/manualScoring.js'

const NOTE = 'NOTE-CANARY-7714'
const LINK = 'https://canary-7714.acme.example/private'
const LABEL = 'LABEL-CANARY-7714'
const SOURCE_URL = 'https://canary-7714.linkedin.example/posts/secret'
const ID = 'manual-123e4567-e89b-12d3-a456-426614174000'
const OTHER = 'manual-223e4567-e89b-12d3-a456-426614174000'
const FORM = {
  title: 'Product Manager', company: 'Acme', description: 'Own the roadmap.', jobUrl: 'https://acme.example/jobs/9',
  sourceUrl: SOURCE_URL, location: 'Remote', salary: '2500 EUR/month', notes: NOTE, extraLinks: [{ url: LINK, label: LABEL }],
}
const CREATED = '2026-10-01T08:00:00.000Z'
const SCORED = { jobId: ID, title: 'Senior Product Manager', company: 'Acme', description: 'Own the roadmap.', jobUrl: FORM.jobUrl, status: 'new', matchScore: 77, matchLabel: 'Good', priority: 'P2', aiEnrichment: 'missing' }

const items = new Map()
function seed() {
  const manual = {
    ...buildManualJob(FORM, { id: ID, now: new Date(CREATED) }),
    status: 'saved', matchScore: 61, matchLabel: 'Good', outreach: { contacts: [{ name: 'Jo' }], messages: [], activity: [], status: 'none' }, tailoredAssets: { cv: 'x' },
  }
  saveJobs({ meta: null, jobs: [{ jobId: 'd-1', status: 'saved', title: 'Backend', company: 'Zed', jobUrl: 'https://jobs.example/1?gh_jid=5' }, manual], filters: {}, importedAt: null })
  invalidateJobs()
}
beforeEach(() => {
  items.clear()
  vi.stubGlobal('localStorage', { getItem: (k) => items.get(k) ?? null, setItem: (k, v) => { items.set(k, v) }, removeItem: (k) => { items.delete(k) } })
  vi.stubGlobal('window', new EventTarget())
  seed()
})
afterEach(() => vi.unstubAllGlobals())

const json = (status, body) => ({ status, json: async () => body })
/** Answers like the server: score -> the scored row, check -> ok, sync -> ok. `overrides` maps a path to a reply. */
function server(overrides = {}) {
  return vi.fn(async (url, init) => {
    if (overrides[url]) return overrides[url](init)
    if (url === '/api/jobs/manual/score') return json(200, { ok: true, jobs: [{ ...SCORED, ...JSON.parse(init.body).job }].map((j) => ({ ...SCORED, title: j.title, company: j.company, jobUrl: j.jobUrl, location: j.location, matchScore: 77 })) })
    if (url === '/api/jobs/manual/check') return json(200, { ok: true })
    if (url === '/api/jobs/manual/sync') return json(200, { ok: true, stored: [ID] })
    return json(404, {})
  })
}
const paths = (fetchFn) => fetchFn.mock.calls.map(([url]) => url)
const bodies = (fetchFn) => fetchFn.mock.calls.map(([, init]) => init.body).join('\n')
const form = (changes = {}) => ({ ...formFromJob(getStoredJob(ID)), ...changes })

describe('the Edit form starts from the stored job', () => {
  it('has every field of the Add job form prefilled', () => {
    expect(formFromJob(getStoredJob(ID))).toEqual({
      title: 'Product Manager', company: 'Acme', description: 'Own the roadmap.', jobUrl: 'https://acme.example/jobs/9',
      sourceUrl: SOURCE_URL, location: 'Remote', salary: '2500 EUR/month', notes: NOTE, extraLinks: [{ url: LINK, label: LABEL }],
    })
  })

  describe('as rendered', () => {
    let AddJobDialog
    let ManualJobSection
    beforeAll(async () => {
      globalThis.React = React
      AddJobDialog = (await import('../../src/components/jobs/AddJobDialog.jsx')).default
      ManualJobSection = (await import('../../src/components/jobs/ManualJobSection.jsx')).default
    })

    it('shows the values in the same form, titled Edit job, without "Save and open details"', () => {
      const html = renderToStaticMarkup(createElement(AddJobDialog, { job: getStoredJob(ID), onClose: () => {}, onSaved: () => {} }))
      expect(html).toContain('>Edit job<')
      for (const value of ['Product Manager', 'Acme', 'Own the roadmap.', 'https://acme.example/jobs/9', SOURCE_URL, 'Remote', '2500 EUR/month', NOTE, LINK, LABEL]) expect(html).toContain(value)
      expect(html).toContain('Fill from ad')
      expect(html).not.toContain('Save and open details')
    })

    it('the Add form is still empty', () => {
      const html = renderToStaticMarkup(createElement(AddJobDialog, { onClose: () => {}, onSaved: () => {} }))
      expect(html).toContain('>Add job<')
      expect(html).not.toContain('Product Manager')
    })

    it('only a hand-entered job has an Edit button', () => {
      const manual = renderToStaticMarkup(createElement(ManualJobSection, { job: getStoredJob(ID) }))
      expect(manual).toMatch(/<button[^>]*>(<svg[^>]*>.*?<\/svg>)?Edit<\/button>/)
      expect(renderToStaticMarkup(createElement(ManualJobSection, { job: { jobId: 'd-1', title: 'Backend' } }))).toBe('')
      const discoveredWithNotes = renderToStaticMarkup(createElement(ManualJobSection, { job: { jobId: 'd-1', notes: 'hello' } }))
      expect(discoveredWithNotes).not.toMatch(/>Edit</)
    })
  })
})

describe('what an edit changes', () => {
  it('compares trimmed values and finds nothing when nothing changed', () => {
    expect(editChanges({ ...formFromJob(getStoredJob(ID)), title: '  Product Manager ' }, getStoredJob(ID))).toMatchObject({ patch: {}, rescore: false, urlChanged: false })
  })

  it.each([['title'], ['company'], ['description'], ['location'], ['salary']])('a changed %s needs a re-score', (field) => {
    expect(editChanges({ ...formFromJob(getStoredJob(ID)), [field]: 'changed' }, getStoredJob(ID)).rescore).toBe(true)
  })

  it.each([['notes'], ['sourceUrl'], ['jobUrl']])('a changed %s does not', (field) => {
    expect(editChanges({ ...formFromJob(getStoredJob(ID)), [field]: field === 'notes' ? 'new' : 'https://other.example/x' }, getStoredJob(ID)).rescore).toBe(false)
  })

  it('extra links are compared as cleaned rows; an emptied optional field is removed', () => {
    const base = formFromJob(getStoredJob(ID))
    expect(editChanges({ ...base, extraLinks: [...base.extraLinks, { url: '', label: '' }] }, getStoredJob(ID)).patch).toEqual({})
    const emptied = editChanges({ ...base, notes: '', extraLinks: [], sourceUrl: '' }, getStoredJob(ID))
    expect(Object.keys(emptied.patch).sort()).toEqual(['extraLinks', 'notes', 'sourceUrl'])
    expect(Object.values(emptied.patch).every((v) => v === undefined)).toBe(true)
  })

  it('the address counts as changed only when the posting differs (tracking parameters do not)', () => {
    expect(editChanges({ ...formFromJob(getStoredJob(ID)), jobUrl: 'https://acme.example/jobs/9?utm_source=x' }, getStoredJob(ID)).urlChanged).toBe(false)
    expect(editChanges({ ...formFromJob(getStoredJob(ID)), jobUrl: 'https://acme.example/jobs/10' }, getStoredJob(ID)).urlChanged).toBe(true)
  })

  it('a scored job keeps its description: it can be replaced, not removed', () => {
    expect(validateEditedJob({ ...formFromJob(getStoredJob(ID)), description: ' ' }, getStoredJob(ID)).description).toMatch(/Replace the description/)
    expect(validateEditedJob({ ...formFromJob(getStoredJob(ID)), notes: '' }, getStoredJob(ID))).toEqual({})
    expect(validateEditedJob({ title: 'x', company: 'y', jobUrl: 'https://a.example/1', description: '' }, { description: '' })).toEqual({})
  })
})

describe('editManualJob: a scoring field changed', () => {
  it('stores the edit on the job, scores it on the server, and keeps id, dates, status and tracking', async () => {
    const fetchFn = server()
    const result = await editManualJob(ID, form({ title: 'Senior Product Manager' }), { fetchFn })
    expect(result).toMatchObject({ status: 'saved', scored: true, rescored: true })
    expect(paths(fetchFn)).toEqual(['/api/jobs/manual/score'])
    const job = loadJobs().jobs.find((j) => j.jobId === ID)
    expect(job).toMatchObject({
      jobId: ID, title: 'Senior Product Manager', matchScore: 77, createdAt: CREATED, firstSeen: CREATED,
      status: 'saved', manualEntry: true, notes: NOTE, sourceUrl: SOURCE_URL, extraLinks: [{ url: LINK, label: LABEL }],
      outreach: { contacts: [{ name: 'Jo' }] }, tailoredAssets: { cv: 'x' },
    })
    expect(Date.parse(job.updatedAt)).toBeGreaterThan(Date.parse(CREATED))
    expect(loadJobs().jobs).toHaveLength(2)
    // the payload names the same id and carries the new title and the unchanged dates
    expect(JSON.parse(fetchFn.mock.calls[0][1].body).job).toMatchObject({ jobId: ID, title: 'Senior Product Manager', createdAt: CREATED, firstSeen: CREATED })
  })

  it('a description pasted into a job that had none is scored too', async () => {
    saveJobs({ meta: null, jobs: [{ ...getStoredJob(ID), description: '', matchScore: undefined }], filters: {}, importedAt: null })
    invalidateJobs()
    const fetchFn = server()
    await editManualJob(ID, form({ description: 'Now there is text.' }), { fetchFn })
    expect(paths(fetchFn)).toEqual(['/api/jobs/manual/score'])
  })

  it('keeps the edit and says so when scoring fails, leaving the scored fields as they were', async () => {
    const fetchFn = server({ '/api/jobs/manual/score': () => json(500, { ok: false, error: 'scoring_failed' }) })
    const result = await editManualJob(ID, form({ company: 'Acme Corp' }), { fetchFn })
    expect(result).toMatchObject({ status: 'saved', scored: false, message: expect.stringMatching(/next Re-score/) })
    expect(getStoredJob(ID)).toMatchObject({ company: 'Acme Corp', matchScore: 61, status: 'saved' })
    const offline = await editManualJob(ID, form({ company: 'Acme Inc' }), { apiAvailable: false })
    expect(offline.message).toMatch(/could not be reached/)
    expect(getStoredJob(ID).company).toBe('Acme Inc')
  })
})

describe('editManualJob: only owner fields or the Job URL changed', () => {
  it('Notes, extra links and Source URL: saved, no request at all', async () => {
    const fetchFn = server()
    const result = await editManualJob(ID, form({ notes: `${NOTE} more`, sourceUrl: 'https://elsewhere.example/p', extraLinks: [] }), { fetchFn })
    expect(result).toMatchObject({ status: 'saved', rescored: false })
    expect(fetchFn).not.toHaveBeenCalled()
    expect(getStoredJob(ID)).toMatchObject({ notes: `${NOTE} more`, sourceUrl: 'https://elsewhere.example/p', matchScore: 61, status: 'saved' })
    expect(getStoredJob(ID).extraLinks).toBeUndefined()
  })

  it('a new Job URL is checked, stored on the server without scoring, and the score stays', async () => {
    const fetchFn = server()
    const result = await editManualJob(ID, form({ jobUrl: 'https://acme.example/jobs/10' }), { fetchFn })
    expect(result).toMatchObject({ status: 'saved', scored: false, rescored: false })
    expect(paths(fetchFn)).toEqual(['/api/jobs/manual/check', '/api/jobs/manual/sync'])
    expect(getStoredJob(ID)).toMatchObject({ jobUrl: 'https://acme.example/jobs/10', site: 'acme.example', matchScore: 61 })
    expect(JSON.parse(fetchFn.mock.calls[1][1].body).jobs[0]).toMatchObject({ jobId: ID, jobUrl: 'https://acme.example/jobs/10' })
  })

  it('nothing changed: nothing written, nothing sent', async () => {
    const fetchFn = server()
    const before = items.get([...items.keys()][0])
    expect(await editManualJob(ID, form(), { fetchFn })).toMatchObject({ status: 'unchanged' })
    expect(fetchFn).not.toHaveBeenCalled()
    expect(items.get([...items.keys()][0])).toBe(before)
  })

  it('only a hand-entered job can be edited', async () => {
    expect((await editManualJob('d-1', form({ title: 'x' }), { fetchFn: server() })).status).toBe('missing')
    expect((await editManualJob('nope', form(), { fetchFn: server() })).status).toBe('missing')
    expect(getStoredJob('d-1').title).toBe('Backend')
  })
})

describe('editManualJob: duplicate Job URL', () => {
  const other = () => ({ ...buildManualJob({ title: 'Other', company: 'Zed', description: 'x', jobUrl: 'https://zed.example/p/1?gh_jid=7' }, { id: OTHER }) })
  const withOther = () => { saveJobs({ meta: null, jobs: [...loadJobs().jobs, other()], filters: {}, importedAt: null }); invalidateJobs() }

  it('refuses an address another job in the list has, writes nothing, sends nothing', async () => {
    withOther()
    const fetchFn = server()
    const before = JSON.stringify(loadJobs().jobs.find((j) => j.jobId === ID))
    const result = await editManualJob(ID, form({ jobUrl: 'https://ZED.example/p/1/?gh_jid=7&utm_source=li#top', title: 'Changed' }), { fetchFn })
    expect(result).toMatchObject({ status: 'duplicate', existing: { jobId: OTHER } })
    expect(fetchFn).not.toHaveBeenCalled()
    expect(JSON.stringify(loadJobs().jobs.find((j) => j.jobId === ID))).toBe(before)
  })

  it('a sibling posting (another ?gh_jid=) is not a clash', async () => {
    withOther()
    const result = await editManualJob(ID, form({ jobUrl: 'https://zed.example/p/1?gh_jid=8' }), { fetchFn: server() })
    expect(result.status).toBe('saved')
  })

  it('refuses an address the server knows from the discovered, scored or manual files', async () => {
    const fetchFn = server({ '/api/jobs/manual/check': () => json(409, { ok: false, error: 'duplicate', existing: { jobId: 'd-77', title: 'Found by discovery' } }) })
    const result = await editManualJob(ID, form({ jobUrl: 'https://found.example/1' }), { fetchFn })
    expect(result).toMatchObject({ status: 'duplicate', existing: { jobId: 'd-77' } })
    expect(paths(fetchFn)).toEqual(['/api/jobs/manual/check'])
    expect(getStoredJob(ID).jobUrl).toBe(FORM.jobUrl)
  })

  it('ignores the job itself: the same posting under another tracking tag is not a clash', async () => {
    const fetchFn = server()
    const result = await editManualJob(ID, form({ jobUrl: 'https://acme.example/jobs/9?utm_campaign=z' }), { fetchFn })
    expect(result.status).toBe('saved')
    expect(paths(fetchFn)).not.toContain('/api/jobs/manual/check')
  })
})

describe('privacy: Notes, extra links and Source URL on the edit path', () => {
  it.each([
    ['a scoring field', { title: 'Senior Product Manager', notes: `${NOTE} 2` }],
    ['a new Job URL', { jobUrl: 'https://acme.example/jobs/10', notes: `${NOTE} 3` }],
    ['links and Source URL', { extraLinks: [{ url: `${LINK}/2`, label: LABEL }], sourceUrl: `${SOURCE_URL}/2` }],
  ])('no request carries them after %s changed', async (_name, changes) => {
    const fetchFn = server()
    await editManualJob(ID, form(changes), { fetchFn })
    expect(bodies(fetchFn)).not.toMatch(/CANARY|canary/)
    for (const [, init] of fetchFn.mock.calls) {
      const sent = JSON.parse(init.body)
      const rows = sent.jobs ?? [sent.job]
      for (const row of rows) expect(Object.keys(row).filter((k) => ['notes', 'extraLinks', 'sourceUrl'].includes(k))).toEqual([])
    }
  })
})

describe('the edit survives a re-score, a re-scrape and the pipeline', () => {
  it('a re-import of the scored file keeps the edited address, site and updatedAt, and takes the new score', async () => {
    await editManualJob(ID, form({ jobUrl: 'https://acme.example/jobs/10' }), { fetchFn: server() })
    const edited = getStoredJob(ID)
    // The file still has the row from before the edit (or the next run's row, scored from the manual store).
    const stale = { jobId: ID, title: 'Product Manager', company: 'Acme', jobUrl: FORM.jobUrl, site: 'old.example', updatedAt: '2000-01-01T00:00:00.000Z', matchScore: 90, status: 'new' }
    const imported = importJobsFromFile({ jobs: [stale] }, { jobs: loadJobs().jobs, filters: {} })
    const row = imported.jobs.find((j) => j.jobId === ID)
    expect(row).toMatchObject({ jobUrl: 'https://acme.example/jobs/10', site: 'acme.example', updatedAt: edited.updatedAt, notes: NOTE, sourceUrl: SOURCE_URL, status: 'saved', matchScore: 90 })
  })

  it('does not make a discovered job keep its old address or timestamp', () => {
    const prior = { jobs: [{ jobId: 'd-1', title: 'Backend', jobUrl: 'https://jobs.example/old', site: 'old', updatedAt: 'then', status: 'saved' }], filters: {} }
    const imported = importJobsFromFile({ jobs: [{ jobId: 'd-1', title: 'Backend', jobUrl: 'https://jobs.example/new', site: 'new', updatedAt: 'now' }] }, prior)
    expect(imported.jobs[0]).toMatchObject({ jobUrl: 'https://jobs.example/new', site: 'new', updatedAt: 'now', status: 'saved' })
  })

  it('the next scoring run is handed the edited job (sync sends the browser copy)', async () => {
    const { syncManualJobs } = await import('../../src/modules/jobs/manualScoring.js')
    await editManualJob(ID, form({ title: 'Senior Product Manager', jobUrl: 'https://acme.example/jobs/10' }), { fetchFn: server() })
    const fetchFn = server()
    await syncManualJobs({ fetchFn })
    expect(JSON.parse(fetchFn.mock.calls[0][1].body).jobs[0]).toMatchObject({ jobId: ID, title: 'Senior Product Manager', jobUrl: 'https://acme.example/jobs/10' })
    expect(bodies(fetchFn)).not.toMatch(/CANARY|canary/)
  })

  it('the stored list is what the list screen reads at once', async () => {
    await editManualJob(ID, form({ company: 'Acme Corp' }), { fetchFn: server() })
    expect(getStoredJob(ID).company).toBe('Acme Corp')
    expect(loadJobs().jobs.find((j) => j.jobId === ID).company).toBe('Acme Corp')
  })
})
