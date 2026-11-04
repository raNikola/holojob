// GET /api/runs (S7a): read-only, slim, bounded, built from an allow-list. The raw record is never returned.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_LIMIT, KNOWN_PROOF_CODES, MAX_LIMIT, errorSummary, listRuns, lockIsHeld, message, parseQuery, project, summarise, text } from '../../scripts/run-history.js'

const REPO = path.resolve(import.meta.dirname, '../..')
let dir

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'holojob-runs-'))
})
afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true })
  vi.restoreAllMocks()
})

const stamp = (n) => `202611${String(1 + Math.floor(n / 24)).padStart(2, '0')}T${String(n % 24).padStart(2, '0')}0000Z`
const start = (n) => `2026-11-${String(1 + Math.floor(n / 24)).padStart(2, '0')}T${String(n % 24).padStart(2, '0')}:00:00+00:00`

function record(n, extra = {}) {
  const runId = `run${String(n).padStart(4, '0')}`
  return {
    version: 1, runId, trigger: 'manual', startedAt: start(n), finishedAt: start(n).replace(':00:00', ':20:00'), status: 'ok',
    sources: [{ name: 'jobspy', status: 'ok', read: 100, kept: 40, new: 3, error: null, boardsFailed: [], skipReason: null }],
    issues: [], steps: [{ name: 'discovery', status: 'ok', startedAt: start(n), finishedAt: start(n), exitCode: 0 }], staging: { ok: true, problems: [] },
    ...extra,
  }
}

function plant(n, extra = {}) {
  const rec = record(n, extra)
  fs.writeFileSync(path.join(dir, `${stamp(n)}-${rec.runId}.json`), JSON.stringify(rec))
  return rec
}

const list = (query = '', options = {}) => listRuns(new URLSearchParams(query), { dir, lock: () => true, ...options })

describe('the query', () => {
  it('defaults to 30, caps at 100, and refuses what is not a number or a record name', () => {
    expect(parseQuery(new URLSearchParams())).toEqual({ limit: DEFAULT_LIMIT, before: null })
    expect(DEFAULT_LIMIT).toBe(30)
    expect(parseQuery(new URLSearchParams('limit=100000')).limit).toBe(MAX_LIMIT)
    expect(MAX_LIMIT).toBe(100)
    for (const bad of ['0', '-1', 'abc', '1.5', '', '1e3']) expect(parseQuery(new URLSearchParams(`limit=${bad}`)).error).toBe('limit')
    for (const bad of ['../x', 'x.json', '20261101T000000Z-run1.json/..', '20261101T000000Z-run 1.json']) expect(parseQuery(new URLSearchParams({ before: bad })).error).toBe('before')
  })

  it('answers 422 naming the field', () => {
    expect(list('limit=zero')).toMatchObject({ status: 422, body: { ok: false, error: 'invalid', field: 'limit' } })
    expect(list('before=../../etc/passwd')).toMatchObject({ status: 422, body: { field: 'before' } })
  })
})

describe('the list', () => {
  it('is empty with no folder and with no records', () => {
    fs.rmSync(dir, { recursive: true })
    expect(list().body).toMatchObject({ ok: true, runs: [], next: null, skipped: 0, retentionDays: 90, activeRunId: null })
  })

  it('is newest first, bounded, and pages by the record name', () => {
    for (let n = 0; n < 70; n += 1) plant(n)
    const first = list().body
    expect(first.runs).toHaveLength(30)
    expect(first.runs[0].runId).toBe('run0069')
    expect(first.runs[29].runId).toBe('run0040')
    expect(first.next).toBe(`${stamp(40)}-run0040.json`)
    const second = list(`before=${first.next}`).body
    expect(second.runs[0].runId).toBe('run0039')
    expect(second.runs).toHaveLength(30)
    const third = list(`limit=100&before=${second.next}`).body
    expect(third.runs.map((r) => r.runId)).toEqual(Array.from({ length: 10 }, (_, i) => `run${String(9 - i).padStart(4, '0')}`))
    expect(third.next).toBeNull()
    expect(list('limit=100000').body.runs).toHaveLength(70)
  })

  it('reads only the page: a 500-record folder costs 5 reads for limit=5', () => {
    for (let n = 0; n < 500; n += 1) plant(n % 700)
    const spy = vi.spyOn(fs, 'readFileSync')
    const reads = () => spy.mock.calls.filter(([file]) => String(file).endsWith('.json')).length
    list('limit=5')
    expect(reads()).toBe(5)
  })

  it('skips what it cannot read and says how many, and ignores files that are not records', () => {
    plant(1)
    fs.writeFileSync(path.join(dir, `${stamp(2)}-garbage.json`), '{not json')
    fs.writeFileSync(path.join(dir, `${stamp(3)}-big.json`), JSON.stringify({ runId: 'big', pad: 'x'.repeat(300 * 1024) }))
    fs.writeFileSync(path.join(dir, `${stamp(4)}-norun.json`), JSON.stringify({ status: 'ok' }))
    fs.writeFileSync(path.join(dir, `${stamp(1)}-run0001.events.jsonl`), 'x')
    fs.writeFileSync(path.join(dir, '.commit-in-progress.json'), '{}')
    const body = list().body
    expect(body.runs.map((r) => r.runId)).toEqual(['run0001'])
    expect(body.skipped).toBe(3)
  })
})

