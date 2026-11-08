import { describe, it, expect } from 'vitest'
import { filterJobs } from '../../src/modules/jobs/jobFilters.js'
import { approximateMonthlyEur, statedSalary, passesSalaryFilters, salaryBadges, withProfileSalaryDefaults, formatMonthlyEur } from '../../src/modules/jobs/jobSalary.js'
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
    expect(formatMonthlyEur({ min: 7122, max: 16062, currency: 'USD', converted: true })).toBe('≈€7,122–16,062/month (from USD)')
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
    expect(withProfileSalaryDefaults({ minSalary: '', desiredSalaryMin: 3000 }, bp).salaryFromProfile).toBe(false)
    expect(withProfileSalaryDefaults({ salaryFrom: '', salaryTo: '' }, bp).salaryFromProfile).toBe(false)
    expect(withProfileSalaryDefaults({ minSalary: null }, {}).salaryFromProfile).toBe(false)
  })
})

describe('the salary as stated', () => {
  it.each([
    ['142500 - 237500 yearly', '$142,500–237,500/year'],
    ['60000 - 72000 yearly EUR', '€60,000–72,000/year'],
    ['5000 monthly EUR', '€5,000/month'],
    ['50 - 60 hourly GBP', '£50–60/hour'],
    ['100000 - 120000 yearly CHF', 'CHF 100,000–120,000/year'],
    ['€2,500–3,000 net/month', '€2,500–3,000 net/month'],
    ['80000-100000', '80000-100000'],
  ])('%s reads %s', (text, shown) => {
    expect(statedSalary(text)).toBe(shown)
  })

  it.each([undefined, null, '', '   '])('%j is nothing', (text) => {
    expect(statedSalary(text)).toBeNull()
  })
})

describe('the approximate monthly figure', () => {
  const range = (extra) => ({ min: 7000, max: 16000, currency: 'USD', converted: true, ...extra })

  it('a converted figure is marked approximate', () => {
    expect(approximateMonthlyEur({ salary: '92900 - 209500 yearly', salaryMonthlyEur: range() })).toBe('≈ €7,000–16,000/mo')
  })

  it('a yearly EUR figure divided by twelve is approximate too', () => {
    expect(approximateMonthlyEur({ salary: '60000 yearly EUR', salaryMonthlyEur: range({ min: 5000, max: 5000, currency: 'EUR', converted: false }) })).toBe('≈ €5,000/mo')
  })

  it('an ad already stating EUR per month needs no second figure', () => {
    expect(approximateMonthlyEur({ salary: '5000 monthly EUR', salaryMonthlyEur: range({ currency: 'EUR', converted: false }) })).toBeNull()
  })

  it('no reading, no figure', () => {
    expect(approximateMonthlyEur({ salary: '50 hourly' })).toBeNull()
  })
})
