import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadJobs, saveJobs } from '../../src/modules/jobs/jobStorage.js'
import { getStoredJob, invalidateJobs } from '../../src/modules/jobs/jobsStore.js'
import { rescoreKeptAd, syncKeptIds, tailoringBlocked } from '../../src/modules/jobs/keptRescore.js'
import { emptyStore } from '../../scripts/application-store.js'
import { applicationJobIds, pruneKeptRescored, runKeptRescore } from '../../scripts/run-kept-rescore.js'

const KEPT = { jobId: 'kept1', title: 'PM', company: 'Gone', status: 'saved', keptByUser: true, keptAt: '2026-11-01T00:00:00Z', notes: 'my note', applicationTracking: { stage: 'applied' }, tailoredAssets: { cv: 'x' } }
const SCORED = { jobId: 'kept1', title: 'PM', company: 'Gone', status: 'new', matchScore: 66, matchLabel: 'Good', priority: 'P2', notes: '', tailoredAssets: null }

const items = new Map()
beforeEach(() => {
  items.clear()
  vi.stubGlobal('localStorage', { getItem: (k) => items.get(k) ?? null, setItem: (k, v) => { items.set(k, v) }, removeItem: (k) => { items.delete(k) } })
  vi.stubGlobal('window', new EventTarget())
  saveJobs({ meta: null, jobs: [KEPT, { jobId: 'plain', title: 'X', status: 'new' }], filters: {}, importedAt: null })
  invalidateJobs()
})
afterEach(() => vi.unstubAllGlobals())

const reply = (status, body) => vi.fn(async () => ({ status, json: async () => body }))

describe('rescoreKeptAd', () => {
  it('patches the scored fields and keeps Keep, notes, status, tracking and tailored assets', async () => {
    const fetchFn = reply(200, { ok: true, job: SCORED })
    const result = await rescoreKeptAd('kept1', { fetchFn, now: () => 'T' })
    expect(result.ok).toBe(true)
    expect(JSON.parse(fetchFn.mock.calls[0][1].body)).toEqual({ jobId: 'kept1' })
    const job = getStoredJob('kept1')
    expect(job).toMatchObject({ matchScore: 66, matchLabel: 'Good', keptByUser: true, keptAt: KEPT.keptAt, keptRescoredAt: 'T', status: 'saved', notes: 'my note', applicationTracking: { stage: 'applied' }, tailoredAssets: { cv: 'x' } })
  })

  it('changes nothing when the server refuses or is away', async () => {
    for (const [fetchFn, reason] of [[reply(409, { ok: false, error: 'run_active' }), 'run_active'], [reply(404, { ok: false, error: 'not_in_history' }), 'not_in_history'], [vi.fn(async () => { throw new Error('down') }), 'unreachable']]) {
      const result = await rescoreKeptAd('kept1', { fetchFn })
      expect(result).toMatchObject({ ok: false, reason })
    }
    expect(getStoredJob('kept1').matchScore).toBeUndefined()
    expect(loadJobs().jobs).toHaveLength(2)
  })

  it('refuses an ad that is not kept, without a request', async () => {
    const fetchFn = reply(200, {})
    expect((await rescoreKeptAd('plain', { fetchFn })).reason).toBe('not_kept')
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('unlocks tailoring only for a re-scored kept ad', async () => {
    expect(tailoringBlocked(getStoredJob('kept1'))).toBe(true)
    await rescoreKeptAd('kept1', { fetchFn: reply(200, { ok: true, job: SCORED }) })
    expect(tailoringBlocked(getStoredJob('kept1'))).toBe(false)
    expect(tailoringBlocked({ offList: true })).toBe(true)
  })
})

describe('syncKeptIds', () => {
  it('sends only the ids that are kept', async () => {
    const fetchFn = reply(200, { ok: true })
    expect(await syncKeptIds({ fetchFn })).toBe(true)
    expect(JSON.parse(fetchFn.mock.calls[0][1].body)).toEqual({ keptIds: ['kept1'] })
  })
})

function fakeSpawn(stdout, code = 0) {
  const calls = []
  const fn = (python, args) => {
    calls.push(args)
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    setImmediate(() => { child.stdout.emit('data', Buffer.from(stdout)); child.emit('close', code) })
    return child
  }
  fn.calls = calls
  return fn
}

describe('server side', () => {
  it('maps the script answers', async () => {
    expect((await runKeptRescore('kept1', { spawnFn: fakeSpawn(JSON.stringify({ ok: true, job: SCORED })) })).status).toBe(200)
    expect((await runKeptRescore('kept1', { spawnFn: fakeSpawn('{"ok":false}', 75) })).body.error).toBe('run_active')
    expect((await runKeptRescore('kept1', { spawnFn: fakeSpawn('{"ok":false,"error":"not_in_history"}', 4) })).status).toBe(404)
    expect((await runKeptRescore('../x', { spawnFn: fakeSpawn('') })).status).toBe(422)
  })

  it('prunes with the kept ids plus the ads that have an application', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'kept-'))
    fs.mkdirSync(path.join(root, 'data/applications'), { recursive: true })
    fs.writeFileSync(path.join(root, 'data/applications/applications.json'), JSON.stringify({ ...emptyStore(), applications: { a: { posting: { jobId: 'app1' } }, b: { posting: {} } } }))
    expect([...applicationJobIds(root)]).toEqual(['app1'])
    const spawnFn = fakeSpawn('{"ok":true,"dropped":["old"]}')
    const result = await pruneKeptRescored(['kept1'], { spawnFn, root })
    expect(result.body.dropped).toEqual(['old'])
    expect(spawnFn.calls[0][1].replace('--prune=', '').split(',').sort()).toEqual(['app1', 'kept1'])
    expect((await pruneKeptRescored(['bad id!'], { spawnFn: fakeSpawn('') })).status).toBe(422)
  })

  it('prunes nothing when the application store cannot be read', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'kept-'))
    fs.mkdirSync(path.join(root, 'data/applications'), { recursive: true })
    fs.writeFileSync(path.join(root, 'data/applications/applications.json'), '{broken')
    const spawnFn = fakeSpawn('{"ok":true,"dropped":["x"]}')
    const result = await pruneKeptRescored(['kept1'], { spawnFn, root })
    expect(result.body).toMatchObject({ ok: true, dropped: [], skipped: 'applications_unreadable' })
    expect(spawnFn.calls).toHaveLength(0)
  })
})
