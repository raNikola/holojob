// The Jobs table and the filter panel on the server's list (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P3 S2). With `server` the table shows the rows in the order the
// server gave and counts, sorts and cuts nothing itself; the filter panel takes the server's facets instead of reading rows. Server-rendered markup, as jobTable.test.js.
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import JobFilters from '../../src/components/jobs/JobFilters.jsx'
import JobTable from '../../src/components/jobs/JobTable.jsx'
import { getDefaultJobsState } from '../../src/modules/jobs/jobStorage.js'

vi.mock('../../src/components/jobs/JobTailorActions.jsx', () => ({ default: () => null }))
afterEach(() => vi.unstubAllGlobals())

const viewport = (matches) => vi.stubGlobal('matchMedia', () => ({ matches, addEventListener() {}, removeEventListener() {} }))
const job = (n, extra = {}) => ({ jobId: `j${n}`, title: `Ad ${n}`, company: 'Acme', location: 'Remote', jobUrl: `https://x.example/${n}`, provider: 'jobspy', status: 'new', ...extra })
const serverProps = (extra = {}) => ({ total: 3, pageSize: 100, loadingMore: false, sort: null, onSort() {}, onShowMore() {}, hasScores: true, hasProvider: true, ...extra })
const render = (jobs, server, props = {}) => renderToStaticMarkup(createElement(JobTable, { jobs, server, onStatusChange() {}, onJobSelect() {}, onToggleSelect() {}, onToggleSelectAll() {}, ...props }))
const at = (html, text) => html.indexOf(text)

describe('the table on the server\'s list', () => {
  it('keeps the order the server gave, even where the table\'s own default order would put them differently', () => {
    viewport(true)
    const weak = job(1, { title: 'Weak ad', matchScore: 30, matchLabel: 'Weak', priority: 'P3', dataStatus: 'ok' })
    const strong = job(2, { title: 'Strong ad', matchScore: 90, matchLabel: 'Strong', priority: 'P1', dataStatus: 'ok' })
    // the local default order is Strong before Weak; the server's rows are given Weak first, and that is what is shown
    const html = render([weak, strong], serverProps({ total: 2 }))
    expect(at(html, 'Weak ad')).toBeLessThan(at(html, 'Strong ad'))
    const local = renderToStaticMarkup(createElement(JobTable, { jobs: [weak, strong], onStatusChange() {}, onJobSelect() {}, onToggleSelect() {}, onToggleSelectAll() {} }))
    expect(at(local, 'Strong ad')).toBeLessThan(at(local, 'Weak ad'))
  })

  it('shows every row it is given: the table does not cut a list at a page size of its own', () => {
    viewport(true)
    const rows = Array.from({ length: 230 }, (_, n) => job(n))
    const html = render(rows, serverProps({ total: 230 }))
    expect(html.split('<tr').length - 1).toBeGreaterThanOrEqual(231)
    expect(html).toContain('Showing 230 of 230')
    expect(html).not.toContain('more') // nothing is left to show
  })

  it('says how many the server holds and offers the next page at the server\'s size', () => {
    viewport(true)
    const html = render(Array.from({ length: 40 }, (_, n) => job(n)), serverProps({ total: 140, pageSize: 40 }))
    expect(html).toContain('Showing 40 of 140')
    expect(html).toContain('Show 40 more')
    expect(render(Array.from({ length: 40 }, (_, n) => job(n)), serverProps({ total: 55, pageSize: 40 }))).toContain('Show 15 more')
  })

  it('shows Loading while the next page comes, and the button cannot be pressed twice', () => {
    viewport(true)
    const html = render([job(1)], serverProps({ total: 5, pageSize: 4, loadingMore: true }))
    expect(html).toContain('Loading…')
    expect(html).toMatch(/<button[^>]*disabled[^>]*>Loading…/)
  })

  it('the columns follow the server\'s facets, not the rows loaded so far', () => {
    viewport(true)
    const scored = [job(1, { matchScore: 80, matchLabel: 'Strong', dataStatus: 'ok' })]
    expect(render(scored, serverProps({ total: 1, hasScores: false }))).not.toContain('Fit tier')
    expect(render([job(1)], serverProps({ total: 1, hasScores: true }))).toContain('Fit tier')
    expect(render([job(1)], serverProps({ total: 1, hasProvider: false }))).not.toContain('>Provider<')
  })

  it('a selection reaching rows not loaded yet is said, and the select-all box is for the whole filtered list', () => {
    viewport(true)
    const html = render([job(1), job(2)], serverProps({ total: 90 }), { selectedJobIds: new Set(['j1', 'ghost-1', 'ghost-2']) })
    expect(html).toContain('2 selected jobs are not shown yet')
    expect(html).toContain('not only the 2 shown')
  })

  it('the narrow layout takes the same rows and the same Show more', () => {
    viewport(false)
    const html = render([job(1), job(2)], serverProps({ total: 9, pageSize: 2 }))
    expect(html).not.toContain('<table')
    expect(html).toContain('Show 2 more')
    expect(html).toContain('Showing 2 of 9')
  })
})

describe('the filter panel on the server\'s facets', () => {
  const panel = (props) => renderToStaticMarkup(createElement(JobFilters, { filters: getDefaultJobsState().filters, sites: [], providers: [], jobs: [], onChange() {}, ...props }))
  const facets = (extra = {}) => ({ hasScores: true, sites: [], providers: [], companyOptions: [], priorityCounts: [{ value: 'P1', count: 3 }], statusOptions: ['new', 'saved'], ...extra })

  it('offers the score filters when the server says there are scores, with no rows to read them from', () => {
    expect(panel({ facets: facets({ hasScores: true }) })).toContain('All priorities')
    expect(panel({ facets: facets({ hasScores: false }) })).not.toContain('All priorities')
  })

  it('without facets it reads the rows, as it always did', () => {
    expect(panel({ jobs: [{ jobId: 'a', matchScore: 70, priority: 'P1' }] })).toContain('All priorities')
    expect(panel({ jobs: [] })).not.toContain('All priorities')
  })
})
