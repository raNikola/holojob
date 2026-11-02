import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import * as store from '../../scripts/application-store.js'
import { RedactionError, redactContext, setContactSource } from '../../scripts/ai-redact.js'
import * as client from '../../src/modules/applications/applicationsClient.js'
import { foldApplication, isActive } from '../../src/modules/applications/foldApplication.js'
import {
  draftFrom, markApplied, newRequestId, panelMode, planSave, saveDraft, scheduleFollowUp, stageOptions,
  restoreApplication, voidApplication,
} from '../../src/modules/applications/trackerController.js'
import { applicationsForJob, overlayTracking, trackingFromApplication } from '../../src/modules/applications/trackingView.js'
import { computeJobStats } from '../../src/modules/jobs/jobStats.js'
import { importJobsFromFile, updateJobRecord } from '../../src/modules/jobs/jobStorage.js'

const id16 = (n) => crypto.createHash('sha256').update(`panel-${n}`).digest('hex').slice(0, 16)
const FRESH = id16('fresh')
const LEGACY = id16('legacy')
const slim = (jobId, extra = {}) => ({ jobId, title: `PM ${jobId.slice(0, 4)}`, company: 'Acme', jobUrl: `https://acme.example/${jobId}`, ...extra })
const LEGACY_TRACKING = { applied: true, appliedDate: '2026-10-01', notes: 'phoned', recruiterName: 'Old Recruiter', interviewStage: 'HR Screen', lastUpdated: '2026-10-02T09:00:00.000Z' }

let root
let server
let clock
let fetchCalls
const now = () => clock
const storeFile = () => path.join(root, 'data/applications/applications.json')
const storeBytes = () => (fs.existsSync(storeFile()) ? fs.readFileSync(storeFile()) : null)
const clone = (v) => JSON.parse(JSON.stringify(v))
const cache = () => client.getApplicationsState()
const form = (extra = {}) => ({ requestId: newRequestId(), channel: 'company_site', appliedDate: '2026-11-01', applicationUrl: 'https://acme.example/apply', ...extra })

beforeEach(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'panel-'))
  clock = new Date('2026-11-03T10:00:00.000Z')
  fetchCalls = 0
  server = http.createServer(async (req, res) => {
    if (!(await store.handleApplicationsRequest(req, res, req.url.split('?')[0], { root, now }))) { res.statusCode = 418; res.end() }
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  client.configureClient({
    base: `http://127.0.0.1:${server.address().port}`,
    ensure: async () => true,
    fetch: (...args) => { fetchCalls += 1; return globalThis.fetch(...args) },
  })
  await client.refreshApplications()
})

afterEach(async () => {
  client.configureClient()
  setContactSource()
  vi.restoreAllMocks()
  await new Promise((resolve) => server.close(resolve))
  fs.rmSync(root, { recursive: true, force: true })
})

const migrate = (jobs) => store.migrateApplications(root, { jobs, confirm: true, previewSha: store.previewShaOf(jobs) }, { now })

describe('the panel is blocked for a job that is not migrated', () => {
  it('shows nothing while the cache is not loaded', () => {
    expect(panelMode(slim(FRESH), { status: 'idle' })).toEqual({ mode: 'loading' })
    expect(panelMode(slim(FRESH), { status: 'error', error: 'down' })).toEqual({ mode: 'error', message: 'down' })
  })

  it('uses the same rule as the migration: old tracking and no application means migrate first', async () => {
    const legacy = slim(LEGACY, { applicationTracking: LEGACY_TRACKING })
    expect(panelMode(legacy, cache())).toMatchObject({ mode: 'migrate-first', reason: null })
    expect(panelMode(slim(LEGACY, { status: 'applied_manually' }), cache()).mode).toBe('migrate-first')
    // opened and saved empty: the migration ignores it, so the panel must not block it
    const empty = slim(FRESH, { applicationTracking: { applied: false, lastUpdated: '2026-10-01T00:00:00.000Z' } })
    expect(store.planMigration([empty], { store: store.emptyStore(), settings: store.loadSettings(root), now: clock }).counts.candidates).toBe(0)
    expect(panelMode(empty, cache()).mode).toBe('new')
    // a job the migration cannot map says why
    expect(panelMode(slim('not-hex', { applicationTracking: LEGACY_TRACKING }), cache())).toMatchObject({ mode: 'migrate-first', reason: 'jobId is not 16 hex characters' })
  })

  it('refuses a new entry without a request or a write, so a job cannot get two records', async () => {
    const legacy = slim(LEGACY, { applicationTracking: LEGACY_TRACKING })
    const before = fetchCalls
    await expect(markApplied(legacy, cache(), form())).rejects.toMatchObject({ status: 409, message: expect.stringContaining('Run the migration first') })
    expect(fetchCalls).toBe(before)
    expect(storeBytes()).toBeNull()
  })

  it('opens once the job is migrated', async () => {
    const legacy = slim(LEGACY, { applicationTracking: LEGACY_TRACKING })
    await migrate([legacy])
    await client.refreshApplications()
    const mode = panelMode(legacy, cache())
    expect(mode.mode).toBe('tracked')
    expect(mode.current.id).toBe(`mig-${LEGACY}`)
    // and a second record for the same job is still refused by the store while that one is open
    await expect(markApplied(legacy, cache(), form({ channel: 'other' }))).rejects.toMatchObject({ status: 409 })
    expect(Object.keys(store.loadStore(root).applications)).toEqual([`mig-${LEGACY}`])
  })
})

