// The merge and the two lists behind Active and All (slice S5e3a). Pure, plus the in-memory loader; nothing reaches a server or a store.
import fs from 'node:fs'
import { createElement } from 'react'
import { renderToString } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ACTIVE_WINDOW_MS, AD_FIELDS, ROUTE_FIELDS, classLabel, composeJobList, mergeRow } from '../../src/modules/jobs/allAds.js'
import { createAllAdsLoader, fetchAllAds, useAllAds } from '../../src/modules/jobs/useAllAds.js'

const NOW = Date.parse('2026-11-20T12:00:00.000Z')
const DAY = 24 * 60 * 60 * 1000
const ago = (ms) => new Date(NOW - ms).toISOString()
const READY = { status: 'ready', store: { applications: {} } }
const withApplications = (...jobIds) => ({
  status: 'ready',
  store: { applications: Object.fromEntries(jobIds.map((jobId, i) => [`a${i}`, { id: `a${i}`, posting: { jobId } }])) },
})

function route(jobId, cls = 'found', extra = {}) {
  return {
    jobId, title: `Ad ${jobId}`, company: 'Acme', location: 'Remote', jobUrl: `https://x.example/${jobId}`, provider: 'jobspy', site: 'linkedin', isRemote: true, datePosted: '2026-11-01',
    firstSeen: ago(30 * DAY), lastSeen: ago(DAY), closedAt: null, absentSince: null, class: cls, reason: `reason of ${jobId}`, reasonCode: null, from: 'ledger', copyGroup: null, matchScore: null, ...extra,
  }
}
const local = (jobId, extra = {}) => ({ jobId, title: `Stored ${jobId}`, company: 'Stored Co', location: 'Niš', jobUrl: `https://x.example/${jobId}`, status: 'new', ...extra })
const ids = (rows) => rows.map((row) => row.jobId)
const compose = (input) => composeJobList({ stored: [], server: [], applications: READY, reference: NOW, ...input })
const frozen = (value) => {
  if (value && typeof value === 'object') { Object.values(value).forEach(frozen); Object.freeze(value) }
  return value
}

describe('mergeRow: one test per row of the merge table', () => {
  it.each(['status', 'aiInsights', 'tailoredAssets', 'outreach'])('%s: local always', (field) => {
    const stored = local('a', { [field]: 'mine' })
    expect(mergeRow(stored, route('a', 'found', { [field]: 'from the route' }))[field]).toBe('mine')
  })

  it.each(['notes', 'extraLinks', 'sourceUrl', 'sourceChoice', 'createdAt'])('%s: local always', (field) => {
    expect(mergeRow(local('a', { [field]: 'mine' }), route('a', 'found', { [field]: 'from the route' }))[field]).toBe('mine')
  })

  it('tracking is not a field of the merge: what is stored stays and the route adds none', () => {
    expect(mergeRow(local('a'), route('a', 'found', { applicationTracking: { stage: 'x' } })).applicationTracking).toBeUndefined()
  })

  it.each(ROUTE_FIELDS)('%s: from the route always', (field) => {
    const merged = mergeRow(local('a', { [field]: 'stored value' }), route('a', 'absent', { [field]: 'route value' }))
    expect(merged[field]).toBe('route value')
  })

  it.each(ROUTE_FIELDS)('%s: a null from the route replaces the stored value too', (field) => {
    expect(mergeRow(local('a', { [field]: 'stored value' }), route('a', 'absent', { [field]: null }))[field]).toBeNull()
  })

  it('the route fields are the agreed ones', () => {
    expect(ROUTE_FIELDS).toEqual(['class', 'reason', 'reasonCode', 'from', 'copyGroup', 'firstSeen', 'lastSeen', 'closedAt', 'absentSince'])
    expect(AD_FIELDS).toEqual(['title', 'company', 'location', 'jobUrl', 'provider', 'site', 'isRemote', 'datePosted'])
  })

  it.each(AD_FIELDS)('%s: from the route when it has a value', (field) => {
    expect(mergeRow(local('a', { [field]: 'stored value' }), route('a', 'found', { [field]: 'route value' }))[field]).toBe('route value')
  })

  it.each(AD_FIELDS)('%s: the stored value when the route has none', (field) => {
    expect(mergeRow(local('a', { [field]: 'stored value' }), route('a', 'found', { [field]: null }))[field]).toBe('stored value')
  })

  it('isRemote false from the route is a value', () => {
    expect(mergeRow(local('a', { isRemote: true }), route('a', 'found', { isRemote: false })).isRemote).toBe(false)
  })

  it.each(['description', 'llmFacts', 'engineShadow', 'matchScore', 'matchLabel', 'priority', 'salaryMonthlyEur', 'workAuthorization'])('%s: local only', (field) => {
    const merged = mergeRow(local('a', { [field]: 'stored value' }), route('a', 'absent', { [field]: null }))
    expect(merged[field]).toBe('stored value')
  })

  it('the route never overwrites a stored score, on an absent row too', () => {
    const merged = mergeRow(local('a', { matchScore: 77, matchLabel: 'Strong', priority: 'P1' }), route('a', 'absent', { matchScore: null }))
    expect([merged.matchScore, merged.matchLabel, merged.priority]).toEqual([77, 'Strong', 'P1'])
  })

  it('a hand-entered row is entirely local and takes no route field', () => {
    const stored = local('m', { manualEntry: true, title: 'By hand', jobUrl: 'https://own.example/1' })
    expect(mergeRow(stored, route('m', 'closed'))).toEqual(stored)
  })

  it('the stored jobId stays when the rows matched by address', () => {
    expect(mergeRow(local('old'), route('new')).jobId).toBe('old')
  })

  it('a server-only row is the route row, Unreviewed and marked, with no score', () => {
    const row = mergeRow(null, route('a', 'absent'))
    expect([row.status, row.serverOnly, row.matchScore, row.class]).toEqual(['new', true, null, 'absent'])
  })

  it('a stored row alone stays as it is, with no class', () => {
    expect(mergeRow(local('a'), null)).toEqual(local('a'))
    expect(mergeRow(null, null)).toBeNull()
  })

  it('changes neither input', () => {
    const stored = frozen(local('a', { outreach: { contacts: [] } }))
    const row = frozen(route('a', 'absent'))
    expect(() => { mergeRow(stored, row); mergeRow(null, row); mergeRow(stored, null) }).not.toThrow()
  })
})

