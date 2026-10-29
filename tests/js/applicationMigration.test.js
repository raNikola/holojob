import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import * as store from '../../scripts/application-store.js'
import { foldApplication, isActive } from '../../src/modules/applications/foldApplication.js'
import { INTERVIEW_STAGES } from '../../src/modules/jobs/applicationTracking.js'

const NOW = new Date('2026-11-03T10:00:00.000Z')
const id16 = (n) => crypto.createHash('sha256').update(`job-${n}`).digest('hex').slice(0, 16)
const ID = { full: id16('full'), onlyStage: id16('only-stage'), notesOnly: id16('notes'), statusOnly: id16('status'), ledger: id16('ledger'), slim: id16('slim'), tracked: id16('tracked'), blank: id16('blank'), untracked: id16('untracked') }

const FULL_TRACKING = {
  applied: true,
  appliedDate: '2026-10-12',
  applicationUrl: 'https://acme.example/apply/1',
  recruiterName: 'Jane Doe',
  recruiterEmail: 'jane@acme.example',
  recruiterLinkedIn: 'https://linkedin.com/in/jane',
  notes: '  Spoke on the phone.\nSecond line  ',
  followUpDate: '2026-10-30',
  interviewStage: 'Technical Round 2',
  lastUpdated: '2026-10-20T08:30:00.000Z',
}
const scoredJob = (jobId, extra = {}) => ({
  jobId, provider: 'greenhouse', source: 'greenhouse', title: `Product Manager ${jobId.slice(0, 4)}`, company: 'Acme',
  location: 'Remote', jobUrl: `https://acme.example/jobs/${jobId}`, description: 'Own the roadmap.', ...extra,
})
const slim = (jobId, extra = {}) => ({ jobId, title: `Slim PM ${jobId.slice(0, 4)}`, company: 'Beta', ...extra })

let root
let clock
const now = () => clock
const storeFile = () => path.join(root, 'data/applications/applications.json')
const storeBytes = () => (fs.existsSync(storeFile()) ? fs.readFileSync(storeFile()) : null)
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex')
const clone = (v) => JSON.parse(JSON.stringify(v))
const tree = (dir) => (fs.existsSync(dir)
  ? fs.readdirSync(dir, { recursive: true }).sort().map((f) => `${f}:${fs.statSync(path.join(dir, f)).mtimeMs}`)
  : null)
const preview = (jobs) => store.previewMigration(root, { jobs }, { now })
const migrate = async (jobs, extra = {}) => store.migrateApplications(root, {
  jobs, confirm: true, previewSha: store.previewShaOf(jobs), ...extra,
}, { now })
const getStore = () => store.loadStore(root)
const backups = () => (fs.existsSync(path.join(root, 'data/backups')) ? fs.readdirSync(path.join(root, 'data/backups')).filter((d) => d.startsWith('applications-')) : [])

/** The fixture of 6d: one job per case. */
function fixture() {
  return [
    { ...scoredJob(ID.full), status: 'applied_manually', applicationTracking: { ...FULL_TRACKING } },
    { ...slim(id16('stage-key')), applicationTracking: { stage: 'applied' } },
    { ...slim(ID.notesOnly), applicationTracking: { applied: false, notes: 'Think about it', lastUpdated: '2026-10-01T10:00:00.000Z' } },
    { ...slim(ID.statusOnly), status: 'applied_manually' },
    ...INTERVIEW_STAGES.map((stage, i) => ({
      ...slim(id16(`stage-${i}`)),
      applicationTracking: { applied: true, appliedDate: '2026-10-05', interviewStage: stage, lastUpdated: '2026-10-06T09:00:00.000Z' },
    })),
    { ...slim(ID.slim, { description: '' }), applicationTracking: { applied: true, appliedDate: '2026-10-02' } },
    { ...slim(ID.ledger), applicationTracking: { applied: true, appliedDate: '2026-10-03' } },
    { ...slim(ID.blank), applicationTracking: { applied: false, appliedDate: '', notes: '', lastUpdated: '2026-10-09T09:00:00.000Z' } },
    { ...slim(ID.untracked) },
  ]
}

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'mig-'))
  clock = new Date(NOW)
  fs.mkdirSync(path.join(root, 'data/jobs'), { recursive: true })
  fs.writeFileSync(path.join(root, 'data/jobs/scored_jobs.json'), JSON.stringify({ meta: {}, jobs: [scoredJob(ID.full), scoredJob(ID.tracked)] }))
  fs.writeFileSync(path.join(root, 'data/jobs/job_history.json'), JSON.stringify({
    jobs: { [ID.ledger]: { job: { ...scoredJob(ID.ledger), title: 'Ledger-only PM', description: 'From the ledger.' } } },
  }))
})

