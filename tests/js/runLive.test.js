// GET /api/runs/<runId>?after=N (S7c): one run and its events, Node only, from the same allow-list as the list.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getRun, projectEvent, readEvents } from '../../scripts/run-history.js'

const REPO = path.resolve(import.meta.dirname, '../..')
let dir

beforeEach(() => { dir = fs.mkdtempSync(path.join(os.tmpdir(), 'holojob-live-')) })
afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true })
  vi.restoreAllMocks()
})

const NAME = '20261103T100000Z-live0001'

function plant(extra = {}, events = []) {
  const record = {
    version: 1, runId: 'live0001', trigger: 'manual', startedAt: '2026-11-03T10:00:00+00:00', finishedAt: null, status: 'running', orchestrator: 'rescrape',
    sources: [{ name: 'jobspy', status: 'ok', read: 100, kept: 40, new: 3, error: null, boardsFailed: [], skipReason: null }],
    issues: [], steps: [{ name: 'discovery', status: 'running', exitCode: null }], staging: { ok: true, problems: [] }, ...extra,
  }
  fs.writeFileSync(path.join(dir, `${NAME}.json`), JSON.stringify(record))
  if (events.length) fs.writeFileSync(path.join(dir, `${NAME}.events.jsonl`), `${events.map((e) => JSON.stringify(e)).join('\n')}\n`)
  return record
}

const get = (id = 'live0001', query = '', options = {}) => getRun(id, new URLSearchParams(query), { dir, lock: () => true, ...options })

describe('the request', () => {
  it('404 for a run that is not there, 422 for an id or a cursor that is not valid', () => {
    expect(get('nosuchrun')).toMatchObject({ status: 404, body: { ok: false, error: 'unknown_run' } })
    for (const bad of ['../x', 'a b', '', 'x'.repeat(40), 'a.json']) expect(get(bad)).toMatchObject({ status: 422, body: { field: 'runId' } })
    plant()
    for (const bad of ['-1', 'abc', '1.5', '1e3', '9999999999']) expect(get('live0001', `after=${bad}`)).toMatchObject({ status: 422, body: { field: 'after' } })
    expect(get('live0001', 'after=0').status).toBe(200)
  })

  it('finds the run by its id and no other, and a missing folder is a 404', () => {
    plant()
    fs.writeFileSync(path.join(dir, '20261103T090000Z-live00010.json'), JSON.stringify({ runId: 'live00010', status: 'ok' }))
    expect(get('live0001').body.run.runId).toBe('live0001')
    fs.rmSync(dir, { recursive: true })
    expect(get('live0001').status).toBe(404)
  })

  it('an unreadable record is a 404 that says so', () => {
    fs.writeFileSync(path.join(dir, `${NAME}.json`), '{not json')
    expect(get()).toMatchObject({ status: 404, body: { error: 'unreadable_run' } })
  })
})

describe('the run', () => {
  it('is the list\'s projection of the record, with active and the cancel flags', () => {
    plant()
    const { body } = get()
    expect(body).toMatchObject({ ok: true, active: true, run: { runId: 'live0001', status: 'running', canCancel: true, cancelRequested: false, inferred: false } })
    fs.writeFileSync(path.join(dir, `${NAME}.cancel`), '{}')
    expect(get().body.run).toMatchObject({ cancelRequested: true, status: 'running' })
  })

  it('a finished run is not active', () => {
    plant({ status: 'cancelled', finishedAt: '2026-11-03T10:05:00+00:00', cancel: { requestedAt: null, outcome: 'collected_ads_saved', saved: 4 } })
    expect(get().body).toMatchObject({ active: false, run: { status: 'cancelled', canCancel: false } })
  })

  it('a running record nobody holds the lock for is interrupted and inferred, and no file changes', () => {
    plant({}, [{ type: 'run_start', at: '2026-11-03T10:00:00+00:00' }])
    const snapshot = () => fs.readdirSync(dir).map((f) => [f, fs.statSync(path.join(dir, f)).mtimeMs, fs.readFileSync(path.join(dir, f), 'utf-8')])
    const before = snapshot()
    const { body } = get('live0001', '', { lock: () => false })
    expect(body).toMatchObject({ active: false, run: { status: 'interrupted', inferred: true, canCancel: false } })
    expect(snapshot()).toEqual(before)
    expect(JSON.parse(fs.readFileSync(path.join(dir, `${NAME}.json`), 'utf-8')).status).toBe('running')
  })

  it('a lock that cannot be read counts as alive', () => {
    plant()
    expect(get('live0001', '', { lock: () => null }).body).toMatchObject({ active: true, run: { status: 'running', inferred: false } })
  })

  it('does not look at the lock for a finished record', () => {
    plant({ status: 'ok', finishedAt: '2026-11-03T10:05:00+00:00' })
    const lock = vi.fn(() => true)
    get('live0001', '', { lock })
    expect(lock).not.toHaveBeenCalled()
  })
})

