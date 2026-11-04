// The Jobs table on a long list (slice S5e3b): one layout, the whole list sorted before a batch is taken, selection across batches.
// The repo has no DOM for tests, so markup is server-rendered and clicks are the pure state functions behind them.
import fs from 'node:fs'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FitScore from '../../src/components/jobs/FitScore.jsx'
import JobTable from '../../src/components/jobs/JobTable.jsx'
import {
  JOB_PAGE_SIZE, everySelected, pageLimit, selectedNotShown, selectionFor, showMore, toggleAllSelected, toggleSelected,
} from '../../src/modules/jobs/jobTableModel.js'
import { getDefaultJobsState, saveJobs, updateFilters } from '../../src/modules/jobs/jobStorage.js'

// Cards hold the tailoring tools, which need the profile; they are not what is tested here.
vi.mock('../../src/components/jobs/JobTailorActions.jsx', () => ({ default: () => null }))

afterEach(() => vi.unstubAllGlobals())

const job = (n, extra = {}) => ({ jobId: `j${n}`, title: `Ad ${n}`, company: 'Acme', location: 'Remote', jobUrl: `https://x.example/${n}`, provider: 'jobspy', status: 'new', matchScore: 50, matchLabel: 'Good', ...extra })
const list = (count) => Array.from({ length: count }, (_, n) => job(n))
const viewport = (matches) => vi.stubGlobal('matchMedia', () => ({ matches, addEventListener() {}, removeEventListener() {} }))
const render = (jobs, props = {}) => renderToStaticMarkup(createElement(JobTable, { jobs, onStatusChange() {}, onJobSelect() {}, onToggleSelect() {}, onToggleSelectAll() {}, ...props }))
const count = (html, text) => html.split(text).length - 1

describe('one layout', () => {
  it('a wide window mounts only the table', () => {
    viewport(true)
    const html = render(list(3))
    expect(count(html, '<table')).toBe(1)
    expect(count(html, '<tr')).toBe(4)
    expect(html).not.toContain('Open link')
  })

  it('a narrow window mounts only the cards', () => {
    viewport(false)
    const html = render(list(3))
    expect(html).not.toContain('<table')
    expect(count(html, 'Open link')).toBe(3)
  })

  it('it asks for the width the layouts have always switched at', () => {
    const asked = []
    vi.stubGlobal('matchMedia', (query) => { asked.push(query); return { matches: true, addEventListener() {}, removeEventListener() {} } })
    render(list(1))
    expect(asked[0]).toBe('(min-width: 768px)')
  })

  it('with no matchMedia it falls back to the table', () => {
    expect(render(list(1))).toContain('<table')
  })

  it('neither layout is hidden by CSS any more', () => {
    viewport(true)
    expect(render(list(1))).not.toContain('md:hidden')
    expect(render(list(1))).not.toContain('md:block')
  })

  it.each([[true], [false]])('rows keep their actions and labels (wide: %s)', (wide) => {
    viewport(wide)
    const html = render([job(1)])
    for (const text of ['Ad 1', 'Acme', 'aria-label="Save"', 'aria-label="Reject"', 'type="checkbox"']) expect(html).toContain(text)
  })
})