afterEach(() => {
  vi.restoreAllMocks()
  fs.rmSync(root, { recursive: true, force: true })
})

describe('plan and dry run', () => {
  it('counts every job once and maps each candidate', async () => {
    const jobs = fixture()
    const res = await preview(jobs)
    expect(res.dryRun).toBe(true)
    const { counts } = res
    expect(counts.scanned).toBe(jobs.length)
    expect(counts.ignored + counts.candidates).toBe(counts.scanned)
    expect(counts.candidates).toBe(counts.created + counts.alreadyMigrated + counts.alreadyTracked + counts.unmappable)
    expect(counts).toMatchObject({ ignored: 2, created: jobs.length - 2, alreadyMigrated: 0, alreadyTracked: 0, unmappable: 0 })
    expect(res.toCreate).toBe(counts.created)
    expect(res.previewSha).toBe(store.previewShaOf(jobs))

    const entry = (jobId) => res.entries.find((e) => e.jobId === jobId)
    expect(entry(ID.full)).toMatchObject({
      action: 'create', appId: `mig-${ID.full}`, capturedFrom: 'scored_jobs',
      events: ['applied', 'contact_added', 'note_added', 'follow_up_set', 'stage_changed'], warnings: [],
    })
    expect(entry(ID.ledger)).toMatchObject({ capturedFrom: 'job_history' })
    expect(entry(ID.slim).warnings).toContain('the snapshot has no description')
    expect(entry(ID.notesOnly).warnings).toEqual(expect.arrayContaining(['tracked but not marked applied', 'no applied date']))
    expect(entry(id16('stage-key')).warnings.join(' ')).toContain('unmapped keys kept only in legacy: stage')
    expect(entry(ID.statusOnly)).toMatchObject({ events: ['applied'] })
    expect(entry(ID.blank)).toBeUndefined()
    expect(entry(ID.untracked)).toBeUndefined()
  })

  it('writes nothing: no files, no mtimes changed', async () => {
    const before = [tree(path.join(root, 'data'))]
    await preview(fixture())
    expect(tree(path.join(root, 'data'))).toEqual(before[0])
    expect(fs.existsSync(path.join(root, 'data/applications'))).toBe(false)
    expect(backups()).toEqual([])
  })

  it('lists what cannot be mapped and still balances', async () => {
    const dup = slim(id16('dup'), { applicationTracking: { applied: true } })
    const jobs = [
      { ...slim('not-hex'), applicationTracking: { applied: true } },
      dup,
      clone(dup),
      { jobId: id16('notitle'), applicationTracking: { applied: true } },
      { ...slim(id16('badobj')), applicationTracking: 'yes' },
      { ...slim(id16('baddate')), applicationTracking: { applied: true, appliedDate: 'last week', followUpDate: 'soon', interviewStage: 'Coffee chat' } },
    ]
    const res = await preview(jobs)
    expect(res.counts).toMatchObject({ candidates: 6, created: 2, unmappable: 4 })
    expect(res.entries.filter((e) => e.action === 'unmappable').map((e) => e.reason)).toEqual([
      'jobId is not 16 hex characters', 'jobId appears twice in the payload',
      'no source has a title and a company for this job', 'applicationTracking is not an object',
    ])
    const odd = res.entries.find((e) => e.jobId === id16('baddate'))
    expect(odd.events).toEqual(['applied'])
    expect(odd.warnings.join('|')).toMatch(/appliedDate "last week" is not a date.*followUpDate "soon".*unknown interviewStage "Coffee chat"/)
  })

  it('refuses a body that is not a job list', async () => {
    for (const body of [{}, { jobs: 'x' }, { jobs: [1] }, { jobs: [[]] }]) {
      await expect(store.previewMigration(root, body, { now })).rejects.toMatchObject({ status: 400 })
    }
  })

  it('warns when a default target stage is not on the board', async () => {
    fs.mkdirSync(path.join(root, 'data/applications'), { recursive: true })
    const settings = store.loadSettings(root)
    settings.stages.work.find((s) => s.key === 'offer').retired = true
    fs.writeFileSync(path.join(root, 'data/applications/settings.json'), JSON.stringify(settings))
    const res = await preview([{ ...slim(id16('o')), applicationTracking: { applied: true, appliedDate: '2026-10-01', interviewStage: 'Offer' } }])
    expect(res.entries[0].warnings.join()).toContain('target stage "offer" is not on the board')
  })
})

