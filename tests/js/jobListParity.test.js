// Parity of the Jobs list between the browser's way and the server's (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P1).
//
// One fixture builds the browser input (`importJobsFromFile` + the route's rows + the job-state doc + the application store) and the server input
// (the same data after a JSON round trip, deep-frozen so nothing may write to it). A seeded property test then draws random filter, mode, class and sort
// combinations and asserts that `queryJobList` (the server's function) gives the same ids, in the same order, on the first page and on every next page,
// and the same counts (computeJobStats, tier counts, class and facet counts), as the screen's own pipeline written out below, step for step.
//
// The screen's pipeline is repeated here on purpose: it is the reference that P3 replaces by a call to `queryJobList`, and until then this test is what
// holds the two together. Known and accepted difference: rows only the browser has (an `offList` row, a hand-entered job not yet synced) are not in the
// fixture, because the server cannot hold them (plan P5, Orphans).
import { describe, expect, it } from 'vitest'
import { composeJobList } from '../../src/modules/jobs/allAds.js'
import { applyAllControls, classOptions, filterComposed } from '../../src/modules/jobs/jobListView.js'
import { countByValue, getCompanyOptions, getUniqueProviders, getUniqueSites, hiddenAsNotOnBoard } from '../../src/modules/jobs/jobFilters.js'
import { computeJobStats } from '../../src/modules/jobs/jobStats.js'
import { tierCounts, tierIndexOf } from '../../src/modules/jobs/fitTier.js'
import { DEFAULT_SORT, SORT_COLUMNS, blockedLast, closedLast, defaultOrder, neutralCompare, neutralOrder, notReadFirst, orderDefault } from '../../src/modules/jobs/jobTableModel.js'
import { withServerState } from '../../src/modules/jobs/jobStateClient.js'
import { JOB_STATUSES, importJobsFromFile, jobMatchKey } from '../../src/modules/jobs/jobStorage.js'
import { PRIORITIES, hasMatchScores } from '../../src/modules/jobs/matchScore.js'
import { dayOf, deadlineSortValue } from '../../src/modules/jobs/jobDeadline.js'
import { overlayTracking, trackerStats } from '../../src/modules/applications/trackingView.js'
import { appliedJobIds, statusFilterOptions } from '../../src/modules/applications/appliedFilter.js'
import { queryJobList } from '../../src/modules/jobs/jobListQuery.js'

const NOW = Date.parse('2026-11-20T12:00:00Z')
const DAY = 86400000
const iso = (offsetMs) => new Date(NOW - offsetMs).toISOString()