describe('paging: the whole list is sorted, then a batch is taken', () => {
  it('a row that sorts first is in the first batch wherever it sits in the list', () => {
    viewport(true)
    const jobs = list(3500)
    jobs[3200] = job(3200, { matchScore: 99, title: 'The best ad' })
    const html = render(jobs)
    expect(html).toContain('The best ad')
    expect(html.indexOf('The best ad')).toBeLessThan(html.indexOf('Ad 0<'))
  })

  it('a row that sorts last is not, though it is first in the list', () => {
    viewport(true)
    const jobs = list(500)
    jobs[0] = job(0, { matchScore: 1, title: 'The worst ad' })
    expect(render(jobs)).not.toContain('The worst ad')
  })

  it('shows one batch, N of M and the button', () => {
    viewport(true)
    const html = render(list(3500))
    expect(JOB_PAGE_SIZE).toBe(100)
    expect(count(html, '<tr')).toBe(101)
    expect(html).toContain('Showing 100 of 3500')
    expect(html).toContain('Show 100 more')
  })

  it('cards are one batch too', () => {
    viewport(false)
    expect(count(render(list(250)), 'Open link')).toBe(100)
  })

  it('the button names what is left, and goes when nothing is', () => {
    viewport(true)
    expect(render(list(150))).toContain('Show 50 more')
    const all = render(list(100))
    expect(all).not.toContain('more</button>')
    expect(all).toContain('Showing 100 of 100')
  })

  it('the count is announced', () => {
    viewport(true)
    expect(render(list(3))).toContain('role="status"')
  })

  it('an empty list says so and offers nothing', () => {
    const html = render([])
    expect(html).toContain('No jobs match the current filters.')
    expect(html).not.toContain('Select all')
  })

  it('the Provider column is judged on the whole list, not the batch', () => {
    viewport(true)
    const jobs = list(150).map((j) => ({ ...j, provider: '', site: '' }))
    jobs[149] = { ...jobs[149], matchScore: 1, provider: 'greenhouse', title: 'Last in the sort' }
    const html = render(jobs)
    expect(html).not.toContain('Last in the sort')
    expect(html).toContain('Provider')
  })
})

describe('the paging state', () => {
  it('starts at one batch and grows by one', () => {
    expect(pageLimit(null, 'k')).toBe(100)
    const once = showMore(null, 'k')
    expect(once).toEqual({ key: 'k', limit: 200 })
    expect(showMore(once, 'k').limit).toBe(300)
  })

  it('a new key, a filter or a sort, is back to one batch', () => {
    const paged = showMore(showMore(null, 'filters|score|desc'), 'filters|score|desc')
    expect(pageLimit(paged, 'filters|score|desc')).toBe(300)
    expect(pageLimit(paged, 'filters|title|asc')).toBe(100)
    expect(pageLimit(paged, 'other filters|score|desc')).toBe(100)
    expect(showMore(paged, 'filters|title|asc').limit).toBe(200)
  })

  it('the table builds its key from the filters and the sort', () => {
    const source = fs.readFileSync('src/components/jobs/JobTable.jsx', 'utf-8')
    expect(source).toContain('const pageKey = `${filterKey}|${sort.key}|${sort.dir}`')
    expect(source).toContain('const limit = pageLimit(paging, pageKey)')
  })
})

describe('selection', () => {
  const start = toggleSelected(null, 'f', 'a')

  it('is a Set, and toggles', () => {
    expect(selectionFor(start, 'f')).toEqual(new Set(['a']))
    expect(selectionFor(toggleSelected(start, 'f', 'b'), 'f')).toEqual(new Set(['a', 'b']))
    expect(selectionFor(toggleSelected(start, 'f', 'a'), 'f')).toEqual(new Set())
  })

  it('does not change the state it is given', () => {
    toggleSelected(start, 'f', 'b')
    expect(selectionFor(start, 'f')).toEqual(new Set(['a']))
  })

  it('a filter change resets it: the key is the filters alone', () => {
    expect(selectionFor(start, 'other filters')).toEqual(new Set())
    expect(selectionFor(toggleSelected(start, 'other filters', 'b'), 'other filters')).toEqual(new Set(['b']))
  })

  it('Show more and a sort do not reset it: they are not in its key', () => {
    const screen = fs.readFileSync('src/components/jobs/JobDiscoveryScreen.jsx', 'utf-8')
    expect(screen).toContain('() => JSON.stringify([effectiveFilters, listMode, [...listClasses].sort(), seenRecentlyOnly])')
    expect(screen).toContain('const selectedJobIds = selectionFor(selection, filterKey)')
    expect(screen).toContain('filterKey={filterKey}')
  })

  it('a selected row stays checked when more rows load and when it moves', () => {
    viewport(true)
    const selected = new Set(['j1'])
    const checked = (html) => count(html, 'checked=""')
    expect(checked(render(list(150), { selectedJobIds: selected }))).toBe(1)
    const later = new Set(['j149'])
    expect(checked(render(list(150), { selectedJobIds: later }))).toBe(0)
  })

  it('a card shows its selection too', () => {
    viewport(false)
    expect(count(render(list(3), { selectedJobIds: new Set(['j1']) }), 'checked=""')).toBe(1)
  })

  it('counts the selected rows that are not on screen', () => {
    const jobs = list(300)
    expect(selectedNotShown(new Set(['j5', 'j150', 'j299']), jobs, 100)).toBe(2)
    expect(selectedNotShown(new Set(['j5']), jobs, 100)).toBe(0)
    expect(selectedNotShown(new Set(), jobs, 100)).toBe(0)
    expect(selectedNotShown(new Set(['j0']), jobs, 0)).toBe(1)
  })
})