describe('Active: each class', () => {
  const server = ['found', 'held', 'absent', 'closed', 'older_key', 'stale', 'filtered', 'filtered_incomplete', 'unclassified'].map((cls) => route(cls, cls))

  it('found, held and absent seen recently are in Active; all nine are in All', () => {
    const { active, all } = compose({ server })
    expect(ids(active).sort()).toEqual(['absent', 'found', 'held'])
    expect(all).toHaveLength(9)
  })

  it('a hand-entered row is in Active with no route row, even marked off the list', () => {
    expect(ids(compose({ stored: [local('m', { manualEntry: true })] }).active)).toEqual(['m'])
    expect(ids(compose({ stored: [local('m', { manualEntry: true, offList: true })] }).active)).toEqual(['m'])
  })

  it('a stored row the route does not hold, off the list, with an application on it', () => {
    expect(ids(compose({ stored: [local('off', { offList: true })], applications: withApplications('off') }).active)).toEqual(['off'])
  })

  it('a hand-entered row is never collapsed with anything', () => {
    const stored = [local('m', { manualEntry: true }), local('n', { manualEntry: true })]
    const server = [route('m', 'found', { copyGroup: 'g' }), route('n', 'found', { copyGroup: 'g' })]
    expect(ids(compose({ stored, server }).active)).toEqual(['m', 'n'])
  })

  it.each(['older_key', 'stale', 'filtered', 'filtered_incomplete', 'unclassified'])('%s with a status from the owner is in Active', (cls) => {
    expect(ids(compose({ stored: [local(cls, { status: 'saved' })], server: [route(cls, cls)] }).active)).toEqual([cls])
  })

  it.each(['older_key', 'stale', 'filtered', 'filtered_incomplete', 'unclassified'])('%s with an application is in Active', (cls) => {
    expect(ids(compose({ server: [route(cls, cls)], applications: withApplications(cls) }).active)).toEqual([cls])
  })

  it('a voided application is still work on that job', () => {
    const applications = { status: 'ready', store: { applications: { x: { id: 'x', voided: true, posting: { jobId: 's' } } } } }
    expect(ids(compose({ server: [route('s', 'stale')], applications }).active)).toEqual(['s'])
  })

  it.each([
    ['a status', { status: 'saved' }], ['a rejected triage', { status: 'rejected' }], ['Keep this ad', { keptByUser: true }], ['AI insights', { aiInsights: { summary: 'x' } }],
  ])('a closed ad leaves Active with %s, and stays in All', (_name, work) => {
    const { active, all } = compose({ stored: [local('c', work)], server: [route('c', 'closed')] })
    expect(active).toEqual([])
    expect(ids(all)).toEqual(['c'])
    expect(all[0]).toMatchObject(work)
  })

  it('a closed ad with an application leaves Active and stays in All', () => {
    const { active, all } = compose({ server: [route('c', 'closed')], applications: withApplications('c') })
    expect(active).toEqual([])
    expect(ids(all)).toEqual(['c'])
  })

  it('a stored row marked closed that the route does not hold leaves Active', () => {
    expect(compose({ stored: [local('c', { isClosed: true, status: 'saved' })] }).active).toEqual([])
  })

  it('a stale ad with the owner\'s work stays in Active', () => {
    expect(ids(compose({ stored: [local('s', { keptByUser: true })], server: [route('s', 'stale')] }).active)).toEqual(['s'])
  })

  it('the live copy of an ad applied to under a closed copy is marked, and shown', () => {
    const server = [route('old', 'closed', { copyGroup: 'g' }), route('new', 'found', { copyGroup: 'g' })]
    const { active } = compose({ server, applications: withApplications('old') })
    expect(ids(active)).toEqual(['new'])
    expect(active[0].appliedOtherCopy).toBe(true)
  })

  it('the applied copy itself is not marked', () => {
    const { active } = compose({ server: [route('a', 'found', { copyGroup: 'g' })], applications: withApplications('a') })
    expect(active[0].appliedOtherCopy).toBeUndefined()
  })

  it.each([
    [{ aiInsights: { summary: 'x' } }], [{ tailoredAssets: { cv: 'x' } }], [{ outreach: { contacts: [{ name: 'x' }] } }],
  ])('other work counts: %j', (work) => {
    expect(ids(compose({ stored: [local('c', work)], server: [route('c', 'stale')] }).active)).toEqual(['c'])
  })

  it('a closed row with no work is only in All, stored or not', () => {
    const { active, all } = compose({ stored: [local('c')], server: [route('c', 'closed'), route('d', 'closed')] })
    expect(active).toEqual([])
    expect(ids(all).sort()).toEqual(['c', 'd'])
  })

  it('an application on the route id counts when the row is stored under another id', () => {
    const stored = [local('old', { jobUrl: 'https://x.example/same' })]
    const { active } = compose({ stored, server: [route('new', 'stale', { jobUrl: 'https://x.example/same' })], applications: withApplications('new') })
    expect(ids(active)).toEqual(['old'])
  })

  it('a stored row the route does not hold: in Active unless it is off the list with no work', () => {
    const stored = [local('kept'), local('off', { offList: true }), local('off-worked', { offList: true, status: 'saved' })]
    expect(ids(compose({ stored }).active)).toEqual(['kept', 'off-worked'])
  })
})