describe('apply', () => {
  it('refuses without confirm or with the hash of another job list, writing nothing', async () => {
    const jobs = fixture()
    const before = tree(path.join(root, 'data'))
    for (const body of [
      { jobs }, { jobs, confirm: true }, { jobs, previewSha: store.previewShaOf(jobs) },
      { jobs, confirm: true, previewSha: store.previewShaOf(jobs.slice(1)) }, { jobs, confirm: 'yes', previewSha: store.previewShaOf(jobs) },
    ]) {
      await expect(store.migrateApplications(root, body, { now })).rejects.toMatchObject({ status: 409 })
    }
    expect(tree(path.join(root, 'data'))).toEqual(before)
  })

  it('is lossless: every legacy field is in the new record, the original is kept verbatim', async () => {
    const jobs = fixture()
    const original = clone(jobs)
    const res = await migrate(jobs)
    expect(res.verified).toBe(true)
    expect(jobs).toEqual(original) // jobs without tracking, and tracked ones, are not touched
    const apps = getStore().applications
    const app = apps[`mig-${ID.full}`]
    expect(app).toMatchObject({ origin: 'migration', legacy: FULL_TRACKING })
    expect(app.attempt).toMatchObject({ appliedDate: '2026-10-12', applicationUrl: FULL_TRACKING.applicationUrl, channel: 'other', cv: { kind: 'unknown' } })
    expect(app.posting).toMatchObject({ jobId: ID.full, capturedFrom: 'scored_jobs', capturedAfterApply: true, descriptionMissing: false })
    expect(app.events.map((e) => [e.type, e.date, e.at, e.source])).toEqual([
      ['applied', '2026-10-12', '2026-10-20T08:30:00.000Z', 'migration'],
      ['contact_added', '2026-10-20', '2026-10-20T08:30:00.000Z', 'migration'],
      ['note_added', '2026-10-20', '2026-10-20T08:30:00.000Z', 'migration'],
      ['follow_up_set', '2026-10-20', '2026-10-20T08:30:00.000Z', 'migration'],
      ['stage_changed', '2026-10-20', '2026-10-20T08:30:00.000Z', 'migration'],
    ])
    expect(app.events[1].data).toEqual({ contactId: 'c1', role: 'recruiter', name: 'Jane Doe', email: 'jane@acme.example', linkedin: 'https://linkedin.com/in/jane' })
    expect(app.events[2].data.text).toBe(FULL_TRACKING.notes) // whitespace kept
    expect(app.events[3].data).toEqual({ dueDate: '2026-10-30' })
    expect(app.events[4].data).toEqual({ stage: 'tech', legacyStage: 'Technical Round 2' })
    expect(foldApplication(app)).toMatchObject({ stage: 'tech', followUpDate: '2026-10-30', appliedDate: '2026-10-12' })

    // every INTERVIEW_STAGES value and the other fixture cases
    const stage = (i) => foldApplication(apps[`mig-${id16(`stage-${i}`)}`])
    expect(INTERVIEW_STAGES.map((_, i) => [stage(i).stage, stage(i).outcome])).toEqual([
      ['applied', null], ['screen', null], ['tech', null], ['tech', null], ['tech', null],
      ['onsite', null], ['onsite', null], ['offer', null], ['applied', 'rejected'], ['applied', 'withdrawn'],
    ])
    expect(apps[`mig-${id16('stage-key')}`].legacy).toEqual({ stage: 'applied' })
    expect(apps[`mig-${ID.notesOnly}`]).toMatchObject({ attempt: { appliedDate: null } })
    expect(apps[`mig-${ID.notesOnly}`].events.map((e) => e.type)).toEqual(['applied', 'note_added'])
    expect(apps[`mig-${ID.statusOnly}`]).toMatchObject({ legacy: null })
    expect(apps[`mig-${ID.slim}`].posting.descriptionMissing).toBe(true)
    expect(apps[`mig-${ID.ledger}`].posting).toMatchObject({ title: 'Ledger-only PM', capturedFrom: 'job_history' })
    expect(apps[`mig-${ID.blank}`]).toBeUndefined()
    expect(apps[`mig-${ID.untracked}`]).toBeUndefined()
    expect(Object.keys(apps)).toHaveLength(res.counts.created)
  })

  it('migrates an applied job that is no longer in the discovered list', async () => {
    const gone = slim(id16('gone'), { applicationTracking: { applied: true, appliedDate: '2026-09-01', interviewStage: 'HR Screen' } })
    await migrate([gone])
    const app = getStore().applications[`mig-${id16('gone')}`]
    expect(app.posting).toMatchObject({ capturedFrom: 'browser', title: gone.title })
    expect(isActive(app)).toBe(true)
  })

  it('writes a backup of the old store and the raw job list before the store', async () => {
    const first = [{ ...slim(id16('b1')), applicationTracking: { applied: true, appliedDate: '2026-10-01' } }]
    await migrate(first)
    const storeBefore = storeBytes()
    const second = [...first, { ...slim(id16('b2')), applicationTracking: { applied: true, appliedDate: '2026-10-02' } }]
    clock = new Date('2026-11-04T10:00:00.000Z')
    const res = await migrate(second)
    const dir = path.join(root, res.backupPath)
    expect(res.backupPath).toMatch(/^data\/backups\/applications-20261104-\d{6}$/)
    expect(JSON.parse(fs.readFileSync(path.join(dir, 'legacy-jobs.json'), 'utf-8'))).toEqual(second)
    expect(sha(fs.readFileSync(path.join(dir, 'applications.json')))).toBe(sha(storeBefore))
    expect(fs.statSync(path.join(dir, 'legacy-jobs.json')).mtimeMs).toBeLessThanOrEqual(fs.statSync(storeFile()).mtimeMs)
  })

  it('a failed backup stops everything: no store, no log', async () => {
    fs.mkdirSync(path.join(root, 'data'), { recursive: true })
    fs.writeFileSync(path.join(root, 'data/backups'), 'a file where the directory should be')
    await expect(migrate(fixture())).rejects.toMatchObject({ status: 500, message: expect.stringContaining('Backup failed') })
    expect(storeBytes()).toBeNull()
    expect(fs.existsSync(path.join(root, 'data/applications/migration.json'))).toBe(false)
  })

  it('the field-level check finds a lost note and a changed legacy object', async () => {
    const jobs = [{ ...slim(id16('v1')), applicationTracking: { applied: true, appliedDate: '2026-10-01', notes: 'n' } }]
    const plan = store.planMigration(jobs, { store: store.emptyStore(), settings: store.loadSettings(root), now: NOW })
    const next = { ...store.emptyStore(), applications: clone(plan.applications) }
    expect(store.verifyMigration(jobs, plan, next, store.emptyStore())).toEqual([])
    next.applications[`mig-${id16('v1')}`].events.pop() // the note is lost
    expect(store.verifyMigration(jobs, plan, next, store.emptyStore())).toEqual(expect.arrayContaining([
      `mig-${id16('v1')}: notes differ`,
    ]))
    const changedLegacy = clone(next)
    changedLegacy.applications[`mig-${id16('v1')}`].legacy.notes = 'other'
    expect(store.verifyMigration(jobs, plan, changedLegacy, store.emptyStore())).toEqual(expect.arrayContaining([
      `mig-${id16('v1')}: legacy differs from the original`,
    ]))
  })

  it('zero tracked applications is a valid run: log and backup, no store', async () => {
    const jobs = [slim(id16('z1')), { ...slim(id16('z2')), applicationTracking: { applied: false, lastUpdated: '2026-10-01T00:00:00.000Z' } }]
    const dry = await preview(jobs)
    expect(dry.counts).toEqual({ scanned: 2, ignored: 2, candidates: 0, created: 0, alreadyMigrated: 0, alreadyTracked: 0, unmappable: 0 })
    const res = await migrate(jobs)
    expect(res.counts.created).toBe(0)
    expect(storeBytes()).toBeNull()
    const log = JSON.parse(fs.readFileSync(path.join(root, 'data/applications/migration.json'), 'utf-8'))
    expect(log.runs).toHaveLength(1)
    expect(log.runs[0]).toMatchObject({ counts: { candidates: 0 }, backupPath: res.backupPath })
    expect(backups()).toHaveLength(1)
  })
})