describe('the events', () => {
  const EVENTS = [
    { type: 'run_start', at: '2026-11-03T10:00:00+00:00', trigger: 'manual' },
    { type: 'step_start', at: '2026-11-03T10:00:01+00:00', step: 'discovery' },
    { type: 'source_start', at: '2026-11-03T10:00:02+00:00', source: 'jobspy' },
    { type: 'source_end', at: '2026-11-03T10:01:00+00:00', source: 'jobspy', status: 'ok', read: 100, kept: 40, error: null, skipReason: null },
  ]

  it('returns them from the cursor, with the next cursor', () => {
    plant({}, EVENTS)
    const first = get().body
    expect(first.events.map((e) => e.type)).toEqual(['run_start', 'step_start', 'source_start', 'source_end'])
    expect(first.next).toBe(4)
    expect(first.events[3]).toMatchObject({ source: 'jobspy', status: 'ok', read: 100, kept: 40 })
    expect(get('live0001', 'after=2').body.events.map((e) => e.type)).toEqual(['source_start', 'source_end'])
    expect(get('live0001', 'after=4').body).toMatchObject({ events: [], next: 4 })
    expect(get('live0001', 'after=99').body).toMatchObject({ events: [], next: 99 })
  })

  it('does not read a torn last line yet, and counts a bad line without showing it', () => {
    plant()
    fs.writeFileSync(path.join(dir, `${NAME}.events.jsonl`), `${JSON.stringify(EVENTS[0])}\n{torn\n${JSON.stringify(EVENTS[1])}\n{"type":"source_sta`)
    const { events, next } = get().body
    expect(events.map((e) => e.type)).toEqual(['run_start', 'step_start'])
    expect(next).toBe(3)
  })

  it('has none when the run has no log, and caps one answer at 200', () => {
    plant()
    expect(get().body).toMatchObject({ events: [], next: 0 })
    fs.writeFileSync(path.join(dir, `${NAME}.events.jsonl`), `${Array.from({ length: 500 }, () => JSON.stringify(EVENTS[1])).join('\n')}\n`)
    const first = get().body
    expect(first.events).toHaveLength(200)
    expect(first.next).toBe(200)
    expect(get('live0001', `after=${first.next}`).body.next).toBe(400)
  })

  it('refuses to read a log past a megabyte', () => {
    plant()
    fs.writeFileSync(path.join(dir, `${NAME}.events.jsonl`), `${'x'.repeat(2 * 1024 * 1024)}\n`)
    expect(get().body).toMatchObject({ events: [], next: 0 })
  })

  it('shows the app\'s own message whole and withholds the rest, as for issues', () => {
    expect(projectEvent({ type: 'error', message: 'discovery failed with exit code 1: Traceback ... CANARY-TITLE' }).message).toBe('discovery failed with exit code 1')
    expect(projectEvent({ type: 'error', message: 'We could not parse the ad "CANARY-TITLE"' }).message).toBe('Message details withheld')
    expect(projectEvent({ type: 'source_end', source: 'jobspy', status: 'failed', error: 'acme: HTTPError 404 CANARY-TITLE' }).error).toBe('acme: details withheld (HTTPError, HTTP 404)')
    expect(projectEvent({ type: 'source_end', source: 'infostud', status: 'skipped', skipReason: "Infostud covers Serbia only, not 'Germany'" }).skipReason).toBe("Infostud covers Serbia only, not 'Germany'")
    expect(projectEvent({ type: 'made_up' }).type).toBe('unknown')
    expect(projectEvent(null)).toBeNull()
    expect(readEvents(path.join(dir, 'missing.jsonl'), 3)).toEqual({ events: [], next: 0 })
  })
})

