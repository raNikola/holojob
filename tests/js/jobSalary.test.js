import { describe, it, expect } from 'vitest'
import { filterJobs } from '../../src/modules/jobs/jobFilters.js'
import { passesSalaryFilters, salaryBadges, withProfileSalaryDefaults, formatMonthlyEur } from '../../src/modules/jobs/jobSalary.js'
import { normalizeSalaryEur, salaryPreferences } from '../../src/utils/salary.js'

const job = (id, pay, extra = {}) => ({ jobId: id, salaryMonthlyEur: pay, matchScore: 60, ...extra })
const jobs = [
  job('low', { min: 1500, max: 2500 }),
  job('mid', { min: 3000, max: 4000 }),
  job('high', { min: 6000, max: 8000 }),
  job('unknown', null),
]
const ids = (list) => list.map((j) => j.jobId)

describe('salary filters', () => {
  it('Min salary keeps jobs whose top figure reaches it', () => {
    expect(ids(filterJobs(jobs, { minSalary: '3000' }))).toEqual(['mid', 'high', 'unknown'])
  })

  it('Desired range keeps jobs whose range overlaps it', () => {
    expect(ids(filterJobs(jobs, { desiredSalaryMin: '3500', desiredSalaryMax: '5000' }))).toEqual(['mid', 'unknown'])
    expect(ids(filterJobs(jobs, { desiredSalaryMax: '2000' }))).toEqual(['low', 'unknown'])
  })

  it('a job with unreadable pay always passes: unknown is not below anything', () => {
    expect(passesSalaryFilters(job('x', null), { minSalary: '99999', desiredMin: '99999' })).toBe(true)
  })

  it('empty or invalid bounds filter nothing', () => {
    expect(filterJobs(jobs, { minSalary: '', desiredSalaryMin: null, desiredSalaryMax: 'abc' })).toHaveLength(4)
  })

  it('does not touch score, priority or any other field of a job', () => {
    const scored = [{ ...job('a', { min: 1, max: 2 }), matchScore: 81, priority: 'P1', applyRecommendation: 'Apply' }]
    const out = filterJobs(scored, { minSalary: '0' })
    expect(out[0]).toBe(scored[0])
  })
})

describe('profile pre-fill', () => {
  const bp = { minSalaryEur: 2500, desiredSalaryMinEur: 3000, desiredSalaryMaxEur: 4500 }

  it('untouched (null) filters take the profile figures', () => {
    const f = withProfileSalaryDefaults({ minSalary: null, desiredSalaryMin: null, desiredSalaryMax: null }, bp)
    expect(f).toMatchObject({ minSalary: 2500, desiredSalaryMin: 3000, desiredSalaryMax: 4500 })
  })

  it('a field the user emptied stays empty; one they set wins', () => {
    const f = withProfileSalaryDefaults({ minSalary: '', desiredSalaryMin: '3200', desiredSalaryMax: null }, bp)
    expect(f).toMatchObject({ minSalary: '', desiredSalaryMin: '3200', desiredSalaryMax: 4500 })
  })

  it('a profile with nothing set pre-fills nothing', () => {
    expect(withProfileSalaryDefaults({ minSalary: null }, {}).minSalary).toBe('')
  })
})

describe('badge and profile fields', () => {
  it('badges only a true belowMinSalary', () => {
    expect(salaryBadges({ belowMinSalary: true, salaryMonthlyEur: { min: 1500, max: 2500 } })[0]).toMatchObject({ label: 'Below min salary' })
    expect(salaryBadges({ belowMinSalary: false })).toEqual([])
    expect(salaryBadges({ belowMinSalary: null })).toEqual([])
    expect(salaryBadges({})).toEqual([])
  })

  it('formats a range and a single figure', () => {
    expect(formatMonthlyEur({ min: 1500, max: 2500 })).toBe('€1,500–2,500/month')
    expect(formatMonthlyEur({ min: 4500, max: 4500 })).toBe('€4,500/month')
    expect(formatMonthlyEur(null)).toBe('')
  })

  it('normalises profile numbers and flows them into the intelligence shape', () => {
    expect(normalizeSalaryEur('')).toBeNull()
    expect(normalizeSalaryEur(0)).toBeNull()
    expect(normalizeSalaryEur('abc')).toBeNull()
    expect(normalizeSalaryEur('2500')).toBe(2500)
    expect(salaryPreferences({ minSalaryEur: 2500, desiredSalaryMinEur: 3000 })).toEqual({
      minSalaryEur: 2500,
      desiredSalaryEur: { min: 3000, max: null },
    })
  })
})

describe('pre-fill notice', () => {
  it('flags that a filter value came from the profile, only while it did', () => {
    const bp = { minSalaryEur: 2500 }
    expect(withProfileSalaryDefaults({ minSalary: null }, bp).salaryFromProfile).toBe(true)
    expect(withProfileSalaryDefaults({ minSalary: '' }, bp).salaryFromProfile).toBe(false)
    expect(withProfileSalaryDefaults({ minSalary: null }, {}).salaryFromProfile).toBe(false)
  })
})
