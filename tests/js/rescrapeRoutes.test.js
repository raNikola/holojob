// The routes around a run: the new ones answer as they should, the old ones say 409 while a run is active.
import { Readable } from 'node:stream'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const run = vi.hoisted(() => ({
  discovery: vi.fn(), pipeline: vi.fn(), scoring: vi.fn(), judged: vi.fn(), manual: vi.fn(), importUrl: vi.fn(),
  start: vi.fn(), status: vi.fn(), busy: vi.fn(), lock: vi.fn(), restore: vi.fn(),
}))

vi.mock('../../scripts/run-discovery.js', () => ({ buildDiscoveryCommand: () => '', getDiscoveryStatus: () => ({}), runDiscovery: run.discovery }))
vi.mock('../../scripts/run-pipeline.js', () => ({ runPipeline: run.pipeline }))
vi.mock('../../scripts/run-scoring.js', () => ({ buildScoringCommand: () => '', getScoringStatus: () => ({}), previewJudge: vi.fn(), runJudgedScoring: run.judged, runScoring: run.scoring }))
vi.mock('../../scripts/run-job-import.js', () => ({ runJobImport: run.importUrl }))
vi.mock('../../scripts/run-rescrape.js', async (original) => ({
  ...(await original()),
  startRescrape: run.start, rescrapeStatus: run.status, isRunBusy: run.busy, withRunLock: run.lock,
}))
vi.mock('../../src/utils/apiAvailability.js', async (original) => ({ ...(await original()), ensureApiAvailable: async () => true }))
vi.mock('../../scripts/backup-handler.js', () => ({ importBackupZip: run.restore, createBackupStream: vi.fn() }))

const { handleApiRoutes } = await import('../../scripts/api-handler.js')
const { default: RescrapeProgress } = await import('../../src/components/jobs/RescrapeProgress.jsx')
const { RUN_ACTIVE, runHttpStatus } = await import('../../scripts/run-rescrape.js')
const { applyStatus, emptyRunView, eventText, latestEventText } = await import('../../src/modules/jobs/rescrapeRun.js')
const { runManualJobs } = await import('../../scripts/run-manual-job.js')
const { scoreOnServer, scoreStoredJob } = await import('../../src/modules/jobs/manualScoring.js')

async function call(method, url, body, contentType = 'application/json') {
  const raw = body === undefined ? [] : [Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body))]
  const req = Object.assign(Readable.from(raw), { method, url, headers: { 'content-type': contentType, host: 'localhost' } })
  const res = {
    statusCode: 200, body: '', headers: {}, writableEnded: false,
    setHeader(k, v) { this.headers[k] = v }, end(text) { this.body = text ?? ''; this.writableEnded = true },
  }
  await handleApiRoutes(req, res)
  return { status: res.statusCode, data: res.body ? JSON.parse(res.body) : null }
}

const LOCKED = { ok: false, exitCode: 75, stderr: 'A job run is in progress; nothing started.', stdout: '', payload: null }

beforeEach(() => {
  for (const fn of Object.values(run)) fn.mockReset()
  run.busy.mockResolvedValue(false)
})

describe('runHttpStatus', () => {
  it('200, 409 on the lock exit code, 500 otherwise', () => {
    expect(runHttpStatus({ ok: true, exitCode: 0 })).toBe(200)
    expect(runHttpStatus({ ok: false, exitCode: 75 })).toBe(409)
    expect(runHttpStatus({ ok: false, exitCode: 1 })).toBe(500)
  })
})

describe('the new routes', () => {
  it('POST /api/rescrape passes the body and the answer through', async () => {
    run.start.mockResolvedValue({ status: 202, body: { ok: true, runId: 'abc' } })
    const { status, data } = await call('POST', '/api/rescrape', { providers: 'serbia', country: 'Serbia' })
    expect(status).toBe(202)
    expect(data.runId).toBe('abc')
    expect(run.start.mock.calls[0][0]).toMatchObject({ providers: 'serbia', country: 'Serbia' })
  })

  it('POST /api/rescrape answers 409 when busy', async () => {
    run.start.mockResolvedValue({ status: 409, body: RUN_ACTIVE })
    expect((await call('POST', '/api/rescrape', {})).status).toBe(409)
  })

  it('GET /api/rescrape/status reads the cursor from the query', async () => {
    run.status.mockResolvedValue({ status: 200, body: { ok: true, active: false, events: [], next: 0 } })
    expect((await call('GET', '/api/rescrape/status?after=7')).status).toBe(200)
    expect(run.status.mock.calls[0][0]).toBe('7')
  })
})

