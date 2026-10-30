import { describe, expect, it } from 'vitest'
import {
  CLEAR_ALL_FILTERS,
  activeFilterChips,
  countByValue,
  filterJobs,
  moreFiltersCount,
  normalizeMultiFilter,
} from '../../src/modules/jobs/jobFilters.js'
import { withProfileSalaryDefaults } from '../../src/modules/jobs/jobSalary.js'
import { FILTER_HELP } from '../../src/modules/jobs/filterHelp.js'

const jobs = [
  { jobId: '1', site: 'linkedin', provider: 'jobspy', priority: 'P1' },
  { jobId: '2', site: 'nebius', provider: 'greenhouse', priority: 'P2' },
  { jobId: '3', site: 'fivetran', provider: 'greenhouse', priority: 'P2' },
  { jobId: '4', site: 'infostud', priority: 'Reject' },
]
const ids = (list) => list.map((j) => j.jobId)

describe('multi-value Source and Provider filters', () => {
  it('a saved single value still works, a list keeps any of them, empty keeps all', () => {
    expect(ids(filterJobs(jobs, { site: 'nebius' }))).toEqual(['2'])
    expect(ids(filterJobs(jobs, { site: ['nebius', 'fivetran'] }))).toEqual(['2', '3'])
    expect(filterJobs(jobs, { site: [] })).toHaveLength(4)
    expect(filterJobs(jobs, { site: '' })).toHaveLength(4)
  })

  it('matches case-insensitively', () => {
    expect(ids(filterJobs(jobs, { site: ['NEBIUS'] }))).toEqual(['2'])
  })

  it('Provider falls back to the site when the job has none', () => {
    expect(ids(filterJobs(jobs, { provider: ['greenhouse', 'infostud'] }))).toEqual(['2', '3', '4'])
    expect(ids(filterJobs(jobs, { provider: 'jobspy' }))).toEqual(['1'])
  })

  it('normalizeMultiFilter reads a string as a list of one', () => {
    expect(normalizeMultiFilter('a')).toEqual(['a'])
    expect(normalizeMultiFilter('')).toEqual([])
    expect(normalizeMultiFilter(null)).toEqual([])
    expect(normalizeMultiFilter(['a', '', 'b'])).toEqual(['a', 'b'])
  })
})

describe('priority counts', () => {
  it('counts every priority over the whole list and leaves out values with no job', () => {
    expect(countByValue(jobs, 'priority', ['P1', 'P2', 'P3'])).toEqual([
      { value: 'P1', count: 1 },
      { value: 'P2', count: 2 },
    ])
  })
})

describe('active filter chips', () => {
  it('lists nothing for the defaults', () => {
    expect(activeFilterChips({ searchText: '', site: [], provider: [], priority: [], minScore: '', status: '', remoteOnly: false })).toEqual([])
  })

  it('has one removable chip per active filter, and the patch resets that filter only', () => {
    const chips = activeFilterChips({ site: ['nebius', 'fivetran'], priority: ['P1'], minScore: '55', remoteOnly: true, hideNeedsVisa: true, provider: 'greenhouse' })
    expect(chips.map((c) => c.label)).toEqual([
      'Source: nebius, fivetran',
      'Priority: P1',
      'Min score: 55',
      'Remote only',
      'Provider: greenhouse',
      'Hiding jobs that need a visa',
    ])
    expect(chips[0].patch).toEqual({ site: [] })
    expect(chips[3].patch).toEqual({ remoteOnly: false })
  })

  it('a minimum score of 0 is an active filter', () => {
    expect(activeFilterChips({ minScore: '0' }).map((c) => c.key)).toEqual(['minScore'])
  })

  it('counts only the filters inside More filters', () => {
    const chips = activeFilterChips({ site: ['a'], provider: ['x'], matchLabel: 'Good', hideNeedsVisa: true, salaryFrom: 2500, salaryTo: '' })
    expect(moreFiltersCount(chips)).toBe(4)
  })

  it('Clear all sets salary to empty, so the profile figures do not come back', () => {
    const cleared = { ...CLEAR_ALL_FILTERS }
    const effective = withProfileSalaryDefaults(cleared, { minSalaryEur: 2500, desiredSalaryMinEur: 3000, desiredSalaryMaxEur: 4500 })
    expect(activeFilterChips(effective)).toEqual([])
    expect(filterJobs(jobs, effective)).toHaveLength(4)
  })
})

describe('filter tooltips', () => {
  it('every filter on the panel has a text', () => {
    for (const key of ['searchText', 'location', 'site', 'status', 'priority', 'minScore', 'remoteOnly', 'provider', 'matchLabel', 'salary', 'hideNeedsVisa', 'hideClosed']) {
      expect(FILTER_HELP[key], key).toBeTruthy()
    }
  })
})

describe('Hide closed jobs', () => {
  const list = [{ jobId: 'a' }, { jobId: 'b', isClosed: true }, { jobId: 'c', isClosed: false }]

  it('is off by default and when unset', () => {
    expect(filterJobs(list, {})).toHaveLength(3)
    expect(filterJobs(list, { hideClosed: false })).toHaveLength(3)
  })

  it('drops jobs that are no longer listed when on', () => {
    expect(ids(filterJobs(list, { hideClosed: true }))).toEqual(['a', 'c'])
  })

  it('has a chip that is counted in More filters, and Clear all turns it off', () => {
    const chips = activeFilterChips({ hideClosed: true })
    expect(chips).toEqual([{ key: 'hideClosed', label: 'Hiding closed jobs', patch: { hideClosed: false } }])
    expect(moreFiltersCount(chips)).toBe(1)
    expect(CLEAR_ALL_FILTERS.hideClosed).toBe(false)
  })
})
