// The visible Active/All view (slice S5e3c): filters, badges, notices, read-only rows. The merge itself is tests/js/allAds.test.js.
import fs from 'node:fs'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AddJobDialog from '../../src/components/jobs/AddJobDialog.jsx'
import JobFilters from '../../src/components/jobs/JobFilters.jsx'
import JobListControls from '../../src/components/jobs/JobListControls.jsx'
import JobTable from '../../src/components/jobs/JobTable.jsx'
import {
  ALL_SEARCH_NOTE, CLASS_FILTERS, EXPORT_NOTE, INCOMPLETE_FILTERED, INCOMPLETE_ROUTE, SAVED_IN_BROWSER, SERVER_ONLY_NOTE,
  applyAllControls, classBadges, classFilterLabel, classOptions, filterComposed, listNotices, rowKind, selectableIds,
} from '../../src/modules/jobs/jobListView.js'
import { composeJobList } from '../../src/modules/jobs/allAds.js'
import { computeJobStats } from '../../src/modules/jobs/jobStats.js'
import { getDefaultJobsState, saveJobs, updateFilters } from '../../src/modules/jobs/jobStorage.js'

vi.mock('../../src/components/jobs/JobTailorActions.jsx', () => ({ default: () => 'TAILOR-ACTIONS' }))
afterEach(() => vi.unstubAllGlobals())

const NOW = Date.parse('2026-11-20T12:00:00Z')
const DAY = 86400000
const ago = (ms) => new Date(NOW - ms).toISOString()
const READY = { status: 'ready', store: { applications: {} } }
const route = (jobId, cls = 'found', extra = {}) => ({
  jobId, title: `Ad ${jobId}`, company: 'Acme', location: 'Remote', jobUrl: `https://x.example/${jobId}`, provider: 'jobspy', site: 'linkedin', isRemote: true, datePosted: null,
  firstSeen: ago(30 * DAY), lastSeen: ago(DAY), closedAt: null, absentSince: null, class: cls, reason: `reason ${cls}`, reasonCode: null, from: 'ledger', copyGroup: null, matchScore: null, ...extra,
})
const serverOnly = (jobId, cls, extra) => ({ ...route(jobId, cls, extra), status: 'new', serverOnly: true })
const filtered = (jobId = 'f', extra = {}) => serverOnly(jobId, 'filtered', { from: 'filtered', reason: 'Filtered out: Title didn\'t match', ...extra })
const stored = (jobId, extra = {}) => ({ jobId, title: `Stored ${jobId}`, company: 'Acme', jobUrl: `https://x.example/${jobId}`, status: 'new', matchScore: 60, matchLabel: 'Good', ...extra })
const ids = (rows) => rows.map((row) => row.jobId)
const viewport = (matches) => vi.stubGlobal('matchMedia', () => ({ matches, addEventListener() {}, removeEventListener() {} }))
const table = (jobs, props = {}) => renderToStaticMarkup(createElement(JobTable, { jobs, onStatusChange() {}, onJobSelect() {}, onToggleSelect() {}, onToggleSelectAll() {}, classView: true, ...props }))

