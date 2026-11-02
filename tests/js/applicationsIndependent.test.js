import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'
import * as store from '../../scripts/application-store.js'
import * as client from '../../src/modules/applications/applicationsClient.js'
import { applicationOnlyJobs, trackerStats } from '../../src/modules/applications/trackingView.js'
import { applicationStatistics } from '../../src/modules/applications/applicationStatistics.js'
import { buildBoard } from '../../src/modules/applications/boardModel.js'
import { draftFrom, newRequestId, panelMode, saveDraft, voidApplication } from '../../src/modules/applications/trackerController.js'
import { JOBS_STORAGE_KEY, loadJobs, saveJobs } from '../../src/modules/jobs/jobStorage.js'
import { invalidateJobs } from '../../src/modules/jobs/jobsStore.js'
import { applicationOpenTarget } from '../../src/modules/jobs/jobRoute.js'
import { computeJobStats } from '../../src/modules/jobs/jobStats.js'
import { resolveJob } from '../../src/modules/jobs/jobResolve.js'
import { buildAiContext, buildApplicationContext, buildSkillGapContext } from '../../src/modules/ai/aiContextBuilder.js'

const id16 = (n) => crypto.createHash('sha256').update(`independent-${n}`).digest('hex').slice(0, 16)
const items = new Map()
let root
let server
const cache = () => client.getApplicationsState()
const stats = () => trackerStats(cache().store, cache().settings)

beforeEach(async () => {
  items.clear()
  vi.stubGlobal('localStorage', {
    getItem: (k) => (items.has(k) ? items.get(k) : null),
    setItem: (k, v) => items.set(k, String(v)),
    removeItem: (k) => items.delete(k),
  })
  invalidateJobs()
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'independent-'))
  server = http.createServer(async (req, res) => {
    if (!(await store.handleApplicationsRequest(req, res, req.url.split('?')[0], { root }))) { res.statusCode = 418; res.end() }
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  client.configureClient({ base: `http://127.0.0.1:${server.address().port}`, ensure: async () => true })
  await client.refreshApplications()
})

afterEach(async () => {
  client.configureClient()
  vi.unstubAllGlobals()
  await new Promise((resolve) => server.close(resolve))
  fs.rmSync(root, { recursive: true, force: true })
})

async function apply(n, { channel = 'company_site', newAttempt } = {}) {
  const jobId = id16(n)
  const { application } = await client.createApplication({
    requestId: newRequestId(),
    jobId,
    posting: { jobId, title: `Role ${n}`, company: `Company ${n}`, jobUrl: `https://c${n}.example/job`, description: `AD-TEXT-${n}` },
    attempt: { channel, channelDetail: '', applicationUrl: 'https://apply.example/APPLY-URL-CANARY', appliedDate: '2026-10-20', cv: { kind: 'unknown' } },
    ...(newAttempt ? { newAttempt } : {}),
  })
  return application
}
const row = (id, extra = {}) => ({ jobId: id, title: `Row ${id}`, company: 'Acme', status: 'new', ...extra })
const save = (jobs) => { saveJobs({ meta: null, jobs, filters: {}, importedAt: null }); invalidateJobs() }

describe('tracker stats come from the store', () => {
  it('counts an application that has no browser row', async () => {
    await apply(1)
    expect(computeJobStats([]).crmApplied).toBe(0)
    expect(stats()).toEqual({ crmApplied: 1, crmInterviewing: 0, crmOffers: 0, crmRejected: 0, crmFollowUpsDue: 0 })
  })

  it('agrees with the board and Application Statistics', async () => {
    await apply(1)
    await apply(2)
    const b = buildBoard(cache().store, cache().settings, '2026-11-03')
    expect(stats().crmApplied).toBe(2)
    expect(b.total).toBe(2)
    expect(applicationStatistics(cache().store, cache().settings, '2026-11-03').total).toBe(2)
  })

  it('counts two attempts at one job twice, as the board does', async () => {
    await apply(1)
    await apply(1, { channel: 'email', newAttempt: { distinctReason: 'different_channel' } })
    expect(stats().crmApplied).toBe(2)
    expect(buildBoard(cache().store, cache().settings, '2026-11-03').total).toBe(2)
  })

  it('counts stages, outcomes and follow-ups, each without a row', async () => {
    const a = await apply(1)
    await saveDraft(a.id, { ...draftFrom(cache().store.applications[a.id]), stage: 'tech', followUpDate: '2020-01-01' })
    const b = await apply(2)
    await saveDraft(b.id, { ...draftFrom(cache().store.applications[b.id]), stage: 'rejected' })
    expect(stats()).toEqual({ crmApplied: 2, crmInterviewing: 1, crmOffers: 0, crmRejected: 1, crmFollowUpsDue: 1 })
  })

  it('leaves a voided application out', async () => {
    const a = await apply(1)
    await apply(2)
    await voidApplication(a.id, 'mistake')
    expect(stats().crmApplied).toBe(1)
  })

  it('has nothing to say before the store is loaded', () => {
    expect(trackerStats(null, undefined)).toBeNull()
  })
})

