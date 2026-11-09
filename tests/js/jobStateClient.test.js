import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../src/utils/apiAvailability.js', () => ({ ensureApiAvailable: async () => true }))

import {
  getJobState, pendingRows, refreshJobState, resetJobState, rowsFromJobs, withServerState, writeJobState,
} from '../../src/modules/jobs/jobStateClient.js'
import { jobMatchKey } from '../../src/modules/jobs/jobStorage.js'

const job = (n, extra = {}) => ({ jobId: `job${n}`, jobUrl: `https://acme.example/${n}`, title: `Secret title ${n}`, status: 'new', ...extra })
const entry = (n, extra = {}) => ({ jobId: `job${n}`, status: 'new', statusAt: null, keep: false, ...extra })
const docOf = (entries) => ({ version: 1, updatedAt: null, jobs: Object.fromEntries(entries.map(([n, e]) => [jobMatchKey(job(n)), e])) })

beforeEach(() => resetJobState())
afterEach(() => vi.restoreAllMocks())

describe('display overlay of the server state', () => {
  it('shows the server value where it has an entry, leaves every other row alone, and does not change the input list', () => {
    const jobs = [job(1, { status: 'saved' }), job(2, { status: 'rejected' }), job(3)]
    const shown = withServerState(jobs, docOf([[1, entry(1, { status: 'rejected', keep: true })]]))
    expect(shown[0]).toMatchObject({ status: 'rejected', keptByUser: true })
    expect(shown[1]).toBe(jobs[1])
    expect(shown[2]).toBe(jobs[2])
    expect(jobs[0].status).toBe('saved') // the input list is not mutated, so there is nothing to save back
    expect(withServerState(jobs, null)).toBe(jobs)
  })

  it('counts local statuses and Keep flags the server lacks or holds differently, and nothing else', () => {
    const jobs = [job(1, { status: 'saved' }), job(2, { keptByUser: true }), job(3), job(4, { status: 'saved' }), job(5, { status: 'applied_manually' }), job(6, { status: 'saved' })]
    const doc = docOf([[4, entry(4, { status: 'saved' })], [6, entry(6, { status: 'rejected' })]])
    // job5 is applied (a tracker matter, not a status to copy); job3 has nothing; job4 matches the server.
    expect(pendingRows(jobs, doc).map((r) => r.jobId).sort()).toEqual(['job1', 'job2', 'job5', 'job6'])
    expect(pendingRows(jobs, null)).toEqual([])
  })

  it('sends ids and flags only', () => {
    const rows = rowsFromJobs([job(1, { keptByUser: true, notes: 'private', description: 'long ad text' })])
    expect(JSON.stringify(rows)).not.toMatch(/Secret|private|long ad/)
    expect(rows[0]).toEqual({ jobId: 'job1', key: jobMatchKey(job(1)), status: 'new', keep: true, offList: false })
  })
})

describe('writes go to the server first', () => {
  const respond = (status, body) => vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: status < 400, status, json: async () => body })

  it('a failed write rejects and leaves the cache as it was', async () => {
    respond(200, { doc: docOf([]), sha256: 'aa' })
    await refreshJobState()
    const before = getJobState()
    respond(400, { error: 'status is not valid' })
    await expect(writeJobState(job(1), { status: 'saved' })).rejects.toThrow('status is not valid')
    expect(getJobState()).toBe(before)
  })

  it('a successful write puts the server entry in the cache and sends the base hash', async () => {
    respond(200, { doc: docOf([]), sha256: 'aa' })
    await refreshJobState()
    const spy = respond(200, { entry: entry(1, { status: 'saved' }), sha256: 'bb' })
    await writeJobState(job(1), { status: 'saved' })
    expect(JSON.parse(spy.mock.calls[0][1].body)).toMatchObject({ key: jobMatchKey(job(1)), jobId: 'job1', patch: { status: 'saved' }, baseSha256: 'aa' })
    expect(getJobState().doc.jobs[jobMatchKey(job(1))].status).toBe('saved')
    expect(getJobState().sha256).toBe('bb')
  })

  it('a stale answer refreshes the cache and still rejects', async () => {
    respond(200, { doc: docOf([]), sha256: 'aa' })
    await refreshJobState()
    const spy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ error: 'changed', code: 'stale' }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ doc: docOf([[2, entry(2)]]), sha256: 'cc' }) })
    await expect(writeJobState(job(1), { keep: true })).rejects.toMatchObject({ status: 409 })
    expect(spy).toHaveBeenCalledTimes(2)
    expect(getJobState().sha256).toBe('cc')
  })
})