describe('the old routes while a run is active', () => {
  it.each([
    ['/api/scoring/run', {}, 'scoring'],
    ['/api/scoring/judge', { confirm: true }, 'judged'],
  ])('%s answers 409 on the lock exit code', async (url, body, fn) => {
    run[fn].mockResolvedValue(LOCKED)
    const { status, data } = await call('POST', url, body)
    expect(status).toBe(409)
    expect(data.stderr).toMatch(/in progress/)
  })

  it.each([
    ['/api/discovery/run', 'discovery'],
    ['/api/pipeline/run', 'pipeline'],
  ])('%s answers 409 before it writes the mirrors the browser sent', async (url, fn) => {
    run.busy.mockResolvedValue(true)
    const { status, data } = await call('POST', url, { intelligence: { a: 1 } })
    expect(status).toBe(409)
    expect(data.error).toBe('run_active')
    expect(data.stderr).toMatch(/in progress/) // what runDiscovery and runFullPipeline show the owner
    expect(run[fn]).not.toHaveBeenCalled()
  })

  it.each([
    ['/api/discovery/run', 'discovery'],
    ['/api/pipeline/run', 'pipeline'],
  ])('%s still answers 409 if the run started after the check', async (url, fn) => {
    run[fn].mockResolvedValue(LOCKED)
    expect((await call('POST', url, {})).status).toBe(409)
  })

  it('URL import answers 409', async () => {
    run.busy.mockResolvedValue(true)
    const { status } = await call('POST', '/api/jobs/import-url', { url: 'https://a.example/1' })
    expect(status).toBe(409)
    expect(run.importUrl).not.toHaveBeenCalled()
  })

  it('backup restore answers 409 and restores nothing', async () => {
    run.lock.mockResolvedValue({ busy: true })
    const { status, data } = await call('POST', '/api/backup/import', Buffer.from('zip'), 'application/zip')
    expect(status).toBe(409)
    expect(data.error).toBe('run_active')
    expect(run.restore).not.toHaveBeenCalled()
  })

  it('the restore screen shows the sentence, not the code', async () => {
    const { importBackupZip } = await import('../../src/modules/backup/backupClient.js')
    vi.stubGlobal('fetch', async () => ({ ok: false, status: 409, json: async () => RUN_ACTIVE }))
    await expect(importBackupZip({ arrayBuffer: async () => new ArrayBuffer(1) })).rejects.toThrow(/in progress/)
    vi.unstubAllGlobals()
  })

  it('backup restore runs inside the lock when there is no run', async () => {
    run.lock.mockImplementation(async (fn) => ({ busy: false, value: await fn() }))
    run.restore.mockResolvedValue({ ok: true, count: 1 })
    const { status, data } = await call('POST', '/api/backup/import', Buffer.from('zip'), 'application/zip')
    expect(status).toBe(200)
    expect(data.count).toBe(1)
    expect(run.restore).toHaveBeenCalledOnce()
  })

  it('a broken archive is still the 400 it was, not a lock problem', async () => {
    run.lock.mockRejectedValue(new Error('bad zip'))
    expect((await call('POST', '/api/backup/import', Buffer.from('zip'), 'application/zip')).status).toBe(400)
  })

  it('an unanswerable lock refuses the restore rather than risk it', async () => {
    run.lock.mockRejectedValue(Object.assign(new Error('no python'), { lockUnknown: true }))
    expect((await call('POST', '/api/backup/import', Buffer.from('zip'), 'application/zip')).status).toBe(503)
    expect(run.restore).not.toHaveBeenCalled()
  })
})

describe('manual add while a run is active', () => {
  function exiting(code) {
    return () => {
      const handlers = {}
      const child = {
        stdout: { on: () => {} }, stderr: { on: () => {} }, stdin: { end: () => setTimeout(() => handlers.close(code), 0) },
        on: (name, fn) => { handlers[name] = fn },
      }
      return child
    }
  }

  it('the lock exit code becomes a 409 with its own error, for score and sync alike', async () => {
    for (const mode of ['score', 'store']) {
      const { status, body } = await runManualJobs([{ jobId: 'manual-x' }], { mode, spawnFn: exiting(75) })
      expect(status).toBe(409)
      expect(body.error).toBe('run_active')
    }
  })

  it('the job stays saved here with a message that says why and what to do', async () => {
    const fetchFn = async () => ({ status: 409, json: async () => ({ ok: false, error: 'run_active' }) })
    const result = await scoreOnServer({ jobId: 'manual-x', title: 'PM', company: 'A', description: 'd' }, { fetchFn })
    expect(result.ok).toBe(false)
    expect(result.reason).toBe('run_active')
    expect(result.message).toMatch(/Re-scrape is running/)
    expect(result.message).toMatch(/Score now/)
    expect(typeof scoreStoredJob).toBe('function')
  })

  it('a duplicate is still a duplicate', async () => {
    const fetchFn = async () => ({ status: 409, json: async () => ({ ok: false, error: 'duplicate', existing: { jobId: 'd-1' } }) })
    const result = await scoreOnServer({ jobId: 'manual-x', title: 'PM', company: 'A', description: 'd' }, { fetchFn })
    expect(result.reason).toBe('duplicate')
  })
})

