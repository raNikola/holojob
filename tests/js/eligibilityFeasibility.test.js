import { describe, it, expect } from 'vitest'
import { clearRemoteText, eligibilityBadges, eligibilityFeasibility, isRemoteFeasible } from '../../src/modules/jobs/workAuthorization.js'
import { defaultOrder, postedTimeOf } from '../../src/modules/jobs/jobTableModel.js'
import { CLEAR_ALL_FILTERS, MORE_FILTER_KEYS, activeFilterChips, filterJobs, hiddenAsNotOnBoard } from '../../src/modules/jobs/jobFilters.js'
import { getDefaultJobsState } from '../../src/modules/jobs/jobStorage.js'
import { listNotices } from '../../src/modules/jobs/jobListView.js'

const unknown = (extra = {}, facts = {}) => ({
  jobId: 'x', matchScore: 60, matchLabel: 'Good',
  eligibility: { state: 'unknown', reason: 'r', b2b: false },
  llmFacts: { workMode: 'unclear', jobCountry: 'US', remoteEligibility: [], ...facts },
  ...extra,
})
const sub = (job) => eligibilityBadges(job).map((b) => b.label)

describe('eligibility sub-state inside Unconfirmed (owner decision 2026-11-18, display and order only)', () => {
  it('remote with no country restriction, Europe or worldwide is Remote-feasible', () => {
    expect(eligibilityFeasibility(unknown({ isRemote: true }))).toBe('remote_feasible')
    expect(eligibilityFeasibility(unknown({}, { workMode: 'remote' }))).toBe('remote_feasible')
    expect(eligibilityFeasibility(unknown({}, { workMode: 'remote', remoteEligibility: ['WORLDWIDE'] }))).toBe('remote_feasible')
    expect(eligibilityFeasibility(unknown({}, { workMode: 'remote', remoteEligibility: ['EUROPE'] }))).toBe('remote_feasible')
    expect(eligibilityFeasibility(unknown({}, { workMode: 'remote', remoteEligibility: ['RS'] }))).toBe('remote_feasible')
  })

  it('a remote ad limited to the US, Canada or the EU (Serbia is not in it) needs authorization', () => {
    expect(eligibilityFeasibility(unknown({ isRemote: true }, { remoteEligibility: ['US'] }))).toBe('onsite_needs_authorization')
    expect(eligibilityFeasibility(unknown({}, { workMode: 'remote', remoteEligibility: ['EU'] }))).toBe('onsite_needs_authorization')
  })

  it('a job in Serbia and a B2B / employer-of-record exception are Remote-feasible; an onsite or hybrid job elsewhere is not', () => {
    expect(eligibilityFeasibility(unknown({}, { jobCountry: 'RS' }))).toBe('remote_feasible')
    expect(eligibilityFeasibility(unknown({ eligibility: { state: 'unknown', b2b: true, kind: 'b2b_exception' } }))).toBe('remote_feasible')
    expect(eligibilityFeasibility(unknown({}, { workMode: 'onsite' }))).toBe('onsite_needs_authorization')
    expect(eligibilityFeasibility(unknown({}, { workMode: 'hybrid' }))).toBe('onsite_needs_authorization')
    expect(eligibilityFeasibility(unknown())).toBe('onsite_needs_authorization')
  })

  it('the board work mode wins over the extracted one, as in the Location dimension', () => {
    expect(eligibilityFeasibility(unknown({ workMode: 'onsite' }, { workMode: 'remote' }))).toBe('onsite_needs_authorization')
  })

  it('clear remote wording in the ad text wins over a structured field that says onsite or hybrid', () => {
    const text = (description, extra = {}, facts = {}) => unknown({ description, ...extra }, facts)
    expect(eligibilityFeasibility(text('This role is fully remote.', { workMode: 'onsite' }))).toBe('remote_feasible')
    expect(eligibilityFeasibility(text('You can work from anywhere in Europe', {}, { workMode: 'hybrid' }))).toBe('remote_feasible')
    expect(eligibilityFeasibility(text('<p>100% remote</p>', { isRemote: false }))).toBe('remote_feasible')
    // the country restriction still applies to a remote ad
    expect(eligibilityFeasibility(text('We are fully remote', {}, { remoteEligibility: ['US'] }))).toBe('onsite_needs_authorization')
    // a negation cancels it; plain "remote" is not clear text
    expect(eligibilityFeasibility(text('This is not a fully remote position', { workMode: 'onsite' }))).toBe('onsite_needs_authorization')
    expect(eligibilityFeasibility(text('Remote work is possible two days a week'))).toBe('onsite_needs_authorization')
    expect(clearRemoteText('We offer work from anywhere')).toBe('work from anywhere')
    // a benefit line or an allowance is not the job
    expect(clearRemoteText('For fully remote workers we provide extra support for their home office.')).toBeNull()
    expect(clearRemoteText("Two weeks of 'Work from Anywhere' each year.")).toBeNull()
    expect(clearRemoteText('')).toBeNull()
  })

  it('only an Unconfirmed ad has a sub-state; the other states and a dormant check have none', () => {
    for (const state of ['authorized', 'sponsorship_offered', 'sponsorship_refused']) {
      expect(eligibilityFeasibility(unknown({ eligibility: { state } }))).toBeNull()
    }
    expect(eligibilityFeasibility({ jobId: 'a', eligibility: null })).toBeNull()
    expect(eligibilityFeasibility({})).toBeNull()
  })

  it('is shown as a badge after Unconfirmed, with the reason in the tooltip', () => {
    expect(sub(unknown({ isRemote: true }))).toEqual(['Unconfirmed', 'Remote-feasible'])
    expect(sub(unknown())).toEqual(['Unconfirmed', 'Onsite, authorization needed'])
    expect(sub({ jobId: 'a', eligibility: { state: 'authorized' } })).toEqual(['Authorized'])
    const badge = eligibilityBadges(unknown({}, { jobCountry: 'RS' })).find((b) => b.label === 'Remote-feasible')
    expect(badge.reason).toMatch(/Serbia/)
  })

  it('authorized and sponsored ads count as feasible for the order, a refused or dormant one does not', () => {
    expect(isRemoteFeasible({ eligibility: { state: 'authorized' } })).toBe(true)
    expect(isRemoteFeasible({ eligibility: { state: 'sponsorship_offered' } })).toBe(true)
    expect(isRemoteFeasible({ eligibility: { state: 'sponsorship_refused' } })).toBe(false)
    expect(isRemoteFeasible({ eligibility: null })).toBe(false)
    expect(isRemoteFeasible(unknown({ isRemote: true }))).toBe(true)
  })
})

