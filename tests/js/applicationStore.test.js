import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import * as store from '../../scripts/application-store.js'
import { createBackupStream, importBackupZip } from '../../scripts/backup-handler.js'
import { deleteCvFile } from '../../scripts/cv-store.js'
import { daysBetween, daysInCurrentStage, daysInStage, foldApplication, isActive } from '../../src/modules/applications/foldApplication.js'
import { boardColumn, labelFor } from '../../src/modules/applications/stageRegistry.js'

const require = createRequire(import.meta.url)
const AdmZip = require('adm-zip')

const JOB = {
  jobId: 'a1b2c3d4e5f60718',
  provider: 'greenhouse',
  source: 'greenhouse',
  title: 'Senior Product Manager, Payments',
  company: 'Acme Payments',
  location: 'Remote (EU)',
  jobUrl: 'https://boards.greenhouse.io/acme/jobs/123',
  description: 'We are looking for a product manager.',
  datePosted: '2026-10-20',
  salary: '',
  employmentType: 'full-time',
  isRemote: true,
}
const OTHER_BOARD_JOB = { ...JOB, jobId: 'ffff000011112222', jobUrl: 'https://www.linkedin.com/jobs/view/9' }
const CV_A = '0123456789abcdef'
const CV_B = 'fedcba9876543210'
const PDF_A = Buffer.from('%PDF-1.4\nCV version A')
const PDF_B = Buffer.from('%PDF-1.4\nCV version B')
const TAILORED = Buffer.from('%PDF-1.4\ntailored for Acme')

let root
let server
let base
let clock

const sha = (data) => crypto.createHash('sha256').update(data).digest('hex')
const storeFile = () => path.join(root, 'data/applications/applications.json')
const storeBytes = () => (fs.existsSync(storeFile()) ? fs.readFileSync(storeFile()) : null)
const now = () => clock
let seq = 0
const rid = () => `req-${(seq += 1)}-${crypto.randomUUID()}`

function makeRoot() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'apps-'))
  fs.mkdirSync(path.join(dir, 'data/jobs'), { recursive: true })
  fs.writeFileSync(path.join(dir, 'data/jobs/scored_jobs.json'), JSON.stringify({ meta: {}, jobs: [JOB, OTHER_BOARD_JOB] }))
  fs.mkdirSync(path.join(dir, 'data/profile/cvs'), { recursive: true })
  fs.writeFileSync(path.join(dir, `data/profile/cvs/${CV_A}.pdf`), PDF_A)
  fs.writeFileSync(path.join(dir, `data/profile/cvs/${CV_B}.pdf`), PDF_B)
  fs.mkdirSync(path.join(dir, `data/resumes/${JOB.jobId}`), { recursive: true })
  fs.writeFileSync(path.join(dir, `data/resumes/${JOB.jobId}/Acme_Resume.pdf`), TAILORED)
  return dir
}

beforeEach(async () => {
  root = makeRoot()
  clock = new Date('2026-11-03T10:00:00.000Z')
  server = http.createServer(async (req, res) => {
    const handled = await store.handleApplicationsRequest(req, res, req.url.split('?')[0], { root, now })
    if (!handled) {
      res.statusCode = 418
      res.end()
    }
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  base = `http://127.0.0.1:${server.address().port}`
})

afterEach(async () => {
  vi.restoreAllMocks()
  await new Promise((resolve) => server.close(resolve))
  fs.rmSync(root, { recursive: true, force: true })
})

async function call(method, url, body) {
  const res = await fetch(`${base}${url}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await res.text()
  let json = null
  try { json = JSON.parse(text) } catch { /* binary */ }
  return { status: res.status, json, text }
}

function createBody(overrides = {}) {
  const { attempt = {}, ...rest } = overrides
  return {
    requestId: rid(),
    jobId: JOB.jobId,
    attempt: {
      channel: 'company_site',
      channelDetail: 'Greenhouse form',
      applicationUrl: `${JOB.jobUrl}#app`,
      appliedDate: '2026-11-03',
      cv: { kind: 'library', cvLibraryId: CV_A, label: 'Main CV', fileName: 'Nikola_CV.pdf' },
      ...attempt,
    },
    ...rest,
  }
}

const create = (overrides) => call('POST', '/api/applications', createBody(overrides))
const addEvent = (id, body) => call('POST', `/api/applications/${id}/events`, body)
const getStore = async () => (await call('GET', '/api/applications')).json
const activeIds = (s) => Object.values(s.applications).filter(isActive).map((a) => a.id).sort()

/** The counts every statistic is built from, read through the one filter. */
function stats(apps) {
  const folded = apps.filter(isActive).map(foldApplication)
  const count = (key) => folded.reduce((acc, f) => ({ ...acc, [f[key]]: (acc[f[key]] ?? 0) + 1 }), {})
  return {
    applications: folded.length,
    outcomes: count('outcome'),
    stages: count('stage'),
    offers: folded.filter((f) => f.outcome === 'offer_accepted').length,
    followUpsDue: folded.filter((f) => f.followUpDate && f.followUpDate <= '2026-11-20').length,
  }
}

// --- data integrity ----------------------------------------------------------------------------

describe('data integrity', () => {
  it('creates an application with a frozen snapshot, attempt and first event', async () => {
    const { status, json } = await create()
    expect(status).toBe(201)
    const app = json.application
    expect(app.id).toMatch(/^app-[0-9a-f]{16}$/)
    expect(app.posting).toMatchObject({
      jobId: JOB.jobId, postingKey: `job:${JOB.jobId}`, title: JOB.title, url: JOB.jobUrl,
      capturedFrom: 'scored_jobs', capturedAfterApply: false, descriptionMissing: false,
    })
    expect(app.posting.capturedAt).toBe(app.events[0].at)
    expect(app.events).toEqual([{
      id: `${app.id}:1`, seq: 1, type: 'applied', at: '2026-11-03T10:00:00.000Z',
      date: '2026-11-03', source: 'user', data: {},
    }])
    expect(app.attempt.cv).toEqual({
      kind: 'library', cvLibraryId: CV_A, label: 'Main CV', fileName: 'Nikola_CV.pdf', sha256: sha(PDF_A),
    })
    const disk = JSON.parse(storeBytes())
    expect(disk.applications[app.id]).toEqual(app)
    expect(fs.readdirSync(path.dirname(storeFile())).filter((f) => f.endsWith('.tmp'))).toEqual([])
  })

  it('leaves the old file intact and no temp file when the rename fails', async () => {
    const first = (await create()).json.application
    const before = storeBytes()
    vi.spyOn(fs, 'renameSync').mockImplementationOnce(() => { throw new Error('disk full') })
    const { status } = await addEvent(first.id, { type: 'note_added', data: { text: 'x' } })
    expect(status).toBe(500)
    expect(storeBytes()).toEqual(before)
    expect(fs.existsSync(`${storeFile()}.tmp`)).toBe(false)
  })

  it('leaves no partial file when the write dies half way', async () => {
    const first = (await create()).json.application
    const before = storeBytes()
    const realWrite = fs.writeFileSync
    vi.spyOn(fs, 'writeFileSync').mockImplementationOnce((fd, data) => {
      realWrite(fd, data.slice(0, 20))
      throw new Error('EIO')
    })
    const { status } = await addEvent(first.id, { type: 'note_added', data: { text: 'x' } })
    expect(status).toBe(500)
    expect(storeBytes()).toEqual(before)
    expect(fs.existsSync(`${storeFile()}.tmp`)).toBe(false)
  })

  it('removes the frozen copy when a create fails to save', async () => {
    vi.spyOn(fs, 'renameSync').mockImplementationOnce(() => { throw new Error('disk full') })
    expect((await create()).status).toBe(500)
    expect(storeBytes()).toBeNull()
    const files = path.join(root, 'data/applications/files')
    expect(fs.existsSync(files) ? fs.readdirSync(files) : []).toEqual([])
  })

  it('never writes over an unreadable store', async () => {
    fs.mkdirSync(path.dirname(storeFile()), { recursive: true })
    fs.writeFileSync(storeFile(), '{broken')
    expect((await create()).status).toBe(500)
    expect(fs.readFileSync(storeFile(), 'utf-8')).toBe('{broken')
  })

  it('appends keep the old log as a prefix and seq runs 1..n', async () => {
    const id = (await create()).json.application.id
    let prev = (await getStore()).applications[id]
    const bodies = [
      { type: 'stage_changed', data: { stage: 'screen' } },
      { type: 'note_added', data: { text: 'Call went well' } },
      { type: 'contact_added', data: { role: 'recruiter', name: 'Ana Example', email: 'ana@example.com' } },
      { type: 'message_sent', data: { via: 'email', contactId: 'c1' } },
      { type: 'follow_up_set', data: { dueDate: '2026-11-10' } },
      { type: 'stage_changed', data: { stage: 'tech' } },
    ]
    for (const body of bodies) {
      expect((await addEvent(id, body)).status).toBe(201)
      const next = (await getStore()).applications[id]
      expect(next.events.slice(0, prev.events.length)).toEqual(prev.events)
      expect(next.events.map((e) => e.seq)).toEqual(next.events.map((_, i) => i + 1))
      expect(() => store.assertAppendOnly(prev, next)).not.toThrow()
      prev = next
    }
    expect(prev.events[3].data.contactId).toBe('c1')
  })

  it('assertAppendOnly rejects any rewrite', async () => {
    const id = (await create()).json.application.id
    await addEvent(id, { type: 'note_added', data: { text: 'one' } })
    await addEvent(id, { type: 'note_added', data: { text: 'two' } })
    const app = (await getStore()).applications[id]
    const clone = () => structuredClone(app)
    const mutations = [
      (a) => { a.events[1].data.text = 'onE' },
      (a) => { a.events.splice(1, 1) },
      (a) => { a.events.reverse() },
      (a) => { a.posting.description = 'changed' },
      (a) => { a.attempt.channel = 'email' },
      (a) => { a.events.push({ ...a.events[2], seq: 5, id: `${id}:5` }) },
    ]
    for (const mutate of mutations) {
      const next = clone()
      mutate(next)
      expect(() => store.assertAppendOnly(app, next)).toThrow(/append-only/)
    }
    expect(() => store.assertAppendOnly(app, undefined)).toThrow(/removed/)
  })

  it('the snapshot stays frozen when the ad changes', async () => {
    const app = (await create()).json.application
    fs.writeFileSync(path.join(root, 'data/jobs/scored_jobs.json'), JSON.stringify({
      jobs: [{ ...JOB, title: 'Changed', description: 'New text', salary: '9000 EUR' }],
    }))
    const after = (await getStore()).applications[app.id]
    expect(after.posting).toEqual(app.posting)
    expect(store.snapshotSha(after.posting)).toBe(after.posting.snapshotSha256)
  })

  it('has no update or delete path', async () => {
    const names = Object.keys(store).sort()
    expect(names).toEqual([
      'APPLICATION_ROUTES', 'StoreError', 'appendEvent', 'applicationFilePath', 'assertAppendOnly',
      'assertStoreAppendOnly', 'changeSettings', 'changeStageRegistry', 'createApplication', 'emptyStore',
      'handleApplicationsRequest', 'isAppId', 'isStoreBackupEntry', 'knownContactIdentity', 'loadSettings', 'loadStore', 'localDay',
      'mergeFromBackup', 'migrateApplications', 'moveApplication', 'norm', 'normalizeUrl', 'planMigration',
      'postingKeyFor', 'previewMigration', 'previewShaOf', 'readSettings', 'snapshotSha', 'stageCounts',
      'storePaths', 'verifyMigration', 'withApplicationLock', 'writeFileAtomic',
    ])
    expect(names.filter((n) => /^(update|delete|set)/i.test(n))).toEqual([])
    expect([...new Set(store.APPLICATION_ROUTES.map((r) => r.method))].sort()).toEqual(['GET', 'POST'])
    const id = (await create()).json.application.id
    const before = storeBytes()
    for (const method of ['PUT', 'PATCH', 'DELETE']) {
      for (const url of ['/api/applications', `/api/applications/${id}`, `/api/applications/${id}/events/${id}:1`]) {
        expect((await call(method, url, {})).status).toBe(404)
      }
    }
    expect(storeBytes()).toEqual(before)
  })

  it('the event route takes one event and no server-assigned field', async () => {
    const id = (await create()).json.application.id
    const before = storeBytes()
    const bad = [
      { events: [{ type: 'note_added', data: { text: 'a' } }] },
      { type: 'note_added', data: { text: 'a' }, id: `${id}:2` },
      { type: 'note_added', data: { text: 'a' }, seq: 2 },
      { type: 'note_added', data: { text: 'a' }, source: 'migration' },
      [{ type: 'note_added', data: { text: 'a' } }],
      { type: 'applied', data: {} },
      { type: 'made_up', data: {} },
      { type: 'stage_changed', data: { stage: 'lunch' } },
      { type: 'stage_changed', data: { stage: 'tech', legacyStage: 'Technical Round 1' } },
      { type: 'stage_changed', data: { stage: 'tech', label: 'Technical round 1' } },
      { type: 'stage_changed', data: { stage: 'rejected' } },
      { type: 'stage_changed', data: { stage: 'interview' } },
      { type: 'contact_added', data: { contactId: 'c9', name: 'X' } },
      { type: 'message_sent', data: { via: 'email', contactId: 'c1' } },
      { type: 'note_added', date: '2026-11-04', data: { text: 'from the future' } },
      { type: 'follow_up_set', data: { dueDate: '2026-02-30' } },
    ]
    for (const body of bad) expect((await addEvent(id, body)).status).toBe(400)
    expect((await addEvent('app-0000000000000000', { type: 'note_added', data: { text: 'a' } })).status).toBe(404)
    expect((await addEvent('not-an-id', { type: 'note_added', data: { text: 'a' } })).status).toBe(400)
    expect(storeBytes()).toEqual(before)
  })
})

// --- concurrency -------------------------------------------------------------------------------

describe('concurrent writes', () => {
  it('parallel creates and events lose nothing', async () => {
    const first = (await create()).json.application.id
    const creates = Array.from({ length: 8 }, (_, i) => create({
      jobId: null,
      posting: { title: `Role ${i}`, company: `Company ${i}`, url: `https://example.com/jobs/${i}` },
      attempt: { cv: { kind: 'external', label: 'PDF from laptop' } },
    }))
    const events = Array.from({ length: 8 }, (_, i) => addEvent(first, { type: 'note_added', data: { text: `n${i}` } }))
    const results = await Promise.all([...creates, ...events])
    expect(results.map((r) => r.status)).toEqual(Array(16).fill(201))
    const s = await getStore()
    expect(Object.keys(s.applications)).toHaveLength(9)
    const log = s.applications[first].events
    expect(log.map((e) => e.seq)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9])
    expect(log.slice(1).map((e) => e.data.text).sort()).toEqual(['n0', 'n1', 'n2', 'n3', 'n4', 'n5', 'n6', 'n7'])
  })

  it('two parallel creates of one attempt give one application and one 409', async () => {
    const [a, b] = await Promise.all([create(), create()])
    expect([a.status, b.status].sort()).toEqual([201, 409])
    expect(Object.keys((await getStore()).applications)).toHaveLength(1)
  })

  it('a retried requestId returns the first result, even in parallel', async () => {
    const body = createBody()
    const [a, b] = await Promise.all([call('POST', '/api/applications', body), call('POST', '/api/applications', body)])
    expect([a.status, b.status].sort()).toEqual([200, 201])
    expect(a.json.application.id).toBe(b.json.application.id)
    const before = storeBytes()
    const c = await call('POST', '/api/applications', body)
    expect(c.json.application.id).toBe(a.json.application.id)
    expect(storeBytes()).toEqual(before)
    expect(Object.keys((await getStore()).applications)).toHaveLength(1)
  })
})