describe('idempotency and later work', () => {
  it('a second run adds nothing and leaves the store byte-identical', async () => {
    const jobs = fixture()
    const first = await migrate(jobs)
    const bytes = storeBytes()
    clock = new Date('2026-11-05T10:00:00.000Z')
    const dry = await preview(jobs)
    expect(dry.toCreate).toBe(0)
    const second = await migrate(jobs)
    expect(second.counts).toMatchObject({ created: 0, alreadyMigrated: first.counts.created })
    expect(sha(storeBytes())).toBe(sha(bytes))
    const log = JSON.parse(fs.readFileSync(path.join(root, 'data/applications/migration.json'), 'utf-8'))
    expect(log.runs.map((r) => r.counts.created)).toEqual([first.counts.created, 0])
  })

  it('an existing mig- record is never rebuilt, even after user events', async () => {
    const jobs = [{ ...slim(id16('u1')), applicationTracking: { applied: true, appliedDate: '2026-10-01', notes: 'old' } }]
    await migrate(jobs)
    const appId = `mig-${id16('u1')}`
    await store.appendEvent(root, appId, { type: 'note_added', data: { text: 'later note' } }, { now })
    const bytes = storeBytes()
    jobs[0].applicationTracking.notes = 'edited in the old panel'
    const res = await migrate(jobs)
    expect(res.counts).toMatchObject({ created: 0, alreadyMigrated: 1 })
    expect(storeBytes()).toEqual(bytes)
  })

  it('a voided migrated application stays voided on a re-run', async () => {
    const jobs = [{ ...slim(id16('v2')), applicationTracking: { applied: true, appliedDate: '2026-10-01' } }]
    await migrate(jobs)
    const appId = `mig-${id16('v2')}`
    await store.appendEvent(root, appId, { type: 'application_voided', data: { reason: 'entered by mistake' } }, { now })
    await migrate(jobs)
    const app = getStore().applications[appId]
    expect(isActive(app)).toBe(false)
    expect(Object.keys(getStore().applications)).toEqual([appId])
    expect((await preview(jobs)).entries[0].action).toBe('alreadyMigrated')
  })
})

