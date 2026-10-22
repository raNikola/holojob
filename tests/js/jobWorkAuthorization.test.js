import { describe, it, expect } from 'vitest'
import { filterJobs } from '../../src/modules/jobs/jobFilters.js'
import { authorizationBadge, isCapReason } from '../../src/modules/jobs/workAuthorization.js'

const job = (status) => ({ jobId: status, status: 'new', workAuthorization: { status, reason: 'why' } })

describe('work authorization on the job list', () => {
  it('badges only the statuses worth a human look', () => {
    expect(authorizationBadge(job('needs_visa_refused')).label).toBe('No visa')
    expect(authorizationBadge(job('needs_visa_silent')).label).toBe('Needs visa')
    expect(authorizationBadge(job('authorized'))).toBeNull()
    expect(authorizationBadge({})).toBeNull()
  })

  it('hides needs-visa jobs only when asked, and never an unscored job', () => {
    const jobs = ['needs_visa_refused', 'needs_visa_silent', 'outside_allowed', 'authorized', 'sponsored'].map(job).concat({ jobId: 'raw' })
    expect(filterJobs(jobs, {})).toHaveLength(6)
    expect(filterJobs(jobs, { hideNeedsVisa: true }).map((j) => j.jobId)).toEqual(['outside_allowed', 'authorized', 'sponsored', 'raw'])
  })

  it('recognises cap reasons', () => {
    expect(isCapReason('Capped: needs a work permit for EU')).toBe(true)
    expect(isCapReason('Remote, matches stated preference')).toBe(false)
  })
})
