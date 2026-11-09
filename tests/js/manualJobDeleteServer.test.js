import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { EventEmitter } from 'node:events'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { deleteManualJob } from '../../scripts/manual-job-delete.js'
import { loadState, patchState } from '../../scripts/job-state-store.js'
import { createApplication } from '../../scripts/application-store.js'
import crypto from 'node:crypto'

const ID = 'manual-123e4567-e89b-12d3-a456-426614174000'
const OTHER = 'manual-223e4567-e89b-12d3-a456-426614174000'
const URL_A = 'https://acme.example/jobs/9'
let root

const write = (rel, data) => {
  const file = path.join(root, rel)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, typeof data === 'string' ? data : JSON.stringify(data))
}
const app = (id, posting, events = [{ seq: 1, type: 'applied' }]) => ({ id, posting: { title: 'x', ...posting }, events })
const store = (...apps) => write('data/applications/applications.json', { version: 1, updatedAt: null, requests: {}, applications: Object.fromEntries(apps.map((a) => [a.id, a])) })
const read = (rel) => fs.readFileSync(path.join(root, rel))

/** A stand-in for the Python process: records its argv and exits with `code`. */
function fakePython(code = 0, result = { ok: true, removed: { manual: 1, scored: 1 } }) {
  const calls = []
  const spawnFn = vi.fn((_py, argv) => {
    calls.push(argv)
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    setImmediate(() => { child.stdout.emit('data', Buffer.from(`${JSON.stringify(result)}\n`)); child.emit('close', code) })
    return child
  })
  return { spawnFn, calls }
}

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'manualdel-'))
})

async function seedState() {
  await patchState(root, { key: `url:${URL_A}`, jobId: ID, patch: { status: 'saved', keep: true } })
  await patchState(root, { key: 'url:https://other.example/1', jobId: OTHER, patch: { status: 'rejected' } })
}

describe('deleteManualJob (server)', () => {
  it('deletes a job with no application: runs the Python delete and removes only that job from job-state', async () => {
    store(app('app-1', { jobId: 'someone-else', postingKey: 'job:someone-else', url: 'https://x.example/1' }))
    await seedState()
    const py = fakePython()
    const res = await deleteManualJob(root, { jobId: ID, jobUrl: URL_A }, { spawnFn: py.spawnFn, python: 'py' })
    expect(res.status).toBe(200)
    expect(res.body.removed).toMatchObject({ manual: 1, scored: 1, state: 1 })
    expect(py.calls[0]).toEqual(expect.arrayContaining(['--delete-job', ID]))
    // The Python process edits the files under the root it was given, never the default data/ folder.
    expect(py.calls[0]).toEqual(expect.arrayContaining(['--manual', path.join(root, 'data/jobs/manual_jobs.json'), '--scored', path.join(root, 'data/jobs/scored_jobs.json')]))
    expect(Object.values(loadState(root).doc.jobs).map((e) => e.jobId)).toEqual([OTHER])
  })

  it.each([
    ['its job id', { jobId: ID, postingKey: `job:${ID}`, url: '' }],
    ['its posting key only', { jobId: null, postingKey: `job:${ID}`, url: '' }],
    ['its address only', { jobId: null, postingKey: 'url:https://acme.example/jobs/9', url: `${URL_A}?utm_source=x` }],
  ])('refuses when an application names the job by %s, and changes nothing', async (_n, posting) => {
    store(app('app-1', posting))
    await seedState()
    const appsBefore = read('data/applications/applications.json')
    const stateBefore = read('data/jobs/job-state.json')
    const py = fakePython()
    const res = await deleteManualJob(root, { jobId: ID, jobUrl: URL_A }, { spawnFn: py.spawnFn, python: 'py' })
    expect(res.status).toBe(409)
    expect(res.body).toMatchObject({ error: 'has_application', applicationIds: ['app-1'] })
    expect(py.spawnFn).not.toHaveBeenCalled()
    expect(read('data/applications/applications.json')).toEqual(appsBefore)
    expect(read('data/jobs/job-state.json')).toEqual(stateBefore)
  })

  it('a voided application still protects the job: voiding never unlocks deletion', async () => {
    store(app('app-1', { jobId: ID, postingKey: `job:${ID}` }, [{ seq: 1, type: 'applied' }, { seq: 2, type: 'application_voided' }]))
    const py = fakePython()
    const res = await deleteManualJob(root, { jobId: ID }, { spawnFn: py.spawnFn, python: 'py' })
    expect(res.status).toBe(409)
    expect(py.spawnFn).not.toHaveBeenCalled()
  })

  it('a migrated record (mig-<jobId>) protects it too', async () => {
    store(app(`mig-${ID}`, { jobId: null, postingKey: 'tcl:a|b|c' }))
    expect((await deleteManualJob(root, { jobId: ID }, { spawnFn: fakePython().spawnFn, python: 'py' })).status).toBe(409)
  })

  it('uses the address stored on the server even when the browser sends none', async () => {
    write('data/jobs/manual_jobs.json', { jobs: [{ jobId: ID, jobUrl: URL_A }] })
    store(app('app-1', { jobId: null, postingKey: `url:${URL_A}`, url: URL_A }))
    const py = fakePython()
    expect((await deleteManualJob(root, { jobId: ID }, { spawnFn: py.spawnFn, python: 'py' })).status).toBe(409)
    expect(py.spawnFn).not.toHaveBeenCalled()
  })

  it('fails closed when the tracker cannot be read', async () => {
    write('data/applications/applications.json', '{ not json')
    const py = fakePython()
    const res = await deleteManualJob(root, { jobId: ID }, { spawnFn: py.spawnFn, python: 'py' })
    expect(res.status).toBe(500)
    expect(res.body.error).toBe('tracker_unreadable')
    expect(py.spawnFn).not.toHaveBeenCalled()
  })

  it('a non-manual job is refused by the Python side and its job-state entry stays', async () => {
    await seedState()
    const stateBefore = read('data/jobs/job-state.json')
    const res = await deleteManualJob(root, { jobId: ID }, { spawnFn: fakePython(6, { ok: false, error: 'not_manual' }).spawnFn, python: 'py' })
    expect(res.status).toBe(422)
    expect(res.body.error).toBe('not_manual')
    expect(read('data/jobs/job-state.json')).toEqual(stateBefore)
  })

  it('answers 409 while a run holds the lock, and rejects a bad id', async () => {
    expect((await deleteManualJob(root, { jobId: ID }, { spawnFn: fakePython(75, { ok: false }).spawnFn, python: 'py' })).status).toBe(409)
    expect((await deleteManualJob(root, { jobId: '../x' }, { spawnFn: fakePython().spawnFn, python: 'py' })).status).toBe(422)
  })
})

