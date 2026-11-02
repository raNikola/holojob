import { beforeEach, describe, expect, it, vi } from 'vitest'
import { hasUserData, importJobsFromFile, loadJobs, saveJobs } from '../../src/modules/jobs/jobStorage.js'
import { invalidateJobs } from '../../src/modules/jobs/jobsStore.js'
import {
  CLEAR_ALL_FILTERS,
  activeFilterChips,
  filterJobs,
  isOffList,
  listedJobs,
  moreFiltersCount,
} from '../../src/modules/jobs/jobFilters.js'
import { FILTER_HELP } from '../../src/modules/jobs/filterHelp.js'
import { computeJobStats, countTailoredResumes } from '../../src/modules/jobs/jobStats.js'
import { derivePipelineStateFromHealth } from '../../src/modules/jobs/pipelineState.js'
import { syncManualJobs } from '../../src/modules/jobs/manualScoring.js'
import { computeOutreachMetrics } from '../../src/modules/outreach/outreachMetrics.js'
import { buildAiContext, buildSkillGapContext } from '../../src/modules/ai/aiContextBuilder.js'

const items = new Map()
beforeEach(() => {
  items.clear()
  vi.stubGlobal('localStorage', {
    getItem: (k) => (items.has(k) ? items.get(k) : null),
    setItem: (k, v) => items.set(k, String(v)),
    removeItem: (k) => items.delete(k),
  })
  invalidateJobs()
})

const row = (id, extra = {}) => ({ jobId: id, title: `Title ${id}`, company: 'Acme', jobUrl: `https://jobs.example/${id}`, status: 'new', ...extra })
const OUTREACH = { contacts: [{ name: 'A Contact' }], messages: [], activity: [], status: 'contacted' }
const TRACKING = { applied: true, appliedDate: '2026-10-30', notes: '' }
const ASSETS = { resumeMd: 'data/resumes/x/tailored_resume.md', generatedAt: '2026-10-30' }
const INSIGHTS = { jobAnalysis: { summary: 'worth a look' }, updatedAt: '2026-10-30' }
const importInto = (prior, fileRows = []) => importJobsFromFile({ jobs: fileRows }, { jobs: prior, filters: {} })
const byId = (state, id) => state.jobs.find((j) => j.jobId === id)

describe('a row the file no longer lists', () => {
  it.each([
    ['saved status', { status: 'saved' }],
    ['rejected status', { status: 'rejected' }],
    ['applied_manually status', { status: 'applied_manually' }],
    ['AI insights', { aiInsights: INSIGHTS }],
    ['tailored assets', { tailoredAssets: ASSETS }],
    ['outreach', { outreach: OUTREACH }],
    ['legacy application tracking', { applicationTracking: TRACKING }],
  ])('with %s is kept whole and marked offList', (_name, data) => {
    const prior = row('a', { description: 'the ad', ...data })
    const kept = byId(importInto([prior]), 'a')
    expect(kept).toEqual({ ...prior, offList: true })
  })

  it.each([
    ['status new', {}],
    ['no status at all', { status: undefined }],
    ['null tracking, as a saved row carries it', { applicationTracking: null }],
    ['default tracking with nothing filled in', { applicationTracking: { applied: false, appliedDate: '', notes: '', lastUpdated: '2026-10-30' } }],
    ['insights that hold only a timestamp', { aiInsights: { updatedAt: '2026-10-30' } }],
    ['empty tailored assets', { tailoredAssets: {} }],
    ['outreach that never started', { outreach: { contacts: [], messages: [], activity: [], status: 'none', lastUpdated: '2026-10-30' } }],
  ])('with %s is dropped, as before', (_name, data) => {
    expect(byId(importInto([row('a', data)]), 'a')).toBeUndefined()
  })

  it('stays kept through later imports that still lack it', () => {
    const once = importInto([row('a', { status: 'saved' })])
    const twice = importInto(once.jobs, [row('b')])
    expect(byId(twice, 'a')).toMatchObject({ status: 'saved', offList: true })
    expect(twice.jobs.map((j) => j.jobId)).toEqual(['b', 'a'])
  })

  it('edits to a kept row survive the next import', () => {
    const once = importInto([row('a', { status: 'saved' })])
    const edited = once.jobs.map((j) => ({ ...j, status: 'rejected' }))
    expect(byId(importInto(edited), 'a')).toMatchObject({ status: 'rejected', offList: true })
  })
})

describe('a kept row that returns', () => {
  const kept = row('a', { status: 'rejected', aiInsights: INSIGHTS, tailoredAssets: ASSETS, outreach: OUTREACH, applicationTracking: TRACKING, offList: true })

  it('matched on jobId loses the mark and keeps all its user data', () => {
    const back = byId(importInto([kept], [row('a', { jobUrl: 'https://jobs.example/moved', matchScore: 70 })]), 'a')
    expect(back).not.toHaveProperty('offList')
    expect(back).toMatchObject({ status: 'rejected', aiInsights: INSIGHTS, tailoredAssets: ASSETS, outreach: OUTREACH, applicationTracking: TRACKING, matchScore: 70 })
  })

  it('matched on the lowercased URL under a new id does the same, with one row', () => {
    const state = importInto([kept], [row('other', { jobUrl: 'HTTPS://JOBS.EXAMPLE/a' })])
    expect(state.jobs).toHaveLength(1)
    expect(state.jobs[0]).not.toHaveProperty('offList')
    expect(state.jobs[0]).toMatchObject({ jobId: 'other', status: 'rejected', outreach: OUTREACH })
  })

  it('a rejected ad does not come back as new', () => {
    const gone = importInto([row('a', { status: 'rejected' })])
    expect(byId(gone, 'a').offList).toBe(true)
    expect(byId(importInto(gone.jobs, [row('a', { status: 'new' })]), 'a').status).toBe('rejected')
  })

  it('a mark inside the imported file itself is not taken in', () => {
    expect(byId(importInto([], [row('a', { offList: true })]), 'a')).not.toHaveProperty('offList')
  })
})

