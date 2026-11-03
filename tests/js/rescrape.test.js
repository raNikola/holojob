// The background Re-scrape, Node side: start, 409, status, reattach. The real orchestrator and lock over fake steps.
import { EventEmitter } from 'node:events'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reconcileRuns, readEventsFile, rescrapeStatus, startRescrape, withRunLock } from '../../scripts/run-rescrape.js'

const REPO = path.resolve(import.meta.dirname, '../..')
let hasPython = true
try { execFileSync('python3', ['--version']) } catch { hasPython = false }

let dir
let saved
const ENV = ['CAREER_OS_ANALYTICS_DIR', 'CAREER_OS_PIPELINE_LOCK', 'PYTHONDONTWRITEBYTECODE', 'FAKE_MARKS']

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'holojob-rescrape-'))
  saved = Object.fromEntries(ENV.map((k) => [k, process.env[k]]))
  process.env.CAREER_OS_ANALYTICS_DIR = path.join(dir, 'analytics')
  process.env.CAREER_OS_PIPELINE_LOCK = path.join(dir, 'pipeline.lock')
  process.env.PYTHONDONTWRITEBYTECODE = '1'
  process.env.FAKE_MARKS = dir
})
afterEach(() => {
  try { fs.writeFileSync(path.join(dir, 'go'), 'x') } catch { /* gone */ }
  for (const k of ENV) { if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k] }
})

const runsDir = () => path.join(dir, 'analytics', 'runs')
function plant(runId, status, events = '') {
  fs.mkdirSync(runsDir(), { recursive: true })
  const name = `20261103T100000Z-${runId}`
  fs.writeFileSync(path.join(runsDir(), `${name}.json`), JSON.stringify({ version: 1, runId, trigger: 'manual', startedAt: '2026-11-03T10:00:00+00:00', finishedAt: null, status, sources: [], issues: [] }))
  if (events) fs.writeFileSync(path.join(runsDir(), `${name}.events.jsonl`), events)
}

/** The real run_rescrape.py with step scripts that wait for a file, so a test can hold a run open. */
function driver() {
  const discovery = path.join(dir, 'fake_discovery.py')
  fs.writeFileSync(discovery, `
import os, sys, time
sys.path.append(${JSON.stringify(path.join(REPO, 'python/job_discovery'))}); sys.path.append(${JSON.stringify(path.join(REPO, 'python/job_scoring'))})
from types import SimpleNamespace
import pipeline_lock, run_log
lock = pipeline_lock.acquire()
if lock is None: sys.exit(75)
record = run_log.find_record(sys.argv[sys.argv.index("--run-id") + 1])
run_log.event(record, "source_start", source="greenhouse")
run_log.add_source(record, "greenhouse", SimpleNamespace(status="ok", read=2, kept=1, error=None, boards_failed=[], skip_reason=None, warnings=[]))
run_log.save(record)
run_log.event(record, "source_end", source="greenhouse", status="ok", read=2, kept=1)
while not os.path.exists(os.path.join(os.environ["FAKE_MARKS"], "go")):
    time.sleep(0.02)
`)
  const scoring = path.join(dir, 'fake_scoring.py')
  fs.writeFileSync(scoring, `
import os
open(os.path.join(os.environ["FAKE_MARKS"], "scored"), "w").write("x")
`)
  const script = path.join(dir, 'driver.py')
  fs.writeFileSync(script, `
import sys
sys.path.insert(0, ${JSON.stringify(path.join(REPO, 'python'))})
import run_rescrape
run_rescrape.DISCOVERY = ${JSON.stringify(discovery)}
run_rescrape.SCORING = ${JSON.stringify(scoring)}
sys.exit(run_rescrape.main(sys.argv[1:]))
`)
  return { python: 'python3', script }
}

async function until(check, ms = 15000) {
  const end = Date.now() + ms
  for (;;) {
    const value = await check()
    if (value) return value
    if (Date.now() > end) throw new Error('timed out')
    await new Promise((r) => setTimeout(r, 30))
  }
}

const body = { providers: 'serbia', country: 'Serbia' }
const noMirrors = { writeMirrors: () => null }