describe('what a run shows', () => {
  it('keeps returned, collected, filtered out, saved, new and refreshed apart', () => {
    plant(1, { sources: [
      { name: 'jobspy', status: 'ok', read: 100, kept: 40, new: 3, error: null, boardsFailed: [], skipReason: null },
      { name: 'infostud', status: 'ok', read: 50, kept: 10, new: 0, error: null, boardsFailed: [], skipReason: null },
    ], import: { kind: 'complete', complete: true, saved: 45, new: 3, refreshed: 42, duplicatesRemoved: 5, crosspostsMerged: 0, rejected: 0, ledger: { closed: 1, absent: 2, reopened: 0, changed: 4, known: 42 }, sources: [] } })
    const [run] = list().body.runs
    expect(run.counts).toEqual({ returned: 150, filteredOut: 100, collected: 50, saved: 45, new: 3, refreshed: 42 })
    expect(run.import).toMatchObject({ kind: 'complete', duplicatesRemoved: 5, ledger: { closed: 1, absent: 2, reopened: 0, changed: 4, known: 42 } })
    expect(run.sources.map((s) => [s.returned, s.collected, s.filteredOut])).toEqual([[100, 40, 60], [50, 10, 40]])
  })

  it('for a cancelled run, saved includes refreshed ads and the cancel outcome is shown', () => {
    plant(1, { status: 'cancelled', cancel: { requestedAt: start(1), outcome: 'collected_ads_saved', saved: 455 },
      import: { kind: 'partial', complete: false, saved: 455, new: 3, refreshed: 452, sources: [] } })
    const [run] = list().body.runs
    expect(run.status).toBe('cancelled')
    expect(run.cancel).toEqual({ requestedAt: start(1), outcome: 'collected_ads_saved', saved: 455 })
    expect(run.counts).toMatchObject({ saved: 455, new: 3, refreshed: 452 })
    expect(run.import.ledger).toBeNull()
  })

  it('says null, not zero, for what an older record never recorded', () => {
    plant(1)
    const [run] = list().body.runs
    expect(run.counts).toEqual({ returned: 100, filteredOut: 60, collected: 40, saved: null, new: null, refreshed: null })
    expect(run.import).toBeNull()
    expect(run.recorded).toEqual({ import: false, sourceTimes: false })
    expect(run.sources[0]).toMatchObject({ startedAt: null, finishedAt: null, durationSeconds: null })
  })

  it('shows a source the import knows but the record has no row for as unfinished, with its proof', () => {
    plant(1, { status: 'cancelled', sources: [], cancel: { requestedAt: start(1), outcome: 'collected_ads_saved', saved: 4 },
      import: { kind: 'partial', complete: false, saved: 4, new: 2, refreshed: 2, sources: [{ name: 'jobspy', proof: { proven: false, why: ['not_finished', 'run_cancelled'], boards: [] }, filterReasons: {} }] } })
    const [run] = list().body.runs
    expect(run.sources).toHaveLength(1)
    expect(run.sources[0]).toMatchObject({ name: 'jobspy', status: 'unfinished', returned: null, collected: null, proof: { state: 'not_proven', codes: ['not_finished', 'run_cancelled'] } })
    expect(run.counts).toMatchObject({ returned: null, saved: 4, new: 2, refreshed: 2 })
  })

  it('times a source and the run', () => {
    plant(1, { sources: [{ name: 'jobspy', status: 'ok', read: 1, kept: 1, new: 0, startedAt: '2026-11-01T01:00:00+00:00', finishedAt: '2026-11-01T01:02:30+00:00' }] })
    const [run] = list().body.runs
    expect(run.sources[0].durationSeconds).toBe(150)
    expect(run.durationSeconds).toBe(1200)
    expect(run.recorded.sourceTimes).toBe(true)
  })
})

