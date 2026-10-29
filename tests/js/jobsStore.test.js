import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { JOBS_STORAGE_KEY, loadJobs, saveJobs, updateJobStatus } from '../../src/modules/jobs/jobStorage.js'
import {
  addJobIfAbsent,
  adoptStored,
  diffPatch,
  getJobsSnapshot,
  getStoredJob,
  invalidateJobs,
  mergeLive,
  patchJob,
  patchJobFromCopy,
  subscribe,
} from '../../src/modules/jobs/jobsStore.js'

const items = new Map()
const windowEvents = new EventTarget()

beforeEach(() => {
  items.clear()
  vi.stubGlobal('localStorage', {
    getItem: (k) => items.get(k) ?? null,
    setItem: (k, v) => { items.set(k, v) },
    removeItem: (k) => { items.delete(k) },
  })
  vi.stubGlobal('window', windowEvents)
  saveJobs({ meta: null, jobs: [{ jobId: 'a', status: 'new', title: 'PM', notes: '' }, { jobId: 'b', status: 'new', title: 'Other' }], filters: {}, importedAt: null })
  invalidateJobs()
})

afterEach(() => vi.unstubAllGlobals())

const stored = (id) => loadJobs().jobs.find((j) => j.jobId === id)

describe('patchJob', () => {
  it('writes only the given fields on top of the latest stored record', () => {
    const result = patchJob('a', { status: 'saved' })
    expect(result).toMatchObject({ ok: true, changed: true })
    expect(stored('a')).toMatchObject({ status: 'saved', title: 'PM' })
    expect(stored('b').status).toBe('new')
  })

  it('A patches status, B patches another field from a stale copy: both survive', () => {
    const copyA = stored('a')
    const copyB = stored('a')
    patchJobFromCopy('a', copyA, { ...copyA, status: 'saved' })
    patchJobFromCopy('a', copyB, { ...copyB, notes: 'call on Monday' })
    expect(stored('a')).toMatchObject({ status: 'saved', notes: 'call on Monday' })
  })

  it('a stale copy cannot revert A\'s change', () => {
    const stale = stored('a')
    patchJob('a', { status: 'saved' })
    // the stale view sets the same field it changed, plus hands back everything else it still holds
    patchJobFromCopy('a', stale, { ...stale, notes: 'x' })
    expect(stored('a').status).toBe('saved')
    // and a whole stale object that changes nothing writes nothing
    const before = items.get(JOBS_STORAGE_KEY)
    expect(patchJobFromCopy('a', stale, { ...stale })).toMatchObject({ ok: true, changed: false })
    expect(items.get(JOBS_STORAGE_KEY)).toBe(before)
  })

  it('never writes the id, updatedAt or the legacy tracking field from a patch', () => {
    patchJob('a', { jobId: 'zzz', updatedAt: 'x', applicationTracking: { stage: 'applied' }, notes: 'n' })
    const job = stored('a')
    expect(job.jobId).toBe('a')
    expect(job.applicationTracking).toBeUndefined()
    expect(job.updatedAt).not.toBe('x')
    expect(job.notes).toBe('n')
  })

  it('reports an unknown job as missing and writes nothing', () => {
    const before = items.get(JOBS_STORAGE_KEY)
    expect(patchJob('nope', { status: 'saved' })).toEqual({ ok: false, reason: 'missing', jobId: 'nope' })
    expect(items.get(JOBS_STORAGE_KEY)).toBe(before)
  })

  it('answers a conflict, not an overwrite, when baseUpdatedAt is behind', () => {
    patchJob('a', { status: 'saved' })
    const current = stored('a')
    const result = patchJob('a', { status: 'rejected' }, { baseUpdatedAt: null })
    expect(result).toMatchObject({ ok: false, reason: 'conflict' })
    expect(stored('a').status).toBe('saved')
    expect(patchJob('a', { status: 'rejected' }, { baseUpdatedAt: current.updatedAt }).ok).toBe(true)
  })

  it('removes a field the caller dropped', () => {
    patchJob('a', { notes: undefined })
    expect('notes' in stored('a')).toBe(false)
  })
})

describe('diffPatch', () => {
  it('lists changed, added and removed fields only', () => {
    expect(diffPatch({ a: 1, b: { x: 1 }, c: 3 }, { a: 1, b: { x: 2 }, d: 4 })).toEqual({ b: { x: 2 }, c: undefined, d: 4 })
  })
})