describe('an application without a browser row', () => {
  it('is on the board with its job id, and its card opens Job Details', async () => {
    const a = await apply(1)
    const card = buildBoard(cache().store, cache().settings, '2026-11-03').columns.flatMap((c) => c.cards).find((c) => c.appId === a.id)
    expect(applicationOpenTarget(loadJobs().jobs, card.jobId)).toEqual({ kind: 'page', jobId: id16(1) })
  })

  it('opens from its own frozen posting, in tracked mode, so notes and follow-ups work', async () => {
    const a = await apply(1)
    const resolved = resolveJob({ applications: Object.values(cache().store.applications), fileChecked: true })
    expect(resolved).toMatchObject({ status: 'found', source: 'application', notInLatest: true, job: { jobId: id16(1), title: 'Role 1', description: 'AD-TEXT-1' } })
    expect(panelMode(resolved.job, cache()).mode).toBe('tracked')

    await client.addEvent(a.id, { type: 'note_added', data: { text: 'a note' } })
    await saveDraft(a.id, { ...draftFrom(cache().store.applications[a.id]), followUpDate: '2026-12-01' })
    const fresh = cache().store.applications[a.id]
    expect(fresh.events.map((e) => e.type)).toContain('note_added')
    expect(draftFrom(fresh).followUpDate).toBe('2026-12-01')
  })

  it('opening it writes nothing to the browser list', async () => {
    await apply(1)
    save([])
    const before = localStorage.getItem(JOBS_STORAGE_KEY)
    expect(before).not.toBeNull()
    resolveJob({ applications: Object.values(cache().store.applications), fileChecked: true })
    applicationOnlyJobs(loadJobs().jobs, cache().store, cache().settings)
    expect(localStorage.getItem(JOBS_STORAGE_KEY)).toBe(before)
    expect(loadJobs().jobs).toEqual([])
  })
})

describe('applicationOnlyJobs', () => {
  it('lists jobs with an active application and no row, one per job, carrying the latest attempt', async () => {
    await apply(1)
    await apply(1, { channel: 'email', newAttempt: { distinctReason: 'different_channel' } })
    await apply(2)
    const list = applicationOnlyJobs([row(id16(2))], cache().store, cache().settings)
    expect(list.map((j) => j.jobId)).toEqual([id16(1)])
    expect(list[0]).toMatchObject({ title: 'Role 1', jobUrl: 'https://c1.example/job', status: 'applied_manually', applicationTracking: { applied: true } })
  })

  it('treats an offList row as a row', async () => {
    await apply(1)
    expect(applicationOnlyJobs([row(id16(1), { offList: true })], cache().store, cache().settings)).toEqual([])
  })

  it('leaves a job out when every attempt is voided', async () => {
    const a = await apply(1)
    await voidApplication(a.id, 'mistake')
    expect(applicationOnlyJobs([], cache().store, cache().settings)).toEqual([])
  })
})

describe('AI contexts', () => {
  const on = (id) => row(id, { matchScore: 80, missingSkills: ['OnSkill'], priority: 'P1', applyRecommendation: 'Apply' })

  it('the application context holds an application without a row, safely', async () => {
    const a = await apply(1)
    await client.addEvent(a.id, { type: 'note_added', data: { text: 'NOTE-CANARY' } })
    await saveDraft(a.id, { ...draftFrom(cache().store.applications[a.id]), recruiterName: 'RECRUITER-CANARY', recruiterEmail: 'canary@recruiter.example' })
    save([])
    const context = buildApplicationContext()
    expect(context.applied.map((j) => j.jobId)).toEqual([id16(1)])
    expect(context.applied[0]).toMatchObject({ title: 'Role 1', company: 'Company 1', description: 'AD-TEXT-1' })
    const text = JSON.stringify(context)
    for (const canary of ['NOTE-CANARY', 'RECRUITER-CANARY', 'canary@recruiter.example', 'APPLY-URL-CANARY', 'https://c1.example']) expect(text).not.toContain(canary)
  })

  it('jobStats count it', async () => {
    await apply(1)
    save([on('on1')])
    expect(buildAiContext({ featureId: 'chat' }).jobStats).toMatchObject({ total: 1, crmApplied: 1 })
  })

  it('an application does not leak into top jobs or the skill gap', async () => {
    await apply(1)
    save([on('on1'), row('off1', { matchScore: 99, missingSkills: ['OffSkill'], offList: true, status: 'saved', applyRecommendation: 'Apply' })])
    const context = buildAiContext({ featureId: 'careerStrategy' })
    expect(context.topJobs.map((j) => j.jobId)).toEqual(['on1'])
    expect(buildSkillGapContext()).toEqual({ topMissing: [{ skill: 'OnSkill', count: 1 }], jobCount: 1 })
    expect(context.applications.applied.map((j) => j.jobId)).toEqual([id16(1)])
  })

  it('a ledger-only ad reaches no context: nothing reads the ledger there', async () => {
    const sources = fs.readFileSync(new URL('../../src/modules/ai/aiContextBuilder.js', import.meta.url), 'utf-8')
    expect(sources).not.toMatch(/jobs\/history|loadJobHistory|jobResolve/)
    save([on('on1')])
    const context = buildAiContext({ featureId: 'careerStrategy' })
    expect(JSON.stringify(context)).not.toContain('LEDGER-ONLY')
  })
})