describe('proof has three states', () => {
  const imp = (sources) => ({ kind: 'complete', complete: true, saved: 1, new: 1, refreshed: 0, sources })

  it('Proven, Not proven with codes, and Not recorded are never mixed up', () => {
    plant(1, { sources: [
      { name: 'jobspy', status: 'ok', read: 1, kept: 1, new: 1 },
      { name: 'infostud', status: 'failed', read: 0, kept: 0, new: 0 },
      { name: 'lever', status: 'ok', read: 1, kept: 1, new: 0 },
    ], import: imp([
      { name: 'jobspy', proof: { proven: true, why: ['proven'], boards: [] }, filterReasons: { title_not_matched: 3 } },
      { name: 'infostud', proof: { proven: false, why: ['source_failed', 'nothing_read'], boards: [] }, filterReasons: {} },
    ]) })
    const [run] = list().body.runs
    const byName = Object.fromEntries(run.sources.map((s) => [s.name, s]))
    expect(byName.jobspy.proof).toEqual({ state: 'proven', codes: ['proven'], boards: [] })
    expect(byName.infostud.proof).toEqual({ state: 'not_proven', codes: ['source_failed', 'nothing_read'], boards: [] })
    expect(byName.lever.proof.state).toBe('not_recorded')
    expect(byName.jobspy.filterReasons).toEqual({ title_not_matched: 3 })
  })

  it('an old record, or a record with no import block, is Not recorded and never Not proven', () => {
    plant(1)
    plant(2, { import: undefined })
    for (const run of list().body.runs) expect(run.sources.every((s) => s.proof.state === 'not_recorded' && s.proof.codes.length === 0)).toBe(true)
  })

  it('boards carry their own state and reasons', () => {
    plant(1, { sources: [{ name: 'greenhouse', status: 'ok', read: 2, kept: 2, new: 0 }], import: imp([
      { name: 'greenhouse', proof: { proven: false, why: ['boards_not_proven'], boards: [
        { board: 'acme', proven: true, why: ['board_complete'], detail: null },
        { board: 'beta corp', proven: false, why: ['total_differs'], detail: 'the answer reports 9 postings and 8 were read' },
        { board: '../etc/passwd', proven: false, why: ['board_unreadable'], detail: null },
      ] }, filterReasons: {} },
    ]) })
    const proof = list().body.runs[0].sources[0].proof
    expect(proof.boards.map((b) => [b.board, b.state, b.codes])).toEqual([['acme', 'proven', ['board_complete']], ['beta corp', 'not_proven', ['total_differs']], ['[board]', 'not_proven', ['board_unreadable']]])
    expect(proof.boards[1].detail).toMatch(/9 postings/)
  })

  it('a code the shared file does not know is dropped, not passed on as text', () => {
    plant(1, { import: imp([{ name: 'jobspy', proof: { proven: false, why: ['source_failed', 'CANARY free text', 'made_up_code'], boards: [] } }]) })
    expect(list().body.runs[0].sources[0].proof.codes).toEqual(['source_failed'])
  })
})