// --- duplicates (6c) ---------------------------------------------------------------------------

describe('duplicate rules', () => {
  it('a duplicate open attempt is refused', async () => {
    const first = (await create()).json.application.id
    const before = storeBytes()
    const res = await create()
    expect(res.status).toBe(409)
    expect(res.json.conflictingId).toBe(first)
    expect(storeBytes()).toEqual(before)
    expect(fs.readdirSync(path.join(root, 'data/applications/files'))).toEqual([first])
  })

  it('a reapply after a rejection is allowed', async () => {
    const first = (await create()).json.application.id
    await addEvent(first, { type: 'outcome_set', data: { outcome: 'rejected' } })
    const res = await create()
    expect(res.status).toBe(201)
    expect(res.json.application.attempt).toMatchObject({ previousApplicationId: first, distinctReason: 'reapply_after_outcome' })
  })

  it('a different channel is allowed; the same channel claimed as different is refused', async () => {
    const first = (await create()).json.application.id
    const same = await create({ newAttempt: { distinctReason: 'different_channel' } })
    expect(same.status).toBe(409)
    expect(same.json.conflictingId).toBe(first)
    const other = await create({ attempt: { channel: 'referral' }, newAttempt: { distinctReason: 'different_channel' } })
    expect(other.status).toBe(201)
    expect(other.json.application.attempt).toMatchObject({ previousApplicationId: first, distinctReason: 'different_channel' })
  })

  it('a new CV needs a different file', async () => {
    await create()
    const sameCv = await create({ newAttempt: { distinctReason: 'resubmitted_new_cv' } })
    expect(sameCv.status).toBe(409)
    const noFile = await create({ attempt: { cv: { kind: 'external' } }, newAttempt: { distinctReason: 'resubmitted_new_cv' } })
    expect(noFile.status).toBe(409)
    const newCv = await create({
      attempt: { cv: { kind: 'library', cvLibraryId: CV_B } },
      newAttempt: { distinctReason: 'resubmitted_new_cv' },
    })
    expect(newCv.status).toBe(201)
    expect(newCv.json.application.attempt.cv.sha256).toBe(sha(PDF_B))
  })

  it('warns, without blocking, about the same role on another board', async () => {
    await create()
    const res = await create({ jobId: OTHER_BOARD_JOB.jobId })
    expect(res.status).toBe(201)
    expect(res.json.warnings).toEqual(['possible_duplicate'])
  })

  it('a voided application does not block a new one, and its restore cannot duplicate', async () => {
    const x = (await create()).json.application.id
    expect((await addEvent(x, { type: 'application_voided', data: { reason: 'wrong job' } })).status).toBe(201)
    const y = (await create()).json.application.id

    const before = storeBytes()
    const refused = await addEvent(x, { type: 'application_restored', data: { reason: 'oops' } })
    expect(refused.status).toBe(409)
    expect(refused.json.conflictingId).toBe(y)
    expect(storeBytes()).toEqual(before)
    expect(foldApplication((await getStore()).applications[x]).voided).toBe(true)

    await addEvent(y, { type: 'application_voided', data: { reason: 'duplicate' } })
    expect((await addEvent(x, { type: 'application_restored', data: { reason: 'the real one' } })).status).toBe(201)
    expect(activeIds(await getStore())).toEqual([x])
  })

  it('distinct attempts at one posting are never collapsed (API half)', async () => {
    const first = (await create()).json.application.id
    await addEvent(first, { type: 'outcome_set', data: { outcome: 'rejected' } })
    const reapply = (await create()).json.application.id
    const referral = (await create({ attempt: { channel: 'referral' }, newAttempt: { distinctReason: 'different_channel' } })).json.application.id
    const newCv = (await create({
      attempt: { cv: { kind: 'library', cvLibraryId: CV_B } }, newAttempt: { distinctReason: 'resubmitted_new_cv' },
    })).json.application.id
    const s = await getStore()
    const forPosting = Object.values(s.applications).filter((a) => a.posting.postingKey === `job:${JOB.jobId}`)
    expect(new Set([first, reapply, referral, newCv]).size).toBe(4)
    expect(forPosting.filter(isActive)).toHaveLength(4)
    expect(stats(Object.values(s.applications)).applications).toBe(4)
  })
})

// --- void and restore (6e) ---------------------------------------------------------------------