describe('panel writes go to the store only', () => {
  it('creates and edits through the routes and never touches the job record', async () => {
    const job = slim(FRESH)
    const raw = clone(job)
    const created = await markApplied(job, cache(), form())
    const appId = created.application.id
    expect(created.application).toMatchObject({ origin: 'manual', posting: { jobId: FRESH, capturedFrom: 'browser' }, attempt: { channel: 'company_site', appliedDate: '2026-11-01', cv: { kind: 'unknown' } } })

    clock = new Date('2026-11-05T10:00:00.000Z')
    const draft = {
      ...draftFrom(cache().store.applications[appId]),
      stage: 'tech', appliedDate: '2026-10-30', followUpDate: '2026-11-12',
      recruiterName: 'Jane Doe', recruiterEmail: 'jane@acme.example', recruiterLinkedIn: '', newNote: 'Intro call went well',
    }
    expect(await saveDraft(appId, draft)).toBe(5)
    const app = store.loadStore(root).applications[appId]
    expect(app.events.map((e) => e.type)).toEqual(['applied', 'stage_changed', 'applied_date_corrected', 'follow_up_set', 'contact_added', 'note_added'])
    expect(cache().store.applications[appId]).toEqual(app)
    expect(foldApplication(app)).toMatchObject({ stage: 'tech', appliedDate: '2026-10-30', followUpDate: '2026-11-12' })

    // an unchanged draft sends nothing; a changed contact is an update, a cleared date is a done event
    expect(planSave(app, draftFrom(app))).toEqual([])
    const second = { ...draftFrom(app), recruiterName: 'Jane D.', followUpDate: '' }
    expect(planSave(app, second).map((c) => c.event.type)).toEqual(['follow_up_done', 'contact_updated'])

    expect(job).toEqual(raw) // the job record has no applicationTracking and none was added
  })

  it('an overlaid row cannot write tracking back into the job', () => {
    const job = slim(FRESH, { applicationTracking: LEGACY_TRACKING })
    const derived = { ...job, applicationTracking: { applied: true, notes: 'from the store' } }
    expect(updateJobRecord([job], FRESH, { ...derived, title: 'Renamed' })[0]).toEqual({ ...job, title: 'Renamed' })
  })

  it('the panel, the three writers and the drawer no longer write the legacy field', () => {
    const files = [
      'components/jobs/ApplicationTrackerPanel.jsx', 'components/jobs/JobDetailDrawer.jsx', 'components/applications/ApplicationHome.jsx',
      'components/jobs/JobDiscoveryScreen.jsx', 'components/outreach/OutreachDashboard.jsx',
      'modules/applications/trackerController.js',
    ]
    for (const file of files) {
      const text = fs.readFileSync(path.join(process.cwd(), 'src', file), 'utf-8')
      expect(text, file).not.toMatch(/updateApplicationTracking|onApplicationSave|handleApplicationSave/)
      expect(text, file).not.toMatch(/applicationTracking\s*:\s*(?!null)/)
    }
    const all = fs.readdirSync(path.join(process.cwd(), 'src'), { recursive: true }).filter((f) => /\.jsx?$/.test(f))
    const writers = all.filter((f) => fs.readFileSync(path.join(process.cwd(), 'src', f), 'utf-8').includes('updateApplicationTracking'))
    expect(writers).toEqual([])
  })

  it('a save that fails half way is retried without repeating what landed', async () => {
    const job = slim(FRESH)
    const appId = (await markApplied(job, cache(), form())).application.id
    const draft = { ...draftFrom(cache().store.applications[appId]), stage: 'screen', appliedDate: '2026-12-31', newNote: 'only once' }
    await expect(saveDraft(appId, draft)).rejects.toMatchObject({ status: 400 }) // the date is in the future
    expect(foldApplication(cache().store.applications[appId]).stage).toBe('screen')
    await saveDraft(appId, { ...draft, appliedDate: '2026-10-29' })
    const events = store.loadStore(root).applications[appId].events.map((e) => e.type)
    expect(events).toEqual(['applied', 'stage_changed', 'applied_date_corrected', 'note_added'])
  })

  it('a retry with the same request id returns the same application', async () => {
    const job = slim(FRESH)
    const f = form()
    const a = await markApplied(job, cache(), f)
    const b = await markApplied(job, cache(), f)
    expect(b.application.id).toBe(a.application.id)
    expect(Object.keys(store.loadStore(root).applications)).toHaveLength(1)
  })

  it('tracking switched off is reported as such', async () => {
    await client.refreshApplications()
    const res = await fetch(`http://127.0.0.1:${server.address().port}/api/applications/settings`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ trackingEnabled: false }),
    })
    expect(res.status).toBe(200)
    await expect(markApplied(slim(FRESH), cache(), form())).rejects.toMatchObject({ status: 409, extra: { code: 'tracking_disabled' } })
  })

  it('offers the outcomes only on an open application and the stage targets always', async () => {
    const appId = (await markApplied(slim(FRESH), cache(), form())).application.id
    const open = foldApplication(cache().store.applications[appId])
    expect(stageOptions(cache().settings, open).map((o) => o.value)).toEqual(expect.arrayContaining(['applied', 'tech', 'rejected', 'ghosted', 'outcome:withdrawn']))
    await saveDraft(appId, { ...draftFrom(cache().store.applications[appId]), stage: 'outcome:withdrawn' })
    const closed = foldApplication(cache().store.applications[appId])
    expect(closed.outcome).toBe('withdrawn')
    expect(stageOptions(cache().settings, closed).filter((o) => o.kind === 'outcome').map((o) => o.value)).toEqual(['outcome:withdrawn'])
    expect(() => planSave(cache().store.applications[appId], { ...draftFrom(cache().store.applications[appId]), stage: 'outcome:position_closed' })).toThrow(/Reopen/)
    // reopening to a stage is a move
    await saveDraft(appId, { ...draftFrom(cache().store.applications[appId]), stage: 'screen' })
    expect(foldApplication(cache().store.applications[appId])).toMatchObject({ stage: 'screen', outcome: null })
  })
})