// --- a seeded generator --------------------------------------------------------------------------------------------------------------------------
function rng(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
const picker = (rand) => ({
  one: (list) => list[Math.floor(rand() * list.length)],
  chance: (p) => rand() < p,
  int: (lo, hi) => lo + Math.floor(rand() * (hi - lo + 1)),
  some: (list, p) => list.filter(() => rand() < p),
})

const TITLES = ['Senior Product Manager', 'Product Owner', 'Technical Program Manager', 'Delivery Lead', 'Data Analyst', 'Engineering Manager', 'product manager']
const COMPANIES = ['Acme', 'Globex GmbH', 'Initech', 'Umbrella Ltd', 'acme', 'Stark Industries']
const LOCATIONS = ['Remote', 'Niš, Serbia', 'Belgrade, Serbia', 'Berlin, Germany', 'Remote, EU', 'Austin, TX']
const PROVIDERS = ['jobspy', 'greenhouse', 'lever', 'infostud', 'workable']
const SITES = ['linkedin', 'indeed', 'glassdoor', 'infostud']
const CLASSES = ['found', 'held', 'absent', 'closed', 'older_key', 'stale', 'unclassified']
const WORDS = ['payments', 'roadmap', 'sponsorship', 'kubernetes', 'discovery', 'remote', 'stakeholders']

/** The fixture: scored rows, the route's rows, the job-state doc and the application store, all plain data. */
function fixture(seed, size = 70) {
  const rand = rng(seed)
  const p = picker(rand)
  const scored = []
  for (let i = 0; i < size; i += 1) {
    const jobId = `j${String(i).padStart(3, '0')}`
    const read = !p.chance(0.1)
    const score = read && !p.chance(0.15) ? p.int(20, 95) : null
    scored.push({
      jobId, title: p.one(TITLES), company: p.one(COMPANIES), location: p.one(LOCATIONS), site: p.one(SITES), provider: p.one(PROVIDERS),
      jobUrl: `https://x.example/${jobId}`, description: `${p.one(WORDS)} ${p.one(WORDS)} ad ${jobId}`, isRemote: p.chance(0.5),
      matchScore: score, matchLabel: score === null ? 'Not read' : 'Good', dataStatus: read ? 'ok' : 'not_read',
      priority: p.one(['P1', 'P2', 'P3', 'Reject']), applyRecommendation: p.one(['Apply', 'Maybe', 'Skip']),
      blockedBy: p.chance(0.1) ? ['no_sponsorship'] : [],
      eligibility: p.chance(0.5) ? { state: p.one(['authorized', 'needs_sponsorship', 'unknown']) } : undefined,
      datePosted: p.chance(0.7) ? iso(p.int(0, 40) * DAY) : null, firstSeen: iso(p.int(1, 60) * DAY),
      isClosed: p.chance(0.1), isAbsent: p.chance(0.08),
      salaryMonthlyEur: p.chance(0.4) ? { min: p.int(1, 40) * 100, max: p.int(41, 90) * 100 } : undefined,
      engineCoverage: p.chance(0.5) ? { status: p.one(['not_evaluated', 'answered']) } : undefined,
    })
  }
  const file = { meta: { generatedAt: iso(0) }, jobs: scored }
  const route = scored.map((row, i) => {
    const cls = p.one(CLASSES)
    return {
      jobId: row.jobId, title: row.title, company: row.company, location: row.location, jobUrl: row.jobUrl, provider: row.provider, site: row.site, isRemote: row.isRemote,
      datePosted: row.datePosted, salary: null, expiresAt: null, firstSeen: row.firstSeen, lastSeen: iso(p.int(0, 30) * DAY),
      closedAt: cls === 'closed' ? iso(DAY) : null, absentSince: cls === 'absent' ? iso(2 * DAY) : null, class: cls, reason: `why ${cls} ${i}`, reasonCode: null, from: 'ledger',
      copyGroup: p.chance(0.2) ? `g${p.int(0, 6)}` : null, matchScore: null,
    }
  })
  for (let i = 0; i < 25; i += 1) { // ads the ledger knows and no scored row holds
    const jobId = `s${String(i).padStart(3, '0')}`
    const cls = p.one(CLASSES)
    route.push({
      jobId, title: p.one(TITLES), company: p.one(COMPANIES), location: p.one(LOCATIONS), jobUrl: `https://y.example/${jobId}`, provider: p.one(PROVIDERS), site: p.one(SITES), isRemote: p.chance(0.5),
      datePosted: p.chance(0.5) ? iso(p.int(0, 40) * DAY) : null, salary: null, expiresAt: null, firstSeen: iso(p.int(10, 80) * DAY), lastSeen: iso(p.int(0, 45) * DAY),
      closedAt: cls === 'closed' ? iso(DAY) : null, absentSince: cls === 'absent' ? iso(2 * DAY) : null, class: cls, reason: `why ${cls}`, reasonCode: null, from: 'ledger',
      copyGroup: p.chance(0.2) ? `g${p.int(0, 6)}` : null, matchScore: null,
    })
  }
  const stored = importJobsFromFile(file, null).jobs
  const doc = { version: 1, updatedAt: iso(0), jobs: {} }
  for (const job of stored) {
    if (p.chance(0.3)) doc.jobs[jobMatchKey(job)] = { jobId: job.jobId, status: p.one(['saved', 'rejected', 'new']), statusAt: iso(DAY), keep: p.chance(0.3) }
  }
  const applications = {}
  for (const jobId of p.some([...scored.map((r) => r.jobId), 's001', 's002', 's003'], 0.12)) {
    applications[`a-${jobId}`] = {
      id: `a-${jobId}`, schemaVersion: 1, createdAt: iso(5 * DAY), posting: { jobId, title: `T ${jobId}`, company: 'Acme', capturedAt: iso(5 * DAY) },
      attempt: { channel: 'company_site', channelDetail: '', applicationUrl: '', appliedDate: '2026-11-03', cv: null }, events: [],
    }
  }
  return {
    stored,
    server: route,
    jobStateDoc: doc,
    applications: { status: 'ready', store: { applications }, settings: { stages: { work: [{ key: 'applied', label: 'Applied' }, { key: 'interview', label: 'Interview' }] } } },
  }
}

/** The server's copy of the input: JSON in and out, and frozen, so a write to it throws. */
function serverCopy(input) {
  const freeze = (value) => {
    if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value) }
    return value
  }
  return freeze(JSON.parse(JSON.stringify(input)))
}

// --- the screen's pipeline, as it was before the query existed -----------------------------------------------------------------------------------
function screenFiltered(input, query) {
  const { stored, server, jobStateDoc, applications } = input
  const store = applications.status === 'ready' ? applications.store : null
  const settings = applications.settings
  const composed = composeJobList({ stored, server, applications, reference: NOW })
  const rows = overlayTracking(withServerState(query.mode === 'all' ? composed.all : composed.active, jobStateDoc), store, settings)
    .map((row) => (row.serverOnly && row.applicationTracking ? { ...row, status: 'applied_manually' } : row))
  const shown = query.mode === 'all' ? applyAllControls(rows, { classes: new Set(query.classes), recent: query.recent, reference: NOW }) : rows
  const effective = query.mode === 'all' ? { ...query.filters, showNotOnBoard: true } : query.filters
  const filtered = filterComposed(shown, effective, { appliedJobIds: appliedJobIds(store) })
  return { composed, rows, shown, effective, filtered, store, settings }
}