describe('void and restore', () => {
  async function voidedFixture() {
    clock = new Date('2026-11-20T09:00:00.000Z')
    const v = (await create({ attempt: { appliedDate: '2026-11-01' } })).json.application.id
    await addEvent(v, { type: 'stage_changed', date: '2026-11-05', data: { stage: 'tech' } })
    await addEvent(v, { type: 'outcome_set', date: '2026-11-12', data: { outcome: 'offer_accepted' } })
    await addEvent(v, { type: 'follow_up_set', date: '2026-11-12', data: { dueDate: '2026-11-19' } })
    const s = (await create({
      jobId: null, posting: { title: 'Other role', company: 'Other Co' }, attempt: { cv: { kind: 'external' } },
    })).json.application.id
    const live = (await getStore()).applications
    const withoutVoid = live[v]
    await addEvent(v, { type: 'application_voided', data: { reason: 'created by mistake' } })
    return { v, s, withoutVoid }
  }

  it('a voided application is kept with its history and counts nowhere', async () => {
    const { v, s, withoutVoid } = await voidedFixture()
    const all = (await getStore()).applications
    expect(all[v].events).toHaveLength(5)
    expect(all[v].events.slice(0, 4)).toEqual(withoutVoid.events)
    expect(() => store.assertAppendOnly(withoutVoid, all[v])).not.toThrow()
    expect(activeIds({ applications: all })).toEqual([s])
    expect(stats(Object.values(all))).toEqual(stats([all[s]]))
    expect(stats(Object.values(all)).offers).toBe(0)
  })

  it('a voided application is read-only apart from restore', async () => {
    const { v } = await voidedFixture()
    const before = storeBytes()
    expect((await addEvent(v, { type: 'note_added', data: { text: 'x' } })).status).toBe(400)
    expect((await addEvent(v, { type: 'application_voided', data: { reason: 'again' } })).status).toBe(400)
    expect(storeBytes()).toEqual(before)
  })

  it('a restore keeps the history, adds no application and counts once', async () => {
    const { v, s, withoutVoid } = await voidedFixture()
    const voided = (await getStore()).applications[v]
    expect((await addEvent(v, { type: 'application_restored', data: { reason: 'it was real' } })).status).toBe(201)
    const all = (await getStore()).applications
    expect(Object.keys(all)).toHaveLength(2)
    expect(all[v].posting).toEqual(voided.posting)
    expect(all[v].attempt).toEqual(voided.attempt)
    expect(all[v].events.slice(0, 5)).toEqual(voided.events)
    expect(all[v].events[5].type).toBe('application_restored')
    expect(() => store.assertAppendOnly(voided, all[v])).not.toThrow()
    expect(activeIds({ applications: all }).filter((id) => id === v)).toHaveLength(1)
    expect(stats(Object.values(all))).toEqual(stats([all[s], withoutVoid]))
    expect(stats(Object.values(all)).offers).toBe(1)
    expect(foldApplication(all[v]).followUpDate).toBe('2026-11-19')
  })

  it('void and restore can repeat, each as a new event', async () => {
    const id = (await create()).json.application.id
    const before = storeBytes()
    expect((await addEvent(id, { type: 'application_restored', data: { reason: 'r' } })).status).toBe(400)
    expect(storeBytes()).toEqual(before)
    for (const type of ['application_voided', 'application_restored', 'application_voided', 'application_restored']) {
      expect((await addEvent(id, { type, data: { reason: 'r' } })).status).toBe(201)
    }
    let app = (await getStore()).applications[id]
    expect(app.events).toHaveLength(5)
    expect(foldApplication(app).voided).toBe(false)
    await addEvent(id, { type: 'application_voided', data: { reason: 'r' } })
    app = (await getStore()).applications[id]
    expect(foldApplication(app).voided).toBe(true)
  })

  it('a void is undone only by a restore', async () => {
    const id = (await create()).json.application.id
    await addEvent(id, { type: 'application_voided', data: { reason: 'r' } })
    await addEvent(id, { type: 'application_restored', data: { reason: 'r' } })
    const before = storeBytes()
    for (const eventId of [`${id}:2`, `${id}:3`, `${id}:1`]) {
      expect((await addEvent(id, { type: 'event_voided', data: { eventId, reason: 'r' } })).status).toBe(400)
    }
    expect(storeBytes()).toEqual(before)
  })

  it('a correction is an event, not a rewrite', async () => {
    const id = (await create()).json.application.id
    await addEvent(id, { type: 'stage_changed', data: { stage: 'onsite' } })
    expect((await addEvent(id, { type: 'event_voided', data: { eventId: `${id}:2`, reason: 'wrong app' } })).status).toBe(201)
    const app = (await getStore()).applications[id]
    expect(app.events.map((e) => e.type)).toEqual(['applied', 'stage_changed', 'event_voided'])
    expect(foldApplication(app).stage).toBe('applied')
    expect((await addEvent(id, { type: 'event_voided', data: { eventId: `${id}:2`, reason: 'again' } })).status).toBe(400)
  })
})

// --- frozen files and independence from discovery (6a) -----------------------------------------

describe('frozen CV copies', () => {
  it('the frozen copy is unchanged after the library CV changes or is deleted', async () => {
    const app = (await create()).json.application
    fs.writeFileSync(path.join(root, `data/profile/cvs/${CV_A}.pdf`), Buffer.from('%PDF-1.4\nedited later'))
    let res = await fetch(`${base}/api/applications/${app.id}/files/Nikola_CV.pdf`)
    expect(res.status).toBe(200)
    expect(sha(Buffer.from(await res.arrayBuffer()))).toBe(app.attempt.cv.sha256)
    expect(deleteCvFile(CV_A, path.join(root, 'data/profile/cvs'))).toBe(true)
    res = await fetch(`${base}/api/applications/${app.id}/files/Nikola_CV.pdf`)
    expect(Buffer.from(await res.arrayBuffer())).toEqual(PDF_A)
    const stat = fs.lstatSync(path.join(root, `data/applications/files/${app.id}/Nikola_CV.pdf`))
    expect(stat.isFile() && stat.nlink).toBe(1)
  })

  it('copies a tailored CV and cover letter from the job folder', async () => {
    fs.writeFileSync(path.join(root, `data/resumes/${JOB.jobId}/cover_letter.pdf`), Buffer.from('%PDF-1.4\nletter'))
    const app = (await create({
      attempt: { cv: { kind: 'tailored', fileName: 'Acme_Resume.pdf', label: 'Tailored' }, coverLetter: { fileName: 'cover_letter.pdf' } },
    })).json.application
    expect(app.attempt.cv).toMatchObject({ kind: 'tailored', cvLibraryId: null, fileName: 'Acme_Resume.pdf', sha256: sha(TAILORED) })
    expect(app.attempt.coverLetter.fileName).toBe('cover_letter.pdf')
  })

  it('refuses a CV path from the client and serves only recorded names', async () => {
    expect((await create({ attempt: { cv: { kind: 'tailored', fileName: '../../profile/cvs/x.pdf' } } })).status).toBe(400)
    expect((await create({ attempt: { cv: { kind: 'library', cvLibraryId: '../../etc' } } })).status).toBe(400)
    const app = (await create({ attempt: { cv: { kind: 'library', cvLibraryId: CV_A, fileName: '../evil.pdf' } } })).json.application
    expect(app.attempt.cv.fileName).toBe('_evil.pdf')
    for (const name of ['..%2Fapplications.json', 'other.pdf', '%2E%2E']) {
      expect((await call('GET', `/api/applications/${app.id}/files/${name}`)).status).toBe(404)
    }
  })

  it('the application survives deleted job files, résumés and library CV', async () => {
    const app = (await create({ attempt: { cv: { kind: 'tailored', fileName: 'Acme_Resume.pdf' } } })).json.application
    for (const f of fs.readdirSync(path.join(root, 'data/jobs'))) fs.rmSync(path.join(root, 'data/jobs', f))
    fs.rmSync(path.join(root, 'data/resumes', JOB.jobId), { recursive: true })
    deleteCvFile(CV_A, path.join(root, 'data/profile/cvs'))
    expect((await getStore()).applications[app.id]).toEqual(app)
    const res = await fetch(`${base}/api/applications/${app.id}/files/Acme_Resume.pdf`)
    expect(sha(Buffer.from(await res.arrayBuffer()))).toBe(app.attempt.cv.sha256)
  })

  it('an application without any posting in discovery folds and lists like any other', async () => {
    const res = await create({
      jobId: null,
      posting: { title: 'Product Lead', company: 'Beta d.o.o.', url: 'https://Beta.example/Jobs/7/?utm_source=x#top' },
      attempt: { cv: { kind: 'external', label: 'Old PDF' } },
    })
    expect(res.status).toBe(201)
    const app = res.json.application
    expect(app.posting).toMatchObject({ jobId: null, capturedFrom: 'manual', descriptionMissing: true })
    expect(app.posting.postingKey).toBe('url:https://beta.example/Jobs/7')
    expect(app.attempt.cv).toMatchObject({ kind: 'external', fileName: null, sha256: null })
    expect(foldApplication(app)).toMatchObject({ stage: 'applied', outcome: null, voided: false })
    expect(activeIds(await getStore())).toEqual([app.id])
  })

  it('falls back to the ledger, then to the browser record', async () => {
    fs.writeFileSync(path.join(root, 'data/jobs/scored_jobs.json'), JSON.stringify({ jobs: [] }))
    fs.writeFileSync(path.join(root, 'data/jobs/job_history.json'), JSON.stringify({ jobs: { [JOB.jobId]: { job: JOB } } }))
    const fromLedger = (await create()).json.application
    expect(fromLedger.posting.capturedFrom).toBe('job_history')
    const fromBrowser = await create({ jobId: 'b'.repeat(16), posting: { title: 'T', company: 'C' } })
    expect(fromBrowser.json.application.posting).toMatchObject({ capturedFrom: 'browser', postingKey: `job:${'b'.repeat(16)}` })
    expect((await create({ jobId: 'c'.repeat(16) })).status).toBe(400)
  })
})

describe('key normalization', () => {
  it('normalizes company names as section 4 describes', () => {
    expect(store.norm('  Đorđe  Ćirić   Software D.O.O. ')).toBe('djordje ciric software')
    expect(store.norm('Acme GmbH')).toBe(store.norm('acme'))
  })
})

// --- backup export and restore (3.1) -----------------------------------------------------------

function streamToBuffer(stream) {
  return new Promise((resolve, reject) => {
    const chunks = []
    stream.on('data', (c) => chunks.push(c))
    stream.on('end', () => resolve(Buffer.concat(chunks)))
    stream.on('error', reject)
  })
}

function zipOf(files) {
  const zip = new AdmZip()
  for (const [name, data] of Object.entries(files)) zip.addFile(name, Buffer.isBuffer(data) ? data : Buffer.from(data))
  return zip.toBuffer()
}

describe('backup', () => {
  it('export includes the store and its frozen files; restore into an empty root reproduces them', async () => {
    const app = (await create()).json.application
    const zip = await streamToBuffer(createBackupStream(root))
    const names = new AdmZip(zip).getEntries().map((e) => e.entryName)
    expect(names).toContain('data/applications/applications.json')
    expect(names).toContain(`data/applications/files/${app.id}/Nikola_CV.pdf`)

    const other = fs.mkdtempSync(path.join(os.tmpdir(), 'apps-restore-'))
    try {
      const result = await importBackupZip(other, zip)
      expect(result.applications.added).toEqual([app.id])
      expect(store.loadStore(other).applications[app.id]).toEqual(app)
      expect(fs.readFileSync(path.join(other, `data/applications/files/${app.id}/Nikola_CV.pdf`))).toEqual(PDF_A)
      expect(fs.readFileSync(path.join(other, 'data/jobs/scored_jobs.json'))).toEqual(
        fs.readFileSync(path.join(root, 'data/jobs/scored_jobs.json')))
    } finally {
      fs.rmSync(other, { recursive: true, force: true })
    }
  })

  it('a restore adds history and never removes or rewrites it', async () => {
    const x = (await create()).json.application.id
    for (let i = 0; i < 2; i += 1) await addEvent(x, { type: 'note_added', data: { text: `early ${i}` } })
    const older = structuredClone((await getStore()))
    for (let i = 0; i < 2; i += 1) await addEvent(x, { type: 'note_added', data: { text: `late ${i}` } })
    expect((await getStore()).applications[x].events).toHaveLength(5)

    // an older backup of X plus a new application Y
    const y = { ...structuredClone(older.applications[x]), id: 'app-00000000000000aa' }
    y.events = [{ ...y.events[0], id: `${y.id}:1` }]
    y.attempt = { ...y.attempt, cv: { ...y.attempt.cv, fileName: 'Y.pdf', sha256: sha(PDF_B) } }
    const backupStore = { ...older, applications: { [x]: older.applications[x], [y.id]: y } }
    const before = storeBytes()
    clock = new Date('2026-11-04T12:00:00.000Z')
    const result = await importBackupZip(root, zipOf({
      'data/applications/applications.json': JSON.stringify(backupStore),
      [`data/applications/files/${x}/Nikola_CV.pdf`]: 'tampered bytes',
      [`data/applications/files/${y.id}/Y.pdf`]: PDF_B,
      'data/applications/files/app-00000000000000aa/not-recorded.pdf': 'x',
    }), { now })
    const after = store.loadStore(root)
    expect(after.applications[x].events).toHaveLength(5)
    expect(after.applications[y.id]).toEqual(y)
    expect(result.applications.added).toEqual([y.id])
    expect(result.applications.unchanged).toEqual([x])
    expect(result.applications.filesAdded).toEqual([`${y.id}/Y.pdf`])
    expect(fs.readFileSync(path.join(root, `data/applications/files/${x}/Nikola_CV.pdf`))).toEqual(PDF_A)
    expect(result.applications.backupPath).toBe('data/backups/applications-20261104-120000')
    expect(fs.readFileSync(path.join(root, result.applications.backupPath, 'applications.json'))).toEqual(before)

    // a backup whose event 2 differs: X unchanged, conflict reported
    const altered = structuredClone(older)
    altered.applications[x].events[1].data.text = 'rewritten'
    const kept = storeBytes()
    const conflict = await importBackupZip(root, zipOf({ 'data/applications/applications.json': JSON.stringify(altered) }), { now })
    expect(conflict.applications.conflicts.map((c) => c.appId)).toEqual([x])
    expect(storeBytes()).toEqual(kept)
    expect(conflict.applications.backupPath).toBe('data/backups/applications-20261104-120000-2')
  })

  it('a restore extends a log that is a prefix of the backup', async () => {
    const x = (await create()).json.application.id
    await addEvent(x, { type: 'note_added', data: { text: 'one' } })
    const longer = structuredClone(await getStore())
    const shorter = structuredClone(longer)
    shorter.applications[x].events.pop()
    fs.writeFileSync(storeFile(), JSON.stringify(shorter))
    const result = await importBackupZip(root, zipOf({ 'data/applications/applications.json': JSON.stringify(longer) }))
    expect(result.applications.extended).toEqual([x])
    expect(store.loadStore(root).applications[x]).toEqual(longer.applications[x])
  })
})