describe('an edit after the migration survives', () => {
  it('a re-import and a re-run of the migration', async () => {
    const legacy = slim(LEGACY, { applicationTracking: LEGACY_TRACKING })
    let browser = { meta: null, jobs: [legacy], filters: {} }
    await migrate(browser.jobs)
    await client.refreshApplications()
    const appId = `mig-${LEGACY}`
    clock = new Date('2026-11-06T10:00:00.000Z')
    await saveDraft(appId, { ...draftFrom(cache().store.applications[appId]), stage: 'onsite', newNote: 'edited after the migration' })
    const bytes = storeBytes()

    // a re-import that lacks the job, then one that carries it changed
    browser = importJobsFromFile({ jobs: [slim(id16('other'))] }, browser)
    expect(browser.jobs.find((j) => j.jobId === LEGACY)?.offList).toBe(true) // a row with tracking is kept, marked
    browser = importJobsFromFile({ jobs: [{ ...legacy, title: 'Retitled', description: 'new ad' }] }, browser)
    expect(storeBytes()).toEqual(bytes)

    // the migration, run again on the browser list as it is now
    const dry = await store.previewMigration(root, { jobs: browser.jobs }, { now })
    expect(dry).toMatchObject({ toCreate: 0, legacyChanged: 0, counts: { alreadyMigrated: 1 } })
    const run = await migrate(browser.jobs)
    expect(run.counts).toMatchObject({ created: 0, alreadyMigrated: 1 })
    expect(storeBytes()).toEqual(bytes)
    const app = store.loadStore(root).applications[appId]
    expect(app.events.map((e) => e.type).slice(-2)).toEqual(['stage_changed', 'note_added'])
    expect(app.events.at(-1).data.text).toBe('edited after the migration')
    expect(applicationsForJob(store.loadStore(root), LEGACY)).toHaveLength(1)
  })

  it('the dry run warns when the old field changed after the migration', async () => {
    const legacy = slim(LEGACY, { applicationTracking: LEGACY_TRACKING })
    await migrate([legacy])
    const edited = { ...legacy, applicationTracking: { ...LEGACY_TRACKING, notes: 'written to the old field', followUpDate: '2026-11-20', lastUpdated: '2026-11-04T08:00:00.000Z' } }
    const dry = await store.previewMigration(root, { jobs: [edited] }, { now })
    expect(dry.legacyChanged).toBe(1)
    expect(dry.entries[0]).toMatchObject({ action: 'alreadyMigrated', legacyChanged: ['followUpDate', 'notes'] })
    expect(dry.entries[0].warnings[0]).toContain('followUpDate, notes')
    expect(dry.counts).toMatchObject({ candidates: 1, alreadyMigrated: 1, unmappable: 0 })
    const run = await migrate([edited])
    const log = JSON.parse(fs.readFileSync(path.join(root, 'data/applications/migration.json'), 'utf-8'))
    expect(log.runs.at(-1).legacyChanged).toEqual([{ jobId: LEGACY, appId: `mig-${LEGACY}`, fields: ['followUpDate', 'notes'] }])
    expect(run.counts.created).toBe(0)

    // no warning when only the bookkeeping stamp moved, or when an import dropped the object
    const stamped = { ...legacy, applicationTracking: { ...LEGACY_TRACKING, lastUpdated: '2026-12-01T00:00:00.000Z' } }
    expect((await store.previewMigration(root, { jobs: [stamped] }, { now })).legacyChanged).toBe(0)
    expect((await store.previewMigration(root, { jobs: [slim(LEGACY)] }, { now })).legacyChanged).toBe(0)
  })

  it('a status-only job that gained tracking counts as changed', async () => {
    const job = slim(LEGACY, { status: 'applied_manually' })
    await migrate([job])
    const dry = await store.previewMigration(root, { jobs: [{ ...job, applicationTracking: { applied: true, notes: 'late' } }] }, { now })
    expect(dry.entries[0].legacyChanged).toEqual(['applied', 'notes'])
  })
})