describe('the 14-day window: a visibility rule on lastSeen, against the time passed in', () => {
  const absent = (lastSeen) => route('a', 'absent', { lastSeen })
  const inActive = (lastSeen, reference = NOW) => compose({ server: [absent(lastSeen)], reference }).active.length === 1

  it('is 14 days', () => expect(ACTIVE_WINDOW_MS).toBe(14 * DAY))
  it('exactly 14 days is in', () => expect(inActive(ago(14 * DAY))).toBe(true))
  it('14 days + 1 second is out', () => expect(inActive(ago(14 * DAY + 1000))).toBe(false))
  it('14 days - 1 second is in', () => expect(inActive(ago(14 * DAY - 1000))).toBe(true))
  it('a time with microseconds, as Python writes it, is read', () => {
    expect(inActive('2026-11-06T12:00:00.000000+00:00')).toBe(true)
    expect(inActive('2026-11-06T11:59:59.000000+00:00')).toBe(false)
  })
  it.each([null, undefined, '', 'not a date'])('no usable lastSeen (%s) is out, and still in All', (lastSeen) => {
    expect(inActive(lastSeen)).toBe(false)
    expect(compose({ server: [absent(lastSeen)] }).all).toHaveLength(1)
  })
  it('a date from the future (another clock) is in', () => expect(inActive(new Date(NOW + DAY).toISOString())).toBe(true))

  it('a date change while the screen is open: the same inputs, a later reference, no import', () => {
    const inputs = frozen({ stored: [local('s', { status: 'new' })], server: [route('s', 'absent', { lastSeen: ago(14 * DAY) }), route('n', 'absent', { lastSeen: ago(13 * DAY) })], applications: READY })
    const today = composeJobList({ ...inputs, reference: NOW })
    const tomorrow = composeJobList({ ...inputs, reference: NOW + DAY })
    const nextWeek = composeJobList({ ...inputs, reference: NOW + 7 * DAY })
    expect(ids(today.active)).toEqual(['s', 'n'])
    expect(ids(tomorrow.active)).toEqual(['n'])
    expect(nextWeek.active).toEqual([])
    expect(ids(nextWeek.all)).toEqual(['s', 'n'])
    expect(ids(composeJobList({ ...inputs, reference: NOW }).active)).toEqual(['s', 'n'])
  })

  it('a row with work stays past the window', () => {
    expect(ids(compose({ stored: [local('a', { status: 'saved' })], server: [absent(ago(90 * DAY))] }).active)).toEqual(['a'])
  })

  it.each([new Date(NOW), NOW, new Date(NOW).toISOString()])('the reference may be %s', (reference) => {
    expect(compose({ server: [absent(ago(DAY))], reference }).active).toHaveLength(1)
  })

  it.each([undefined, null, 'soon', NaN])('with no usable reference (%s) it refuses rather than guess', (reference) => {
    expect(() => composeJobList({ server: [], applications: READY, reference })).toThrow(TypeError)
  })
})