describe('the class filter', () => {
  it('offers all nine classes and the display label, with counts, in a fixed order', () => {
    const options = classOptions([route('a', 'absent'), route('b', 'absent'), stored('s')])
    expect(options.map((o) => o.value)).toEqual(['found', 'held', 'absent', 'closed', 'older_key', 'stale', 'filtered', 'filtered_incomplete', 'unclassified', SAVED_IN_BROWSER])
    expect(options.find((o) => o.value === 'absent').count).toBe(2)
    expect(options.find((o) => o.value === SAVED_IN_BROWSER).count).toBe(1)
    expect(options.find((o) => o.value === 'closed').count).toBe(0)
  })

  it.each([
    ['found', 'Found'], ['held', 'Not checked this run'], ['absent', 'Not in latest search'], ['closed', 'Closed'], ['older_key', 'Search settings changed'],
    ['stale', 'Stale'], ['filtered', 'Filtered out'], ['filtered_incomplete', 'Incomplete'], ['unclassified', 'Status unknown'], [SAVED_IN_BROWSER, 'Saved in this browser'],
  ])('%s reads %s', (key, label) => expect(classFilterLabel(key)).toBe(label))

  it('none ticked shows all; ticked shows those', () => {
    const rows = [route('a', 'absent'), route('c', 'closed'), stored('s')]
    expect(ids(applyAllControls(rows, { classes: new Set(), reference: NOW }))).toEqual(['a', 'c', 's'])
    expect(ids(applyAllControls(rows, { classes: new Set(['closed']), reference: NOW }))).toEqual(['c'])
    expect(ids(applyAllControls(rows, { classes: new Set(['closed', 'absent']), reference: NOW }))).toEqual(['a', 'c'])
    expect(ids(applyAllControls(rows, { classes: new Set([SAVED_IN_BROWSER]), reference: NOW }))).toEqual(['s'])
  })
})

describe('Seen in the last 14 days', () => {
  const rows = [route('in', 'closed', { lastSeen: ago(14 * DAY) }), route('out', 'closed', { lastSeen: ago(14 * DAY + 1000) }), route('none', 'closed', { lastSeen: null }), stored('s')]

  it('reads lastSeen against the time passed in, any class, the boundary included', () => {
    expect(ids(applyAllControls(rows, { recent: true, reference: NOW }))).toEqual(['in'])
    expect(ids(applyAllControls(rows, { recent: false, reference: NOW }))).toEqual(['in', 'out', 'none', 's'])
    expect(applyAllControls(rows, { recent: true, reference: NOW + DAY })).toEqual([])
  })

  it('goes with the class filter', () => {
    expect(applyAllControls(rows, { classes: new Set(['absent']), recent: true, reference: NOW })).toEqual([])
  })
})

describe('the existing filters over a composed list', () => {
  it('Hide no longer listed reads the class, and the stored flag only with no class', () => {
    const rows = [route('c', 'closed'), route('old', 'found', { isClosed: true }), stored('s', { isClosed: true }), route('a', 'absent')]
    expect(ids(filterComposed(rows, { hideNoLongerListed: true }))).toEqual(['old', 'a'])
    expect(ids(filterComposed(rows, {}))).toEqual(['c', 'old', 's', 'a'])
  })

  it('Show off-list has no job here: an off-list row the two lists let in is not hidden', () => {
    expect(ids(filterComposed([stored('s', { offList: true, status: 'saved' })], { showOffList: false }))).toEqual(['s'])
  })

  it('other filters still apply: search reads what a server-only row has, and never finds its ad text', () => {
    const rows = [serverOnly('a', 'absent', { title: 'Chef' }), stored('s', { description: 'chef wanted' })]
    expect(ids(filterComposed(rows, { searchText: 'chef' }))).toEqual(['a', 's'])
    expect(ids(filterComposed([serverOnly('a', 'absent')], { searchText: 'roadmap' }))).toEqual([])
  })
})

describe('what may be done with a row', () => {
  it('kinds', () => {
    expect(rowKind(stored('s'))).toBe('stored')
    expect(rowKind(route('r', 'filtered', { from: 'filtered' }))).toBe('stored')
    expect(rowKind(serverOnly('a', 'absent'))).toBe('server')
    expect(rowKind(filtered())).toBe('filtered')
    expect(rowKind(null)).toBe('stored')
  })

  it('only stored rows can be selected', () => {
    expect(selectableIds([stored('s'), serverOnly('a', 'absent'), filtered()])).toEqual(['s'])
  })
})