// --- stage registry (6f) -----------------------------------------------------------------------

const settingsFile = () => path.join(root, 'data/applications/settings.json')
const settingsBytes = () => (fs.existsSync(settingsFile()) ? fs.readFileSync(settingsFile()) : null)
const stageOp = (body) => call('POST', '/api/applications/settings/stages', body)
const getSettings = async () => (await call('GET', '/api/applications/settings')).json
const move = (id, body) => call('POST', `/api/applications/${id}/move`, body)
const foldedOf = async (id) => foldApplication((await getStore()).applications[id])
const eventTypes = async (id) => (await getStore()).applications[id].events.map((e) => e.type)
const activeKeys = (settings) => settings.stages.work.filter((s) => !s.retired).map((s) => s.key)

/** A second application on a different posting, so tests can hold several apps at once. */
const createOther = (n, overrides = {}) => create({
  jobId: null,
  posting: { title: `Role ${n}`, company: `Company ${n}`, url: `https://example.com/jobs/${n}` },
  ...overrides,
  attempt: { cv: { kind: 'external', label: 'PDF from laptop' }, ...(overrides.attempt ?? {}) },
})

describe('stage registry', () => {
  it('a settings change is not written when the answer cannot be built', async () => {
    fs.mkdirSync(path.dirname(storeFile()), { recursive: true })
    fs.writeFileSync(storeFile(), '{broken')
    expect((await stageOp({ op: 'add', label: 'X' })).status).toBe(500)
    expect((await call('POST', '/api/applications/settings', { followUpReminders: false })).status).toBe(500)
    expect(settingsBytes()).toBeNull()
  })

  it('starts from the defaults and writes nothing until a change', async () => {
    const { status, json } = await call('GET', '/api/applications/settings')
    expect(status).toBe(200)
    expect(json.settings).toMatchObject({ trackingEnabled: true, followUpReminders: true })
    expect(json.settings.stages.work).toEqual([
      { key: 'screen', label: 'Screen', retired: false, interview: false },
      { key: 'tech', label: 'Tech', retired: false, interview: true },
      { key: 'onsite', label: 'Onsite', retired: false, interview: true },
      { key: 'offer', label: 'Offer', retired: false, interview: false },
    ])
    expect(json.counts).toEqual({ applied: 0, screen: 0, tech: 0, onsite: 0, offer: 0, rejected: 0, ghosted: 0, closed: 0, unfiled: 0 })
    await stageOp({ op: 'move', key: 'screen', dir: 'up' })
    expect(settingsBytes()).toBeNull()
  })

  it('rename keeps every reference', async () => {
    const open = (await create()).json.application.id
    await move(open, { toStage: 'tech' })
    const closed = (await createOther(1)).json.application.id
    await move(closed, { toStage: 'tech' })
    await move(closed, { toStage: 'rejected' })
    const before = storeBytes()
    const foldedBefore = [await foldedOf(open), await foldedOf(closed)]

    const res = await stageOp({ op: 'rename', key: 'tech', label: 'Technical Interview' })
    expect(res.status).toBe(200)
    expect(storeBytes()).toEqual(before)
    const { settings } = await getSettings()
    expect(await Promise.all([foldedOf(open), foldedOf(closed)])).toEqual(foldedBefore)
    expect(labelFor('tech', settings)).toBe('Technical Interview')
    expect(boardColumn(foldedBefore[0], settings)).toBe('tech')
    expect(boardColumn(foldedBefore[1], settings)).toBe('rejected')
    // the stage reached by the closed one reads with the new name
    expect(labelFor(foldedBefore[1].stage, settings)).toBe('Technical Interview')
    expect(settings.changes.at(-1)).toMatchObject({ action: 'rename', key: 'tech', old: 'Tech', new: 'Technical Interview' })
  })

  it('add and reorder change no application', async () => {
    const id = (await create()).json.application.id
    await move(id, { toStage: 'onsite' })
    const before = storeBytes()
    const foldedBefore = await foldedOf(id)

    const added = await stageOp({ op: 'add', label: 'Take-home' })
    expect(added.status).toBe(200)
    expect(added.json.settings.stages.work.at(-1)).toEqual({ key: 'take_home', label: 'Take-home', retired: false, interview: false })
    for (let i = 0; i < 3; i += 1) expect((await stageOp({ op: 'move', key: 'take_home', dir: 'up' })).status).toBe(200)
    expect(activeKeys((await getSettings()).settings)).toEqual(['screen', 'take_home', 'tech', 'onsite', 'offer'])
    expect(storeBytes()).toEqual(before)
    expect(await foldedOf(id)).toEqual(foldedBefore)
    // at an edge nothing changes, and nothing is written
    const bytes = settingsBytes()
    expect((await stageOp({ op: 'move', key: 'screen', dir: 'up' })).json.changed).toBe(false)
    expect((await stageOp({ op: 'move', key: 'offer', dir: 'down' })).json.changed).toBe(false)
    expect(settingsBytes()).toEqual(bytes)
  })

  it('retire refuses an occupied column and keeps the label for closed applications', async () => {
    const open = (await create()).json.application.id
    await move(open, { toStage: 'onsite' })
    const closed = (await createOther(1)).json.application.id
    await move(closed, { toStage: 'onsite' })
    await move(closed, { toStage: 'rejected' })
    await stageOp({ op: 'rename', key: 'screen', label: 'Recruiter call' })
    const settingsBefore = settingsBytes()
    const storeBefore = storeBytes()

    const refused = await stageOp({ op: 'retire', key: 'onsite' })
    expect(refused.status).toBe(409)
    expect(refused.json.count).toBe(1)
    expect(settingsBytes()).toEqual(settingsBefore)

    await move(open, { toStage: 'offer' })
    expect((await stageOp({ op: 'retire', key: 'onsite' })).status).toBe(200)
    const { settings } = await getSettings()
    expect(activeKeys(settings)).toEqual(['screen', 'tech', 'offer'])
    expect(labelFor('onsite', settings)).toBe('Onsite')
    expect(labelFor((await foldedOf(closed)).stage, settings)).toBe('Onsite')
    expect(boardColumn(await foldedOf(closed), settings)).toBe('rejected')
    // only the open application moved; the closed one keeps its log
    expect((await getStore()).applications[closed]).toEqual(JSON.parse(storeBefore).applications[closed])
  })

  it('a voided or closed application does not block a retire', async () => {
    const id = (await create()).json.application.id
    await move(id, { toStage: 'tech' })
    await addEvent(id, { type: 'application_voided', data: { reason: 'mistake' } })
    expect((await stageOp({ op: 'retire', key: 'tech' })).status).toBe(200)
  })

  it('retire races a move: never an open application on a retired stage', async () => {
    const id = (await create()).json.application.id
    for (let i = 0; i < 50; i += 1) {
      const [moved, retired] = await Promise.all([move(id, { toStage: 'onsite' }), stageOp({ op: 'retire', key: 'onsite' })])
      expect([moved.status, retired.status].sort()).toEqual(retired.status === 200 ? [200, 400] : [200, 409])
      const { settings } = await getSettings()
      const folded = await foldedOf(id)
      expect(boardColumn(folded, settings)).not.toBe('unfiled')
      if (retired.status === 200) await stageOp({ op: 'unretire', key: 'onsite' })
      await move(id, { toStage: 'screen' })
    }
  })

  it('the last work stage stays', async () => {
    for (const key of ['screen', 'tech', 'onsite']) expect((await stageOp({ op: 'retire', key })).status).toBe(200)
    const before = settingsBytes()
    const res = await stageOp({ op: 'retire', key: 'offer' })
    expect(res.status).toBe(400)
    expect(settingsBytes()).toEqual(before)
  })

  it('unretire brings a stage back at the end with its label', async () => {
    const id = (await create()).json.application.id
    await move(id, { toStage: 'onsite' })
    await move(id, { toStage: 'ghosted' })
    const storeBefore = storeBytes()
    expect((await stageOp({ op: 'retire', key: 'onsite' })).status).toBe(200)
    expect((await stageOp({ op: 'unretire', key: 'onsite' })).status).toBe(200)
    const { settings } = await getSettings()
    expect(activeKeys(settings)).toEqual(['screen', 'tech', 'offer', 'onsite'])
    expect(labelFor('onsite', settings)).toBe('Onsite')
    expect(storeBytes()).toEqual(storeBefore)
    expect((await stageOp({ op: 'unretire', key: 'onsite' })).status).toBe(400)
  })

  it('adding a label equal to a retired stage points at the restore', async () => {
    await stageOp({ op: 'retire', key: 'onsite' })
    const res = await stageOp({ op: 'add', label: ' onsite ' })
    expect(res.status).toBe(409)
    expect(res.json.retiredKey).toBe('onsite')
    expect((await stageOp({ op: 'add', label: 'TECH' })).status).toBe(409)
  })

  it('fixed and reserved keys can neither be reused nor changed', async () => {
    for (const label of ['Applied', 'Rejected', 'Ghosted', 'Unfiled']) {
      const res = await stageOp({ op: 'add', label })
      expect(res.status).toBe(200)
      expect(res.json.settings.stages.work.at(-1).key).toBe(`${label.toLowerCase()}_2`)
    }
    const before = settingsBytes()
    for (const key of ['applied', 'rejected', 'ghosted', 'unfiled']) {
      for (const body of [{ op: 'rename', key, label: 'X' }, { op: 'retire', key }, { op: 'move', key, dir: 'up' }, { op: 'unretire', key }]) {
        expect((await stageOp(body)).status).toBe(400)
      }
    }
    expect(settingsBytes()).toEqual(before)
  })

  it('keys are slugged from the label, suffixed on collision, and never reused after a retire', async () => {
    const a = await stageOp({ op: 'add', label: 'Čaj & Kolači!' })
    expect(a.json.settings.stages.work.at(-1).key).toBe('caj_kolaci')
    await stageOp({ op: 'retire', key: 'caj_kolaci' })
    expect((await stageOp({ op: 'add', label: 'čaj & kolači!' })).status).toBe(409) // the retired stage's label
    const b = await stageOp({ op: 'add', label: 'Caj Kolaci' })
    expect(b.json.settings.stages.work.at(-1).key).toBe('caj_kolaci_2') // the retired key is never reused
    const c = await stageOp({ op: 'add', label: 'Caj-Kolaci!!' })
    expect(c.json.settings.stages.work.at(-1).key).toBe('caj_kolaci_3')
    const long = await stageOp({ op: 'add', label: 'x'.repeat(40) })
    expect(long.json.settings.stages.work.at(-1).key).toMatch(/^[a-z0-9_]{1,40}$/)
  })

  it('refuses bad operations and an eleventh active stage', async () => {
    const before = settingsBytes()
    const bad = [
      {}, { op: 'drop', key: 'tech' }, { op: 'add' }, { op: 'add', label: '   ' }, { op: 'add', label: 'x'.repeat(61) },
      { op: 'rename', key: 'tech' }, { op: 'rename', key: 'nope', label: 'X' }, { op: 'move', key: 'tech', dir: 'left' },
      { op: 'rename', key: 'tech', interview: 'yes' }, { op: 'add', label: 'X', extra: 1 },
    ]
    for (const body of bad) expect([400, 404]).toContain((await stageOp(body)).status)
    expect((await stageOp({ op: 'rename', key: 'tech', label: 'screen' })).status).toBe(409)
    expect(settingsBytes()).toEqual(before)
    for (let i = 0; i < 6; i += 1) expect((await stageOp({ op: 'add', label: `Extra ${i}` })).status).toBe(200)
    expect((await stageOp({ op: 'add', label: 'One too many' })).status).toBe(400)
  })

  it('the interview flag is set per stage and only on that stage', async () => {
    const res = await stageOp({ op: 'rename', key: 'screen', interview: true })
    expect(res.json.settings.stages.work.map((s) => [s.key, s.interview])).toEqual([
      ['screen', true], ['tech', true], ['onsite', true], ['offer', false],
    ])
    expect(res.json.settings.stages.work[0].label).toBe('Screen')
    expect(res.json.settings.changes.at(-1)).toMatchObject({ action: 'interview', key: 'screen', old: false, new: true })
  })

  it('a stage change names the active registry only', async () => {
    const id = (await create()).json.application.id
    await stageOp({ op: 'retire', key: 'onsite' })
    const before = storeBytes()
    for (const stage of ['onsite', 'lunch', 'rejected', 'ghosted', 'unfiled']) {
      expect((await addEvent(id, { type: 'stage_changed', data: { stage } })).status).toBe(400)
      expect((await move(id, { toStage: stage })).status).toBe(stage === 'rejected' || stage === 'ghosted' ? 200 : 400)
      if (stage === 'rejected' || stage === 'ghosted') await move(id, { toStage: 'screen' })
    }
    expect(storeBytes()).not.toEqual(before) // only the two legitimate closed-column moves and back
    expect(await eventTypes(id)).toEqual([
      'applied', 'outcome_set', 'outcome_cleared', 'stage_changed', 'outcome_set', 'outcome_cleared',
    ])
  })

  it('unfiled catches an open application whose stage the registry lacks', async () => {
    const id = (await create()).json.application.id
    await move(id, { toStage: 'onsite' })
    fs.writeFileSync(settingsFile(), JSON.stringify({
      version: 1, updatedAt: null, trackingEnabled: true, followUpReminders: true, changes: [],
      stages: { work: [{ key: 'screen', label: 'Screen', retired: false, interview: false }, { key: 'offer', label: 'Offer', retired: false, interview: false }] },
    }))
    const { settings, counts } = await getSettings()
    expect(boardColumn(await foldedOf(id), settings)).toBe('unfiled')
    expect(counts.unfiled).toBe(1)
    expect((await move(id, { toStage: 'screen' })).status).toBe(200)
    expect(boardColumn(await foldedOf(id), (await getSettings()).settings)).toBe('screen')
  })

  it('invalid settings are never overwritten', async () => {
    const id = (await create()).json.application.id
    fs.mkdirSync(path.dirname(settingsFile()), { recursive: true })
    const storeBefore = storeBytes()
    for (const content of ['{broken', JSON.stringify({ version: 1 }), JSON.stringify({ version: 2 }), '[]']) {
      fs.writeFileSync(settingsFile(), content)
      for (const res of [
        await create({ jobId: OTHER_BOARD_JOB.jobId }),
        await addEvent(id, { type: 'note_added', data: { text: 'x' } }),
        await move(id, { toStage: 'tech' }),
        await stageOp({ op: 'add', label: 'X' }),
        await call('POST', '/api/applications/settings', { trackingEnabled: false }),
        await call('GET', '/api/applications/settings'),
      ]) expect(res.status).toBe(500)
      expect(fs.readFileSync(settingsFile(), 'utf-8')).toBe(content)
    }
    expect(storeBytes()).toEqual(storeBefore)
    expect((await call('GET', '/api/applications')).status).toBe(200)
  })

  it('rejects a duplicate stage key, a reserved key and a bad flag in the file', async () => {
    const mk = (work) => JSON.stringify({ version: 1, trackingEnabled: true, followUpReminders: true, stages: { work } })
    const stage = (key, extra = {}) => ({ key, label: key, retired: false, interview: false, ...extra })
    fs.mkdirSync(path.dirname(settingsFile()), { recursive: true })
    for (const work of [[stage('a'), stage('a')], [stage('applied')], [stage('A')], [stage('a', { retired: 'no' })], [stage('a', { label: ' ' })]]) {
      fs.writeFileSync(settingsFile(), mk(work))
      expect((await call('GET', '/api/applications/settings')).status).toBe(500)
    }
  })
})