describe('the same posting', () => {
  const create = (overrides = {}) => store.createApplication(root, {
    requestId: crypto.randomUUID(), jobId: ID.tracked,
    attempt: { channel: 'company_site', appliedDate: '2026-10-10', cv: { kind: 'unknown' } }, ...overrides,
  }, { now })

  it('an open legacy record next to an open app- is one attempt, not a second application', async () => {
    const app = (await create()).application
    const jobs = [{ ...scoredJob(ID.tracked), applicationTracking: { applied: true, appliedDate: '2026-10-10', interviewStage: 'HR Screen' } }]
    const res = await migrate(jobs)
    expect(res.counts).toMatchObject({ created: 0, alreadyTracked: 1 })
    expect(res.entries[0]).toMatchObject({ action: 'alreadyTracked', appId: app.id })
    expect(Object.keys(getStore().applications)).toEqual([app.id])
  })

  it('the same setup with the app- voided is migrated', async () => {
    const app = (await create()).application
    await store.appendEvent(root, app.id, { type: 'application_voided', data: { reason: 'r' } }, { now })
    const res = await migrate([{ ...scoredJob(ID.tracked), applicationTracking: { applied: true, appliedDate: '2026-10-10' } }])
    expect(res.counts).toMatchObject({ created: 1, alreadyTracked: 0 })
    expect(Object.keys(getStore().applications)).toHaveLength(2)
  })

  it('a rejected legacy record is a separate earlier attempt next to an open app-', async () => {
    const app = (await create()).application
    const res = await migrate([{ ...scoredJob(ID.tracked), applicationTracking: { applied: true, appliedDate: '2026-09-01', interviewStage: 'Rejected' } }])
    expect(res.counts).toMatchObject({ created: 1, alreadyTracked: 0 })
    const apps = Object.values(getStore().applications)
    expect(apps.map((a) => a.id).sort()).toEqual([app.id, `mig-${ID.tracked}`].sort())
    expect(apps.every(isActive)).toBe(true)
    expect(foldApplication(getStore().applications[`mig-${ID.tracked}`]).outcome).toBe('rejected')
    // re-running adds nothing, and the app- is untouched
    const again = await migrate([{ ...scoredJob(ID.tracked), applicationTracking: { applied: true, appliedDate: '2026-09-01', interviewStage: 'Rejected' } }])
    expect(again.counts).toMatchObject({ created: 0, alreadyMigrated: 1 })
    expect(Object.keys(getStore().applications)).toHaveLength(2)
  })

  it('an Offer legacy record is open, so an open app- makes it alreadyTracked', async () => {
    await create()
    const res = await preview([{ ...scoredJob(ID.tracked), applicationTracking: { applied: true, interviewStage: 'Offer' } }])
    expect(res.counts).toMatchObject({ alreadyTracked: 1, created: 0 })
  })
})

