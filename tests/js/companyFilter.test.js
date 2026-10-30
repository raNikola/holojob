import React, { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CLEAR_ALL_FILTERS,
  activeFilterChips,
  companyParts,
  filterJobs,
  getCompanyOptions,
  getUniqueProviders,
  moreFiltersCount,
} from '../../src/modules/jobs/jobFilters.js'
import { getDefaultJobsState, loadJobs, saveJobs, updateFilters } from '../../src/modules/jobs/jobStorage.js'

const jobs = [
  { jobId: '1', title: 'PM', company: 'Fivetran', provider: 'greenhouse' },
  { jobId: '2', title: 'PM', company: 'Fivetran Serbia', provider: 'jobspy' },
  { jobId: '3', title: 'PM', company: 'FIVETRAN', provider: 'jobspy' },
  { jobId: '4', title: 'PM', company: 'Nebius', provider: 'greenhouse' },
  { jobId: '5', title: 'PM', company: 'Bank of Serbia', provider: 'infostud' },
  { jobId: '6', title: 'PM', company: 'Acme', provider: 'manual', manualEntry: true, sourceUrl: 'https://careers.nebius.example/x' },
  { jobId: '7', title: 'PM', company: 'Nebius', provider: 'manual', manualEntry: true },
  { jobId: '8', title: 'PM', company: '' },
]
const ids = (list) => list.map((j) => j.jobId)

describe('Provider: Manual', () => {
  it('lists "Manual" first, once, when jobs were added by hand, and not otherwise', () => {
    expect(getUniqueProviders(jobs)).toEqual(['Manual', 'greenhouse', 'infostud', 'jobspy'])
    expect(getUniqueProviders(jobs.filter((j) => !j.manualEntry))).toEqual(['greenhouse', 'infostud', 'jobspy'])
  })

  it('filters on the manual flag, in any case', () => {
    expect(ids(filterJobs(jobs, { provider: ['Manual'] }))).toEqual(['6', '7'])
    expect(ids(filterJobs(jobs, { provider: ['manual'] }))).toEqual(['6', '7'])
    expect(ids(filterJobs(jobs, { provider: ['Manual', 'infostud'] }))).toEqual(['5', '6', '7'])
  })

  it('does not look at the Source URL: a discovered job whose text or link says manual is not manual', () => {
    const list = [{ jobId: 'a', provider: 'greenhouse', sourceUrl: 'https://manual.example/' }, { jobId: 'b', manualEntry: true, provider: 'manual', sourceUrl: '' }]
    expect(ids(filterJobs(list, { provider: ['Manual'] }))).toEqual(['b'])
    expect(ids(filterJobs([{ jobId: 'c', manualEntry: true }], { provider: ['Manual'] }))).toEqual(['c'])
  })
})

describe('company key', () => {
  it.each([
    ['Fivetran Serbia', 'fivetran'],
    ['fivetran', 'fivetran'],
    ['  FIVETRAN   Srbija ', 'fivetran'],
    ['Acme Corp United Kingdom', 'acme corp'],
    ['Bank of Serbia', 'bank of serbia'],
    ['Serbia', 'serbia'],
    ['Nebius', 'nebius'],
    ['', ''],
    [undefined, ''],
  ])('%s -> %s', (name, key) => {
    expect(companyParts(name).key).toBe(key)
  })

  it('keeps the writing of the name without the country', () => {
    expect(companyParts('Fivetran Serbia').name).toBe('Fivetran')
  })
})

describe('Company filter', () => {
  it('lists one entry per company with its job count, sorted, from the jobs it is given', () => {
    expect(getCompanyOptions(jobs)).toEqual([
      { value: 'Acme', label: 'Acme (1)' },
      { value: 'Bank of Serbia', label: 'Bank of Serbia (1)' },
      { value: 'Fivetran', label: 'Fivetran (3)' },
      { value: 'Nebius', label: 'Nebius (2)' },
    ])
    expect(getCompanyOptions(jobs.slice(3))).toContainEqual({ value: 'Nebius', label: 'Nebius (2)' })
    expect(getCompanyOptions(null)).toEqual([])
  })

  it('ignores case and a trailing country when matching', () => {
    expect(ids(filterJobs(jobs, { company: ['Fivetran'] }))).toEqual(['1', '2', '3'])
    expect(ids(filterJobs(jobs, { company: ['fivetran serbia'] }))).toEqual(['1', '2', '3'])
    expect(ids(filterJobs(jobs, { company: ['NEBIUS'] }))).toEqual(['4', '7'])
  })

  it('several companies are alternatives; none selected is no filter', () => {
    expect(ids(filterJobs(jobs, { company: ['Nebius', 'Acme'] }))).toEqual(['4', '6', '7'])
    expect(filterJobs(jobs, { company: [] })).toHaveLength(jobs.length)
    expect(filterJobs(jobs, {})).toHaveLength(jobs.length)
    expect(filterJobs(jobs, { company: '' })).toHaveLength(jobs.length)
  })

  it('combines with Provider and the other filters (AND)', () => {
    expect(ids(filterJobs(jobs, { company: ['Fivetran'], provider: ['jobspy'] }))).toEqual(['2', '3'])
    expect(ids(filterJobs(jobs, { company: ['Nebius'], provider: ['Manual'] }))).toEqual(['7'])
    expect(ids(filterJobs(jobs, { company: ['Nebius'], provider: ['infostud'] }))).toEqual([])
    expect(ids(filterJobs(jobs, { company: ['Fivetran'], searchText: 'zzz' }))).toEqual([])
  })

  it('an entry whose jobs are gone stays selectable and simply matches nothing', () => {
    expect(filterJobs(jobs, { company: ['Vanished Inc'] })).toEqual([])
  })
})

