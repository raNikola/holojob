import { describe, expect, it } from 'vitest'
import {
  describeRange,
  formatAmount,
  matchesSalary,
  parseAmount,
  rangeError,
  salaryRangeOf,
  sanitizeAmount,
} from '../../src/modules/jobs/salaryFilter.js'
import { activeFilterChips, filterJobs, CLEAR_ALL_FILTERS } from '../../src/modules/jobs/jobFilters.js'
import { withProfileSalaryDefaults } from '../../src/modules/jobs/jobSalary.js'

const pay = (min, max = min) => ({ min, max })
const job = (jobId, salaryMonthlyEur) => ({ jobId, salaryMonthlyEur })
const jobs = [job('low', pay(1500, 2000)), job('mid', pay(3000, 4000)), job('single', pay(3500)), job('high', pay(6000, 8000)), job('none', null)]
const ids = (list) => list.map((j) => j.jobId)

describe('parsing and formatting', () => {
  it('keeps digits only: no decimals, letters or minus', () => {
    expect(sanitizeAmount('3,000')).toBe('3000')
    expect(sanitizeAmount('-12.5abc')).toBe('125')
    expect(sanitizeAmount('')).toBe('')
    expect(sanitizeAmount('123456789')).toBe('1234567')
  })

  it('parses to a non-negative integer or null', () => {
    expect(parseAmount('3,000')).toBe(3000)
    expect(parseAmount('')).toBeNull()
    expect(parseAmount(null)).toBeNull()
    expect(parseAmount('abc')).toBeNull()
    expect(parseAmount(2500)).toBe(2500)
    expect(parseAmount(-5)).toBeNull()
    expect(parseAmount(0)).toBe(0)
  })

  it('formats with thousands separators', () => {
    expect(formatAmount(3000)).toBe('3,000')
    expect(formatAmount(950)).toBe('950')
    expect(formatAmount(null)).toBe('')
  })
})

describe('validation and description', () => {
  it('From above To is the only error', () => {
    expect(rangeError(4000, 3000)).toBe(true)
    expect(rangeError(3000, 3000)).toBe(false)
    expect(rangeError(3000, null)).toBe(false)
    expect(rangeError(null, null)).toBe(false)
  })

  it('describes the range in one line', () => {
    expect(describeRange(null, null)).toBe('')
    expect(describeRange(3000, null)).toBe('At least 3,000 / month')
    expect(describeRange(null, 4000)).toBe('Up to 4,000 / month')
    expect(describeRange(2000, 4000)).toBe('2,000 to 4,000 / month')
  })
})

describe('overlap matching', () => {
  it('empty range matches everything, also a job with no pay', () => {
    expect(matchesSalary(null, {}, false)).toBe(true)
    expect(matchesSalary(pay(100), { from: null, to: null }, false)).toBe(true)
  })

  it('From only means at least: the top figure reaches it', () => {
    expect(ids(filterJobs(jobs, { salaryFrom: 3000, salaryTo: '' }))).toEqual(['mid', 'single', 'high', 'none'])
  })

  it('To only means up to: the bottom figure is not above it', () => {
    expect(ids(filterJobs(jobs, { salaryFrom: '', salaryTo: 2000 }))).toEqual(['low', 'none'])
  })

  it('a range matches when it overlaps, a single figure when it lies inside', () => {
    expect(ids(filterJobs(jobs, { salaryFrom: 3800, salaryTo: 5000 }))).toEqual(['mid', 'none'])
    expect(ids(filterJobs(jobs, { salaryFrom: 3400, salaryTo: 3600 }))).toEqual(['mid', 'single', 'none'])
    expect(ids(filterJobs(jobs, { salaryFrom: 3600, salaryTo: 3900 }))).toEqual(['mid', 'none'])
  })

  it('touching ends overlap', () => {
    expect(matchesSalary(pay(3000, 4000), { from: 4000, to: 5000 })).toBe(true)
    expect(matchesSalary(pay(3000, 4000), { from: 4001, to: 5000 })).toBe(false)
  })
})

describe('jobs without salary', () => {
  it('follow the checkbox when a range is set, and are kept by default', () => {
    expect(ids(filterJobs(jobs, { salaryFrom: 6000 }))).toEqual(['high', 'none'])
    expect(ids(filterJobs(jobs, { salaryFrom: 6000, salaryIncludeUnknown: true }))).toEqual(['high', 'none'])
    expect(ids(filterJobs(jobs, { salaryFrom: 6000, salaryIncludeUnknown: false }))).toEqual(['high'])
  })

  it('the checkbox alone restricts nothing', () => {
    expect(filterJobs(jobs, { salaryIncludeUnknown: false })).toHaveLength(5)
  })
})

describe('state saved by the three-field panel', () => {
  it('reads minSalary and desired-from as one From (the larger), desired-to as To', () => {
    expect(salaryRangeOf({ minSalary: '2500', desiredSalaryMin: 3000, desiredSalaryMax: '4500' })).toEqual({ from: 3000, to: 4500 })
    expect(salaryRangeOf({ minSalary: 2500, desiredSalaryMin: '', desiredSalaryMax: null })).toEqual({ from: 2500, to: null })
    expect(salaryRangeOf({ minSalary: null, desiredSalaryMin: null, desiredSalaryMax: null })).toEqual({ from: null, to: null })
    expect(salaryRangeOf({})).toEqual({ from: null, to: null })
  })

  it('returns the same jobs as the old three tests did', () => {
    const old = { minSalary: '3500', desiredSalaryMin: '3000', desiredSalaryMax: '5000' }
    expect(ids(filterJobs(jobs, old))).toEqual(['mid', 'single', 'none'])
  })

  it('the new keys win once the range is edited', () => {
    expect(salaryRangeOf({ minSalary: 9000, salaryFrom: 2000, salaryTo: '' })).toEqual({ from: 2000, to: null })
  })
})

describe('profile figures', () => {
  const bp = { minSalaryEur: 2500, desiredSalaryMinEur: 3000, desiredSalaryMaxEur: 4500 }

  it('an untouched range takes the profile: From the larger lower figure, To the desired maximum', () => {
    const f = withProfileSalaryDefaults({ minSalary: null, desiredSalaryMin: null, desiredSalaryMax: null }, bp)
    expect(salaryRangeOf(f)).toEqual({ from: 3000, to: 4500 })
    expect(f.salaryFromProfile).toBe(true)
  })

  it('an explicit empty range stays empty', () => {
    const f = withProfileSalaryDefaults({ salaryFrom: '', salaryTo: '' }, bp)
    expect(salaryRangeOf(f)).toEqual({ from: null, to: null })
    expect(f.salaryFromProfile).toBe(false)
  })

  it('Clear all leaves no chip and no restriction', () => {
    const f = withProfileSalaryDefaults({ ...CLEAR_ALL_FILTERS }, bp)
    expect(activeFilterChips(f)).toEqual([])
    expect(filterJobs(jobs, f)).toHaveLength(5)
  })
})

describe('salary chip', () => {
  it('shows the range and whether jobs without salary are hidden, and clears only the numbers', () => {
    const [chip] = activeFilterChips({ salaryFrom: 2000, salaryTo: 4000, salaryIncludeUnknown: false })
    expect(chip.label).toBe('Salary: 2,000 to 4,000 / month, jobs without salary hidden')
    expect(chip.patch).toMatchObject({ salaryFrom: '', salaryTo: '' })
    expect(chip.patch).not.toHaveProperty('salaryIncludeUnknown')
  })
})