describe('select all means every filtered row', () => {
  const ids = list(350).map((j) => j.jobId)

  it('selects all of them, shown or not, and replaces what was selected', () => {
    const selected = selectionFor(toggleAllSelected(toggleSelected(null, 'f', 'gone'), 'f', ids), 'f')
    expect(selected.size).toBe(350)
    expect(selected.has('j349')).toBe(true)
    expect(selected.has('gone')).toBe(false)
  })

  it('with all of them selected, it clears', () => {
    const all = toggleAllSelected(null, 'f', ids)
    expect(selectionFor(toggleAllSelected(all, 'f', ids), 'f').size).toBe(0)
  })

  it('a selection of the same size that is not the same rows is not "all"', () => {
    const other = new Set(ids.map((id) => `${id}x`))
    expect(everySelected(other, ids)).toBe(false)
    expect(selectionFor(toggleAllSelected({ key: 'f', ids: other }, 'f', ids), 'f').size).toBe(350)
  })

  it('an empty list is never "all selected"', () => {
    expect(everySelected(new Set(), [])).toBe(false)
  })

  it('the table says what it selects, in words and to a screen reader', () => {
    viewport(true)
    const html = render(list(350))
    expect(html).toContain('Select all 350 filtered jobs</button>')
    expect(html).toContain('aria-label="Select all 350 filtered jobs, not only the 100 shown"')
    expect(html).toContain('title="Select all 350 filtered jobs, not only the 100 shown"')
  })

  it('a narrow window can select all too', () => {
    viewport(false)
    expect(render(list(350))).toContain('Select all 350 filtered jobs</button>')
  })

  it('with all selected it offers to clear, and says how many are off screen', () => {
    viewport(true)
    const html = render(list(350), { selectedJobIds: new Set(list(350).map((j) => j.jobId)) })
    expect(html).toContain('Clear selection of all 350 filtered jobs')
    expect(html).toContain('250 selected jobs are not shown yet')
    expect(html).toContain('checked=""')
    expect(render(list(150), { selectedJobIds: new Set(['j140']) })).toContain('1 selected job is not shown yet')
  })

  it('every row on screen selected is not all of them', () => {
    viewport(true)
    const html = render(list(350), { selectedJobIds: new Set(list(100).map((j) => j.jobId)) })
    expect(html).toContain('Select all 350 filtered jobs</button>')
    expect(html).not.toContain('Clear selection')
    expect(count(html, 'checked=""')).toBe(100)
  })

  it('the screen hands it every filtered row', () => {
    expect(fs.readFileSync('src/components/jobs/JobDiscoveryScreen.jsx', 'utf-8')).toContain('toggleAllSelected(prev, filterKey, selectableIds(filteredJobs))')
  })

  it('nothing off screen says nothing', () => {
    viewport(true)
    expect(render(list(50), { selectedJobIds: new Set(['j1']) })).not.toContain('not shown yet')
  })
})