describe('cross-post copies', () => {
  const group = (jobId, cls, extra = {}) => route(jobId, cls, { copyGroup: 'tc:pm|acme', ...extra })
  const activeIds = (input) => ids(compose(input).active).sort()

  it('one row per ad: found before held before absent', () => {
    expect(activeIds({ server: [group('z', 'absent'), group('y', 'held'), group('x', 'found')] })).toEqual(['x'])
    expect(activeIds({ server: [group('z', 'absent'), group('y', 'held')] })).toEqual(['y'])
  })

  it('in one class the newest lastSeen, then the smallest jobId', () => {
    expect(activeIds({ server: [group('a', 'absent', { lastSeen: ago(3 * DAY) }), group('b', 'absent', { lastSeen: ago(DAY) })] })).toEqual(['b'])
    expect(activeIds({ server: [group('b', 'absent'), group('a', 'absent')] })).toEqual(['a'])
  })

  it('class comes before date: an old found copy beats a newer absent one', () => {
    expect(activeIds({ server: [group('old', 'found', { lastSeen: ago(9 * DAY) }), group('new', 'absent', { lastSeen: ago(DAY) })] })).toEqual(['old'])
  })

  it('smallest id is plain text order, not a locale\'s', () => {
    expect(activeIds({ server: [group('a', 'absent'), group('B', 'absent')] })).toEqual(['B'])
  })

  it('other groups and rows with no group are left alone', () => {
    const server = [group('a', 'found'), group('b', 'absent'), route('c', 'found', { copyGroup: 'other' }), route('d', 'absent'), route('e', 'absent')]
    expect(activeIds({ server })).toEqual(['a', 'c', 'd', 'e'])
  })

  it('a copy out of Active takes no part in the choice', () => {
    const server = [group('a-closed', 'closed'), group('b-old', 'absent', { lastSeen: ago(20 * DAY) }), group('c', 'absent')]
    expect(activeIds({ server })).toEqual(['c'])
  })

  it('all copies are in All, and the count of hidden ones is given', () => {
    const { all, copies } = compose({ server: [group('a', 'found'), group('b', 'absent'), group('c', 'absent')] })
    expect(all).toHaveLength(3)
    expect(copies).toEqual({ state: 'collapsed', hidden: 2 })
  })

  it('a worked copy stands for the ad, over a found one', () => {
    const server = [group('found', 'found'), group('worked', 'absent')]
    expect(activeIds({ stored: [local('worked', { status: 'saved' })], server })).toEqual(['worked'])
    expect(activeIds({ server, applications: withApplications('worked') })).toEqual(['worked'])
  })

  it('several worked copies all stay', () => {
    const server = [group('found', 'found'), group('s', 'absent'), group('app', 'absent'), group('plain', 'absent')]
    expect(activeIds({ stored: [local('s', { status: 'rejected' })], server, applications: withApplications('app') })).toEqual(['app', 's'])
  })

  it('a worked copy out of Active\'s classes stays, and does not hide the live ad', () => {
    const server = [group('stale', 'stale'), group('found', 'found'), group('other', 'absent')]
    expect(activeIds({ stored: [local('stale', { status: 'saved' })], server })).toEqual(['found', 'stale'])
  })

  it('a worked closed copy leaves Active and does not hide the live ad', () => {
    const server = [group('closed', 'closed'), group('found', 'found'), group('other', 'absent')]
    expect(activeIds({ stored: [local('closed', { status: 'saved' })], server })).toEqual(['found'])
  })

  it('a worked copy past the window does not hide the live ad either', () => {
    const server = [group('old', 'absent', { lastSeen: ago(30 * DAY) }), group('live', 'absent')]
    expect(activeIds({ server, applications: withApplications('old') })).toEqual(['live', 'old'])
  })

  it('a worked stale copy alone is shown alone', () => {
    expect(activeIds({ server: [group('stale', 'stale'), group('older', 'older_key')], applications: withApplications('stale') })).toEqual(['stale'])
  })

  it.each([[{ status: 'loading', store: null }], [{ status: 'idle', store: null }], [null]])('store loading (%j): copies are not collapsed', (applications) => {
    const { active, copies } = compose({ server: [group('a', 'found'), group('b', 'absent')], applications })
    expect(ids(active).sort()).toEqual(['a', 'b'])
    expect(copies).toEqual({ state: 'waiting', hidden: 0 })
  })

  it.each(['error', 'failed'])('store %s: copies are not collapsed, and it is flagged', (status) => {
    const { active, copies } = compose({ server: [group('a', 'found'), group('b', 'absent')], applications: { status, store: { applications: { x: { posting: { jobId: 'gone' } } } } } })
    expect(ids(active).sort()).toEqual(['a', 'b'])
    expect(copies).toEqual({ state: 'failed', hidden: 0 })
  })

  it('a store that failed gives no work from what it last held: only what is known counts', () => {
    const applications = { status: 'error', store: { applications: { x: { posting: { jobId: 'c' } } } } }
    expect(compose({ server: [route('c', 'closed')], applications }).active).toEqual([])
  })

  it('work in the browser counts while the store loads', () => {
    expect(ids(compose({ stored: [local('c', { status: 'saved' })], server: [route('c', 'stale')], applications: { status: 'loading' } }).active)).toEqual(['c'])
  })

  it('when the store arrives the list is worked out again from the same inputs, and nothing stored changes', () => {
    const stored = frozen([local('s', { outreach: { contacts: [] } })])
    const server = frozen([group('s', 'absent'), group('found', 'found'), group('applied', 'absent')])
    const before = JSON.stringify(stored)
    const loading = composeJobList({ stored, server, applications: { status: 'loading', store: null }, reference: NOW })
    expect(ids(loading.active).sort()).toEqual(['applied', 'found', 's'])
    const ready = composeJobList({ stored, server, applications: withApplications('applied'), reference: NOW })
    expect(ids(ready.active)).toEqual(['applied'])
    expect(ready.copies).toEqual({ state: 'collapsed', hidden: 2 })
    expect(JSON.stringify(stored)).toBe(before)
    expect(composeJobList({ stored, server, applications: { status: 'loading', store: null }, reference: NOW })).toEqual(loading)
  })
})