describe('the event reader', () => {
  it('reads complete lines, from the cursor on', () => {
    const file = path.join(dir, 'e.jsonl')
    fs.writeFileSync(file, '{"type":"a"}\n{"type":"b"}\n{"type":"c"}\n')
    expect(readEventsFile(file, 0)).toEqual({ events: [{ type: 'a' }, { type: 'b' }, { type: 'c' }], next: 3 })
    expect(readEventsFile(file, 2)).toEqual({ events: [{ type: 'c' }], next: 3 })
    expect(readEventsFile(file, 3)).toEqual({ events: [], next: 3 })
  })

  it('skips a torn last line and does not move the cursor past it', () => {
    const file = path.join(dir, 'e.jsonl')
    fs.writeFileSync(file, '{"type":"a"}\n{"type":"sou')
    expect(readEventsFile(file, 0)).toEqual({ events: [{ type: 'a' }], next: 1 })
  })

  it('skips a torn line the next writer closed, and keeps counting lines', () => {
    const file = path.join(dir, 'e.jsonl')
    fs.writeFileSync(file, '{"type":"a"}\n{"type":"sou\n{"type":"interrupted"}\n')
    expect(readEventsFile(file, 0)).toEqual({ events: [{ type: 'a' }, { type: 'interrupted' }], next: 3 })
    expect(readEventsFile(file, 2)).toEqual({ events: [{ type: 'interrupted' }], next: 3 })
  })

  it('a missing log is no events; a cursor past the end stays harmless', () => {
    expect(readEventsFile(path.join(dir, 'none'), 5)).toEqual({ events: [], next: 0 })
    const file = path.join(dir, 'e.jsonl')
    fs.writeFileSync(file, '{"type":"a"}\n')
    expect(readEventsFile(file, 9)).toEqual({ events: [], next: 1 })
  })
})