const refDefaultOrder = (rows) => notReadFirst(closedLast(blockedLast(defaultOrder(rows))))
const collator = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true })

function randomQuery(p) {
  const filters = {}
  if (p.chance(0.3)) filters.searchText = p.one([...WORDS, 'manager', 'ACME', 'zzz', ' lead '])
  if (p.chance(0.2)) filters.provider = p.some(PROVIDERS, 0.4)
  if (p.chance(0.2)) filters.site = p.some(SITES, 0.4)
  if (p.chance(0.15)) filters.company = p.some(COMPANIES, 0.4)
  if (p.chance(0.2)) filters.location = p.one(['remote', 'serbia', 'ber'])
  if (p.chance(0.2)) filters.remoteOnly = true
  if (p.chance(0.15)) filters.hideNeedsVisa = true
  if (p.chance(0.2)) filters.hideNoLongerListed = true
  if (p.chance(0.15)) filters.showNotOnBoard = true
  if (p.chance(0.2)) filters.status = p.one(['new', 'saved', 'rejected', 'applied', 'applied_manually'])
  if (p.chance(0.15)) filters.priority = p.some(['P1', 'P2', 'P3'], 0.5)
  if (p.chance(0.15)) filters.minScore = p.one([40, 55, 70])
  if (p.chance(0.1)) filters.matchLabel = 'Good'
  const mode = p.one(['active', 'all'])
  const sort = p.one([null, DEFAULT_SORT, { key: 'tier', dir: 'asc' }, ...Object.keys(SORT_COLUMNS).flatMap((key) => [{ key, dir: 'asc' }, { key, dir: 'desc' }])])
  return {
    mode, filters, sort, classes: mode === 'all' && p.chance(0.5) ? p.some(CLASSES, 0.4) : [], recent: mode === 'all' && p.chance(0.3),
    limit: p.one([1, 3, 10, 25, 100]),
  }
}

describe('the default sort key is the table\'s default order, as one comparison', () => {
  it.each([1, 2, 3, 4, 5, 6])('seed %i: orderDefault equals notReadFirst(closedLast(blockedLast(defaultOrder(rows))))', (seed) => {
    const { stored, server } = fixture(seed * 101, 120)
    // route rows add closed rows and rows with no score; shuffle so the arrival order is not the answer
    const rand = rng(seed)
    const rows = [...stored, ...server.map((r) => ({ ...r, blockedBy: rand() < 0.1 ? ['x'] : [], isClosed: r.class === 'closed', matchScore: rand() < 0.5 ? Math.floor(rand() * 100) : null }))]
      .map((row) => ({ row, k: rand() })).sort((a, b) => a.k - b.k).map((x) => x.row)
    const ids = (list) => list.map((r) => r.jobId)
    expect(ids(orderDefault(rows))).toEqual(ids(refDefaultOrder(rows)))
  })
})