describe('default order: tier, then remote-feasible, then newest (no score or tier change)', () => {
  const row = (jobId, matchScore, extra = {}) => ({ jobId, matchScore, matchLabel: 'x', eligibility: { state: 'unknown' }, llmFacts: { workMode: 'onsite', remoteEligibility: [] }, ...extra })
  const remote = { isRemote: true, llmFacts: { workMode: 'remote', remoteEligibility: [] } }
  const ids = (rows) => defaultOrder(rows).map((r) => r.jobId)

  it('a higher tier always stays above a lower one, whatever the date or feasibility', () => {
    expect(ids([row('weak-remote-new', 50, { ...remote, datePosted: '2026-11-17' }), row('strong-old', 72, { datePosted: '2020-01-01' })])).toEqual(['strong-old', 'weak-remote-new'])
  })

  it('inside a tier, remote-feasible comes first, then newest first (datePosted, else firstSeen)', () => {
    const rows = [
      row('onsite-new', 60, { datePosted: '2026-11-16' }),
      row('remote-old', 56, { ...remote, datePosted: '2026-10-01' }),
      row('remote-new', 58, { ...remote, firstSeen: '2026-11-10T08:00:00Z' }),
      row('onsite-newest', 57, { datePosted: '2026-11-17' }),
    ]
    expect(ids(rows)).toEqual(['remote-new', 'remote-old', 'onsite-newest', 'onsite-new'])
  })

  it('equal feasibility and date fall back to the id, never to a score; an ad with no date goes after dated ones', () => {
    const rows = [row('b', 60, { datePosted: '2026-11-01', scoreBeforeCaps: 70 }), row('a', 60, { datePosted: '2026-11-01', scoreBeforeCaps: 70 }), row('c', 60, { datePosted: '2026-11-01', scoreBeforeCaps: 80 }), row('nodate', 60)]
    expect(ids(rows)).toEqual(['a', 'b', 'c', 'nodate'])
  })

  it('reads the tier from the Fit Score (70 / 55) and keeps unscored rows last', () => {
    expect(ids([row('u', undefined), row('g', 55), row('s', 70), row('e', 85), row('w', 40), row('r', 39)])).toEqual(['e', 's', 'g', 'r', 'w', 'u'])
  })

  it('postedTimeOf reads datePosted first, then firstSeen, and is null for neither or an unreadable date', () => {
    expect(postedTimeOf({ datePosted: '2026-11-17', firstSeen: '2020-01-01' })).toBe(Date.parse('2026-11-17'))
    expect(postedTimeOf({ firstSeen: '2026-11-10T08:00:00Z' })).toBe(Date.parse('2026-11-10T08:00:00Z'))
    expect(postedTimeOf({})).toBeNull()
    expect(postedTimeOf({ datePosted: 'soon' })).toBeNull()
  })
})