describe('Company filter in the summary, the count and Reset', () => {
  it('shows a chip that clears it, and counts under More filters', () => {
    const chips = activeFilterChips({ company: ['Fivetran', 'Nebius'], provider: ['Manual'] })
    expect(chips.map((c) => c.label)).toEqual(['Provider: Manual', 'Company: Fivetran, Nebius'])
    expect(chips.find((c) => c.key === 'company').patch).toEqual({ company: [] })
    expect(moreFiltersCount(chips)).toBe(2)
    expect(activeFilterChips({ company: [] })).toEqual([])
  })

  it('"Clear all" resets it', () => {
    expect(CLEAR_ALL_FILTERS.company).toEqual([])
    const state = updateFilters(updateFilters(getDefaultJobsState(), { company: ['Nebius'] }), CLEAR_ALL_FILTERS)
    expect(state.filters.company).toEqual([])
  })
})

describe('Company filter is saved like the other filters', () => {
  const items = new Map()
  beforeEach(() => {
    items.clear()
    vi.stubGlobal('localStorage', { getItem: (k) => items.get(k) ?? null, setItem: (k, v) => { items.set(k, v) }, removeItem: (k) => { items.delete(k) } })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('defaults to none, survives a save and a load, and an older save without it loads as none', () => {
    expect(getDefaultJobsState().filters.company).toEqual([])
    saveJobs(updateFilters(getDefaultJobsState(), { company: ['Fivetran'], provider: ['Manual'] }))
    expect(loadJobs().filters).toMatchObject({ company: ['Fivetran'], provider: ['Manual'] })
    const old = JSON.parse(items.get([...items.keys()][0]))
    delete old.filters.company
    items.set([...items.keys()][0], JSON.stringify(old))
    expect(loadJobs().filters.company).toEqual([])
  })

  it('reads a string saved by hand as a list of one', () => {
    const key = (saveJobs(getDefaultJobsState()), [...items.keys()][0])
    const saved = JSON.parse(items.get(key))
    items.set(key, JSON.stringify({ ...saved, filters: { ...saved.filters, company: 'Nebius' } }))
    expect(loadJobs().filters.company).toEqual(['Nebius'])
  })
})

describe('Company dropdown in the panel', () => {
  // The test runner compiles JSX with the classic runtime, which needs React in scope.
  let JobFilters
  beforeAll(async () => {
    globalThis.React = React
    JobFilters = (await import('../../src/components/jobs/JobFilters.jsx')).default
  })
  const render = (filters = {}) => renderToStaticMarkup(createElement(JobFilters, {
    filters: { ...CLEAR_ALL_FILTERS, ...filters }, sites: [], providers: getUniqueProviders(jobs), jobs, onChange: () => {},
  }))

  it('has a labelled button beside Provider, in the extras row', () => {
    const html = render()
    const label = html.match(/<label for="([^"]+)"[^>]*>Company<\/label>/)
    expect(label).not.toBeNull()
    expect(html).toMatch(new RegExp(`<button[^>]*id="${label[1].replace(/[:]/g, '\\$&')}"[^>]*aria-haspopup="true"`))
    expect(html).toContain('All companies')
    expect(html.indexOf('>Provider<')).toBeLessThan(html.indexOf('>Company<'))
    expect(html).toContain('About Company')
  })

  it('shows the selection on the button and as a chip with a named remove button', () => {
    const html = render({ company: ['Fivetran'] })
    expect(html).toContain('Company: Fivetran')
    expect(html).toContain('aria-label="Remove filter Company: Fivetran"')
    expect(html).toContain('More filters (1)')
  })
})
