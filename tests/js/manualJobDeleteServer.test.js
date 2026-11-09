import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { EventEmitter } from 'node:events'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { deleteManualJob } from '../../scripts/manual-job-delete.js'
import { loadState, patchState } from '../../scripts/job-state-store.js'

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