// --- tracking switch (6h) ----------------------------------------------------------------------

function dataTree(dir = path.join(root, 'data'), out = {}) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) dataTree(full, out)
    else out[path.relative(root, full)] = sha(fs.readFileSync(full))
  }
  return out
}

describe('tracking switch', () => {
  it('off and on again keeps every byte; writes are refused meanwhile', async () => {
    const id = (await create({ attempt: { cv: { kind: 'tailored', fileName: 'Acme_Resume.pdf' } } })).json.application.id
    await stageOp({ op: 'rename', key: 'tech', label: 'Technical' })
    const treeBefore = dataTree()
    const settingsBefore = JSON.parse(settingsBytes())

    const off = await call('POST', '/api/applications/settings', { trackingEnabled: false })
    expect(off.status).toBe(200)
    expect(off.json.settings.trackingEnabled).toBe(false)
    const refused = [
      await create({ jobId: OTHER_BOARD_JOB.jobId }),
      await addEvent(id, { type: 'note_added', data: { text: 'x' } }),
      await move(id, { toStage: 'tech' }),
      await stageOp({ op: 'add', label: 'X' }),
    ]
    for (const res of refused) {
      expect(res.status).toBe(409)
      expect(res.json.code).toBe('tracking_disabled')
    }
    expect((await call('GET', '/api/applications')).status).toBe(200)
    expect((await call('GET', '/api/applications/settings')).status).toBe(200)
    expect((await call('GET', `/api/applications/${id}/files/Acme_Resume.pdf`)).status).toBe(200)
    expect(dataTree()).toEqual({ ...treeBefore, 'data/applications/settings.json': dataTree()['data/applications/settings.json'] })

    const on = await call('POST', '/api/applications/settings', { trackingEnabled: true })
    expect(on.status).toBe(200)
    const tree = dataTree()
    for (const [name, hash] of Object.entries(treeBefore)) {
      if (name !== 'data/applications/settings.json') expect(tree[name]).toBe(hash)
    }
    const settingsAfter = JSON.parse(settingsBytes())
    const strip = ({ updatedAt, changes, ...rest }) => rest
    expect(strip(settingsAfter)).toEqual(strip(settingsBefore))
    expect(settingsAfter.changes.slice(0, -2)).toEqual(settingsBefore.changes)
    expect(settingsAfter.changes.slice(-2).map((c) => [c.action, c.key, c.old, c.new])).toEqual([
      ['switch', 'trackingEnabled', true, false], ['switch', 'trackingEnabled', false, true],
    ])
  })

  it('the settings route validates and ignores a no-op', async () => {
    for (const body of [{}, { trackingEnabled: 'no' }, { stages: {} }, { followUpReminders: 1 }]) {
      expect((await call('POST', '/api/applications/settings', body)).status).toBe(400)
    }
    expect((await call('POST', '/api/applications/settings', { trackingEnabled: true })).status).toBe(200)
    expect(settingsBytes()).toBeNull()
    const res = await call('POST', '/api/applications/settings', { followUpReminders: false })
    expect(res.json.settings.followUpReminders).toBe(false)
    expect(res.json.settings.trackingEnabled).toBe(true)
  })

  it('backup export and restore work with tracking off', async () => {
    const app = (await create()).json.application
    await call('POST', '/api/applications/settings', { trackingEnabled: false })
    const zip = await streamToBuffer(createBackupStream(root))
    const names = new AdmZip(zip).getEntries().map((e) => e.entryName)
    expect(names).toContain('data/applications/settings.json')
    const result = await importBackupZip(root, zip, { now })
    expect(result.applications.unchanged).toEqual([app.id])
    expect(result.applications.settings).toBe('unchanged')
    expect((await getSettings()).settings.trackingEnabled).toBe(false)
  })

  it('the interview flag creates nothing but the move events', async () => {
    const id = (await create()).json.application.id
    const before = dataTree()
    expect((await move(id, { toStage: 'tech' })).status).toBe(200)
    expect((await move(id, { toStage: 'onsite' })).status).toBe(200)
    const after = dataTree()
    expect(Object.keys(after)).toEqual(Object.keys(before))
    const changed = Object.keys(after).filter((name) => after[name] !== before[name])
    expect(changed).toEqual(['data/applications/applications.json'])
    expect(fs.existsSync(path.join(root, 'data/calendar'))).toBe(false)
    expect(fs.existsSync(path.join(root, 'data/interviews'))).toBe(false)
    expect((await eventTypes(id))).toEqual(['applied', 'stage_changed', 'stage_changed'])
  })

  it('a restart reloads the same store and settings', async () => {
    const id = (await create()).json.application.id
    await move(id, { toStage: 'tech' })
    await stageOp({ op: 'rename', key: 'tech', label: 'Technical' })
    const before = {
      store: store.loadStore(root), settings: store.readSettings(root), get: await call('GET', '/api/applications'), bytes: storeBytes(),
    }
    vi.resetModules()
    const fresh = await import('../../scripts/application-store.js')
    expect(fresh).not.toBe(store)
    expect(fresh.loadStore(root)).toEqual(before.store)
    expect(fresh.readSettings(root)).toEqual(before.settings)
    const server2 = http.createServer(async (req, res) => { await fresh.handleApplicationsRequest(req, res, req.url, { root, now }) })
    await new Promise((resolve) => server2.listen(0, '127.0.0.1', resolve))
    try {
      const res = await fetch(`http://127.0.0.1:${server2.address().port}/api/applications`)
      expect(await res.text()).toBe(before.get.text)
    } finally {
      await new Promise((resolve) => server2.close(resolve))
    }
    expect(storeBytes()).toEqual(before.bytes)
  })

  it('makes no network call', async () => {
    const stub = () => { throw new Error('network call from the tracker') }
    const http = require('node:http')
    const https = require('node:https')
    const real = { fetch: globalThis.fetch, request: http.request, sRequest: https.request, get: http.get }
    globalThis.fetch = stub
    http.request = stub
    http.get = stub
    https.request = stub
    try {
      const created = await store.createApplication(root, createBody(), { now })
      const id = created.application.id
      await store.appendEvent(root, id, { type: 'note_added', data: { text: 'x' } }, { now })
      await store.moveApplication(root, id, { toStage: 'tech' }, { now })
      await store.moveApplication(root, id, { toStage: 'rejected' }, { now })
      await store.changeSettings(root, { followUpReminders: false }, { now })
      await store.changeStageRegistry(root, { op: 'add', label: 'Extra' }, { now })
      await store.changeStageRegistry(root, { op: 'retire', key: 'offer' }, { now })
      store.readSettings(root)
      await store.mergeFromBackup(root, [{ name: 'data/applications/settings.json', data: settingsBytes() }], { now })
    } finally {
      globalThis.fetch = real.fetch
      http.request = real.request
      http.get = real.get
      https.request = real.sRequest
    }
  })
})