describe('the default list leaves out ads that are not on the board in the latest complete check', () => {
  const ad = (jobId, extra = {}) => ({ jobId, title: jobId, company: 'Acme', location: 'Nis', jobUrl: `https://x.example/${jobId}`, status: 'new', ...extra })
  const ids = (rows, filters = {}) => filterJobs(rows, filters).map((r) => r.jobId)

  it('absent and closed ads (route class) are hidden by default and shown by the filter', () => {
    // `absentSince` is the mark of a complete check of the company's board: only an ad with it is "not on the board"
    const rows = [ad('f', { class: 'found' }), ad('h', { class: 'held' }), ad('a', { class: 'absent', absentSince: '2026-11-18T10:00:00.000Z' }), ad('c', { class: 'closed' }), ad('s', { class: 'stale' })]
    expect(ids(rows)).toEqual(['f', 'h', 's'])
    expect(ids(rows, { showNotOnBoard: true })).toEqual(['f', 'h', 'a', 'c', 's'])
  })

  it('an absent ad with no board check is one a search did not return: it says nothing about the ad, so it is not left out (it is in Active within the Settings period)', () => {
    const rows = [ad('spy', { class: 'absent', absentSince: null }), ad('board', { class: 'absent', absentSince: '2026-11-18T10:00:00.000Z' })]
    expect(ids(rows)).toEqual(['spy'])
    expect(hiddenAsNotOnBoard(rows[0], {})).toBe(false)
    expect(hiddenAsNotOnBoard(rows[1], {})).toBe(true)
  })

  it('a stored row with isAbsent or isClosed and no class is hidden the same way; the route class wins over a stale stored flag', () => {
    const rows = [ad('abs', { isAbsent: true }), ad('clo', { isClosed: true }), ad('ok'), ad('back', { class: 'found', isClosed: true })]
    expect(ids(rows)).toEqual(['ok', 'back'])
  })

  it('an ad the owner saved, applied to, or tracks stays in the list', () => {
    const rows = [ad('saved', { class: 'absent', absentSince: '2026-11-18T10:00:00.000Z', status: 'saved' }), ad('applied', { class: 'closed', status: 'applied_manually' }), ad('tracked', { class: 'absent', absentSince: '2026-11-18T10:00:00.000Z', applicationTracking: { stage: 'x' } }), ad('new', { class: 'absent', absentSince: '2026-11-18T10:00:00.000Z' })]
    expect(ids(rows)).toEqual(['saved', 'applied', 'tracked'])
  })

  it('is off by default in saved state and cleared by Clear all, and shows as a chip when on', () => {
    expect(CLEAR_ALL_FILTERS.showNotOnBoard).toBe(false)
    expect(getDefaultJobsState().filters.showNotOnBoard).toBe(false)
    expect(MORE_FILTER_KEYS).toContain('showNotOnBoard')
    expect(activeFilterChips({ showNotOnBoard: true }).map((c) => c.key)).toContain('showNotOnBoard')
    expect(activeFilterChips({}).map((c) => c.key)).not.toContain('showNotOnBoard')
  })

  it('hiddenAsNotOnBoard counts what the notice reports', () => {
    expect(hiddenAsNotOnBoard(ad('a', { class: 'absent', absentSince: '2026-11-18T10:00:00.000Z' }), {})).toBe(true)
    expect(hiddenAsNotOnBoard(ad('a', { class: 'absent', absentSince: '2026-11-18T10:00:00.000Z' }), { showNotOnBoard: true })).toBe(false)
    expect(hiddenAsNotOnBoard(ad('f', { class: 'found' }), {})).toBe(false)
  })

  it('the Active list says how many it left out, and where they are', () => {
    const [notice] = listNotices({ mode: 'active', rows: [], unlisted: 3, copies: { state: 'collapsed' } })
    expect(notice.text).toMatch(/^3 ads are not on the company's board/)
    expect(listNotices({ mode: 'active', rows: [], unlisted: 1, copies: { state: 'collapsed' } })[0].text).toMatch(/^1 ad is not/)
    expect(listNotices({ mode: 'active', rows: [], unlisted: 0, copies: { state: 'collapsed' } })).toEqual([])
    expect(listNotices({ mode: 'all', rows: [], meta: { filteredFile: 'ok' }, unlisted: 5, copies: { state: 'collapsed' } })).toEqual([])
  })
})