describe('the server\'s query gives what the screen works out, on every page', () => {
  it.each([11, 22, 33, 44])('seed %i: ids, order, pages and counts agree for 120 random queries', (seed) => {
    const rand = rng(seed * 7919)
    const p = picker(rand)
    const input = fixture(seed)
    const frozen = serverCopy(input)
    let nonEmpty = 0
    for (let n = 0; n < 120; n += 1) {
      const query = randomQuery(p)
      const ref = screenFiltered(input, query)
      const today = dayOf(NOW)
      const full = []
      let offset = 0
      let first = null
      for (;;) {
        const page = queryJobList({ ...frozen, reference: NOW, mode: query.mode, filters: query.filters, classes: query.classes, recent: query.recent, sort: query.sort, offset, limit: query.limit, today })
        first ??= page
        expect(page.total).toBe(ref.filtered.length)
        expect(page.rows.length).toBeLessThanOrEqual(query.limit)
        full.push(...page.rows)
        offset += query.limit
        if (offset >= page.total) break
      }
      const ids = full.map((r) => r.jobId)
      expect(new Set(ids).size).toBe(ids.length) // no ad on two pages
      expect([...ids].sort()).toEqual(ref.filtered.map((r) => r.jobId).sort()) // every ad on some page
      if (ids.length) nonEmpty += 1

      if (!query.sort || query.sort === DEFAULT_SORT) {
        expect(ids).toEqual(refDefaultOrder(ref.filtered).map((r) => r.jobId))
      } else {
        // a picked column: sorted by its value (empty last, either direction), ties in the neutral order
        const column = SORT_COLUMNS[query.sort.key]
        const value = query.sort.key === 'deadline' ? (r) => deadlineSortValue(r, today) : column.value
        const sign = query.sort.dir === 'desc' ? -1 : 1
        const empty = (v) => v === null || v === undefined || v === '' || (typeof v === 'number' && Number.isNaN(v))
        for (let i = 1; i < full.length; i += 1) {
          const a = value(full[i - 1])
          const b = value(full[i])
          if (empty(a) && !empty(b)) throw new Error(`an empty value before a value at ${i} (${query.sort.key})`)
          if (empty(a) || empty(b)) continue
          const order = column.type === 'number' ? a - b : collator.compare(String(a).trim(), String(b).trim())
          expect(sign * order).toBeLessThanOrEqual(0)
          if (order === 0) expect(neutralCompare(full[i - 1], full[i])).toBeLessThan(0)
        }
      }

      // counts: the screen's, from the same rows
      const viewJobs = overlayTracking(withServerState(input.stored, input.jobStateDoc), ref.store, ref.settings)
      const counts = first.counts
      expect(counts.stats).toEqual({ ...computeJobStats(viewJobs), ...trackerStats(ref.store, ref.settings) })
      expect(counts.tiers).toEqual(tierCounts(ref.filtered))
      expect(counts.classOptions).toEqual(query.mode === 'all' ? classOptions(ref.rows) : [])
      expect(counts.notOnBoardHidden).toBe(query.mode === 'active' ? ref.shown.filter((job) => hiddenAsNotOnBoard(job, ref.effective)).length : 0)
      expect(counts.copies).toEqual(ref.composed.copies)
      expect(counts.hasServerOnly).toBe(ref.rows.some((row) => row.serverOnly))
      expect(counts.facets).toEqual({
        hasScores: hasMatchScores(ref.rows), sites: getUniqueSites(ref.rows), providers: getUniqueProviders(ref.rows), companyOptions: getCompanyOptions(ref.rows),
        priorityCounts: countByValue(ref.rows, 'priority', PRIORITIES.filter((x) => x !== 'Reject')), statusOptions: statusFilterOptions(JOB_STATUSES, ref.rows, ref.store),
      })
    }
    expect(nonEmpty).toBeGreaterThan(40) // the draw is not all empty answers
  })

  it('the default order of a page never depends on the order the rows arrive in', () => {
    const input = fixture(5)
    const shuffled = { ...input, stored: [...input.stored].reverse(), server: [...input.server].reverse() }
    const ask = (i) => queryJobList({ ...i, reference: NOW, mode: 'all', filters: {}, offset: 0, limit: 500 }).rows.map((r) => r.jobId)
    expect(ask(shuffled)).toEqual(ask(input))
  })

  it('refuses a missing page size, a bad offset and an unknown mode instead of guessing', () => {
    const base = { ...fixture(6), reference: NOW, mode: 'active', filters: {}, offset: 0, limit: 10 }
    expect(() => queryJobList({ ...base, limit: undefined })).toThrow(TypeError)
    expect(() => queryJobList({ ...base, limit: 0 })).toThrow(TypeError)
    expect(() => queryJobList({ ...base, offset: -1 })).toThrow(TypeError)
    expect(() => queryJobList({ ...base, offset: 1.5 })).toThrow(TypeError)
    expect(() => queryJobList({ ...base, mode: 'every' })).toThrow(TypeError)
  })

  it('a page past the end is empty, and the total stays', () => {
    const input = fixture(7)
    const all = queryJobList({ ...input, reference: NOW, mode: 'all', filters: {}, offset: 0, limit: 1000 })
    const past = queryJobList({ ...input, reference: NOW, mode: 'all', filters: {}, offset: all.total + 5, limit: 10 })
    expect(past.rows).toEqual([])
    expect(past.total).toBe(all.total)
  })
})

describe('a picked column only changes the order of equal values, so the same ads come in the same order on a server and a browser', () => {
  it('the tier column in its default direction is the default order inside each tier', () => {
    const input = fixture(9)
    const ids = (sort) => queryJobList({ ...input, reference: NOW, mode: 'all', filters: {}, sort, offset: 0, limit: 1000 }).rows
    const tier = ids({ key: 'tier', dir: 'desc' })
    const index = (row) => tierIndexOf(row)
    // rows of one tier come in the neutral order
    for (let i = 1; i < tier.length; i += 1) {
      if (index(tier[i - 1]) === index(tier[i]) && index(tier[i]) !== null) expect(neutralCompare(tier[i - 1], tier[i])).toBeLessThan(0)
    }
    expect(neutralOrder(tier).length).toBe(tier.length)
  })
})
