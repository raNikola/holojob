import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import * as store from '../../scripts/application-store.js'
import * as client from '../../src/modules/applications/applicationsClient.js'
import {
  cvOptions, describeError, draftFrom, markApplied, newRequestId, planSave, rebaseDraft, recordCv, restoreApplication, saveDraft, voidApplication,
} from '../../src/modules/applications/trackerController.js'

const id16 = (n) => crypto.createHash('sha256').update(`state-${n}`).digest('hex').slice(0, 16)
const LIB_A = id16('a')
const LIB_B = id16('b')
const profile = {
  defaultCvId: LIB_A,
  cvLibrary: [LIB_A, LIB_B].map((id, i) => ({ id, label: `CV ${i}`, fileName: `cv${i}.pdf`, filePath: `profile/cvs/${id}.pdf` })),
}
const job = { jobId: id16('job'), title: 'PM', company: 'Acme', jobUrl: 'https://acme.example/pm' }

let root
let server
const cache = () => client.getApplicationsState()
const current = (id) => cache().store.applications[id]

beforeEach(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'pstate-'))
  for (const id of [LIB_A, LIB_B]) {
    fs.mkdirSync(path.join(root, 'data/profile/cvs'), { recursive: true })
    fs.writeFileSync(path.join(root, `data/profile/cvs/${id}.pdf`), '%PDF')
  }
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

async function tracked() {
  const [library] = cvOptions(job, profile)
  const created = await markApplied(job, cache(), { requestId: newRequestId(), channel: 'company_site', appliedDate: '2026-11-01', cv: library })
  return created.application.id
}

describe('the form after the application changed under it', () => {
  it('a CV correction no longer wipes typed fields, and the next save sends exactly what was typed', async () => {
    const id = await tracked()
    const base = draftFrom(current(id))
    // typed before the CV was corrected
    const typed = { ...base, newNote: 'Call went well', followUpDate: '2026-11-12', recruiterName: 'Jane' }

    await recordCv(id, cvOptions(job, profile)[1], { reason: 'sent the other one' })
    const nextBase = draftFrom(current(id))

    // the old behaviour: the form was remounted, the draft rebuilt from the application, and Save found nothing to do
    expect(planSave(current(id), nextBase)).toEqual([])
    // now: the typed fields survive and Save has the three changes
    const rebased = rebaseDraft(base, typed, nextBase)
    expect(rebased).toMatchObject({ newNote: 'Call went well', followUpDate: '2026-11-12', recruiterName: 'Jane' })
    expect(planSave(current(id), rebased).map((c) => c.event.type)).toEqual(['follow_up_set', 'contact_added', 'note_added'])
    expect(await saveDraft(id, rebased)).toBe(3)
    expect(store.loadStore(root).applications[id].events.map((e) => e.type)).toEqual(['applied', 'cv_recorded', 'follow_up_set', 'contact_added', 'note_added'])
  })

  it('after a save, a second save of the same draft sends nothing (no stale replay)', async () => {
    const id = await tracked()
    const base = draftFrom(current(id))
    const typed = { ...base, followUpDate: '2026-11-12', newNote: 'x' }
    await saveDraft(id, typed)
    const after = draftFrom(current(id))
    const rebased = rebaseDraft(base, { ...typed, newNote: '' }, after)
    expect(planSave(current(id), rebased)).toEqual([])
  })

  it('stays consistent after each other event path: stage move, note, void and restore', async () => {
    const id = await tracked()
    let base = draftFrom(current(id))
    const edited = { ...base, recruiterEmail: 'jane@acme.example' }

    // a stage move written elsewhere: the untouched stage follows the server, the edited e-mail stays
    await saveDraft(id, { ...base, stage: 'tech' })
    let next = draftFrom(current(id))
    let rebased = rebaseDraft(base, edited, next)
    expect(rebased).toMatchObject({ stage: 'tech', recruiterEmail: 'jane@acme.example' })
    expect(planSave(current(id), rebased).map((c) => c.event.type)).toEqual(['contact_added'])
    base = next

    // a note added elsewhere does not leave the form with a stale base
    await saveDraft(id, { ...base, newNote: 'first' })
    next = draftFrom(current(id))
    rebased = rebaseDraft(base, { ...base, followUpDate: '2026-11-20' }, next)
    expect(planSave(current(id), rebased).map((c) => c.event.type)).toEqual(['follow_up_set'])
    expect(await saveDraft(id, rebased)).toBe(1)

    // void then restore: the application folds back to a normal open one and saving works again
    await voidApplication(id, 'by mistake')
    await restoreApplication(id, 'restored')
    const fresh = draftFrom(current(id))
    expect(await saveDraft(id, { ...fresh, newNote: 'after restore' })).toBe(1)
    expect(foldNotes(current(id))).toEqual(['first', 'after restore'])
  })
})

const foldNotes = (app) => app.events.filter((e) => e.type === 'note_added').map((e) => e.data.text)

describe('a failed save is never silent', () => {
  it('names the failing step, the HTTP status and how many changes had landed', async () => {
    const id = await tracked()
    const draft = { ...draftFrom(current(id)), appliedDate: '2026-10-30', followUpDate: '2026-13-45' }
    const error = await saveDraft(id, draft).then(() => null, (e) => e)
    expect(error).toMatchObject({ status: 400, extra: { saved: 1, planned: 2 } })
    expect(error.message).toBe('Saving the follow-up date failed (1 of 2 changes were saved): data.dueDate must be YYYY-MM-DD')
    expect(describeError(error)).toContain('(HTTP 400)')
    // what landed is in the cache, so the next save only sends the rest
    expect(planSave(current(id), draft).map((c) => c.event.type)).toEqual(['follow_up_set'])
  })

  it('a draft equal to the application plans nothing, which the form reports instead of ignoring', async () => {
    const id = await tracked()
    expect(await saveDraft(id, draftFrom(current(id)))).toBe(0)
  })

  it('a correction without a reason is refused with the server wording', async () => {
    const id = await tracked()
    await expect(recordCv(id, cvOptions(job, profile)[1], {})).rejects.toMatchObject({ status: 400, message: expect.stringContaining('reason') })
  })
})