// --- move and the way back (1.9) ---------------------------------------------------------------

describe('move', () => {
  it('writes the events the table names, in one save', async () => {
    const id = (await create()).json.application.id
    const first = await move(id, { toStage: 'tech' })
    expect(first.status).toBe(200)
    expect(first.json.events.map((e) => [e.type, e.data])).toEqual([['stage_changed', { stage: 'tech' }]])
    expect(first.json.events[0]).toMatchObject({ id: `${id}:2`, seq: 2, source: 'user', date: '2026-11-03', at: clock.toISOString() })

    const bytes = storeBytes()
    const same = await move(id, { toStage: 'tech' })
    expect(same.status).toBe(200)
    expect(same.json).toMatchObject({ changed: false, events: [] })
    expect(storeBytes()).toEqual(bytes)

    const closed = await move(id, { toStage: 'rejected' })
    expect(closed.json.events.map((e) => [e.type, e.data])).toEqual([['outcome_set', { outcome: 'rejected' }]])
    expect(await foldedOf(id)).toMatchObject({ stage: 'tech', outcome: 'rejected' })

    const other = await move(id, { toStage: 'ghosted' })
    expect(other.json.events.map((e) => e.type)).toEqual(['outcome_cleared', 'outcome_set'])
    expect(other.json.events.map((e) => e.seq)).toEqual([4, 5])
    expect(other.json.events[0].data.reason).toBe('moved on the board')
    expect(await foldedOf(id)).toMatchObject({ stage: 'tech', outcome: 'ghosted' })

    const back = await move(id, { toStage: 'screen' })
    expect(back.json.events.map((e) => [e.type, e.data])).toEqual([
      ['outcome_cleared', { reason: 'moved on the board' }], ['stage_changed', { stage: 'screen' }],
    ])
    const sameStage = await move(id, { toStage: 'ghosted' })
    expect(sameStage.json.events.map((e) => e.type)).toEqual(['outcome_set'])
    const reopenSame = await move(id, { toStage: 'screen' })
    expect(reopenSame.json.events.map((e) => e.type)).toEqual(['outcome_cleared'])
    const app = (await getStore()).applications[id]
    expect(app.events.map((e) => e.seq)).toEqual(app.events.map((_, i) => i + 1))
    expect(() => store.assertAppendOnly(first.json.application, app)).not.toThrow()
  })

  it('a closed-panel outcome moves to a column through the same two events', async () => {
    const id = (await create()).json.application.id
    await addEvent(id, { type: 'outcome_set', data: { outcome: 'withdrawn' } })
    expect(await foldedOf(id)).toMatchObject({ outcome: 'withdrawn' })
    expect(boardColumn(await foldedOf(id), (await getSettings()).settings)).toBe('closed')
    expect((await move(id, { toStage: 'rejected' })).json.events.map((e) => e.type)).toEqual(['outcome_cleared', 'outcome_set'])
  })

  it('refuses a voided application, a bad target and a body with extra fields', async () => {
    const id = (await create()).json.application.id
    const before = storeBytes()
    for (const body of [{}, { toStage: 'lunch' }, { toStage: 'unfiled' }, { toStage: 'tech', events: [] }, { toStage: 'tech', date: '2026-11-04' }, { toStage: 'tech', date: 'x' }, []]) {
      expect((await move(id, body)).status).toBe(400)
    }
    expect((await move('app-0000000000000000', { toStage: 'tech' })).status).toBe(404)
    expect((await move('nope', { toStage: 'tech' })).status).toBe(400)
    expect(storeBytes()).toEqual(before)
    await addEvent(id, { type: 'application_voided', data: { reason: 'r' } })
    const voided = storeBytes()
    expect((await move(id, { toStage: 'tech' })).status).toBe(400)
    expect(storeBytes()).toEqual(voided)
  })

  it('a failed save writes nothing, so the card can go back', async () => {
    const id = (await create()).json.application.id
    const before = storeBytes()
    vi.spyOn(fs, 'renameSync').mockImplementationOnce(() => { throw new Error('disk full') })
    expect((await move(id, { toStage: 'tech' })).status).toBe(500)
    expect(storeBytes()).toEqual(before)
    expect((await move(id, { toStage: 'tech' })).status).toBe(200)
  })

  it('a stage change or outcome on the wrong state is refused', async () => {
    const id = (await create()).json.application.id
    expect((await addEvent(id, { type: 'outcome_cleared', data: { reason: 'r' } })).status).toBe(400)
    await addEvent(id, { type: 'outcome_set', data: { outcome: 'rejected' } })
    const before = storeBytes()
    expect((await addEvent(id, { type: 'outcome_set', data: { outcome: 'ghosted' } })).status).toBe(400)
    expect((await addEvent(id, { type: 'stage_changed', data: { stage: 'tech' } })).status).toBe(400)
    expect(storeBytes()).toEqual(before)
  })
})

describe('create obeys the competing-attempt invariant', () => {
  it('a CV correction that makes two CVs equal blocks the claimed new CV', async () => {
    const a = (await create()).json.application.id // CV_A
    await addEvent(a, { type: 'cv_recorded', data: { kind: 'library', cvLibraryId: CV_B, fileName: 'B.pdf', reason: 'sent B' } })
    const before = storeBytes()
    const res = await create({
      attempt: { cv: { kind: 'library', cvLibraryId: CV_B } }, newAttempt: { distinctReason: 'resubmitted_new_cv' },
    })
    expect(res.status).toBe(409)
    expect(res.json.conflictingId).toBe(a)
    expect(storeBytes()).toEqual(before)
    expect(fs.readdirSync(path.join(root, 'data/applications/files'))).toEqual([a])
  })

  it('an earlier CV that is unknown or external is not a verified difference', async () => {
    for (const cv of [{ kind: 'unknown' }, { kind: 'external', label: 'PDF' }]) {
      fs.rmSync(path.join(root, 'data/applications'), { recursive: true, force: true })
      const a = (await create({ attempt: { cv } })).json.application.id
      const before = storeBytes()
      const res = await create({
        attempt: { cv: { kind: 'library', cvLibraryId: CV_B } }, newAttempt: { distinctReason: 'resubmitted_new_cv' },
      })
      expect(res.status).toBe(409)
      expect(res.json.conflictingId).toBe(a)
      expect(storeBytes()).toEqual(before)
      expect(fs.readdirSync(path.join(root, 'data/applications/files')).filter((d) => d !== a)).toEqual([])
    }
  })

  it('the verified new CV of the 6c rule still creates', async () => {
    await create()
    const res = await create({ attempt: { cv: { kind: 'library', cvLibraryId: CV_B } }, newAttempt: { distinctReason: 'resubmitted_new_cv' } })
    expect(res.status).toBe(201)
  })
})

describe('closed applications and the way back', () => {
  async function rejectedWithReapply() {
    const a = (await create()).json.application.id
    await move(a, { toStage: 'rejected' })
    const b = (await create()).json.application.id
    return { a, b }
  }

  it('example 2: a reopen that competes with a reapply is refused, on /move and /events', async () => {
    const { a, b } = await rejectedWithReapply()
    expect((await getStore()).applications[b].attempt.distinctReason).toBe('reapply_after_outcome')
    const before = storeBytes()
    const viaMove = await move(a, { toStage: 'tech' })
    expect(viaMove.status).toBe(409)
    expect(viaMove.json.conflictingId).toBe(b)
    const viaEvents = await addEvent(a, { type: 'outcome_cleared', data: { reason: 'r' } })
    expect(viaEvents.status).toBe(409)
    expect(viaEvents.json.conflictingId).toBe(b)
    expect(storeBytes()).toEqual(before)
    expect(await foldedOf(a)).toMatchObject({ outcome: 'rejected' })

    await move(b, { toStage: 'rejected' })
    expect((await move(a, { toStage: 'tech' })).status).toBe(200)
    expect(await foldedOf(a)).toMatchObject({ outcome: null, stage: 'tech' })
  })

  it('example 3: another channel does not compete', async () => {
    const a = (await create()).json.application.id
    await move(a, { toStage: 'rejected' })
    expect((await create({ attempt: { channel: 'referral' } })).status).toBe(201)
    expect((await move(a, { toStage: 'tech' })).status).toBe(200)
  })

  it('example 4: a restore that competes is refused and the application stays voided', async () => {
    const a = (await create()).json.application.id
    await addEvent(a, { type: 'application_voided', data: { reason: 'r' } })
    const b = (await create()).json.application.id
    const before = storeBytes()
    const res = await addEvent(a, { type: 'application_restored', data: { reason: 'r' } })
    expect(res.status).toBe(409)
    expect(res.json.conflictingId).toBe(b)
    expect(storeBytes()).toEqual(before)
  })

  it('example 5: a closed application restores without a check; reopening it is checked', async () => {
    const a = (await create()).json.application.id
    await move(a, { toStage: 'rejected' })
    await addEvent(a, { type: 'application_voided', data: { reason: 'mistake' } })
    const b = (await create()).json.application.id
    expect((await addEvent(a, { type: 'application_restored', data: { reason: 'it was real' } })).status).toBe(201)
    expect(boardColumn(await foldedOf(a), (await getSettings()).settings)).toBe('rejected')
    const res = await move(a, { toStage: 'tech' })
    expect(res.status).toBe(409)
    expect(res.json.conflictingId).toBe(b)
  })

  it('closed to closed needs no check', async () => {
    const { a } = await rejectedWithReapply()
    const res = await move(a, { toStage: 'ghosted' })
    expect(res.status).toBe(200)
    expect(res.json.events.map((e) => e.type)).toEqual(['outcome_cleared', 'outcome_set'])
  })

  it('example 6: a ghosted company replies, with no other attempt', async () => {
    const a = (await create()).json.application.id
    await move(a, { toStage: 'ghosted' })
    expect((await move(a, { toStage: 'screen' })).status).toBe(200)
    expect(Object.keys((await getStore()).applications)).toEqual([a])
  })

  it('a verified new CV does not compete; a closed one next to it reopens', async () => {
    const a = (await create()).json.application.id
    const b = (await create({
      attempt: { cv: { kind: 'library', cvLibraryId: CV_B } }, newAttempt: { distinctReason: 'resubmitted_new_cv' },
    })).json.application.id
    await move(a, { toStage: 'rejected' })
    expect((await move(a, { toStage: 'tech' })).status).toBe(200)
    expect(activeIds(await getStore())).toEqual([a, b].sort())
  })

  it('example 7 and 8: a new attempt after a rejection, an accidental duplicate before it', async () => {
    const a = (await create()).json.application.id
    expect((await create()).status).toBe(409)
    await move(a, { toStage: 'rejected' })
    const b = await create()
    expect(b.status).toBe(201)
    expect(b.json.application.attempt).toMatchObject({ previousApplicationId: a, distinctReason: 'reapply_after_outcome' })
    expect(await foldedOf(a)).toMatchObject({ outcome: 'rejected' })
  })
})