describe('bulk actions act on stored rows as before', () => {
  it('reads the Set where it read the list', () => {
    const screen = fs.readFileSync('src/components/jobs/JobDiscoveryScreen.jsx', 'utf-8')
    expect(screen).toContain('selectedJobIds.has(j.jobId) ? { ...j, status } : j')
    expect(screen).toContain('selectedCount={selectedJobIds.size}')
    expect(screen).toContain('jobs={state.jobs}')
    expect(fs.readFileSync('src/components/jobs/BulkActionsBar.jsx', 'utf-8')).toContain('jobs.filter((j) => selectedJobIds.has(j.jobId))')
  })
})

describe('FitScore', () => {
  const score = (props) => renderToStaticMarkup(createElement(FitScore, props))

  it('with no score it still shows a dash unless told otherwise', () => {
    expect(score({})).toContain('>—<')
    expect(score({ score: null })).toContain('>—<')
  })

  it('emptyLabel replaces the dash', () => {
    expect(score({ emptyLabel: 'Not scored' })).toContain('>Not scored<')
  })

  it('a score ignores it', () => {
    const html = score({ score: 70, label: 'Good', emptyLabel: 'Not scored' })
    expect(html).toContain('70')
    expect(html).not.toContain('Not scored')
  })

  it('a score of 0 is a score', () => {
    expect(score({ score: 0, emptyLabel: 'Not scored' })).not.toContain('Not scored')
  })

  it('the Jobs table says Not scored, in both layouts', () => {
    viewport(true)
    expect(render([job(1, { matchScore: null }), job(2)])).toContain('Not scored')
    viewport(false)
    expect(render([job(1, { matchScore: null }), job(2)])).toContain('Not scored')
  })
})

describe('storage', () => {
  const sources = ['src/components/jobs/JobTable.jsx', 'src/modules/jobs/jobTableModel.js', 'src/hooks/useMediaQuery.js']

  it.each(sources)('%s names no storage and no writer', (file) => {
    const code = fs.readFileSync(file, 'utf-8')
    for (const word of ['localStorage', 'sessionStorage', 'saveJobs', 'patchJob', 'addJobIfAbsent']) expect(code).not.toContain(word)
  })

  it('rendering and paging and selecting touch no storage', () => {
    const touch = vi.fn(() => { throw new Error('storage was touched') })
    vi.stubGlobal('localStorage', { getItem: touch, setItem: touch, removeItem: touch })
    viewport(true)
    render(list(150), { selectedJobIds: new Set(['j1']) })
    showMore(null, 'k')
    toggleAllSelected(toggleSelected(null, 'k', 'a'), 'k', ['a', 'b'])
    expect(touch).not.toHaveBeenCalled()
  })

  it('selection and paging state stay out of what is saved', () => {
    const screen = fs.readFileSync('src/components/jobs/JobDiscoveryScreen.jsx', 'utf-8')
    expect(screen).toContain('const [selection, setSelection] = useState(null)')
    expect(fs.readFileSync('src/modules/jobs/jobStorage.js', 'utf-8')).not.toMatch(/selection|paging/i)
  })

  it('a filter change keeps its persistence, and the stored jobs stay byte-identical', () => {
    const saved = new Map()
    const storage = { setItem: (key, value) => saved.set(key, value) }
    const state = { ...getDefaultJobsState(), jobs: list(3).map((j) => ({ ...j, status: 'saved', outreach: { contacts: [{ name: 'x' }] } })) }
    saveJobs(state, storage)
    const [key] = saved.keys()
    const before = JSON.parse(saved.get(key))
    saveJobs(updateFilters(state, { searchText: 'pm' }), storage)
    const after = JSON.parse(saved.get(key))
    expect(after.filters.searchText).toBe('pm')
    expect(JSON.stringify(after.jobs)).toBe(JSON.stringify(before.jobs))
  })
})