describe('the route\'s order plays no part', () => {
  function shuffled(rows, seed) {
    let state = seed + 1
    const random = () => { state = (state * 48271) % 2147483647; return state / 2147483647 }
    const copy = [...rows]
    for (let i = copy.length - 1; i > 0; i -= 1) {
      const j = Math.floor(random() * (i + 1))
      ;[copy[i], copy[j]] = [copy[j], copy[i]]
    }
    return copy
  }
  const server = [
    ...['f', 'a', 'z', 'm'].map((id, i) => route(`g1${id}`, 'absent', { copyGroup: 'one', lastSeen: ago((i % 2) * DAY) })),
    route('g2a', 'absent', { copyGroup: 'two' }), route('g2b', 'found', { copyGroup: 'two' }), route('g2c', 'held', { copyGroup: 'two' }),
    route('g3worked', 'closed', { copyGroup: 'three' }), route('g3live', 'absent', { copyGroup: 'three' }),
    route('s1', 'absent'), route('s2', 'closed'), route('s3', 'filtered', { from: 'filtered' }), route('s4', 'older_key'),
    route('byurl', 'found', { jobUrl: 'https://x.example/old-id' }),
  ]
  const stored = [local('old-id'), local('keep'), local('g1a', { status: 'saved' })]

  it('200 shuffles give the same two lists, down to the row order', () => {
    const input = { stored, applications: withApplications('g3worked'), reference: NOW }
    const expected = JSON.stringify(composeJobList({ ...input, server }))
    for (let seed = 0; seed < 200; seed += 1) {
      expect(JSON.stringify(composeJobList({ ...input, server: shuffled(server, seed) }))).toBe(expected)
    }
    expect(ids(JSON.parse(expected).active)).toEqual(expect.arrayContaining(['g1a', 'g2b', 'g3live']))
    expect(ids(JSON.parse(expected).active)).not.toContain('g3worked')
  })

  it('the shuffle does change the order it was given', () => {
    expect(ids(shuffled(server, 3))).not.toEqual(ids(server))
  })

  it('the input is not sorted in place', () => {
    const input = frozen([route('b'), route('a')])
    expect(() => compose({ server: input })).not.toThrow()
  })
})

