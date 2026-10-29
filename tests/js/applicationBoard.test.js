import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'
import * as store from '../../scripts/application-store.js'
import * as client from '../../src/modules/applications/applicationsClient.js'
import { foldApplication } from '../../src/modules/applications/foldApplication.js'
import { boardFootnote, buildBoard, moveChoices } from '../../src/modules/applications/boardModel.js'
import { applicationStatistics, columnByJobId, median, stageFilterOptions, weekStart } from '../../src/modules/applications/applicationStatistics.js'
import { boardColumn, defaultSettings } from '../../src/modules/applications/stageRegistry.js'
import { newRequestId } from '../../src/modules/applications/trackerController.js'

const id16 = (n) => crypto.createHash('sha256').update(`board-${n}`).digest('hex').slice(0, 16)
let root
let server
let clock
const now = () => clock
const cache = () => client.getApplicationsState()

beforeEach(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'board-'))
  clock = new Date('2026-11-03T10:00:00.000Z')
  server = http.createServer(async (req, res) => {
    if (!(await store.handleApplicationsRequest(req, res, req.url.split('?')[0], { root, now }))) { res.statusCode = 418; res.end() }
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  client.configureClient({ base: `http://127.0.0.1:${server.address().port}`, ensure: async () => true })
  await client.refreshApplications()
})

afterEach(async () => {
  client.configureClient()
  await new Promise((resolve) => server.close(resolve))
  fs.rmSync(root, { recursive: true, force: true })
})

async function apply(n, { appliedDate = '2026-10-20', channel = 'company_site', cv } = {}) {
  const jobId = id16(n)
  const { application } = await client.createApplication({
    requestId: newRequestId(),
    jobId,
    posting: { jobId, title: `Role ${n}`, company: `Company ${n}`, jobUrl: `https://c${n}.example/job` },
    attempt: { channel, channelDetail: '', applicationUrl: '', appliedDate, cv: cv ?? { kind: 'unknown' } },
  })
  return application
}
const move = (app, toStage) => client.moveApplication(app.id, { toStage })
const board = (today = '2026-11-03') => buildBoard(cache().store, cache().settings, today)
const column = (b, key) => b.columns.find((c) => c.key === key)

describe('board model', () => {
  it('has Applied, the registry stages in order, then Rejected and Ghosted', () => {
    expect(board().columns.map((c) => c.label)).toEqual(['Applied', 'Screen', 'Tech', 'Onsite', 'Offer', 'Rejected', 'Ghosted'])
  })

  it('puts a new application in Applied with its days in stage, longest wait first', async () => {
    const a = await apply(1, { appliedDate: '2026-10-30' })
    await apply(2, { appliedDate: '2026-10-01' })
    const cards = column(board(), 'applied').cards
    expect(cards.map((c) => [c.company, c.days, c.stale])).toEqual([['Company 2', 33, true], ['Company 1', 4, false]])
    expect(cards[1]).toMatchObject({ appId: a.id, title: 'Role 1', jobId: id16(1) })
  })

  it('moves a card through the existing /move route and the cache follows', async () => {
    const a = await apply(1)
    await move(a, 'tech')
    expect(column(board(), 'tech').cards.map((c) => c.appId)).toEqual([a.id])
    expect(column(board(), 'applied').cards).toEqual([])
    await move(a, 'rejected')
    expect(column(board(), 'rejected').cards).toHaveLength(1)
    expect(foldApplication(cache().store.applications[a.id]).stage).toBe('tech')
  })

  it('leaves the card where it was when the server refuses, and the cache unchanged', async () => {
    const a = await apply(1)
    const before = JSON.stringify(cache().store)
    await expect(move(a, 'nowhere')).rejects.toMatchObject({ status: 400 })
    expect(JSON.stringify(cache().store)).toBe(before)
    expect(column(board(), 'applied').cards).toHaveLength(1)
  })

  it('offers every column but its own', () => {
    const settings = defaultSettings()
    expect(moveChoices(settings, 'tech').map((o) => o.value)).toEqual(['applied', 'screen', 'onsite', 'offer', 'rejected', 'ghosted'])
    expect(moveChoices(settings, 'tech').find((o) => o.value === 'screen').label).toBe('Screen')
  })

  it('counts closed outcomes and unfiled cards in a footnote, and hides voided ones', async () => {
    const a = await apply(1)
    const b = await apply(2)
    const c = await apply(3)
    await client.addEvent(a.id, { type: 'outcome_set', date: '2026-11-02', data: { outcome: 'withdrawn' } })
    await client.addEvent(b.id, { type: 'application_voided', date: '2026-11-02', data: { reason: 'test' } })
    const out = board()
    expect(out).toMatchObject({ closed: 1, unfiled: 0, total: 2 })
    expect(boardFootnote(out)).toBe('1 closed (other outcomes)')
    expect(column(out, 'applied').cards.map((x) => x.appId)).toEqual([c.id])
    // an application on a stage the registry no longer shows is unfiled, not lost
    const retired = { ...defaultSettings(), stages: { work: defaultSettings().stages.work.map((s) => (s.key === 'screen' ? { ...s, retired: true } : s)) } }
    await move(c, 'screen')
    const withRetired = buildBoard(cache().store, retired, '2026-11-03')
    expect(withRetired.unfiled).toBe(1)
    expect(boardFootnote(withRetired)).toBe('1 closed (other outcomes) · 1 unfiled')
    expect(boardColumn(foldApplication(cache().store.applications[c.id]), retired)).toBe('unfiled')
  })

  it('a renamed column shows the new label with the same cards', async () => {
    const a = await apply(1)
    await move(a, 'tech')
    await store.changeStageRegistry(root, { op: 'rename', key: 'tech', label: 'Technical Interview' }, { now })
    await client.refreshApplications()
    const col = column(board(), 'tech')
    expect(col.label).toBe('Technical Interview')
    expect(col.cards).toHaveLength(1)
  })
})

