import { describe, expect, it } from 'vitest'
import { appliedJobIds, hasUnmigratedApplied, statusFilterOptions } from '../../src/modules/applications/appliedFilter.js'
import { filterJobs } from '../../src/modules/jobs/jobFilters.js'
import { JOB_STATUSES } from '../../src/modules/jobs/jobStorage.js'

const app = (id, jobId, events = []) => ({ id, posting: { jobId }, attempt: {}, events })
const voided = [{ seq: 1, type: 'application_voided', data: {} }]
const restored = [...voided, { seq: 2, type: 'application_restored', data: {} }]
const store = {
  applications: {
    a1: app('a1', 'job-a'),
    a2: app('a2', 'job-b', voided),
    a3: app('a3', 'job-c', restored),
    a4: app('a4', 'job-d', voided),
    a5: app('a5', 'job-d'),
  },
}
const jobs = ['job-a', 'job-b', 'job-c', 'job-d', 'job-e'].map((jobId) => ({ jobId, status: 'new' }))
const ids = (list) => list.map((j) => j.jobId)

describe('Jobs status filter "applied"', () => {
  it('counts a job with a non-voided application, whatever its stage or outcome', () => {
    expect([...appliedJobIds(store)].sort()).toEqual(['job-a', 'job-c', 'job-d'])
  })

  it('a voided application does not count; a restored one does', () => {
    expect(appliedJobIds(store).has('job-b')).toBe(false)
    expect(appliedJobIds(store).has('job-c')).toBe(true)
  })

  it('filters through the store, not the job status', () => {
    const out = filterJobs(jobs, { status: 'applied' }, { appliedJobIds: appliedJobIds(store) })
    expect(ids(out)).toEqual(['job-a', 'job-c', 'job-d'])
  })

  it('shows nothing, not everything, while the store is not loaded', () => {
    expect(filterJobs(jobs, { status: 'applied' })).toEqual([])
    expect(filterJobs(jobs, { status: 'applied' }, { appliedJobIds: appliedJobIds(null) })).toEqual([])
  })

  it('leaves the other statuses alone', () => {
    const mixed = [{ jobId: 'x', status: 'saved' }, { jobId: 'y', status: 'new' }]
    expect(ids(filterJobs(mixed, { status: 'saved' }))).toEqual(['x'])
    expect(filterJobs(mixed, { status: '' })).toHaveLength(2)
  })

  it('hides applied_manually once every such job has an application, and shows it while one has none', () => {
    const legacy = [{ jobId: 'job-a', status: 'applied_manually' }, { jobId: 'job-z', status: 'applied_manually' }]
    expect(hasUnmigratedApplied(legacy, store)).toBe(true)
    expect(statusFilterOptions(JOB_STATUSES, legacy, store)).toEqual(['new', 'saved', 'rejected', 'applied_manually', 'applied'])
    expect(hasUnmigratedApplied([legacy[0]], store)).toBe(false)
    expect(statusFilterOptions(JOB_STATUSES, [legacy[0]], store)).toEqual(['new', 'saved', 'rejected', 'applied'])
    expect(statusFilterOptions(JOB_STATUSES, jobs, null)).toEqual(['new', 'saved', 'rejected', 'applied'])
  })

  it('"applied" is not a job status a row can be set to', () => {
    expect(JOB_STATUSES).not.toContain('applied')
  })
})
