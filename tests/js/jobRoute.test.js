import { describe, expect, it } from 'vitest'
import { closeMode, findRoutedJob, jobHash, parseJobHash } from '../../src/modules/jobs/jobRoute'

describe('job route hash', () => {
  it('reads the job id from #/jobs/<id>', () => {
    expect(parseJobHash('#/jobs/abc123')).toBe('abc123')
    expect(parseJobHash('#/jobs/abc123/')).toBe('abc123')
  })

  it('decodes an encoded id and round-trips through jobHash', () => {
    const id = 'infostud:Senior PM/2 #3'
    expect(parseJobHash(jobHash(id))).toBe(id)
  })

  it.each(['', '#', '#/jobs', '#/jobs/', '#/jobs//', '#/jobs/a/b', '#/settings/x', '#jobs/abc', '#/jobs/%E0%A4%A', '#/jobs/%20', null, undefined, 5])(
    'is not a job route: %s',
    (hash) => {
      expect(parseJobHash(hash)).toBeNull()
    },
  )
})

describe('findRoutedJob', () => {
  const jobs = [{ jobId: 'a', title: 'A' }, { jobId: 'b', title: 'B' }]

  it('finds a known job', () => {
    expect(findRoutedJob(jobs, 'b')).toEqual({ status: 'found', job: jobs[1] })
  })

  it('reports an unknown id as missing, with the id', () => {
    expect(findRoutedJob(jobs, 'zzz')).toEqual({ status: 'missing', jobId: 'zzz' })
  })

  it('reports missing for an empty or absent list', () => {
    expect(findRoutedJob([], 'a').status).toBe('missing')
    expect(findRoutedJob(undefined, 'a').status).toBe('missing')
  })
})

describe('closeMode', () => {
  it('goes back when the entry was pushed by openJobPage, and survives a reload (history.state is kept)', () => {
    expect(closeMode({ holojobJob: true })).toBe('back')
  })

  it('replaces the hash for a deep link or an edited hash, where the entry carries no state', () => {
    expect(closeMode(null)).toBe('replace')
    expect(closeMode(undefined)).toBe('replace')
    expect(closeMode({})).toBe('replace')
  })
})