describe('matching rows, and rows that must not show twice', () => {
  it('by id, then by the address the import matches on', () => {
    const { all } = compose({ stored: [local('old', { jobUrl: 'https://x.example/Same', status: 'saved' })], server: [route('new', 'found', { jobUrl: 'https://x.example/same' })] })
    expect(all).toHaveLength(1)
    expect([all[0].jobId, all[0].status, all[0].class]).toEqual(['old', 'saved', 'found'])
  })

  it('a stored row holds one route row: a second at the same address is its own row', () => {
    const { all } = compose({ stored: [local('old', { jobUrl: 'https://x.example/same' })], server: [route('n1', 'found', { jobUrl: 'https://x.example/same' }), route('n2', 'found', { jobUrl: 'https://x.example/same' })] })
    expect(ids(all)).toEqual(['old', 'n2'])
  })

  it('a route row at a hand-entered job\'s address is that job: it shows once', () => {
    const stored = [local('m', { manualEntry: true, jobUrl: 'https://own.example/1?utm_source=x' })]
    const { active, all } = compose({ stored, server: [route('n', 'filtered', { jobUrl: 'https://own.example/1' }), route('o', 'found')] })
    expect(ids(all)).toEqual(['m', 'o'])
    expect(ids(active)).toEqual(['m', 'o'])
  })

  it('a hand-entered row with the route\'s id is not given a class', () => {
    const { all } = compose({ stored: [local('m', { manualEntry: true })], server: [route('m', 'closed')] })
    expect(all[0].class).toBeUndefined()
  })

  it('stored rows keep their order, then server-only rows by id', () => {
    expect(ids(compose({ stored: [local('z'), local('a')], server: [route('y'), route('b')] }).all)).toEqual(['z', 'a', 'b', 'y'])
  })
})

describe('the route failing or empty never clears stored rows', () => {
  const stored = frozen([local('a', { status: 'saved' }), local('b'), local('m', { manualEntry: true })])

  it.each([[null], [undefined], [[]], ['text'], [{ rows: [] }]])('server %j: every stored row stays', (server) => {
    const { active, all } = composeJobList({ stored, server, applications: READY, reference: NOW })
    expect(ids(all)).toEqual(['a', 'b', 'm'])
    expect(ids(active)).toEqual(['a', 'b', 'm'])
  })

  it('a row with no id in the route\'s answer is ignored', () => {
    expect(compose({ server: [{ title: 'odd' }, null, route('a')] }).all).toHaveLength(1)
  })

  it('nothing at all gives two empty lists', () => {
    expect(composeJobList({ reference: NOW })).toEqual({ active: [], all: [], copies: { state: 'waiting', hidden: 0 } })
  })
})