describe('delete and create are one critical section', () => {
  const create = (now) => createApplication(root, {
    requestId: crypto.randomUUID(), jobId: ID, posting: { title: 'PM', company: 'Acme', jobUrl: URL_A },
    attempt: { channel: 'company_site', appliedDate: '2026-10-10', cv: { kind: 'unknown' } },
  }, { now })

  /** Stands in for Python, slowly, and does what it does: write the deleted id into manual_jobs.json. */
  function slowPython() {
    return vi.fn((_py, argv) => {
      const manual = argv[argv.indexOf('--manual') + 1]
      const child = new EventEmitter()
      child.stdout = new EventEmitter()
      child.stderr = new EventEmitter()
      setTimeout(() => {
        fs.mkdirSync(path.dirname(manual), { recursive: true })
        fs.writeFileSync(manual, JSON.stringify({ jobs: [], deleted: [ID] }))
        child.stdout.emit('data', Buffer.from(`${JSON.stringify({ ok: true, removed: { manual: 1, scored: 1 } })}\n`))
        child.emit('close', 0)
      }, 30)
      return child
    })
  }
  const appsFor = () => {
    try { return Object.values(JSON.parse(read('data/applications/applications.json')).applications).filter((a) => a.posting.jobId === ID) } catch { return [] }
  }
  const deletedIds = () => { try { return JSON.parse(read('data/jobs/manual_jobs.json')).deleted ?? [] } catch { return [] } }
  const now = () => new Date(Date.UTC(2026, 9, 11, 10, 0, 0))

  it.each(['create first', 'delete first', 'create arrives while Python is deleting'])('%s: never an application for a deleted job', async (order) => {
    const spawnFn = slowPython()
    const run = () => deleteManualJob(root, { jobId: ID, jobUrl: URL_A }, { spawnFn, python: 'py' })
    let results
    if (order === 'create first') results = await Promise.allSettled([create(now), run()])
    else if (order === 'delete first') results = await Promise.allSettled([run(), create(now)]).then((r) => [r[1], r[0]])
    else {
      const deleting = run()
      await new Promise((resolve) => setTimeout(resolve, 10))
      results = [await Promise.allSettled([create(now)]).then((r) => r[0]), await deleting.then((v) => ({ status: 'fulfilled', value: v }))]
    }
    const [created, deleted] = results
    const apps = appsFor()
    if (apps.length) {
      // The create won: the delete must have been refused and nothing was deleted.
      expect(created.status).toBe('fulfilled')
      expect(deleted.value.status).toBe(409)
      expect(deletedIds()).toEqual([])
    } else {
      // The delete won: the create must have been refused, and the job is remembered as deleted.
      expect(deleted.value.status).toBe(200)
      expect(created.status).toBe('rejected')
      expect(created.reason.status).toBe(410)
      expect(deletedIds()).toEqual([ID])
    }
    // Never both.
    expect(apps.length > 0 && deletedIds().includes(ID)).toBe(false)
  })

  it('an application created after the delete is refused (410), even with the job row gone', async () => {
    await deleteManualJob(root, { jobId: ID }, { spawnFn: slowPython(), python: 'py' })
    await expect(create(now)).rejects.toMatchObject({ status: 410 })
    expect(appsFor()).toEqual([])
  })
})