describe('manual jobs are not affected', () => {
  const manual = row('m', { manualEntry: true, provider: 'manual', notes: 'mine' })

  it('a hand-entered job the file lacks stays, with no mark, with or without user data', () => {
    const state = importInto([manual, { ...manual, jobId: 'm2', jobUrl: 'https://jobs.example/m2', status: 'saved' }], [row('b')])
    expect(byId(state, 'm')).toEqual(manual)
    expect(byId(state, 'm2')).not.toHaveProperty('offList')
  })

  it('a stored row whose address now belongs to a hand-entered job is not kept as a second row', () => {
    const url = 'https://jobs.example/same'
    const state = importInto([{ ...manual, jobUrl: url }, row('old', { jobUrl: url, status: 'saved' })], [row('file', { jobUrl: url })])
    expect(state.jobs.filter((j) => j.offList)).toEqual([])
  })
})

describe('hasUserData', () => {
  it('reads nothing into a missing row', () => {
    expect(hasUserData(undefined)).toBe(false)
    expect(hasUserData({})).toBe(false)
  })
})

describe('default views leave offList rows out', () => {
  const on = row('on', { status: 'saved', matchScore: 80, priority: 'P1', applyRecommendation: 'Apply', tailoredAssets: ASSETS, outreach: OUTREACH, applicationTracking: TRACKING })
  const off = row('off', { status: 'rejected', matchScore: 90, priority: 'P1', applyRecommendation: 'Apply', tailoredAssets: ASSETS, outreach: OUTREACH, applicationTracking: TRACKING, offList: true })
  const list = [on, off]

  it('filterJobs hides them with no filters and with every other filter', () => {
    expect(filterJobs(list).map((j) => j.jobId)).toEqual(['on'])
    expect(filterJobs(list, { status: 'rejected' })).toEqual([])
    expect(filterJobs(list, { searchText: 'Title off' })).toEqual([])
    expect(filterJobs(list, { status: 'applied' }, { appliedJobIds: new Set(['off']) })).toEqual([])
  })

  it('the explicit filter shows them, as a chip that resets, in the More filters count, and cleared by Clear all', () => {
    expect(filterJobs(list, { showOffList: true }).map((j) => j.jobId)).toEqual(['on', 'off'])
    const chips = activeFilterChips({ showOffList: true })
    expect(chips).toEqual([{ key: 'showOffList', label: 'Showing jobs absent from current results', patch: { showOffList: false } }])
    expect(moreFiltersCount(chips)).toBe(1)
    expect(CLEAR_ALL_FILTERS.showOffList).toBe(false)
    expect(FILTER_HELP.showOffList).toBeTruthy()
    expect(loadJobs().filters.showOffList).toBe(false)
  })

  it('isOffList reads only the mark', () => {
    expect(isOffList(off)).toBe(true)
    expect(isOffList(on)).toBe(false)
    expect(isOffList({ offList: 'yes' })).toBe(false)
    expect(isOffList(null)).toBe(false)
  })

  it('listedJobs follows the filter, for the screen total and the filter options', () => {
    expect(listedJobs(list, {})).toEqual([on])
    expect(listedJobs(list, { showOffList: true })).toEqual(list)
  })

  it('computeJobStats counts none of them', () => {
    expect(computeJobStats(list)).toEqual(computeJobStats([on]))
    expect(computeJobStats(list)).toMatchObject({ total: 1, rejected: 0, saved: 1, p1: 1, crmApplied: 1, avgScore: 80 })
  })

  it('outreach metrics count none of them', () => {
    expect(computeOutreachMetrics(list)).toEqual(computeOutreachMetrics([on]))
    expect(computeOutreachMetrics(list).totalContacts).toBe(1)
  })

  it('the Dashboard tailored count and the pipeline counts count none of them', () => {
    expect(countTailoredResumes(list)).toBe(1)
    expect(derivePipelineStateFromHealth({}, list)).toMatchObject({ jobsDiscovered: 1, jobsScored: 1, resumesGenerated: 1 })
  })
})

describe('offList rows leave no path to the pipeline or the provider', () => {
  const kept = row('kept-1', { status: 'saved', description: 'KEPT-AD-CANARY', matchScore: 99, skills: ['KeptSkill'], offList: true })

  it('the only job list sent to the server for scoring holds hand-entered jobs alone', async () => {
    const fetchFn = vi.fn(async () => ({ status: 200, json: async () => ({ ok: true }) }))
    saveJobs({ meta: null, jobs: [kept], filters: {}, importedAt: null })
    invalidateJobs()
    expect(await syncManualJobs({ fetchFn })).toEqual({ ok: true, sent: 0 })
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('the AI features that read the whole list do not see them', () => {
    saveJobs({ meta: null, jobs: [kept, row('on-1', { matchScore: 50, description: 'listed ad' })], filters: {}, importedAt: null })
    invalidateJobs()
    expect(JSON.stringify(buildSkillGapContext())).not.toContain('kept-1')
    for (const featureId of ['careerStrategy', 'applicationStrategy', 'chat']) {
      const context = JSON.stringify(buildAiContext({ featureId }))
      expect(context, featureId).not.toContain('KEPT-AD-CANARY')
      expect(context, featureId).not.toContain('Title kept-1')
    }
  })
})