describe('badges and reasons per class', () => {
  it.each([
    ['absent', 'Not in latest search'], ['older_key', 'Search settings changed'], ['closed', 'Closed'], ['filtered', 'Filtered out'],
    ['filtered_incomplete', 'Incomplete'], ['held', 'Not checked this run'], ['stale', 'Stale'], ['unclassified', 'Status unknown'],
  ])('%s: the badge %s, and the route\'s reason on the row', (cls, label) => {
    viewport(true)
    const html = table([serverOnly('a', cls, { reason: `The reason of ${cls}` })])
    expect(html).toContain(label)
    expect(html).toContain(`The reason of ${cls}`)
    expect(classBadges(route('a', cls))[0].label).toBe(label)
  })

  it('found has no badge, and its reason shows', () => {
    viewport(true)
    expect(classBadges(route('a', 'found'))).toEqual([])
    expect(table([route('a', 'found', { reason: 'Found by the latest run' })])).toContain('Found by the latest run')
  })

  it('cards show them too', () => {
    viewport(false)
    const html = table([serverOnly('a', 'absent', { reason: 'Why' })])
    expect(html).toContain('Not in latest search')
    expect(html).toContain('Why')
  })

  it('"Just found" stays on a row the latest run saw, and not beside a class that says otherwise', () => {
    const just = (cls) => classBadges(route('a', cls, { isNew: true })).map((b) => b.label)
    expect(just('found')).toEqual(['Just found'])
    expect(just('held')).toEqual(['Not checked this run', 'Just found'])
    expect(just('absent')).toEqual(['Not in latest search'])
    expect(just('closed')).toEqual(['Closed'])
  })

  it('old flags on a stored row are not read: the class decides', () => {
    expect(classBadges(route('a', 'found', { isClosed: true, closedAt: null, isAbsent: true }))).toEqual([])
  })

  it('a stored row the route does not hold says so; a hand-entered one has no badge', () => {
    expect(classBadges(stored('s')).map((b) => b.label)).toEqual(['Saved in this browser'])
    expect(classBadges(stored('m', { manualEntry: true }))).toEqual([])
  })

  it('outside a composed list the row is as it was: no class badge and no reason', () => {
    viewport(true)
    const html = table([stored('s', { isClosed: true, reason: 'not shown' })], { classView: false })
    expect(html).toContain('Closed')
    expect(html).not.toContain('Saved in this browser')
    expect(html).not.toContain('not shown')
  })

  it('Not scored on a row with none, and the stored score on an absent row stays', () => {
    viewport(true)
    const html = table([serverOnly('a', 'absent'), { ...route('b', 'absent'), matchScore: 77, matchLabel: 'Strong', status: 'new' }])
    expect(html).toContain('Not scored')
    expect(html).toContain('77')
  })
})

describe('a filtered row is read-only', () => {
  it.each([[true], [false]])('no checkbox, a link, and Add job (wide: %s)', (wide) => {
    viewport(wide)
    const html = table([filtered()])
    expect(html).not.toContain('type="checkbox"')
    expect(html).toContain('href="https://x.example/f"')
    expect(html).toContain('Open ad')
    expect(html).toContain('Add job')
    expect(html).not.toContain('aria-label="Save"')
    expect(html).not.toContain('cursor-pointer')
  })

  it('and with nothing selectable no select-all is offered', () => {
    viewport(true)
    expect(table([filtered()])).not.toContain('Select all')
  })

  it('Add job hands the row to the screen, and the form starts from title, company and address only', () => {
    const source = fs.readFileSync('src/components/jobs/JobDiscoveryScreen.jsx', 'utf-8')
    expect(source).toContain('setAddInitial({ title: row.title, company: row.company, jobUrl: row.jobUrl })')
    expect(source).toContain('<AddJobDialog initial={addInitial}')
    expect(source).toContain('setAddInitial(null); setAddJobOpen(true)')
  })

  it('the form is a new job, prefilled, not an edit', () => {
    const html = renderToStaticMarkup(createElement(AddJobDialog, { initial: { title: 'Chef', company: 'Beta', jobUrl: 'https://y.example/1', notes: 'NOT-TAKEN', location: 'NOT-TAKEN' }, onClose() {}, onSaved() {} }))
    expect(html).toContain('value="Chef"')
    expect(html).toContain('value="Beta"')
    expect(html).toContain('value="https://y.example/1"')
    expect(html).not.toContain('NOT-TAKEN')
    expect(html).toContain('Add job')
    expect(html).not.toMatch(/Edit job/)
  })

  it('without it the form is empty, and `job` still means edit', () => {
    const empty = renderToStaticMarkup(createElement(AddJobDialog, { onClose() {}, onSaved() {} }))
    expect(empty).not.toContain('value="Chef"')
    const editing = renderToStaticMarkup(createElement(AddJobDialog, { job: stored('m', { manualEntry: true, title: 'Mine' }), initial: { title: 'Chef' }, onClose() {}, onSaved() {} }))
    expect(editing).toContain('value="Mine"')
    expect(editing).not.toContain('value="Chef"')
  })
})