describe('liveness without a lock', () => {
  it('a running record nobody holds the lock for is shown interrupted, inferred, and nothing is written', () => {
    plant(1, { status: 'running', finishedAt: null, orchestrator: 'rescrape' })
    const before = fs.readdirSync(dir).map((f) => [f, fs.statSync(path.join(dir, f)).mtimeMs])
    const [run] = list('', { lock: () => false }).body.runs
    expect(run).toMatchObject({ status: 'interrupted', inferred: true, canCancel: false })
    expect(fs.readdirSync(dir).map((f) => [f, fs.statSync(path.join(dir, f)).mtimeMs])).toEqual(before)
    expect(JSON.parse(fs.readFileSync(path.join(dir, fs.readdirSync(dir)[0]), 'utf-8')).status).toBe('running')
  })

  it('a live run, or one that cannot be told, stays running and offers Cancel only when a Re-scrape owns it', () => {
    plant(1, { status: 'running', finishedAt: null, orchestrator: 'rescrape' })
    plant(2, { status: 'running', finishedAt: null })
    for (const lock of [() => true, () => null]) {
      const body = list('', { lock }).body
      const [pipeline, rescrape] = body.runs
      expect(rescrape).toMatchObject({ status: 'running', inferred: false, canCancel: true, durationSeconds: null })
      expect(pipeline).toMatchObject({ status: 'running', canCancel: false })
      expect(body.activeRunId).toBe('run0002')
    }
  })

  it('does not look at the lock when no record says running', () => {
    plant(1)
    const lock = vi.fn(() => true)
    list('', { lock })
    expect(lock).not.toHaveBeenCalled()
  })

  it('shows that a cancel was requested, from the file name alone', () => {
    plant(1, { status: 'running', finishedAt: null, orchestrator: 'rescrape' })
    expect(list().body.runs[0].cancelRequested).toBe(false)
    fs.writeFileSync(path.join(dir, `${stamp(1)}-run0001.cancel`), '{}')
    expect(list().body.runs[0].cancelRequested).toBe(true)
  })

  it('lockIsHeld matches the inode alone, and says null when it cannot tell', () => {
    const lock = path.join(dir, 'pipeline.lock')
    fs.writeFileSync(lock, '')
    const inode = fs.statSync(lock).ino
    const table = path.join(dir, 'locks')
    fs.writeFileSync(table, `1: FLOCK  ADVISORY  WRITE 4242 de:ad:${inode} 0 EOF\n`)
    expect(lockIsHeld({ lock, procLocks: table })).toBe(true)
    fs.writeFileSync(table, `1: FLOCK  ADVISORY  WRITE 4242 de:ad:${inode + 1} 0 EOF\n2: POSIX ADVISORY WRITE 1 fc:00:${inode} 0 EOF\n`)
    expect(lockIsHeld({ lock, procLocks: table })).toBe(false)
    expect(lockIsHeld({ lock: path.join(dir, 'missing.lock'), procLocks: table })).toBe(false)
    expect(lockIsHeld({ lock, procLocks: path.join(dir, 'no-such-table') })).toBeNull()
  })
})