describe('routes', () => {
  let server
  let base
  beforeEach(async () => {
    server = http.createServer(async (req, res) => {
      if (!(await store.handleApplicationsRequest(req, res, req.url.split('?')[0], { root, now }))) { res.statusCode = 418; res.end() }
    })
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
    base = `http://127.0.0.1:${server.address().port}`
  })
  afterEach(async () => { await new Promise((resolve) => server.close(resolve)) })
  const post = async (url, body) => {
    const res = await fetch(`${base}${url}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    return { status: res.status, json: await res.json() }
  }

  it('preview, then apply with its hash; apply without it is 409', async () => {
    const jobs = [{ ...slim(id16('r1')), applicationTracking: { applied: true, appliedDate: '2026-10-01' } }]
    const dry = await post('/api/applications/migrate/preview', { jobs })
    expect(dry.status).toBe(200)
    expect(dry.json).toMatchObject({ dryRun: true, toCreate: 1 })
    expect(storeBytes()).toBeNull()
    const refused = await post('/api/applications/migrate', { jobs, confirm: true })
    expect(refused.status).toBe(409)
    expect(storeBytes()).toBeNull()
    const done = await post('/api/applications/migrate', { jobs, confirm: true, previewSha: dry.json.previewSha })
    expect(done.status).toBe(200)
    expect(done.json).toMatchObject({ dryRun: false, verified: true, counts: { created: 1 } })
    expect((await post('/api/applications/migrate/preview', { jobs: 'x' })).status).toBe(400)
  })
})