describe('a server-only row until Keep this ad', () => {
  it('its actions are disabled, and say why', () => {
    viewport(true)
    const html = table([serverOnly('a', 'absent')])
    expect(SERVER_ONLY_NOTE).toBe('Keep this ad is coming in the next update')
    expect(html.match(/<button[^>]*aria-label="Save[^>]*>/)[0]).toContain(`title="${SERVER_ONLY_NOTE}"`)
    expect(html.match(/<button[^>]*aria-label="Save[^>]*>/)[0]).toContain('disabled=""')
    expect(html.match(/<input[^>]*type="checkbox"[^>]*>/g).at(-1)).toContain('disabled=""')
  })

  it('in cards too', () => {
    viewport(false)
    const html = table([serverOnly('a', 'absent')])
    expect(html.match(/<button[^>]*aria-label="Save[^>]*>/)[0]).toContain('disabled=""')
    expect(html.match(/<input[^>]*type="checkbox"[^>]*>/)[0]).toContain('disabled=""')
    expect(html.match(/<input[^>]*type="checkbox"[^>]*>/)[0]).toContain(`title="${SERVER_ONLY_NOTE}"`)
  })

  it('the tailoring tools of a card are for stored rows only: they would write to the row', () => {
    viewport(false)
    expect(table([stored('s', { matchScore: 70 })])).toContain('TAILOR-ACTIONS')
    expect(table([stored('s', { matchScore: 70, jobId: 's', title: 'x' }), serverOnly('a', 'absent')]).split('TAILOR-ACTIONS')).toHaveLength(2)
  })

  it('a stored row keeps its working actions', () => {
    viewport(true)
    const save = table([stored('s')]).match(/<button[^>]*aria-label="Save"[^>]*>/)[0]
    expect(save).not.toContain('disabled=""')
  })

  it('select all counts what it can reach and says so', () => {
    viewport(true)
    const html = table([stored('s'), serverOnly('a', 'absent'), filtered()])
    expect(html).toContain('Select all 1 filtered jobs saved in this browser')
    expect(html).toContain('aria-label="Select all 1 filtered jobs saved in this browser, not only the 3 shown"')
  })

  it('the stored rows selected make "all selected", though others are in the list', () => {
    viewport(true)
    expect(table([stored('s'), serverOnly('a', 'absent')], { selectedJobIds: new Set(['s']) })).toContain('Clear selection of all 1 filtered jobs saved in this browser')
  })

  it('the drawer shows it and stores nothing: no store write in its code, and the note', () => {
    const source = fs.readFileSync('src/components/jobs/JobDetailDrawer.jsx', 'utf-8')
    expect(source).not.toMatch(/addJobIfAbsent|saveJobs|createJob/)
    expect(source).toContain('const readOnly = Boolean(row?.serverOnly) && !stored')
    expect(source).toContain('{readOnly && <p')
    expect(source).toContain('{SERVER_ONLY_NOTE}')
    expect(source).toContain('(!readOnly || applicationsForJob(store, jobId).length > 0)')
  })
})

describe('notices', () => {
  const base = { mode: 'active', status: 'ready', error: null, meta: { filteredFile: 'ok' }, rows: [], copies: { state: 'collapsed', hidden: 0 }, hasServerOnly: false }
  const texts = (input) => listNotices({ ...base, ...input }).map((n) => n.text)

  it('nothing to say on a whole list', () => {
    expect(listNotices(base)).toEqual([])
    expect(listNotices({ ...base, mode: 'all' })).toEqual([])
  })

  it('a 503 or a network failure says so and offers another try, keeping the list', () => {
    const [notice] = listNotices({ ...base, status: 'error', error: 'cannot be read', rows: null })
    expect(notice.kind).toBe('error')
    expect(notice.retry).toBe(true)
    expect(notice.text).toContain('cannot be read')
    expect(notice.text).toContain('Showing what is saved in this browser; nothing was changed')
  })

  it('a later failure says the last list is what is showing', () => {
    expect(texts({ status: 'error', error: 'x' })[0]).toContain('Showing the last list loaded')
  })

  it.each([['missing'], ['unreadable'], [undefined]])('filteredFile %s: All says it is incomplete, Active does not need to', (filteredFile) => {
    expect(INCOMPLETE_FILTERED).toBe('This list is incomplete: filtered ads could not be read')
    expect(texts({ mode: 'all', meta: { filteredFile } })).toEqual([INCOMPLETE_FILTERED])
    expect(texts({ mode: 'active', meta: { filteredFile } })).toEqual([])
  })

  it('no meta at all is not presented as complete', () => {
    expect(texts({ mode: 'all', meta: null })).toEqual([INCOMPLETE_FILTERED])
  })

  it('a 503 in All says it is incomplete', () => {
    const notices = texts({ mode: 'all', status: 'error', error: 'x', rows: null, meta: null })
    expect(notices).toContain(INCOMPLETE_ROUTE)
  })

  it('still loading in All says so', () => {
    expect(texts({ mode: 'all', status: 'loading', rows: null, meta: null })[0]).toContain('This list is incomplete until it arrives')
  })

  it('copies not collapsed are noted, a failure as an error', () => {
    expect(texts({ copies: { state: 'waiting', hidden: 0 } })[0]).toContain('until your applications have loaded')
    const [failed] = listNotices({ ...base, copies: { state: 'failed', hidden: 0 } })
    expect(failed.kind).toBe('error')
    expect(failed.text).toContain('Your applications could not be loaded')
  })

  it('server-only rows say why they are read-only', () => {
    expect(texts({ hasServerOnly: true })[0]).toContain(SERVER_ONLY_NOTE)
  })
})

describe('the controls', () => {
  const controls = (props = {}) => renderToStaticMarkup(createElement(JobListControls, { mode: 'active', onMode() {}, classes: new Set(), onClasses() {}, recent: false, onRecent() {}, ...props }))

  it('the toggle says which is on, and Active shows no All controls', () => {
    const html = controls()
    expect(html).toMatch(/aria-pressed="true"[^>]*>Active/)
    expect(html).toMatch(/aria-pressed="false"[^>]*>All/)
    expect(html).not.toContain('Seen in the last 14 days')
    expect(html).not.toContain('<fieldset')
  })

  it('All shows the class filter and the 14-day filter', () => {
    const html = controls({ mode: 'all', options: classOptions([route('a', 'absent')]), classes: new Set(['absent']) })
    expect(html).toContain('Seen in the last 14 days')
    expect(html).toContain('Not in latest search (1)')
    expect(html).toContain('Saved in this browser (0)')
    expect(html).toContain('checked=""')
  })

  it('notices show, an error with its try-again', () => {
    const html = controls({ notices: [{ kind: 'error', text: 'Broke', retry: true }, { kind: 'info', text: 'Note' }] })
    expect(html).toContain('Broke')
    expect(html).toContain('role="alert"')
    expect(html).toContain('Try again')
    expect(html).toContain('Note')
  })
})

describe('the screen', () => {
  const screen = fs.readFileSync('src/components/jobs/JobDiscoveryScreen.jsx', 'utf-8')

  it('the new controls are plain state, outside what is saved', () => {
    for (const line of ["useState('active')", 'const [listClasses, setListClasses] = useState(() => new Set())', 'const [seenRecentlyOnly, setSeenRecentlyOnly] = useState(false)']) expect(screen).toContain(line)
    expect(screen).not.toMatch(/updateFilters\([^)]*(listMode|listClasses|seenRecently)/)
    const storage = fs.readFileSync('src/modules/jobs/jobStorage.js', 'utf-8')
    expect(storage).not.toMatch(/listMode|listClasses|serverOnly/)
  })

  it('no new module writes or names storage', () => {
    for (const file of ['src/modules/jobs/jobListView.js', 'src/components/jobs/JobListControls.jsx']) {
      const code = fs.readFileSync(file, 'utf-8')
      for (const word of ['localStorage', 'sessionStorage', 'saveJobs', 'importJobsFromFile', 'patchJob', 'addJobIfAbsent']) expect(code).not.toContain(word)
    }
  })

  it('what is saved is what it always was: the state, never a composed list', () => {
    expect(screen).toContain('saveJobs(state)')
    expect(screen).not.toMatch(/setState\([^)]*(composed|shownRows|baseRows|filteredJobs)/)
    expect(screen).not.toMatch(/importJobsFromFile\([^)]*(composed|allAds)/)
  })

  it('the metrics keep their inputs', () => {
    expect(screen).toContain('...computeJobStats(viewJobs)')
    expect(screen).toContain('syncPipelineCounts(health, state.jobs)')
    expect(screen).toContain('() => overlayTracking(state.jobs,')
    expect(screen).toContain('jobs: listed,')
    expect(screen).toContain('downloadJobsCsv(listed)')
    expect(screen).toContain('jobs={state.jobs}')
  })

  it('only the list count and the filter options read the composed list', () => {
    expect(screen).toContain('{filteredJobs.length} of {baseRows.length} jobs shown')
    expect(screen).toContain('getUniqueSites(baseRows)')
    expect(screen).toContain('getUniqueProviders(baseRows)')
    expect(screen).toContain('jobs={baseRows}')
  })

  it('an API that is not there, or demo data, keeps today\'s list with no toggle', () => {
    expect(screen).toContain('const routeEnabled = pipelineApiAvailable && !demoMode')
    expect(screen).toContain('{routeEnabled && (\n                <JobListControls')
    expect(screen).toContain('const useComposed = routeEnabled && (allAds.rows !== null || listMode === \'all\')')
  })

  it('Show off-list has no job in a composed list: it is off, disabled and says why', () => {
    expect(screen).toContain('const filtersShown = useComposed ? { ...effectiveFilters, showOffList: false } : effectiveFilters')
    expect(screen).toContain('offListDisabledNote={useComposed ? OFF_LIST_NOTE : null}')
    const filters = (props) => renderToStaticMarkup(createElement(JobFilters, { filters: { ...getDefaultJobsState().filters, ...props.filters }, sites: [], providers: [], jobs: [], onChange() {}, ...props }))
    const box = (html) => html.split('Show jobs absent from current results')[0].match(/<input[^>]*type="checkbox"[^>]*>/g).at(-1)
    expect(box(filters({ offListDisabledNote: 'Already in' }))).toContain('disabled=""')
    expect(box(filters({}))).not.toContain('disabled=""')
    expect(filters({ offListDisabledNote: 'Already in' })).toContain('title="Already in"')
  })

  it('the route is asked each time the screen opens, not only the first', () => {
    expect(fs.readFileSync('src/modules/jobs/useAllAds.js', 'utf-8')).toContain('if (enabled) loader.refetch()')
  })

  it('Export says it covers saved rows only', () => {
    expect(EXPORT_NOTE).toContain('saved in this browser only')
    expect(screen).toContain('title={EXPORT_NOTE}')
    expect(screen).toContain('JSON, saved rows')
    expect(screen).toContain('CSV, saved rows')
  })

  it('search says what it covers, in All only', () => {
    expect(ALL_SEARCH_NOTE).toContain('does not match the ad text')
    expect(screen).toContain("searchNote={useComposed && listMode === 'all' ? ALL_SEARCH_NOTE : null}")
  })

  it('the route is asked again after any import, and after a Re-scrape however it ended', () => {
    expect(screen).toContain('if (lastImportedAt.current === state.importedAt) return')
    expect(screen).toContain('if (routeEnabled) refetchAllAds() // the ledger may have moved')
  })
})

describe('metrics: server-only rows cannot move them', () => {
  it('the average fit score and the other numbers read the stored rows, whatever the route holds', () => {
    const jobs = [stored('a', { matchScore: 80 }), stored('b', { matchScore: 60 })]
    const before = computeJobStats(jobs)
    const { all, active } = composeJobList({ stored: jobs, server: [route('a'), route('b'), ...Array.from({ length: 50 }, (_, i) => route(`n${i}`, 'absent'))], applications: READY, reference: NOW })
    expect(all).toHaveLength(52)
    expect(active.length).toBeGreaterThan(2)
    expect(computeJobStats(jobs)).toEqual(before)
    expect(before.total ?? jobs.length).toBe(2)
    // what would happen if they were fed in: the guard above and the source check together keep this from being so
    expect(computeJobStats(all)).not.toEqual(before)
  })
})

describe('storage', () => {
  it('choosing a mode, a class or the 14 days touches no storage', () => {
    const touch = vi.fn(() => { throw new Error('storage was touched') })
    vi.stubGlobal('localStorage', { getItem: touch, setItem: touch, removeItem: touch })
    const rows = composeJobList({ stored: [stored('s')], server: [route('s'), route('a', 'absent')], applications: READY, reference: NOW }).all
    classOptions(rows)
    applyAllControls(rows, { classes: new Set(['absent']), recent: true, reference: NOW })
    filterComposed(rows, { searchText: 'x' })
    listNotices({ mode: 'all', status: 'ready', meta: {}, rows })
    expect(touch).not.toHaveBeenCalled()
  })

  it('the saved payload is byte-identical however the list is viewed', () => {
    const saved = new Map()
    const storage = { setItem: (key, value) => saved.set(key, value) }
    const state = { ...getDefaultJobsState(), jobs: [stored('s', { status: 'saved', outreach: { contacts: [{ name: 'x' }] } })] }
    saveJobs(state, storage)
    const [[key, first]] = saved
    const { all } = composeJobList({ stored: state.jobs, server: [route('s', 'absent'), route('n', 'absent')], applications: READY, reference: NOW })
    applyAllControls(all, { classes: new Set(['absent']), reference: NOW })
    saveJobs(state, storage)
    expect(saved.get(key)).toBe(first)
    expect(first).not.toMatch(/"class"|"serverOnly"|"reason"/)
  })

  it('an existing filter keeps its persistence, and the jobs stay as they were', () => {
    const saved = new Map()
    const storage = { setItem: (key, value) => saved.set(key, value) }
    const state = { ...getDefaultJobsState(), jobs: [stored('s')] }
    saveJobs(updateFilters(state, { searchText: 'pm' }), storage)
    const body = JSON.parse([...saved.values()][0])
    expect(body.filters.searchText).toBe('pm')
    expect(body.jobs).toEqual(state.jobs)
  })
})

describe('the class filter list is complete', () => {
  it('ten entries, one of them for display only', () => {
    expect(CLASS_FILTERS).toHaveLength(10)
    expect(CLASS_FILTERS).toContain(SAVED_IN_BROWSER)
  })
})