describe('the run view', () => {
  const status = (over) => ({ ok: true, active: true, run: { runId: 'r1', status: 'running' }, events: [], next: 0, incompleteCommit: null, ...over })

  it('collects the new events and moves the cursor', () => {
    let view = applyStatus(emptyRunView(), status({ events: [{ type: 'run_start' }], next: 1 }))
    view = applyStatus(view, status({ events: [{ type: 'step_start', step: 'discovery' }], next: 2 }))
    expect(view.events.map((e) => e.type)).toEqual(['run_start', 'step_start'])
    expect(view.next).toBe(2)
    expect(view.active).toBe(true)
  })

  it('a different run starts over: its events are not added to the old ones', () => {
    let view = applyStatus(emptyRunView(), status({ events: [{ type: 'run_start' }], next: 5 }))
    view = applyStatus(view, status({ run: { runId: 'r2', status: 'running' }, events: [{ type: 'run_end' }], next: 9 }))
    expect(view.reread).toBe(true)
    expect(view.next).toBe(0)
    expect(view.events).toEqual([])
    expect(view.run.runId).toBe('r2')
  })

  it('reattaches: the first answer after a reload is a whole run, and active keeps polling', () => {
    const view = applyStatus(emptyRunView(), status({ events: [{ type: 'run_start' }, { type: 'step_start', step: 'scoring' }], next: 2 }))
    expect(view.reread).toBe(false)
    expect(view.active).toBe(true)
    expect(latestEventText(view)).toBe('Scoring started')
  })

  it('says each event in words', () => {
    expect(eventText({ type: 'source_start', source: 'greenhouse' })).toBe('Reading greenhouse')
    expect(eventText({ type: 'source_end', source: 'greenhouse', status: 'ok', read: 5, kept: 2 })).toBe('greenhouse: ok, 2 kept of 5 read')
    expect(eventText({ type: 'source_end', source: 'wwr', status: 'failed', error: 'timeout' })).toBe('wwr: failed, timeout')
    expect(eventText({ type: 'step_end', step: 'discovery', status: 'ok' })).toBe('Discovery finished')
    expect(eventText({ type: 'step_end', step: 'scoring', status: 'failed' })).toBe('Scoring failed')
    expect(eventText({ type: 'run_end', status: 'partial' })).toBe('Run finished: partial')
    expect(eventText({ type: 'interrupted', message: 'gone' })).toBe('gone')
    expect(eventText({ type: 'future_kind' })).toBe('future_kind')
  })
})

describe('the progress line', () => {
  const view = (over) => ({ ...emptyRunView(), run: { runId: 'r1', status: 'running' }, active: true, ...over })
  const html = (v) => renderToStaticMarkup(createElement(RescrapeProgress, { view: v }))

  it('shows nothing before any run', () => {
    expect(html(emptyRunView())).toBe('')
  })

  it('shows the latest event and lists them all in an expandable list', () => {
    const out = html(view({ events: [{ type: 'run_start', at: '2026-11-03T10:00:00+00:00' }, { type: 'source_start', source: 'greenhouse', at: '2026-11-03T10:00:01+00:00' }] }))
    expect(out).toContain('<details')
    expect(out).toContain('Reading greenhouse')
    expect(out).toContain('Run started')
    expect(out).toContain('2 events')
  })

  it('says clearly when a run was interrupted, and that nothing resumes it', () => {
    const out = html(view({ active: false, run: { runId: 'r1', status: 'interrupted' } }))
    expect(out).toMatch(/interrupted/i)
    expect(out).toMatch(/not resumed|start it again/i)
  })

  it('says clearly when a commit is incomplete, naming the files', () => {
    const out = html(view({ active: false, run: { runId: 'r2', status: 'ok' }, incompleteCommit: { runId: 'killed', written: ['job_history'], pending: ['discovered_jobs'] } }))
    expect(out).toContain('job_history')
    expect(out).toContain('discovered_jobs')
    expect(out).toMatch(/incomplete/i)
  })

  it('says when the scores do not come from the latest discovery', () => {
    const out = html(view({ active: false, run: { runId: 'r2', status: 'failed' }, scoringBehind: true }))
    expect(out).toMatch(/not scored|Re-score/)
  })
})