describe('subscribe and invalidate', () => {
  it('tells a subscriber after a patch, with the source, and the snapshot is re-read', () => {
    const seen = []
    const stop = subscribe((e) => seen.push(e.source))
    const before = getJobsSnapshot()
    patchJob('a', { status: 'saved' })
    expect(seen).toEqual(['patch'])
    expect(getJobsSnapshot()).not.toBe(before)
    expect(getJobsSnapshot().jobs.find((j) => j.jobId === 'a').status).toBe('saved')
    stop()
  })

  it('reports a screen\'s own saveJobs as `save`, so the screen can ignore its echo', () => {
    const seen = []
    const stop = subscribe((e) => seen.push(e.source))
    saveJobs({ meta: null, jobs: updateJobStatus(loadJobs().jobs, 'b', 'saved'), filters: {}, importedAt: null })
    expect(seen).toEqual(['save'])
    stop()
  })

  it('re-reads on a storage event from another tab, for this key or a clear', () => {
    const seen = []
    const stop = subscribe((e) => seen.push(e.source))
    items.set(JOBS_STORAGE_KEY, JSON.stringify({ jobs: [{ jobId: 'a', status: 'applied_manually' }] }))
    windowEvents.dispatchEvent(Object.assign(new Event('storage'), { key: JOBS_STORAGE_KEY }))
    windowEvents.dispatchEvent(Object.assign(new Event('storage'), { key: 'something-else' }))
    expect(seen).toEqual(['storage'])
    expect(getStoredJob('a').status).toBe('applied_manually')
    windowEvents.dispatchEvent(Object.assign(new Event('storage'), { key: null }))
    expect(seen).toEqual(['storage', 'storage'])
    stop()
  })

  it('stops notifying after unsubscribe and drops the storage listener', () => {
    const seen = []
    const stop = subscribe((e) => seen.push(e.source))
    stop()
    patchJob('a', { status: 'saved' })
    windowEvents.dispatchEvent(Object.assign(new Event('storage'), { key: JOBS_STORAGE_KEY }))
    expect(seen).toEqual([])
  })

  it('invalidateJobs notifies everyone', () => {
    const seen = []
    const stop = subscribe((e) => seen.push(e.source))
    invalidateJobs()
    expect(seen).toEqual(['invalidate'])
    stop()
  })

  it('getStoredJob returns the same object while the content is unchanged', () => {
    const first = getStoredJob('a')
    patchJob('b', { title: 'Changed' })
    expect(getStoredJob('a')).toBe(first)
    patchJob('a', { title: 'New title' })
    expect(getStoredJob('a')).not.toBe(first)
  })
})

describe('addJobIfAbsent', () => {
  it('adds a new job and never replaces an existing record', () => {
    expect(addJobIfAbsent({ jobId: 'c', title: 'C' })).toBe(true)
    patchJob('a', { status: 'saved' })
    expect(addJobIfAbsent({ jobId: 'a', status: 'new' })).toBe(false)
    expect(stored('a').status).toBe('saved')
    expect(stored('c').title).toBe('C')
  })
})

describe('adoptStored and mergeLive', () => {
  it('adoptStored keeps fields the stored record lacks and jobs only the screen holds', () => {
    const memory = [{ jobId: 'a', status: 'new', description: 'long ad' }, { jobId: 'm', title: 'only here' }]
    const merged = adoptStored(memory, [{ jobId: 'a', status: 'saved' }, { jobId: 'n', title: 'new elsewhere' }])
    expect(merged.find((j) => j.jobId === 'a')).toEqual({ jobId: 'a', status: 'saved', description: 'long ad' })
    expect(merged.map((j) => j.jobId)).toEqual(['a', 'm', 'n'])
  })

  it('mergeLive lays the stored record over the prop copy but keeps the derived tracking', () => {
    const prop = { jobId: 'a', status: 'new', applicationTracking: { stage: 'Applied' }, description: 'ad' }
    const live = mergeLive(prop, { jobId: 'a', status: 'saved', applicationTracking: { stage: 'old' } })
    expect(live).toEqual({ jobId: 'a', status: 'saved', applicationTracking: { stage: 'Applied' }, description: 'ad' })
    expect(mergeLive(prop, null)).toBe(prop)
  })
})