describe('several applications for one posting', () => {
  it('stay possible: reapply after a rejection, and a separate attempt through another channel', async () => {
    const job = slim(FRESH)
    const first = (await markApplied(job, cache(), form())).application
    clock = new Date('2026-11-03T11:00:00.000Z')
    // an accidental duplicate is refused with the id of the open one
    await expect(markApplied(job, cache(), form())).rejects.toMatchObject({ status: 409, extra: { conflictingId: first.id } })
    // another channel needs the user to say so
    await expect(markApplied(job, cache(), form({ channel: 'referral' }))).rejects.toMatchObject({ status: 409 })
    const referral = (await markApplied(job, cache(), form({ channel: 'referral', separateAttempt: 'different_channel' }))).application
    expect(referral.attempt).toMatchObject({ previousApplicationId: first.id, distinctReason: 'different_channel' })
    clock = new Date('2026-11-03T12:00:00.000Z')

    await saveDraft(first.id, { ...draftFrom(cache().store.applications[first.id]), stage: 'rejected' })
    await saveDraft(referral.id, { ...draftFrom(cache().store.applications[referral.id]), stage: 'rejected' })
    const again = (await markApplied(job, cache(), form({ appliedDate: '2026-11-03' }))).application
    expect(again.attempt.distinctReason).toBe('reapply_after_outcome')

    const mode = panelMode(job, cache())
    expect(mode.mode).toBe('tracked')
    expect(mode.attempts.map((a) => a.id)).toEqual([first.id, referral.id, again.id])
    expect(mode.current.id).toBe(again.id)
    expect(Object.keys(store.loadStore(root).applications)).toHaveLength(3)
  })

  it('a voided application can be restored, and a restore that would duplicate is refused', async () => {
    const job = slim(FRESH)
    const a = (await markApplied(job, cache(), form())).application
    await voidApplication(a.id, 'mistake')
    expect(isActive(cache().store.applications[a.id])).toBe(false)
    const b = (await markApplied(job, cache(), form())).application
    await expect(restoreApplication(a.id, 'back')).rejects.toMatchObject({ status: 409, extra: { conflictingId: b.id } })
    await voidApplication(b.id, 'also')
    await restoreApplication(a.id, 'back')
    expect(isActive(cache().store.applications[a.id])).toBe(true)
  })
})