describe('the allow-list', () => {
  const CANARIES = ['CANARY-TITLE', 'CANARY-DESCRIPTION', 'CANARY-COMPANY', 'canary.person@example.com', '+381 64 123 4567', 'https://example.com/jobs/CANARY-PATH', 'sk-CANARYSECRETKEY123456789', 'CANARY-EXTRA']
  const dirty = 'Failed for CANARY-TITLE at https://example.com/jobs/CANARY-PATH, contact canary.person@example.com or +381 64 123 4567, api_key=sk-CANARYSECRETKEY123456789'

  it('lets no canary through, from the record or from the event log', () => {
    plant(
      { title: 'CANARY-TITLE', description: 'CANARY-DESCRIPTION', company: 'CANARY-COMPANY', extra: 'CANARY-EXTRA', issues: [{ level: 'error', source: 'jobspy', message: dirty, title: 'CANARY-TITLE' }],
        sources: [{ name: 'jobspy', status: 'failed', read: 1, kept: 1, new: 0, error: dirty, skipReason: dirty, boardsFailed: [dirty], jobs: [{ title: 'CANARY-TITLE' }] }],
        staging: { ok: false, problems: [dirty] }, import: { kind: 'complete', saved: 1, note: dirty, sources: [{ name: 'jobspy', proof: { proven: false, why: [dirty, 'source_failed'], boards: [] } }] } },
      [
        { type: 'error', at: '2026-11-03T10:00:00+00:00', message: dirty, title: 'CANARY-TITLE', description: 'CANARY-DESCRIPTION', files: ['CANARY-EXTRA'] },
        { type: 'source_end', at: '2026-11-03T10:00:01+00:00', source: 'jobspy', status: 'failed', error: dirty, skipReason: dirty, extra: 'CANARY-EXTRA', jobs: ['CANARY-TITLE'] },
        { type: 'CANARY-EXTRA', at: 'CANARY-EXTRA', step: 'CANARY-EXTRA', source: 'CANARY-EXTRA with spaces', status: 'CANARY-EXTRA', read: 'CANARY-EXTRA' },
      ],
    )
    const text = JSON.stringify(get().body)
    for (const canary of CANARIES) expect(text, canary).not.toContain(canary)
    expect(text).not.toMatch(/sk-[A-Za-z0-9]{8,}/)
  })

  it('returns exactly the listed fields for an event', () => {
    plant({}, [{ type: 'source_end', at: '2026-11-03T10:00:01+00:00', source: 'jobspy', status: 'ok', read: 1, kept: 1, extra: 'x' }])
    expect(Object.keys(get().body.events[0]).sort()).toEqual(['at', 'error', 'exitCode', 'kept', 'message', 'read', 'saved', 'skipReason', 'source', 'sourcesDone', 'status', 'step', 'type'])
    expect(Object.keys(get().body).sort()).toEqual(['active', 'events', 'next', 'ok', 'run'])
  })
})

describe('what it does not touch', () => {
  it('opens nothing outside the runs folder, starts no process and writes nothing', async () => {
    plant({}, [{ type: 'run_start', at: '2026-11-03T10:00:00+00:00' }])
    const read = vi.spyOn(fs, 'readFileSync')
    const dirs = vi.spyOn(fs, 'readdirSync')
    const stat = vi.spyOn(fs, 'statSync')
    const write = vi.spyOn(fs, 'writeFileSync')
    const append = vi.spyOn(fs, 'appendFileSync')
    const open = vi.spyOn(fs, 'openSync')
    const unlink = vi.spyOn(fs, 'unlinkSync')
    const child = await import('node:child_process')
    const spawned = []
    for (const fn of ['spawn', 'exec', 'execFile', 'execSync', 'execFileSync', 'spawnSync', 'fork']) {
      try { vi.spyOn(child, fn).mockImplementation(() => { spawned.push(fn); throw new Error('no process') }) } catch { /* not spy-able */ }
    }
    get('live0001', '', { lock: () => true })
    const touched = [...read.mock.calls, ...dirs.mock.calls, ...stat.mock.calls].map(([file]) => String(file))
    expect(touched.length).toBeGreaterThan(0)
    for (const file of touched) expect(file.startsWith(dir), file).toBe(true)
    for (const spy of [write, append, open, unlink]) expect(spy).not.toHaveBeenCalled()
    expect(spawned).toEqual([])
  })

  it('names no ledger, staging or Python in its source', () => {
    const code = fs.readFileSync(path.join(REPO, 'scripts/run-history.js'), 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
    expect(code).not.toMatch(/job_history|spawn|execFile|child_process|python|writeFile|appendFile|unlink|rename|mkdir/i)
  })
})
