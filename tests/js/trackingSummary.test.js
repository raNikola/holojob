import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import * as store from '../../scripts/application-store.js'
import * as client from '../../src/modules/applications/applicationsClient.js'
import { foldApplication } from '../../src/modules/applications/foldApplication.js'
import { applicationsForJob } from '../../src/modules/applications/trackingView.js'
import {
  DEFAULT_CHANNEL, markApplied, newApplicationDefaults, newRequestId, panelMode, restoreApplication, saveDraft, draftFrom, voidApplication,
} from '../../src/modules/applications/trackerController.js'
import { cvName, drawerTracking, formatAppDate, summarizeApplication } from '../../src/modules/applications/trackingSummary.js'
import { canOpenJobPage } from '../../src/modules/jobs/jobRoute.js'

const id16 = (n) => crypto.createHash('sha256').update(`summary-${n}`).digest('hex').slice(0, 16)
const LIB = id16('lib')
const profile = { defaultCvId: LIB, cvLibrary: [{ id: LIB, label: 'Main CV', fileName: 'main.pdf', filePath: `profile/cvs/${LIB}.pdf` }] }
const job = { jobId: id16('job'), title: 'PM', company: 'Acme', jobUrl: 'https://acme.example/pm' }

let root
let server
const cache = () => client.getApplicationsState()

beforeEach(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'psummary-'))
  fs.mkdirSync(path.join(root, 'data/profile/cvs'), { recursive: true })
  fs.writeFileSync(path.join(root, `data/profile/cvs/${LIB}.pdf`), '%PDF')
  const now = () => new Date('2026-11-03T10:00:00.000Z')
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

const quickApply = (extra = {}) => markApplied(job, cache(), { ...newApplicationDefaults(job, profile), ...extra })

describe('formatting', () => {
  it('formats a stored day like the board and returns nothing for an empty value', () => {
    expect(formatAppDate('2026-11-01')).toBe(new Date(2026, 10, 1).toLocaleDateString())
    expect(formatAppDate('')).toBe('')
    expect(formatAppDate(null)).toBe('')
  })
  it('names a CV only when one was recorded', () => {
    expect(cvName({ kind: 'unknown' })).toBe('')
    expect(cvName(null)).toBe('')
    expect(cvName({ kind: 'library', label: 'Main CV', fileName: 'main.pdf' })).toBe('Main CV')
    expect(cvName({ kind: 'library', fileName: 'main.pdf' })).toBe('main.pdf')
    expect(cvName({ kind: 'external' })).toBe('A CV outside the app')
  })
})

describe('the summary of an existing application', () => {
  it('shows the recorded values', async () => {
    const created = await quickApply({ appliedDate: '2026-11-01' })
    const id = created.application.id
    await saveDraft(id, { ...draftFrom(cache().store.applications[id]), followUpDate: '2026-11-10', recruiterName: 'Jane', newNote: 'Call went well' })
    const view = drawerTracking(job, cache())
    expect(view.kind).toBe('summary')
    expect(view.summary).toMatchObject({
      stage: 'Applied', appliedOn: formatAppDate('2026-11-01'), followUp: formatAppDate('2026-11-10'),
      cv: 'Main CV', recruiter: 'Jane', noteCount: 1,
    })
    expect(view.summary.eventCount).toBe(cache().store.applications[id].events.length)
  })

  it('leaves missing fields empty so the view shows a neutral placeholder, never an invented value', async () => {
    const created = await markApplied(job, cache(), { ...newApplicationDefaults(job, { cvLibrary: [] }), appliedDate: '' })
    const s = summarizeApplication(cache().store.applications[created.application.id], cache().settings)
    expect(s).toMatchObject({ followUp: '', cv: '', recruiter: '', noteCount: 0 })
    expect(s.appliedOn).not.toBe('')
  })

  it('shows a closed application by its outcome and a voided-only job as having none', async () => {
    const created = await quickApply()
    const id = created.application.id
    await voidApplication(id, 'test')
    expect(drawerTracking(job, cache())).toEqual({ kind: 'none', voidedOnly: true })
    await restoreApplication(id, 'test')
    expect(drawerTracking(job, cache()).kind).toBe('summary')
  })

  it('reports loading, error and a job with no application', () => {
    expect(drawerTracking(job, { status: 'loading' }).kind).toBe('loading')
    expect(drawerTracking(job, { status: 'error', error: 'down' })).toMatchObject({ kind: 'error', message: 'down' })
    expect(drawerTracking(job, cache())).toEqual({ kind: 'none', voidedOnly: false })
  })

  it('asks for the migration first when old tracking exists and no application', () => {
    const legacy = { ...job, applicationTracking: { applied: true, appliedDate: '2026-10-01', interviewStage: 'HR Screen' } }
    expect(drawerTracking(legacy, cache()).kind).toBe('migrate-first')
  })
})

describe('Mark Applied', () => {
  it('starts from today, the profile default CV and the form default channel', () => {
    const d = newApplicationDefaults(job, profile, 'req-1')
    expect(d).toMatchObject({ requestId: 'req-1', channel: DEFAULT_CHANNEL, appliedDate: new Date().toISOString().slice(0, 10), separateAttempt: null })
    expect(d.cv).toMatchObject({ kind: 'library', cvLibraryId: LIB })
  })

  it('creates the application through the existing workflow, and a repeated request id returns the first result', async () => {
    const form = newApplicationDefaults(job, profile)
    const first = await markApplied(job, cache(), form)
    const again = await markApplied(job, cache(), form)
    expect(again.application.id).toBe(first.application.id)
    const apps = applicationsForJob(cache().store, job.jobId)
    expect(apps).toHaveLength(1)
    expect(apps[0].attempt).toMatchObject({ channel: DEFAULT_CHANNEL, cv: { kind: 'library', cvLibraryId: LIB } })
  })

  it('reuses the duplicate check: a second click with a new request id is a 409 naming the existing one', async () => {
    const first = await quickApply()
    const err = await quickApply({ requestId: newRequestId() }).catch((e) => e)
    expect(err.status).toBe(409)
    expect(err.extra.conflictingId).toBe(first.application.id)
    // the quick view offers no channel choice, so a separate attempt stays a job for the full form
    const same = await quickApply({ requestId: newRequestId(), separateAttempt: 'different_channel' }).catch((e) => e)
    expect(same.status).toBe(409)
    const other = await quickApply({ requestId: newRequestId(), channel: 'job_board', separateAttempt: 'different_channel' })
    expect(other.application.id).not.toBe(first.application.id)
  })
})

describe('one store for the drawer and the page', () => {
  it('both read the same current application, so an edit on the page shows in the quick view', async () => {
    const created = await quickApply()
    const id = created.application.id
    expect(panelMode(job, cache()).current.id).toBe(id)
    expect(drawerTracking(job, cache()).app.id).toBe(id)
    await saveDraft(id, { ...draftFrom(cache().store.applications[id]), stage: 'rejected', appliedDate: '2026-11-02' })
    const view = drawerTracking(job, cache())
    expect(view.app).toBe(panelMode(job, cache()).current)
    expect(view.summary.appliedOn).toBe(formatAppDate(foldApplication(view.app).appliedDate))
    expect(view.summary.stage).toBe(summarizeApplication(view.app, cache().settings).stage)
  })
})

describe('Open full details', () => {
  it('is available only for a job the stored list holds', () => {
    expect(canOpenJobPage({ jobId: 'x' })).toBe(true)
    expect(canOpenJobPage(null)).toBe(false)
    expect(canOpenJobPage(undefined)).toBe(false)
  })
})