describe('what the older screens read', () => {
  it('derives the old tracking shape from the store, and voided means no tracking', async () => {
    const job = slim(FRESH)
    const appId = (await markApplied(job, cache(), form())).application.id
    await saveDraft(appId, { ...draftFrom(cache().store.applications[appId]), stage: 'tech', followUpDate: '2020-01-01', recruiterName: 'Jane', newNote: 'a' })
    await client.addEvent(appId, { type: 'note_added', data: { text: 'b' } })
    const tracking = trackingFromApplication(cache().store.applications[appId], cache().settings)
    expect(tracking).toMatchObject({ applied: true, appliedDate: '2026-11-01', applicationUrl: 'https://acme.example/apply', recruiterName: 'Jane', notes: 'a\nb', followUpDate: '2020-01-01', interviewStage: 'Tech' })
    const rows = overlayTracking([job, slim(id16('x'))], cache().store, cache().settings)
    expect(rows[0].applicationTracking).toEqual(tracking)
    expect(rows[1]).toEqual(slim(id16('x')))
    expect(computeJobStats(rows)).toMatchObject({ crmApplied: 1, crmInterviewing: 1, crmFollowUpsDue: 1 })

    await saveDraft(appId, { ...draftFrom(cache().store.applications[appId]), stage: 'ghosted' })
    expect(overlayTracking([job], cache().store, cache().settings)[0].applicationTracking.interviewStage).toBe('Ghosted')
    expect(computeJobStats(overlayTracking([job], cache().store, cache().settings))).toMatchObject({ crmInterviewing: 0, crmFollowUpsDue: 0 })

    await voidApplication(appId, 'mistake')
    const voided = overlayTracking([job], cache().store, cache().settings)[0]
    expect(voided.applicationTracking).toBeNull()
    expect(computeJobStats([voided])).toMatchObject({ crmApplied: 0 })
  })

  it('a follow-up scheduled from the Outreach screen is an event on the current application', async () => {
    await expect(scheduleFollowUp(FRESH, '2026-11-20', cache())).rejects.toMatchObject({ status: 409 })
    const appId = (await markApplied(slim(FRESH), cache(), form())).application.id
    await scheduleFollowUp(FRESH, '2026-11-20')
    expect(foldApplication(store.loadStore(root).applications[appId]).followUpDate).toBe('2026-11-20')
  })
})

describe('recruiters entered through the store are redacted for the AI features', () => {
  it('the contact hints come from every contact ever recorded, voided applications included', async () => {
    const appId = (await markApplied(slim(FRESH), cache(), form())).application.id
    await saveDraft(appId, { ...draftFrom(cache().store.applications[appId]), recruiterName: 'Mirela Fakeson', recruiterEmail: 'mirela@recruit-test.example', recruiterLinkedIn: 'https://www.linkedin.com/in/mirela-fakeson' })
    await saveDraft(appId, { ...draftFrom(cache().store.applications[appId]), recruiterName: 'Mirela F.' })
    await voidApplication(appId, 'mistake')
    const identity = store.knownContactIdentity(root)
    expect(identity.names).toEqual(['Mirela Fakeson', 'Mirela F.'])
    expect(identity.emails).toEqual(['mirela@recruit-test.example'])
    expect(identity.links).toEqual(['https://www.linkedin.com/in/mirela-fakeson'])
  })

  it('redactContext removes a contact that only the store knows, and fails closed when the store is unreadable', () => {
    setContactSource(() => ({ names: ['Mirela Fakeson'], emails: [], phones: [], links: [] }))
    const { context } = redactContext({ note: 'Spoke with Mirela Fakeson about the role', redactionHints: { owner: {}, contacts: {} } })
    expect(context.note).not.toContain('Mirela')
    expect(context.note).not.toContain('Fakeson')
    setContactSource(() => { throw new Error('boom') })
    expect(() => redactContext({ note: 'x' })).toThrow(RedactionError)
  })

  it('an unreadable store makes the identity reader throw rather than return nothing', () => {
    fs.mkdirSync(path.join(root, 'data/applications'), { recursive: true })
    fs.writeFileSync(storeFile(), '{broken')
    expect(() => store.knownContactIdentity(root)).toThrow()
  })
})
