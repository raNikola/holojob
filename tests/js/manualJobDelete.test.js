import React, { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { importJobsFromFile, loadJobs, saveJobs } from '../../src/modules/jobs/jobStorage.js'
import { adoptStored, getStoredJob, invalidateJobs, subscribe, syncMemoryJobs } from '../../src/modules/jobs/jobsStore.js'
import { buildManualJob } from '../../src/modules/jobs/manualJob.js'
import { deleteConfirmMessage, deleteManualJob, scoreOnServer } from '../../src/modules/jobs/manualScoring.js'

const ID = 'manual-123e4567-e89b-12d3-a456-426614174000'
const FORM = { title: 'Product Manager Canary', company: 'Acme', description: 'Own the roadmap.', jobUrl: 'https://acme.example/jobs/9', notes: 'n', extraLinks: [] }
const DISCOVERED = { jobId: 'd-1', status: 'saved', title: 'Backend', company: 'Zed', provider: 'jobspy', jobUrl: 'https://jobs.example/1' }

const items = new Map()
beforeEach(() => {
  items.clear()
  vi.stubGlobal('localStorage', { getItem: (k) => items.get(k) ?? null, setItem: (k, v) => { items.set(k, v) }, removeItem: (k) => { items.delete(k) } })
  vi.stubGlobal('window', new EventTarget())
  saveJobs({ meta: null, jobs: [DISCOVERED, buildManualJob(FORM, { id: ID, now: new Date('2026-10-01T08:00:00.000Z') })], filters: {}, importedAt: null })
  invalidateJobs()
})
afterEach(() => vi.unstubAllGlobals())

const json = (status, body) => ({ status, json: async () => body })
const ids = () => loadJobs().jobs.map((j) => j.jobId)

describe('deleteManualJob (browser side)', () => {
  it('removes it from the browser only after the server agreed, and no other job is touched', async () => {
    const fetchFn = vi.fn(async () => json(200, { ok: true }))
    expect(await deleteManualJob(ID, { fetchFn })).toEqual({ ok: true })
    expect(fetchFn).toHaveBeenCalledWith('/api/jobs/manual/delete', expect.objectContaining({ method: 'POST' }))
    expect(JSON.parse(fetchFn.mock.calls[0][1].body)).toEqual({ jobId: ID, jobUrl: FORM.jobUrl })
    expect(ids()).toEqual(['d-1'])
    expect(getStoredJob(ID)).toBeNull()
    expect(loadJobs().jobs[0]).toMatchObject(DISCOVERED)
  })

  it('does not come back after a reload or a re-import of a scored file that no longer holds it', async () => {
    await deleteManualJob(ID, { fetchFn: async () => json(200, { ok: true }) })
    const reloaded = loadJobs()
    expect(reloaded.jobs.some((j) => j.jobId === ID)).toBe(false)
    const reimported = importJobsFromFile({ meta: {}, jobs: [DISCOVERED] }, reloaded)
    expect(reimported.jobs.some((j) => j.jobId === ID)).toBe(false)
  })

  it('a refusal for an existing application keeps the job and returns the reason', async () => {
    const reply = { ok: false, error: 'has_application', applicationIds: ['app-1'], message: 'in the tracker' }
    const result = await deleteManualJob(ID, { fetchFn: async () => json(409, reply) })
    expect(result).toEqual({ ok: false, reason: 'has_application', applicationIds: ['app-1'], message: 'in the tracker' })
    expect(ids()).toEqual(['d-1', ID])
  })

  it('with the server unreachable, or any other failure, nothing is deleted', async () => {
    expect((await deleteManualJob(ID, { fetchFn: async () => { throw new Error('down') } })).reason).toBe('unreachable')
    expect((await deleteManualJob(ID, { fetchFn: async () => json(500, { ok: false, error: 'delete_failed' }) })).ok).toBe(false)
    expect(ids()).toEqual(['d-1', ID])
  })

  it('a job that is not hand-entered is refused before any request', async () => {
    const fetchFn = vi.fn()
    expect((await deleteManualJob('d-1', { fetchFn })).reason).toBe('not_manual')
    expect(fetchFn).not.toHaveBeenCalled()
    expect(ids()).toEqual(['d-1', ID])
  })

  it('a screen that keeps its own copy of the list drops the row instead of saving it back', async () => {
    const memory = loadJobs().jobs
    let event
    const off = subscribe((e) => { event = e })
    await deleteManualJob(ID, { fetchFn: async () => json(200, { ok: true }) })
    off()
    expect(event.removedId).toBe(ID)
    const next = adoptStored(memory.filter((j) => j.jobId !== event.removedId), loadJobs().jobs)
    expect(next.map((j) => j.jobId)).toEqual(['d-1'])
  })
})

describe('as rendered', () => {
  let ManualJobSection
  beforeAll(async () => {
    globalThis.React = React
    ManualJobSection = (await import('../../src/components/jobs/ManualJobSection.jsx')).default
  })

  it('only a hand-entered job has a Delete button; a discovered one has none, even with notes', () => {
    expect(renderToStaticMarkup(createElement(ManualJobSection, { job: getStoredJob(ID) }))).toMatch(/Delete job/)
    expect(renderToStaticMarkup(createElement(ManualJobSection, { job: { ...DISCOVERED, notes: 'hello' } }))).not.toMatch(/Delete/)
  })

  it('the confirmation names the job title', () => {
    expect(deleteConfirmMessage(getStoredJob(ID))).toContain('“Product Manager Canary”')
  })
})

describe('stale-tab protection', () => {
  it('the scoring route answers 410 deleted and the client says so, nothing is stored', async () => {
    const fetchFn = vi.fn(async () => json(410, { ok: false, error: 'deleted' }))
    const result = await scoreOnServer({ jobId: ID, title: 'PM', company: 'Acme', description: 'x', jobUrl: FORM.jobUrl }, { fetchFn })
    expect(result).toMatchObject({ ok: false, reason: 'deleted' })
    expect(result.message).toMatch(/deleted on the server/)
  })

  it('the other tab drops the row on the storage event, and its own save cannot write it back', async () => {
    const memory = loadJobs().jobs // this tab's screen state, still holding the job
    saveJobs({ ...loadJobs(), jobs: memory.filter((j) => j.jobId !== ID) }) // what the deleting tab wrote
    const stored = loadJobs().jobs
    const next = syncMemoryJobs(memory, stored, { source: 'storage' })
    expect(next.map((j) => j.jobId)).toEqual(['d-1'])
    // Without the rule the screen keeps the row (the old behaviour), and its save effect would write it back:
    expect(adoptStored(memory, stored).map((j) => j.jobId)).toContain(ID)
    // A job only this tab holds and that is not hand-entered is untouched; other sources keep memory-only rows.
    const local = { jobId: 'local-1', title: 'x', manualEntry: true }
    expect(syncMemoryJobs([...memory, local], stored, { source: 'patch' }).map((j) => j.jobId)).toContain('local-1')
  })
})