describe('the allow-list', () => {
  const CANARIES = [
    'CANARY-TITLE', 'CANARY-DESCRIPTION', 'CANARY-COMPANY', 'canary.person@example.com', '+381 64 123 4567', 'CANARY-NOTE',
    'https://example.com/jobs/CANARY-PATH', 'sk-CANARYSECRETKEY123456789', 'CANARY-EXTRA-FIELD',
  ]
  const dirty = 'Provider failed for CANARY-TITLE at https://example.com/jobs/CANARY-PATH, contact canary.person@example.com or +381 64 123 4567, api_key=sk-CANARYSECRETKEY123456789'

  function seeded() {
    return plant(1, {
      title: 'CANARY-TITLE', description: 'CANARY-DESCRIPTION', company: 'CANARY-COMPANY', jobUrl: 'https://example.com/jobs/CANARY-PATH', notes: 'CANARY-NOTE', extra: 'CANARY-EXTRA-FIELD',
      sources: [{ name: 'jobspy', status: 'ok', read: 10, kept: 5, new: 1, error: dirty, skipReason: dirty, boardsFailed: [dirty, 'acme'],
        jobs: [{ title: 'CANARY-TITLE' }], description: 'CANARY-DESCRIPTION', extra: 'CANARY-EXTRA-FIELD' }],
      issues: [{ level: 'error', source: 'jobspy', message: dirty, title: 'CANARY-TITLE' }, { level: 'weird', source: 'CANARY-EXTRA-FIELD with spaces', message: 'x' }],
      steps: [{ name: 'discovery', status: 'failed', exitCode: 1, tail: dirty, output: 'CANARY-DESCRIPTION' }],
      staging: { ok: false, problems: [dirty] },
      cancel: { requestedAt: start(1), outcome: 'collected_ads_saved', saved: 2, note: dirty },
      incompleteCommit: { runId: 'x', written: ['CANARY-EXTRA-FIELD'] },
      import: { kind: 'complete', complete: true, saved: 1, new: 1, refreshed: 0, note: dirty, sources: [{ name: 'jobspy', note: dirty,
        proof: { proven: false, why: ['source_failed'], note: dirty, boards: [{ board: 'acme', proven: false, why: ['board_empty'], detail: dirty, extra: dirty }] },
        filterReasons: { title_not_matched: 2, [dirty]: 5, 'CANARY-EXTRA-FIELD': 1 } }] },
    })
  }

  it('lets no canary through: ad text, title, link, contact, a secret, a field nobody listed', () => {
    seeded()
    const body = JSON.stringify(list().body)
    for (const canary of CANARIES) expect(body, canary + ' in ' + body.slice(Math.max(0, body.indexOf(canary) - 80), body.indexOf(canary) + 80)).not.toContain(canary)
    expect(body).not.toMatch(/sk-[A-Za-z0-9]{8,}/)
  })

  it('returns exactly the listed fields at every level, and keeps what is safe in the messages', () => {
    seeded()
    const [run] = list().body.runs
    expect(Object.keys(run).sort()).toEqual(['canCancel', 'cancel', 'cancelRequested', 'counts', 'durationSeconds', 'finishedAt', 'import', 'incompleteCommit', 'inferred', 'issues', 'issuesCount',
      'recorded', 'runId', 'sources', 'staging', 'startedAt', 'status', 'steps', 'trigger'])
    expect(Object.keys(run.sources[0]).sort()).toEqual(['boardsFailed', 'collected', 'durationSeconds', 'error', 'filterReasons', 'filteredOut', 'finishedAt', 'name', 'new', 'proof', 'returned', 'skipReason', 'startedAt', 'status'])
    expect(Object.keys(run.issues[0]).sort()).toEqual(['level', 'message', 'source'])
    expect(Object.keys(run.steps[0]).sort()).toEqual(['exitCode', 'name', 'status'])
    expect(Object.keys(run.sources[0].proof).sort()).toEqual(['boards', 'codes', 'state'])
    expect(Object.keys(run.sources[0].proof.boards[0]).sort()).toEqual(['board', 'codes', 'detail', 'state'])
    expect(Object.keys(run.import).sort()).toEqual(['complete', 'crosspostsMerged', 'duplicatesRemoved', 'kind', 'ledger', 'new', 'nothingSaved', 'refreshed', 'rejected', 'saved'])
    expect(run.issues[0].message).toBe('Message details withheld')
    expect(run.issues[1]).toEqual({ level: 'warning', source: null, message: 'Message details withheld' })
    expect(run.sources[0].filterReasons).toEqual({ title_not_matched: 2 })
    expect(run.sources[0].boardsFailed).toEqual(['[board]', 'acme'])
  })

  it('caps what could be large', () => {
    plant(1, { issues: Array.from({ length: 50 }, (_, i) => ({ level: 'warning', source: null, message: `m${i} ${'y'.repeat(1000)}` })),
      sources: Array.from({ length: 40 }, (_, i) => ({ name: `s${i}`, status: 'ok', read: 1, kept: 1, new: 0 })) })
    const [run] = list().body.runs
    expect(run.issues).toHaveLength(10)
    expect(run.issuesCount).toBe(50)
    expect(run.issues[0].message.length).toBeLessThanOrEqual(300)
    expect(run.sources).toHaveLength(20)
  })

  it('treats values of the wrong type as missing, never as text', () => {
    plant(1, { status: { evil: 1 }, trigger: 7, startedAt: 'CANARY-EXTRA-FIELD', sources: [null, 'x', { name: 5, status: [], read: '9', kept: -1, new: 1.5 }], issues: 'CANARY-NOTE', steps: [null] })
    const [run] = list().body.runs
    expect(run).toMatchObject({ status: 'unknown', trigger: 'unknown', startedAt: null })
    expect(JSON.stringify(run)).not.toMatch(/CANARY/)
    expect(run.sources[0]).toMatchObject({ name: '?', status: 'unknown', returned: null, collected: null, new: null })
  })

  it('project() refuses a record with no valid run id', () => {
    expect(project({ runId: '../x' })).toBeNull()
    expect(project(null)).toBeNull()
    expect(project('x')).toBeNull()
  })

  it('text() masks, replaces links, addresses and numbers, and caps', () => {
    expect(text('see https://a.example/x?key=abc and www.b.example , mail a@b.co')).toBe('see [link] and [link] , mail [email]')
    expect(text('x'.repeat(500)).length).toBe(300)
    expect(text(5)).toBeNull()
    expect(text('on 2026-11-03 at 10:00:00 it read 1469 ads')).toBe('on 2026-11-03 at 10:00:00 it read 1469 ads')
  })
})