describe('class labels', () => {
  it.each([
    ['found', null], ['held', 'Not checked this run'], ['absent', 'Not in latest search'], ['closed', 'Closed'], ['older_key', 'Search settings changed'],
    ['stale', 'Stale'], ['filtered', 'Filtered out'], ['filtered_incomplete', 'Incomplete'], ['unclassified', 'Status unknown'], ['something_new', 'Status unknown'], ['constructor', 'Status unknown'],
  ])('%s: %s', (cls, label) => expect(classLabel({ class: cls })).toBe(label))

  it('a stored row with no class, and a hand-entered one', () => {
    expect(classLabel({ jobId: 'a' })).toBe('Saved in this browser')
    expect(classLabel({ jobId: 'm', manualEntry: true })).toBeNull()
  })
})

describe('fetchAllAds', () => {
  const answer = (status, body) => async () => ({ ok: status < 400, status, json: async () => body })

  it('a good answer', async () => {
    expect(await fetchAllAds(answer(200, { ok: true, rows: [route('a')], meta: { filteredFile: 'ok' } }))).toEqual({ ok: true, rows: [route('a')], meta: { filteredFile: 'ok' } })
  })

  it('asks the one route', async () => {
    const fetchFn = vi.fn(answer(200, { ok: true, rows: [] }))
    await fetchAllAds(fetchFn)
    expect(fetchFn).toHaveBeenCalledWith('/api/jobs/all')
  })

  it.each([
    [503, { ok: false, error: 'view_unrecoverable', message: 'cannot be read' }, 'cannot be read'],
    [500, { error: 'odd' }, 'odd'],
    [404, null, 'The list of all ads could not be loaded (404)'],
    [200, { ok: true }, 'The list of all ads could not be loaded (200)'],
    [200, { ok: true, rows: 'text' }, 'The list of all ads could not be loaded (200)'],
    [200, { rows: [] }, 'The list of all ads could not be loaded (200)'],
  ])('%i %j is a failure', async (status, body, message) => {
    expect(await fetchAllAds(answer(status, body))).toEqual({ ok: false, message })
  })

  it('a network failure, and a body that is not JSON', async () => {
    expect((await fetchAllAds(async () => { throw new Error('down') })).message).toContain('down')
    expect((await fetchAllAds(async () => ({ ok: true, status: 200, json: async () => { throw new Error('no') } }))).ok).toBe(false)
  })
})