describe('starting a run', () => {
  /** A spawn that records its options and exits as told, after the record appears if a run id is given. */
  function fakeSpawn({ exit = null, plantRecord = true } = {}) {
    const calls = []
    const spawnFn = (cmd, args, options) => {
      const child = new EventEmitter()
      child.unref = () => { child.unrefed = true }
      calls.push({ cmd, args, options, child })
      const runId = args[args.indexOf('--run-id') + 1]
      if (exit !== null) setTimeout(() => child.emit('exit', exit), 5)
      else if (plantRecord) plant(runId, 'running')
      return child
    }
    return { spawnFn, calls }
  }
  const idle = { reconcile: async () => ({ busy: false, interrupted: [], incompleteCommit: null }) }
  const busy = { reconcile: async () => ({ busy: true, interrupted: [], incompleteCommit: null }) }

  it('answers 202 and leaves the run in its own session, attached to nothing', async () => {
    const { spawnFn, calls } = fakeSpawn()
    const { status, body: answer } = await startRescrape(body, { spawnFn, ...idle, ...noMirrors })
    expect(status).toBe(202)
    expect(answer.ok).toBe(true)
    expect(answer.runId).toMatch(/^[0-9a-f]{12}$/)
    const { args, options, child } = calls[0]
    expect(options.detached).toBe(true)
    expect(options.stdio).toBe('ignore')
    expect(child.unrefed).toBe(true)
    expect(args.slice(1)).toEqual(['start', '--run-id', answer.runId, '--providers', 'serbia', '--country', 'Serbia'])
  })

  it('does not touch the mirrors or start anything when a run is active', async () => {
    const { spawnFn, calls } = fakeSpawn()
    let wrote = false
    const { status, body: answer } = await startRescrape({ ...body, intelligence: { a: 1 } }, { spawnFn, ...busy, writeMirrors: () => { wrote = true; return null } })
    expect(status).toBe(409)
    expect(answer.error).toBe('run_active')
    expect(answer.message).toMatch(/in progress/)
    expect(wrote).toBe(false)
    expect(calls).toHaveLength(0)
  })

  it('writes the mirrors the browser sent before it starts the run', async () => {
    const order = []
    const { spawnFn } = fakeSpawn()
    const wrapped = (...a) => { order.push('spawn'); return spawnFn(...a) }
    await startRescrape({ ...body, intelligence: { a: 1 }, profile: { b: 2 } }, {
      spawnFn: wrapped, ...idle, writeMirrors: (b) => { order.push(['mirrors', b.intelligence, b.profile]); return null },
    })
    expect(order).toEqual([['mirrors', { a: 1 }, { b: 2 }], 'spawn'])
  })

  it('a missing intelligence file stops it before the run, with the reason', async () => {
    const { spawnFn, calls } = fakeSpawn()
    const { status } = await startRescrape(body, { spawnFn, ...idle, writeMirrors: () => 'Missing intelligence' })
    expect(status).toBe(422)
    expect(calls).toHaveLength(0)
  })

  it('losing the race to the lock is a 409 too', async () => {
    const { spawnFn } = fakeSpawn({ exit: 75 })
    const { status, body: answer } = await startRescrape(body, { spawnFn, ...idle, ...noMirrors })
    expect(status).toBe(409)
    expect(answer.error).toBe('run_active')
  })

  it('a run that dies at once is a 500, not a silent success', async () => {
    const { spawnFn } = fakeSpawn({ exit: 1 })
    const { status } = await startRescrape(body, { spawnFn, ...idle, ...noMirrors })
    expect(status).toBe(500)
  })

  it('refuses a provider list that is not one, before anything runs', async () => {
    const { spawnFn, calls } = fakeSpawn()
    for (const providers of ['--judge', 'a b', 'a;b', 7]) {
      expect((await startRescrape({ providers }, { spawnFn, ...idle, ...noMirrors })).status).toBe(422)
    }
    expect((await startRescrape({ providers: 'serbia', country: 7 }, { spawnFn, ...idle, ...noMirrors })).status).toBe(422)
    expect(calls).toHaveLength(0)
  })

  it('two requests at the same moment start one run', async () => {
    const { spawnFn, calls } = fakeSpawn()
    const [a, b] = await Promise.all([
      startRescrape(body, { spawnFn, ...idle, ...noMirrors }),
      startRescrape(body, { spawnFn, ...idle, ...noMirrors }),
    ])
    expect([a.status, b.status].sort()).toEqual([202, 409])
    expect(calls).toHaveLength(1)
  })

  it('never signals a process', () => {
    expect(fs.readFileSync(path.join(REPO, 'scripts/run-rescrape.js'), 'utf8')).not.toMatch(/process\.kill|\.kill\(/)
  })
})

describe.skipIf(!hasPython)('a real run over fake steps', () => {
  it('second start 409, status follows it, reattach reads it all, scoring runs after the requester left', async () => {
    const opts = { ...driver(), ...noMirrors }
    const first = await startRescrape(body, opts)
    expect(first.status).toBe(202)

    const second = await startRescrape(body, opts)
    expect(second.status).toBe(409)

    const during = await until(async () => {
      const { body: s } = await rescrapeStatus(0, opts)
      return s.events.some((e) => e.type === 'source_end') ? s : null
    })
    expect(during.active).toBe(true)
    expect(during.run.runId).toBe(first.body.runId)
    expect(during.run.status).toBe('running')
    expect(during.events[0].type).toBe('run_start')

    // A later poll gets only what is new.
    const next = (await rescrapeStatus(during.next, opts)).body
    expect(next.events.every((e) => !during.events.some((d) => d.at === e.at && d.type === e.type))).toBe(true)

    fs.writeFileSync(path.join(dir, 'go'), 'x')
    const after = await until(async () => {
      const { body: s } = await rescrapeStatus(0, opts)
      return s.active ? null : s
    })
    expect(fs.existsSync(path.join(dir, 'scored'))).toBe(true)
    expect(after.run.status).toBe('ok')
    expect(after.events.map((e) => e.type)).toEqual([
      'run_start', 'step_start', 'source_start', 'source_end', 'step_end', 'step_start', 'step_end', 'run_end',
    ])
    expect((await startRescrape(body, opts)).status).toBe(202)
    await until(async () => !(await rescrapeStatus(0, opts)).body.active)
  })

  it('a dead running record becomes interrupted at the first status; a live one does not', async () => {
    const opts = driver()
    plant('deadrun', 'running')
    const held = await withRunLock(async () => {
      const { body: s } = await rescrapeStatus(0, opts)
      expect(s.active).toBe(true)
      expect(s.run.status).toBe('running')
      return 'inside'
    }, opts)
    expect(held).toEqual({ busy: false, value: 'inside' })

    const { body: s } = await rescrapeStatus(0, opts)
    expect(s.active).toBe(false)
    expect(s.run.status).toBe('interrupted')
    expect(s.events.map((e) => e.type)).toEqual(['interrupted'])
  })

  it('withRunLock says busy and does not run the action while the lock is held', async () => {
    const opts = driver()
    const inner = await withRunLock(() => withRunLock(() => 'nested', opts), opts)
    expect(inner.value).toEqual({ busy: true })
    expect(fs.existsSync(process.env.CAREER_OS_PIPELINE_LOCK)).toBe(true)
    expect((await reconcileRuns(opts)).busy).toBe(false)
  })

  it('reports a stale commit marker, and not one that is live', async () => {
    const opts = driver()
    plant('after', 'ok')
    fs.writeFileSync(path.join(runsDir(), '.commit-in-progress.json'), JSON.stringify({ runId: 'killed', files: ['job_history', 'discovered_jobs'], written: ['job_history'] }))
    const { body: s } = await rescrapeStatus(0, opts)
    expect(s.incompleteCommit.runId).toBe('killed')
    expect(s.incompleteCommit.written).toEqual(['job_history'])
    expect(s.incompleteCommit.pending).toEqual(['discovered_jobs'])

    plant('zlive', 'running')
    fs.renameSync(path.join(runsDir(), '20261103T100000Z-zlive.json'), path.join(runsDir(), '20261103T110000Z-zlive.json'))
    await withRunLock(async () => {
      const { body: live } = await rescrapeStatus(0, opts)
      expect(live.active).toBe(true)
      expect(live.incompleteCommit).toBe(null)
    }, opts)
  })
})

describe('status with nothing to report', () => {
  it('no records is no run', async () => {
    const { status, body: s } = await rescrapeStatus(0, { reconcile: async () => { throw new Error('should not ask') } })
    expect(status).toBe(200)
    expect(s).toMatchObject({ ok: true, active: false, run: null, events: [], next: 0, incompleteCommit: null })
  })

  it('does not ask Python for the lock when the latest run has finished', async () => {
    plant('done', 'ok', '{"type":"run_end"}\n')
    const { body: s } = await rescrapeStatus(0, { reconcile: async () => { throw new Error('should not ask') } })
    expect(s.active).toBe(false)
    expect(s.run.runId).toBe('done')
    expect(s.events).toEqual([{ type: 'run_end' }])
  })

  it('the cursor is a number or nothing', async () => {
    plant('done', 'ok', '{"type":"run_end"}\n')
    for (const bad of ['x', -1, '1;2', null, undefined]) {
      expect((await rescrapeStatus(bad, {})).body.events).toEqual([{ type: 'run_end' }])
    }
  })

  it('a key that reached a message is masked on the way out', async () => {
    plant('done', 'ok', `${JSON.stringify({ type: 'error', message: 'GET x?api_key=hunter2' })}\n`)
    expect(JSON.stringify((await rescrapeStatus(0, {})).body)).not.toContain('hunter2')
  })
})

describe('backup restore and the lock file', () => {
  it('a backup that carries the lock file does not replace it: flock holds the inode', async () => {
    const { createRequire } = await import('node:module')
    const AdmZip = createRequire(import.meta.url)('adm-zip')
    const { importBackupZip } = await vi.importActual('../../scripts/backup-handler.js')
    const root = fs.mkdtempSync(path.join(dir, 'root-'))
    const lock = path.join(root, 'data/jobs/.pipeline.lock')
    fs.mkdirSync(path.dirname(lock), { recursive: true })
    fs.writeFileSync(lock, '')
    const before = fs.statSync(lock).ino
    const zip = new AdmZip()
    zip.addFile('data/jobs/.pipeline.lock', Buffer.from('copy'))
    zip.addFile('data/jobs/scored_jobs.json', Buffer.from('{}'))
    const result = await importBackupZip(root, zip.toBuffer())
    expect(result.restored).toEqual(['data/jobs/scored_jobs.json'])
    expect(fs.statSync(lock).ino).toBe(before)
  })
})