// --- time in stage, applied date and CV corrections (O4) ---------------------------------------

describe('fold: stage history and corrections', () => {
  it('stageSince and stageHistory follow the events, with reopen starting a new spell', async () => {
    const id = (await create({ attempt: { appliedDate: '2026-11-01' } })).json.application.id
    expect(await foldedOf(id)).toMatchObject({
      stage: 'applied', stageSince: '2026-11-01', stageHistory: [{ stage: 'applied', from: '2026-11-01', to: null }],
    })
    clock = new Date('2026-11-05T10:00:00.000Z')
    await move(id, { toStage: 'screen' })
    clock = new Date('2026-11-10T10:00:00.000Z')
    await move(id, { toStage: 'tech' })
    clock = new Date('2026-11-20T10:00:00.000Z')
    await move(id, { toStage: 'rejected' })
    clock = new Date('2026-11-25T10:00:00.000Z')
    await move(id, { toStage: 'tech' })
    const folded = await foldedOf(id)
    expect(folded.stageSince).toBe('2026-11-10')
    expect(folded.stageHistory).toEqual([
      { stage: 'applied', from: '2026-11-01', to: '2026-11-05' },
      { stage: 'screen', from: '2026-11-05', to: '2026-11-10' },
      { stage: 'tech', from: '2026-11-10', to: '2026-11-20' },
      { stage: 'tech', from: '2026-11-25', to: null },
    ])
    expect(folded.stageHistory.map((h) => daysInStage(h, '2026-11-30'))).toEqual([4, 5, 10, 5])
    expect(daysBetween(null, '2026-11-30')).toBeNull()
  })

  describe('time in stage comes from the newest stageHistory entry, not from stageSince', () => {
    const at = (day) => { clock = new Date(`${day}T10:00:00.000Z`) }
    async function tracked() {
      const id = (await create({ attempt: { appliedDate: '2026-11-01' } })).json.application.id
      at('2026-11-05'); await move(id, { toStage: 'screen' })
      at('2026-11-10'); await move(id, { toStage: 'tech' })
      return id
    }

    it('reopening into the same stage restarts the count; stageSince keeps the old date', async () => {
      const id = await tracked()
      at('2026-11-20'); await move(id, { toStage: 'rejected' })
      expect(daysInCurrentStage(await foldedOf(id), '2026-11-30')).toBe(10) // closed: ends on the day it closed
      at('2026-11-25'); await move(id, { toStage: 'tech' })
      const folded = await foldedOf(id)
      expect(folded.stageSince).toBe('2026-11-10')
      expect(daysInCurrentStage(folded, '2026-11-30')).toBe(5)
    })

    it('reopening into a different stage counts from the reopen day', async () => {
      const id = await tracked()
      at('2026-11-20'); await move(id, { toStage: 'ghosted' })
      at('2026-11-25'); await move(id, { toStage: 'onsite' })
      const folded = await foldedOf(id)
      expect(folded.stage).toBe('onsite')
      expect(folded.stageSince).toBe('2026-11-25')
      expect(daysInCurrentStage(folded, '2026-11-30')).toBe(5)
      expect(folded.stageHistory.at(-1)).toEqual({ stage: 'onsite', from: '2026-11-25', to: null })
    })

    it('moving back to an earlier stage counts from the move', async () => {
      const id = await tracked()
      at('2026-11-18'); await move(id, { toStage: 'screen' })
      const folded = await foldedOf(id)
      expect(folded.stageSince).toBe('2026-11-18')
      expect(daysInCurrentStage(folded, '2026-11-30')).toBe(12)
      expect(folded.stageHistory.map((h) => h.stage)).toEqual(['applied', 'screen', 'tech', 'screen'])
    })

    it('stage_changed after a reopen through /events starts a new count', async () => {
      const id = await tracked()
      at('2026-11-20'); await addEvent(id, { type: 'outcome_set', data: { outcome: 'rejected' } })
      at('2026-11-25')
      expect((await addEvent(id, { type: 'outcome_cleared', data: { reason: 'they wrote back' } })).status).toBe(201)
      expect(daysInCurrentStage(await foldedOf(id), '2026-11-30')).toBe(5) // reopened in tech on 11-25
      at('2026-11-27')
      expect((await addEvent(id, { type: 'stage_changed', data: { stage: 'onsite' } })).status).toBe(201)
      const folded = await foldedOf(id)
      expect(folded.stageSince).toBe('2026-11-27')
      expect(daysInCurrentStage(folded, '2026-11-30')).toBe(3)
    })
  })

  it('a voided stage change leaves no trace in the history', async () => {
    const id = (await create({ attempt: { appliedDate: '2026-11-01' } })).json.application.id
    await move(id, { toStage: 'tech' })
    await addEvent(id, { type: 'event_voided', data: { eventId: `${id}:2`, reason: 'wrong card' } })
    const folded = await foldedOf(id)
    expect(folded.stageHistory).toEqual([{ stage: 'applied', from: '2026-11-01', to: null }])
    expect(folded.stageSince).toBe('2026-11-01')
  })

  it('the applied date is corrected by an event; the frozen attempt stays', async () => {
    clock = new Date('2026-11-10T10:00:00.000Z')
    const id = (await create({ attempt: { appliedDate: '2026-11-03' } })).json.application.id
    const before = (await getStore()).applications[id]
    expect((await addEvent(id, { type: 'applied_date_corrected', data: { appliedDate: '2026-11-01' } })).status).toBe(201)
    const after = (await getStore()).applications[id]
    expect(after.attempt).toEqual(before.attempt)
    expect(after.events[0]).toEqual(before.events[0])
    const folded = foldApplication(after)
    expect(folded.appliedDate).toBe('2026-11-01')
    expect(folded.stageSince).toBe('2026-11-01')
    expect(folded.lastActivityDate).toBe('2026-11-03') // a correction is not activity
    for (const bad of [{ appliedDate: '2026-11-11' }, { appliedDate: '2026-02-30' }, { appliedDate: 'x' }, {}]) {
      expect((await addEvent(id, { type: 'applied_date_corrected', data: bad })).status).toBe(400)
    }
    await addEvent(id, { type: 'event_voided', data: { eventId: `${id}:2`, reason: 'wrong day' } })
    expect((await foldedOf(id)).appliedDate).toBe('2026-11-03')
  })
})

describe('outcomes set through /events', () => {
  const column = async (id) => boardColumn(await foldedOf(id), (await getSettings()).settings)

  for (const outcome of ['rejected', 'ghosted']) {
    it(`${outcome} closes the application: out of the open columns, refusing stage and outcome until reopened`, async () => {
      const id = (await create()).json.application.id
      await move(id, { toStage: 'tech' })
      expect((await getSettings()).counts).toMatchObject({ tech: 1, [outcome]: 0 })
      expect((await addEvent(id, { type: 'outcome_set', data: { outcome } })).status).toBe(201)

      const folded = await foldedOf(id)
      expect(folded).toMatchObject({ outcome, stage: 'tech', voided: false })
      expect(await column(id)).toBe(outcome)
      expect((await getSettings()).counts).toMatchObject({ applied: 0, tech: 0, [outcome]: 1 })
      // open-only checks ignore it: the occupied column can be retired
      expect((await call('POST', '/api/applications/settings/stages', { op: 'retire', key: 'tech' })).status).toBe(200)

      const before = storeBytes()
      expect((await addEvent(id, { type: 'stage_changed', data: { stage: 'screen' } })).status).toBe(400)
      expect((await addEvent(id, { type: 'outcome_set', data: { outcome: outcome === 'rejected' ? 'ghosted' : 'rejected' } })).status).toBe(400)
      expect((await addEvent(id, { type: 'outcome_set', data: { outcome } })).status).toBe(400)
      expect(storeBytes()).toEqual(before)

      expect((await addEvent(id, { type: 'outcome_cleared', data: { reason: 'reply' } })).status).toBe(201)
      expect((await foldedOf(id)).outcome).toBeNull()
      expect((await addEvent(id, { type: 'stage_changed', data: { stage: 'screen' } })).status).toBe(201)
    })
  }

  it('a voided application with an outcome stays out of the statistics', async () => {
    const kept = (await create()).json.application.id
    const mistake = (await create({ jobId: OTHER_BOARD_JOB.jobId })).json.application.id
    await addEvent(kept, { type: 'outcome_set', data: { outcome: 'rejected' } })
    const alone = stats([(await getStore()).applications[kept]])
    await addEvent(mistake, { type: 'outcome_set', data: { outcome: 'offer_accepted' } })
    await addEvent(mistake, { type: 'application_voided', data: { reason: 'wrong job' } })
    expect(stats(Object.values((await getStore()).applications))).toEqual(alone)
    expect(await column(mistake)).toBeNull()
    expect((await getSettings()).counts).toMatchObject({ rejected: 1, closed: 0 })
  })
})