describe('statistics', () => {
  it('says nothing is measured for an empty store', () => {
    const stats = applicationStatistics({ applications: {} }, defaultSettings(), '2026-11-03')
    expect(stats).toMatchObject({ total: 0, open: 0, perStage: [], perWeek: [], medianDaysInStage: [], outcomes: [] })
  })

  it('counts per stage, channel, CV, outcome and week from the store only', async () => {
    const cvA = { kind: 'external', label: 'PM CV' }
    const a = await apply(1, { appliedDate: '2026-10-19', channel: 'referral', cv: cvA })
    const b = await apply(2, { appliedDate: '2026-10-21', channel: 'referral', cv: cvA })
    const c = await apply(3, { appliedDate: '2026-11-02', channel: 'job_board' })
    await move(a, 'tech')
    await client.addEvent(b.id, { type: 'outcome_set', date: '2026-10-28', data: { outcome: 'rejected' } })
    const stats = applicationStatistics(cache().store, cache().settings, '2026-11-03')
    expect(stats).toMatchObject({ total: 3, open: 2 })
    expect(stats.perStage.map((r) => [r.label, r.count])).toEqual([['Applied', 1], ['Tech', 1], ['Rejected', 1]])
    expect(stats.perChannel.map((r) => [r.label, r.count])).toEqual([['Referral', 2], ['Job board', 1]])
    expect(stats.perCv).toEqual([{ key: 'external:PM CV', label: 'PM CV', count: 2 }])
    expect(stats.outcomes.map((r) => [r.label, r.count])).toEqual([['Rejected', 1]])
    expect(stats.perWeek).toEqual([{ week: '2026-10-19', count: 2 }, { week: '2026-10-26', count: 0 }, { week: '2026-11-02', count: 1 }])
    expect(stats.missing).toEqual({ appliedDate: 0, channel: 0, cv: 1, stageDates: 0 })
    expect(c.id).toBeTruthy()
  })

  it('computes the median days per stage over every spell, running ones up to today', async () => {
    const a = await apply(1, { appliedDate: '2026-10-01' })
    const b = await apply(2, { appliedDate: '2026-10-10' })
    await client.addEvent(a.id, { type: 'stage_changed', date: '2026-10-05', data: { stage: 'tech' } }) // applied 4 days
    await client.addEvent(b.id, { type: 'stage_changed', date: '2026-10-20', data: { stage: 'tech' } }) // applied 10 days
    const stats = applicationStatistics(cache().store, cache().settings, '2026-11-03')
    expect(stats.medianDaysInStage.find((r) => r.key === 'applied')).toMatchObject({ median: 7, spells: 2 })
    // tech: a is 29 days in (running), b is 14 days in
    expect(stats.medianDaysInStage.find((r) => r.key === 'tech')).toMatchObject({ median: 21.5, spells: 2 })
  })

  it('does not count a voided application anywhere, and reports a missing date instead of guessing', async () => {
    const a = await apply(1)
    await apply(2)
    await client.addEvent(a.id, { type: 'application_voided', date: '2026-11-01', data: { reason: 'test' } })
    const undated = structuredClone(cache().store)
    undated.applications[Object.keys(undated.applications)[1]].attempt.appliedDate = null
    const stats = applicationStatistics(undated, cache().settings, '2026-11-03')
    expect(stats.total).toBe(1)
    expect(stats.perWeek).toEqual([])
    expect(stats.missing.appliedDate).toBe(1)
    expect(stats.missing.stageDates).toBe(1)
    expect(stats.medianDaysInStage).toEqual([])
  })

  it('weeks start on Monday and the median handles even and empty lists', () => {
    expect(weekStart('2026-11-01')).toBe('2026-10-26') // a Sunday
    expect(weekStart('2026-11-02')).toBe('2026-11-02')
    expect(median([])).toBeNull()
    expect(median([1, 4])).toBe(2.5)
    expect(median([3, 1, 2])).toBe(2)
  })
})

describe('stage filter', () => {
  it('offers only stages that hold an application and maps each job to its column', async () => {
    const a = await apply(1)
    const b = await apply(2)
    await apply(3)
    await move(a, 'tech')
    await client.addEvent(b.id, { type: 'application_voided', date: '2026-11-01', data: { reason: 'test' } })
    const { store: s, settings } = cache()
    expect(stageFilterOptions(s, settings).map((o) => o.value)).toEqual(['applied', 'tech'])
    const columns = columnByJobId(s, settings)
    expect(columns.get(id16(1))).toBe('tech')
    expect(columns.get(id16(2))).toBeNull()
    expect(columns.get(id16(3))).toBe('applied')
  })
})