describe('messages', () => {
  it('shows the app\'s own fixed texts whole', () => {
    for (const own of [
      '0 ads kept (read 12, all filtered out); nothing was closed for this source',
      'Every source was skipped: no source searched in this run',
      'Cancelled. 455 collected ads were saved. Nothing else changed. Scoring was skipped.',
      'Cancelled. No ads were saved. Nothing else changed. Scoring was skipped.',
      'board acme answered with 0 ads; its open ads were kept',
      'Ashby board acme: paging field in the answer: nextPage',
      'The run did not finish: it stopped during discovery (killed, or the server restarted). It was not resumed.',
    ]) expect(message(own)).toBe(own)
  })

  it('cuts the output tail after a failed step and keeps the app\'s words before an exception', () => {
    expect(message('discovery failed with exit code 1: Traceback ... KeyError: CANARY-TITLE ... api_key=sk-CANARYSECRETKEY123456789')).toBe('discovery failed with exit code 1')
    expect(message('Discovery stopped: HTTPError 503 for CANARY-TITLE at https://x.example/CANARY-PATH')).toBe('Discovery stopped: details withheld (HTTPError, HTTP 503)')
    expect(message('Import refused: older_run: run abc started 2026-11-01, before CANARY-TITLE')).toBe('Import refused: details withheld (older_run)')
  })

  it('withholds any other text, naming only what is safe to name', () => {
    expect(message('We could not parse the ad "CANARY-TITLE" from Acme Corp')).toBe('Message details withheld')
    expect(message('ConnectionError while reading CANARY-TITLE')).toBe('Message details withheld (ConnectionError)')
    expect(message(5)).toBeNull()
  })

  it('summarises a source error part by part and keeps the board names', () => {
    expect(errorSummary('acme: HTTPError 404 CANARY-TITLE; beta: timeout CANARY-DESCRIPTION')).toBe('acme: details withheld (HTTPError, HTTP 404); beta: details withheld')
    expect(errorSummary('something with CANARY-TITLE')).toBe('Details withheld')
    expect(summarise('status code 429 and TimeoutError')).toBe('details withheld (TimeoutError, HTTP 429)')
  })
})

describe('what it does not touch', () => {
  it('opens nothing outside the runs folder, starts no process and writes nothing', async () => {
    for (let n = 0; n < 5; n += 1) plant(n, { status: n === 4 ? 'running' : 'ok' })
    const read = vi.spyOn(fs, 'readFileSync')
    const dirs = vi.spyOn(fs, 'readdirSync')
    const stat = vi.spyOn(fs, 'statSync')
    const write = vi.spyOn(fs, 'writeFileSync')
    const open = vi.spyOn(fs, 'openSync')
    const spawned = []
    const child = await import('node:child_process')
    for (const fn of ['spawn', 'exec', 'execFile', 'execSync', 'execFileSync', 'spawnSync', 'fork']) {
      try { vi.spyOn(child, fn).mockImplementation((...args) => { spawned.push(fn); throw new Error('no process') }) } catch { /* not spy-able in this build */ }
    }
    list('', { lock: () => true })
    const touched = [...read.mock.calls, ...dirs.mock.calls, ...stat.mock.calls].map(([file]) => String(file))
    expect(touched.length).toBeGreaterThan(0)
    for (const file of touched) expect(file.startsWith(dir), file).toBe(true)
    expect(write).not.toHaveBeenCalled()
    expect(open).not.toHaveBeenCalled()
    expect(spawned).toEqual([])
  })

  it('names no ledger, staging or event log in its source', () => {
    const source = fs.readFileSync(path.join(REPO, 'scripts/run-history.js'), 'utf-8')
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
    expect(code).not.toMatch(/job_history|events\.jsonl|spawn|execFile|child_process|'staging|staging'|\/staging/)
    expect(code).not.toMatch(/data\/jobs(?!\/\.pipeline)/)
  })
})

describe('the shared reason codes', () => {
  const table = JSON.parse(fs.readFileSync(path.join(REPO, 'src/data/proofReasons.json'), 'utf-8'))

  it('every code has a group and a text that says Proven or Not proven', () => {
    for (const [code, entry] of Object.entries(table)) {
      expect(['search', 'board'], code).toContain(entry.group)
      expect(entry.text, code).toMatch(/^(Proven|Not proven)/)
    }
    expect([...KNOWN_PROOF_CODES].sort()).toEqual(Object.keys(table).sort())
  })

  it('are the codes Python can emit, and no others', () => {
    const python = fs.readFileSync(path.join(REPO, 'python/job_discovery/proof_reasons.py'), 'utf-8')
    const emitted = [...python.matchAll(/^[A-Z_]+ = "([a-z_]+)"/gm)].map((m) => m[1]).sort()
    expect(emitted).toEqual(Object.keys(table).sort())
  })
})