describe('createAllAdsLoader: in memory only', () => {
  const good = (rows = [route('a')]) => async () => ({ ok: true, status: 200, json: async () => ({ ok: true, rows, meta: { filteredFile: 'ok' } }) })
  const bad = async () => ({ ok: false, status: 503, json: async () => ({ ok: false, message: 'no list' }) })

  it('starts idle and asks nothing', () => {
    const fetchFn = vi.fn(good())
    expect(createAllAdsLoader({ fetchFn }).getState()).toEqual({ status: 'idle', rows: null, meta: null, error: null })
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('loading, then ready, telling its listeners', async () => {
    const loader = createAllAdsLoader({ fetchFn: good() })
    const seen = []
    loader.subscribe(() => seen.push(loader.getState().status))
    await loader.refetch()
    expect(seen).toEqual(['loading', 'ready'])
    expect(loader.getState().rows).toHaveLength(1)
    expect(loader.getState().meta).toEqual({ filteredFile: 'ok' })
  })

  it('an error on the first request: no rows, and the reason', async () => {
    const loader = createAllAdsLoader({ fetchFn: bad })
    await loader.refetch()
    expect(loader.getState()).toEqual({ status: 'error', rows: null, meta: null, error: 'no list' })
  })

  it('a later error keeps the last good rows, and a later success clears the error', async () => {
    let fetchFn = good()
    const loader = createAllAdsLoader({ fetchFn: (...args) => fetchFn(...args) })
    await loader.refetch()
    fetchFn = bad
    await loader.refetch()
    expect(loader.getState().status).toBe('error')
    expect(loader.getState().rows).toHaveLength(1)
    fetchFn = good([])
    await loader.refetch()
    expect(loader.getState()).toEqual({ status: 'ready', rows: [], meta: { filteredFile: 'ok' }, error: null })
  })

  it('the rows stay while it loads again', async () => {
    const loader = createAllAdsLoader({ fetchFn: good() })
    await loader.refetch()
    const pending = loader.refetch()
    expect(loader.getState().status).toBe('loading')
    expect(loader.getState().rows).toHaveLength(1)
    await pending
  })

  it('only the newest request counts, whichever answers last', async () => {
    const release = []
    const fetchFn = () => new Promise((resolve) => release.push(resolve))
    const loader = createAllAdsLoader({ fetchFn })
    const first = loader.refetch()
    const second = loader.refetch()
    const body = (rows) => ({ ok: true, status: 200, json: async () => ({ ok: true, rows }) })
    release[1](body([route('new')]))
    await second
    release[0](body([route('old')]))
    await first
    expect(ids(loader.getState().rows)).toEqual(['new'])
  })

  it('stops telling a listener that left', async () => {
    const loader = createAllAdsLoader({ fetchFn: good() })
    const listener = vi.fn()
    loader.subscribe(listener)()
    await loader.refetch()
    expect(listener).not.toHaveBeenCalled()
  })
})

describe('useAllAds', () => {
  it('gives the state and a refetch, and asks nothing while rendering', () => {
    const fetchFn = vi.fn()
    const loader = createAllAdsLoader({ fetchFn })
    let seen = null
    function Probe() {
      seen = useAllAds({ loader })
      return null
    }
    renderToString(createElement(Probe))
    expect(seen.status).toBe('idle')
    expect(seen.refetch).toBe(loader.refetch)
    expect(fetchFn).not.toHaveBeenCalled()
  })
})

describe('server-only rows cannot reach the stored list', () => {
  const sources = ['src/modules/jobs/allAds.js', 'src/modules/jobs/useAllAds.js'].map((file) => [file, fs.readFileSync(file, 'utf-8')])
  afterEach(() => vi.unstubAllGlobals())

  it.each(sources)('%s imports only what it may', (file, source) => {
    const imports = [...source.matchAll(/^import\s+(.*?)\s+from\s+'([^']+)'/gm)].map((m) => `${m[1]} from ${m[2]}`)
    const allowed = ["{ hasUserData, jobMatchKey } from ./jobStorage.js", '{ isClosedAd } from ./jobHistory.js', '{ identityJobUrl } from ./manualJob.js', '{ useEffect, useSyncExternalStore } from react']
    for (const line of imports) expect(allowed).toContain(line)
    expect(source).not.toMatch(/import\s*\(/)
    expect(source).not.toMatch(/require\s*\(/)
  })

  it.each(sources)('%s names no writer and no browser storage in its code', (file, source) => {
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
    for (const word of ['saveJobs', 'importJobsFromFile', 'mergeStatusOnImport', 'addJobIfAbsent', 'patchJob', 'createJob', 'jobsStore', 'localStorage', 'sessionStorage', 'indexedDB']) {
      expect(code).not.toContain(word)
    }
  })

  it('no storage is touched while composing and loading', async () => {
    const touch = vi.fn(() => { throw new Error('storage was touched') })
    const storage = { getItem: touch, setItem: touch, removeItem: touch, clear: touch }
    vi.stubGlobal('localStorage', storage)
    vi.stubGlobal('sessionStorage', storage)
    const loader = createAllAdsLoader({ fetchFn: async () => ({ ok: true, status: 200, json: async () => ({ ok: true, rows: [route('a', 'absent')] }) }) })
    await loader.refetch()
    composeJobList({ stored: [local('s', { status: 'saved' })], server: loader.getState().rows, applications: withApplications('a'), reference: NOW })
    expect(touch).not.toHaveBeenCalled()
  })

  it('no input is changed: the stored rows come through a deep freeze whole', () => {
    const stored = frozen([local('a', { status: 'saved', outreach: { contacts: [{ name: 'x' }] } }), local('b')])
    const server = frozen([route('a', 'absent', { copyGroup: 'g' }), route('b', 'found', { copyGroup: 'g' }), route('c', 'filtered')])
    const before = JSON.stringify(stored)
    expect(() => compose({ stored, server })).not.toThrow()
    expect(JSON.stringify(stored)).toBe(before)
  })

  it('class fields go on a copy, never on the stored row', () => {
    const stored = [local('a')]
    const { all } = compose({ stored, server: [route('a', 'absent')] })
    expect(all[0].class).toBe('absent')
    expect(all[0]).not.toBe(stored[0])
    for (const field of ROUTE_FIELDS) expect(field in stored[0]).toBe(false)
  })
})