describe('CV corrections', () => {
  const unknownCv = { cv: { kind: 'unknown' } }

  it('records a CV later as a new event, and the first record needs no reason', async () => {
    const app = (await create({ attempt: unknownCv })).json.application
    expect(app.attempt.cv).toMatchObject({ kind: 'unknown', fileName: null, sha256: null })
    const res = await addEvent(app.id, { type: 'cv_recorded', data: { kind: 'library', cvLibraryId: CV_A, label: 'Main CV', fileName: 'Main.pdf' } })
    expect(res.status).toBe(201)
    expect(res.json.event.data).toEqual({ kind: 'library', cvLibraryId: CV_A, label: 'Main CV', fileName: 'Main.pdf', sha256: sha(PDF_A) })
    const after = (await getStore()).applications[app.id]
    expect(after.attempt).toEqual(app.attempt)
    expect(foldApplication(after).cv).toEqual(res.json.event.data)
    const file = await fetch(`${base}/api/applications/${app.id}/files/Main.pdf`)
    expect(sha(Buffer.from(await file.arrayBuffer()))).toBe(sha(PDF_A))
    expect(foldApplication(after).lastActivityDate).toBe('2026-11-03')
  })

  it('a correction needs a reason, takes a new file name and never replaces a copy', async () => {
    const app = (await create()).json.application // library CV_A as Nikola_CV.pdf
    const body = { kind: 'library', cvLibraryId: CV_B, label: 'Newer CV', fileName: 'Nikola_CV.pdf' }
    const before = storeBytes()
    expect((await addEvent(app.id, { type: 'cv_recorded', data: body })).status).toBe(400)
    expect(storeBytes()).toEqual(before)
    const res = await addEvent(app.id, { type: 'cv_recorded', data: { ...body, reason: 'sent the wrong file' } })
    expect(res.status).toBe(201)
    expect(res.json.event.data).toMatchObject({ fileName: 'Nikola_CV-2.pdf', sha256: sha(PDF_B), reason: 'sent the wrong file' })
    const again = await addEvent(app.id, { type: 'cv_recorded', data: { ...body, reason: 'and again' } })
    expect(again.json.event.data.fileName).toBe('Nikola_CV-3.pdf')

    const dir = path.join(root, `data/applications/files/${app.id}`)
    expect(fs.readdirSync(dir).sort()).toEqual(['Nikola_CV-2.pdf', 'Nikola_CV-3.pdf', 'Nikola_CV.pdf'])
    expect(fs.readFileSync(path.join(dir, 'Nikola_CV.pdf'))).toEqual(PDF_A)
    const stored = (await getStore()).applications[app.id]
    expect(stored.attempt.cv).toEqual(app.attempt.cv)
    expect(foldApplication(stored).cv.fileName).toBe('Nikola_CV-3.pdf')
    // earlier copies stay downloadable, each by its own name
    for (const [name, bytes] of [['Nikola_CV.pdf', PDF_A], ['Nikola_CV-2.pdf', PDF_B]]) {
      const file = await fetch(`${base}/api/applications/${app.id}/files/${name}`)
      expect(Buffer.from(await file.arrayBuffer())).toEqual(bytes)
    }
    // voiding the latest record falls back to the one before
    await addEvent(app.id, { type: 'event_voided', data: { eventId: again.json.event.id, reason: 'no' } })
    expect(foldApplication((await getStore()).applications[app.id]).cv.fileName).toBe('Nikola_CV-2.pdf')
  })

  it('refuses an unknown kind, a path from the client and a file that does not exist; leaves no copy behind', async () => {
    const app = (await create({ attempt: unknownCv })).json.application
    const before = storeBytes()
    for (const data of [
      { kind: 'unknown' }, { kind: 'made_up' }, { kind: 'library', cvLibraryId: '../../etc' }, { kind: 'library' },
      { kind: 'tailored', fileName: '../x.pdf' }, { kind: 'tailored', fileName: 'missing.pdf' }, { kind: 'library', cvLibraryId: 'a'.repeat(16) },
    ]) expect((await addEvent(app.id, { type: 'cv_recorded', data })).status).toBe(400)
    expect(storeBytes()).toEqual(before)
    expect(fs.existsSync(path.join(root, `data/applications/files/${app.id}`))).toBe(false)

    vi.spyOn(fs, 'renameSync').mockImplementationOnce(() => { throw new Error('disk full') })
    const failed = await addEvent(app.id, { type: 'cv_recorded', data: { kind: 'tailored', fileName: 'Acme_Resume.pdf' } })
    expect(failed.status).toBe(500)
    expect(fs.readdirSync(path.join(root, `data/applications/files/${app.id}`))).toEqual([])
  })

  it('an external CV records a label and no file', async () => {
    const app = (await create({ attempt: unknownCv })).json.application
    const res = await addEvent(app.id, { type: 'cv_recorded', data: { kind: 'external', label: 'PDF from my laptop' } })
    expect(res.json.event.data).toEqual({ kind: 'external', cvLibraryId: null, label: 'PDF from my laptop', fileName: null, sha256: null })
  })

  it('a correction may not make two applications compete', async () => {
    await create()
    const b = (await create({
      attempt: { cv: { kind: 'library', cvLibraryId: CV_B } }, newAttempt: { distinctReason: 'resubmitted_new_cv' },
    })).json.application.id
    const before = storeBytes()
    const res = await addEvent(b, { type: 'cv_recorded', data: { kind: 'library', cvLibraryId: CV_A, fileName: 'again.pdf', reason: 'it was CV A' } })
    expect(res.status).toBe(409)
    expect(storeBytes()).toEqual(before)
    expect(fs.readdirSync(path.join(root, `data/applications/files/${b}`))).toEqual(['cv-fedcba9876543210.pdf'])
  })
})

// --- backup of the settings (3.1 step 5) -------------------------------------------------------

describe('backup of the stage settings', () => {
  const backupSettings = (work, extra = {}) => JSON.stringify({
    version: 1, updatedAt: '2026-10-01T00:00:00.000Z', trackingEnabled: true, followUpReminders: true, changes: [], ...extra,
    stages: { work },
  })
  const stage = (key, label, extra = {}) => ({ key, label, retired: false, interview: false, ...extra })

  it('without a current file the backup file is written byte for byte', async () => {
    const data = backupSettings([stage('a', 'A'), stage('b', 'B', { retired: true })])
    const result = await importBackupZip(root, zipOf({ 'data/applications/settings.json': data }), { now })
    expect(result.applications.settings).toBe('written')
    expect(fs.readFileSync(settingsFile(), 'utf-8')).toBe(data)
    expect(result.applications.ignored).toEqual([])
  })

  it('merges by key: current switches, labels and order win; backup-only keys come in retired', async () => {
    await stageOp({ op: 'rename', key: 'tech', label: 'Technical' })
    await call('POST', '/api/applications/settings', { followUpReminders: false })
    const current = JSON.parse(settingsBytes())
    const data = backupSettings([
      stage('offer', 'Offer (old name)'), stage('tech', 'Tech (old name)'), stage('take_home', 'Take-home', { interview: true }),
      stage('panel', 'Panel', { retired: true }),
    ], { followUpReminders: true, trackingEnabled: false })
    clock = new Date('2026-11-04T12:00:00.000Z')
    const result = await importBackupZip(root, zipOf({ 'data/applications/settings.json': data }), { now })
    expect(result.applications.settings).toBe('merged')
    expect(result.applications.backupPath).toBe('data/backups/applications-20261104-120000')
    expect(fs.readFileSync(path.join(root, result.applications.backupPath, 'settings.json'))).toEqual(
      Buffer.from(`${JSON.stringify(current, null, 2)}\n`))

    const merged = JSON.parse(settingsBytes())
    expect(merged.trackingEnabled).toBe(true)
    expect(merged.followUpReminders).toBe(false)
    expect(merged.stages.work.slice(0, 4)).toEqual(current.stages.work)
    expect(merged.stages.work.slice(4)).toEqual([
      stage('take_home', 'Take-home', { retired: true, interview: true }), stage('panel', 'Panel', { retired: true }),
    ])
    expect(merged.changes.slice(-2).map((c) => [c.action, c.key, c.new])).toEqual([['restore', 'take_home', 'Take-home'], ['restore', 'panel', 'Panel']])

    // a second restore of the same file adds nothing
    const bytes = settingsBytes()
    expect((await importBackupZip(root, zipOf({ 'data/applications/settings.json': data }), { now })).applications.settings).toBe('unchanged')
    expect(settingsBytes()).toEqual(bytes)
  })

  it('an open application on a key the board lacks shows under Unfiled after a restore', async () => {
    const id = (await create()).json.application.id
    await move(id, { toStage: 'onsite' })
    fs.writeFileSync(settingsFile(), backupSettings([stage('screen', 'Screen'), stage('offer', 'Offer')]))
    const { settings } = await getSettings()
    expect(boardColumn(await foldedOf(id), settings)).toBe('unfiled')
  })

  it('invalid or unreadable backup settings are reported and change nothing', async () => {
    await stageOp({ op: 'add', label: 'Extra' })
    const before = settingsBytes()
    for (const data of ['{broken', JSON.stringify({ version: 1 }), backupSettings([stage('applied', 'Applied')])]) {
      const result = await importBackupZip(root, zipOf({ 'data/applications/settings.json': data }), { now })
      expect(result.applications.settings).toBe('kept')
      expect(result.applications.conflicts.map((c) => c.appId)).toEqual([null])
      expect(settingsBytes()).toEqual(before)
    }
  })

  it('a current file that is unreadable is left alone, and the applications still merge', async () => {
    fs.mkdirSync(path.dirname(settingsFile()), { recursive: true })
    fs.writeFileSync(settingsFile(), '{broken')
    const app = (await (async () => { fs.rmSync(settingsFile()); return create() })()).json.application
    fs.writeFileSync(settingsFile(), '{broken')
    const zip = zipOf({ 'data/applications/settings.json': backupSettings([stage('a', 'A')]) })
    const result = await importBackupZip(root, zip, { now })
    expect(result.applications.settings).toBe('kept')
    expect(fs.readFileSync(settingsFile(), 'utf-8')).toBe('{broken')
    expect(store.loadStore(root).applications[app.id]).toEqual(app)
  })

  it('a cv_recorded copy in a backup is restored, and a tampered one is refused', async () => {
    const app = (await create({ attempt: { cv: { kind: 'unknown' } } })).json.application
    const res = await addEvent(app.id, { type: 'cv_recorded', data: { kind: 'library', cvLibraryId: CV_A, fileName: 'Later.pdf' } })
    const zip = await streamToBuffer(createBackupStream(root))
    const other = fs.mkdtempSync(path.join(os.tmpdir(), 'apps-restore-'))
    try {
      const result = await importBackupZip(other, zip)
      expect(result.applications.filesAdded).toEqual([`${app.id}/Later.pdf`])
      expect(fs.readFileSync(path.join(other, `data/applications/files/${app.id}/Later.pdf`))).toEqual(PDF_A)
      expect(res.json.event.data.sha256).toBe(sha(PDF_A))
    } finally {
      fs.rmSync(other, { recursive: true, force: true })
    }
    const third = fs.mkdtempSync(path.join(os.tmpdir(), 'apps-restore-'))
    try {
      // Without its manifest, so this reaches the store's own check of the frozen file (the manifest hash refuses it earlier).
      const tampered = Object.fromEntries(new AdmZip(zip).getEntries().filter((e) => !e.isDirectory && e.entryName !== 'backup-manifest.json').map((e) => [
        e.entryName,
        e.entryName.endsWith('Later.pdf') ? Buffer.from('tampered') : e.getData(),
      ]))
      const result = await importBackupZip(third, zipOf(tampered))
      expect(result.applications.filesAdded).toEqual([])
      expect(result.applications.conflicts.map((c) => c.appId)).toEqual([app.id])
    } finally {
      fs.rmSync(third, { recursive: true, force: true })
    }
  })
})

// --- static checks -----------------------------------------------------------------------------

describe('isolation', () => {
  it('only the store module, and the chmod-only permissions script, name data/applications in src/ and scripts/', () => {
    const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
    const hits = []
    const walk = (dir) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) walk(full)
        else if (/\.(js|jsx|ts|tsx|mjs|cjs|sh)$/.test(entry.name) && fs.readFileSync(full, 'utf-8').includes('data/applications')) {
          hits.push(path.relative(repo, full))
        }
      }
    }
    walk(path.join(repo, 'src'))
    walk(path.join(repo, 'scripts'))
    expect(hits.sort()).toEqual(['scripts/application-store.js', 'scripts/tighten-data-permissions.sh'])
  })
})
