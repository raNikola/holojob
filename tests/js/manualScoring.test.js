import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { importJobsFromFile, loadJobs, saveJobs } from '../../src/modules/jobs/jobStorage.js'
import { createJob, getStoredJob, invalidateJobs } from '../../src/modules/jobs/jobsStore.js'
import { SCORING_FIELDS, buildManualJob, identityJobUrl, normalizeJobUrl, scoringPayload } from '../../src/modules/jobs/manualJob.js'
import { NO_DESCRIPTION, addManualJob, scoreStoredJob, scoredPatch, syncManualJobs } from '../../src/modules/jobs/manualScoring.js'
import { manualJobArgs, runManualJobs } from '../../scripts/run-manual-job.js'
import { createBackupStream } from '../../scripts/backup-handler.js'
import { buildAiContext } from '../../src/modules/ai/aiContextBuilder.js'

const require = createRequire(import.meta.url)
const AdmZip = require('adm-zip')

const NOTE = 'NOTE-CANARY-9921'
const LINK = 'https://canary-9921.acme.example/private'
const LABEL = 'LABEL-CANARY-9921'
const SOURCE_URL = 'https://canary-9921.linkedin.example/posts/secret'
const ID = 'manual-123e4567-e89b-12d3-a456-426614174000'
const FORM = {
  title: 'Product Manager', company: 'Acme', description: 'Own the roadmap.', jobUrl: 'https://acme.example/jobs/9',
  sourceUrl: SOURCE_URL,
  notes: NOTE, extraLinks: [{ url: LINK, label: LABEL }],
}
const NOW = new Date('2026-10-30T10:00:00Z')

const SCORED = { jobId: ID, title: 'Product Manager', company: 'Acme', description: 'Own the roadmap.', jobUrl: FORM.jobUrl, status: 'new', matchScore: 71, matchLabel: 'Good', priority: 'P2', aiEnrichment: 'missing', scoreBreakdown: { roleMatch: { raw: 80, weight: 25 } } }

const items = new Map()
beforeEach(() => {
  items.clear()
  vi.stubGlobal('localStorage', { getItem: (k) => items.get(k) ?? null, setItem: (k, v) => { items.set(k, v) }, removeItem: (k) => { items.delete(k) } })
  vi.stubGlobal('window', new EventTarget())
  saveJobs({ meta: null, jobs: [{ jobId: 'd-1', status: 'saved', title: 'Backend', jobUrl: 'https://jobs.example/1' }], filters: {}, importedAt: null })
  invalidateJobs()
})
afterEach(() => vi.unstubAllGlobals())

const json = (status, body) => ({ status, json: async () => body })
/** A fetch stub that records its calls and answers from `reply`. */
function fetchStub(reply) {
  const fn = vi.fn(async (url, init) => reply(url, init))
  return fn
}
const stored = (id) => loadJobs().jobs.find((j) => j.jobId === id)

// --- the payload -----------------------------------------------------------------------------------------------

describe('what leaves the browser for scoring', () => {
  it('is the scoring fields only, in step with the Python whitelist', () => {
    const python = fs.readFileSync(path.resolve('python/job_scoring/manual_jobs.py'), 'utf-8')
    const listed = [...python.match(/SCORING_FIELDS = \(([\s\S]*?)\)\n/)[1].matchAll(/"(\w+)"/g)].map((m) => m[1])
    expect([...SCORING_FIELDS, 'manualEntry'].sort()).toEqual([...listed].sort())
  })

  it('drops notes, extra links and every other field', () => {
    const job = { ...buildManualJob(FORM, { id: ID, now: NOW }), applicationTracking: { notes: NOTE }, outreach: { contacts: [] }, tailoredAssets: {}, matchScore: 4 }
    const payload = scoringPayload(job)
    expect(Object.keys(payload).every((k) => SCORING_FIELDS.includes(k))).toBe(true)
    expect(JSON.stringify(payload)).not.toMatch(/CANARY|canary/)
    expect(payload).toMatchObject({ jobId: ID, title: 'Product Manager', description: 'Own the roadmap.', jobUrl: FORM.jobUrl })
  })

  it('normalises URLs like the Python side (shared fixture)', () => {
    const cases = JSON.parse(fs.readFileSync(path.resolve('tests/fixtures/url-normalisation.json'), 'utf-8'))
    for (const c of cases) {
      expect(normalizeJobUrl(c.input), c.input).toBe(c.expected)
      expect(identityJobUrl(c.input), c.input).toBe(c.identity ?? c.expected)
    }
  })
})

// --- the Node run: stdin, not argv; no echo --------------------------------------------------------------------

function fakeSpawn({ code = 0, stdout = '', stderr = '' }) {
  const calls = []
  const fn = (cmd, args, options) => {
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.stdin = {
      end: (data) => {
        calls.push({ cmd, args, options, stdin: data })
        setImmediate(() => {
          if (stderr) child.stderr.emit('data', Buffer.from(stderr))
          if (stdout) child.stdout.emit('data', Buffer.from(stdout))
          child.emit('close', code)
        })
      },
    }
    return child
  }
  fn.calls = calls
  return fn
}

describe('runManualJobs', () => {
  const full = { ...buildManualJob(FORM, { id: ID, now: NOW }), notes: NOTE }

  it('sends the scoring fields on stdin and nothing in argv or the environment it adds', async () => {
    const spawnFn = fakeSpawn({ stdout: `${JSON.stringify({ ok: true, jobs: [SCORED], skipped: [] })}\n` })
    const result = await runManualJobs([full], { spawnFn })
    expect(result.status).toBe(200)
    expect(result.body.jobs[0].jobId).toBe(ID)
    const [call] = spawnFn.calls
    expect(call.args).toEqual(manualJobArgs('score'))
    expect(call.args.join(' ')).not.toMatch(/CANARY|Own the roadmap/)
    expect(call.stdin).not.toMatch(/CANARY|canary/)
    expect(Object.keys(JSON.parse(call.stdin)[0]).every((k) => SCORING_FIELDS.includes(k))).toBe(true)
  })

  it('store and check modes only add a flag', () => {
    expect(manualJobArgs('check')).toEqual([...manualJobArgs('score'), '--check-only'])
    expect(manualJobArgs('store')).toEqual([...manualJobArgs('score'), '--store-only'])
  })

  it('maps Python exit codes to answers that carry a field name or a class, never the job text or stderr', async () => {
    const leak = `Traceback ... ${NOTE} ... Own the roadmap`
    const dup = await runManualJobs([full], { spawnFn: fakeSpawn({ code: 3, stderr: leak, stdout: JSON.stringify({ ok: false, error: 'duplicate', existing: { jobId: 'd-1', title: 'Backend' } }) }) })
    expect(dup).toMatchObject({ status: 409, body: { error: 'duplicate', existing: { jobId: 'd-1' } } })
    const bad = await runManualJobs([full], { spawnFn: fakeSpawn({ code: 2, stderr: leak, stdout: JSON.stringify({ ok: false, error: 'invalid', field: 'title' }) }) })
    expect(bad).toMatchObject({ status: 422, body: { field: 'title' } })
    const noIntel = await runManualJobs([full], { spawnFn: fakeSpawn({ code: 4, stdout: JSON.stringify({ ok: false, error: 'no_intelligence', saved: [ID] }) }) })
    expect(noIntel).toMatchObject({ status: 503, body: { error: 'no_intelligence', saved: [ID] } })
    const crashed = await runManualJobs([full], { spawnFn: fakeSpawn({ code: 1, stderr: leak, stdout: 'garbage' }) })
    expect(crashed.status).toBe(500)
    for (const r of [dup, bad, noIntel, crashed]) expect(JSON.stringify(r)).not.toMatch(/CANARY|Traceback|roadmap/)
  })

  it('refuses an empty or malformed request without starting Python', async () => {
    const spawnFn = fakeSpawn({})
    for (const jobs of [undefined, [], [{ title: 'x' }], [null]]) expect((await runManualJobs(jobs, { spawnFn })).status).toBe(422)
    expect(spawnFn.calls).toHaveLength(0)
  })
})

// --- add, retry, sync ------------------------------------------------------------------------------------------

describe('addManualJob', () => {
  it('scores on the server, then creates the job with the scored fields and the owner fields intact', async () => {
    const fetchFn = fetchStub(() => json(200, { ok: true, jobs: [SCORED] }))
    const result = await addManualJob(FORM, { fetchFn, id: ID, now: NOW })
    expect(result).toMatchObject({ status: 'created', scored: true })
    expect(stored(ID)).toMatchObject({ matchScore: 71, status: 'new', notes: NOTE, extraLinks: [{ url: LINK, label: LABEL }], manualEntry: true, firstSeen: NOW.toISOString() })
    const [url, init] = fetchFn.mock.calls[0]
    expect(url).toBe('/api/jobs/manual/score')
    expect(init.body).not.toMatch(/CANARY|canary/)
  })

  it('keeps the job as Unreviewed with no score when scoring fails, and says why', async () => {
    const result = await addManualJob(FORM, { fetchFn: fetchStub(() => json(500, { ok: false, error: 'scoring_failed' })), id: ID, now: NOW })
    expect(result).toMatchObject({ status: 'created', scored: false })
    expect(result.message).toMatch(/not scored/)
    expect(stored(ID)).toMatchObject({ status: 'new', manualEntry: true })
    expect(stored(ID).matchScore).toBeUndefined()
  })

  it('still creates the job when the server cannot be reached or is not available', async () => {
    const down = await addManualJob(FORM, { fetchFn: fetchStub(() => { throw new Error('offline') }), id: ID, now: NOW })
    expect(down).toMatchObject({ scored: false })
    expect(down.message).toMatch(/could not be reached/)
    const noApi = fetchStub(() => json(200, {}))
    await addManualJob({ ...FORM, jobUrl: 'https://acme.example/jobs/10' }, { fetchFn: noApi, apiAvailable: false, id: 'manual-223e4567-e89b-12d3-a456-426614174001', now: NOW })
    expect(noApi).not.toHaveBeenCalled()
  })

  it('writes nothing when this browser already has the link (no request either)', async () => {
    const fetchFn = fetchStub(() => json(200, { ok: true, jobs: [SCORED] }))
    const result = await addManualJob({ ...FORM, jobUrl: 'HTTPS://Jobs.Example/1/?utm_source=x' }, { fetchFn, id: ID })
    expect(result).toMatchObject({ status: 'duplicate', existing: { jobId: 'd-1' } })
    expect(fetchFn).not.toHaveBeenCalled()
    expect(loadJobs().jobs).toHaveLength(1)
  })

  it('writes nothing when the server finds the link among its discovered jobs', async () => {
    const before = JSON.stringify(loadJobs().jobs)
    const result = await addManualJob(FORM, { fetchFn: fetchStub(() => json(409, { ok: false, error: 'duplicate', existing: { jobId: 'srv-7', title: 'Same ad' } })), id: ID })
    expect(result).toMatchObject({ status: 'duplicate', existing: { jobId: 'srv-7', title: 'Same ad' } })
    expect(JSON.stringify(loadJobs().jobs)).toBe(before)
  })
})

describe('a job without a description', () => {
  const bare = { ...FORM, description: '' }

  it('is saved Unreviewed and unscored with the note, after a write-nothing clash check, never stored or scored on the server', async () => {
    const fetchFn = fetchStub(() => json(200, { ok: true }))
    const result = await addManualJob(bare, { fetchFn, id: ID, now: NOW })
    expect(result).toMatchObject({ status: 'created', scored: false, message: NO_DESCRIPTION, noDescription: true })
    expect(stored(ID)).toMatchObject({ status: 'new', description: '', manualEntry: true })
    expect(stored(ID).matchScore).toBeUndefined()
    expect(fetchFn.mock.calls.map(([url]) => url)).toEqual(['/api/jobs/manual/check'])
    expect(fetchFn.mock.calls[0][1].body).not.toMatch(/CANARY|canary/)
  })

  it('still refuses a link the server already has, and writes nothing', async () => {
    const before = JSON.stringify(loadJobs().jobs)
    const result = await addManualJob(bare, { fetchFn: fetchStub(() => json(409, { existing: { jobId: 'srv-1', title: 'Same ad' } })), id: ID })
    expect(result).toMatchObject({ status: 'duplicate', existing: { jobId: 'srv-1' } })
    expect(JSON.stringify(loadJobs().jobs)).toBe(before)
  })

  it('is not scored, and not synced, until it has text; then Score now works', async () => {
    await addManualJob(bare, { fetchFn: fetchStub(() => json(200, { ok: true })), id: ID, now: NOW })
    const quiet = fetchStub(() => json(200, { ok: true, jobs: [SCORED] }))
    expect(await scoreStoredJob(ID, { fetchFn: quiet })).toMatchObject({ ok: false, reason: 'no_description', message: NO_DESCRIPTION })
    expect(await syncManualJobs({ fetchFn: quiet })).toEqual({ ok: true, sent: 0 })
    expect(quiet).not.toHaveBeenCalled()

    const { patchJob } = await import('../../src/modules/jobs/jobsStore.js')
    patchJob(ID, { description: 'Own the roadmap.' })
    expect((await scoreStoredJob(ID, { fetchFn: quiet })).ok).toBe(true)
    expect(stored(ID)).toMatchObject({ matchScore: 71, sourceUrl: SOURCE_URL })
    expect(quiet.mock.calls[0][1].body).not.toMatch(/CANARY|canary/)
  })
})

describe('scoreStoredJob (Score now / retry)', () => {
  beforeEach(async () => {
    await addManualJob(FORM, { fetchFn: fetchStub(() => json(500, {})), id: ID, now: NOW })
  })

  it('patches the scored fields without touching the owner fields, and is idempotent', async () => {
    const owner = { ...stored(ID), status: 'saved' }
    saveJobs({ ...loadJobs(), jobs: loadJobs().jobs.map((j) => (j.jobId === ID ? owner : j)) })
    invalidateJobs()
    const fetchFn = fetchStub(() => json(200, { ok: true, jobs: [{ ...SCORED, status: 'new', notes: 'server', extraLinks: [] }] }))

    expect((await scoreStoredJob(ID, { fetchFn })).ok).toBe(true)
    const first = JSON.stringify(stored(ID))
    expect(stored(ID)).toMatchObject({ matchScore: 71, status: 'saved', notes: NOTE, extraLinks: [{ url: LINK, label: LABEL }], firstSeen: NOW.toISOString() })

    expect((await scoreStoredJob(ID, { fetchFn })).ok).toBe(true)
    expect(JSON.stringify(stored(ID))).toBe(first)
    expect(loadJobs().jobs.filter((j) => j.jobId === ID)).toHaveLength(1)
    expect(fetchFn.mock.calls.every(([, init]) => !/CANARY|canary/.test(init.body))).toBe(true)
  })

  it('reports a failure and leaves the job as it was', async () => {
    const before = JSON.stringify(stored(ID))
    const result = await scoreStoredJob(ID, { fetchFn: fetchStub(() => json(503, { ok: false, error: 'no_intelligence' })) })
    expect(result).toMatchObject({ ok: false, reason: 'no_intelligence' })
    expect(result.message).toMatch(/Candidate intelligence/)
    expect(JSON.stringify(stored(ID))).toBe(before)
  })

  it('does not score a link that another job already has', async () => {
    const result = await scoreStoredJob(ID, { fetchFn: fetchStub(() => json(409, { existing: { jobId: 'd-1', title: 'Backend' } })) })
    expect(result).toMatchObject({ ok: false, reason: 'duplicate' })
    expect(stored(ID).matchScore).toBeUndefined()
  })

  it('refuses a job that is not hand-entered', async () => {
    expect(await scoreStoredJob('d-1', { fetchFn: fetchStub(() => json(200, {})) })).toMatchObject({ ok: false, reason: 'missing' })
  })

  it('never lets a server record overwrite the owner fields', () => {
    expect(Object.keys(scoredPatch({ ...SCORED, notes: 'x', extraLinks: [], status: 'new', createdAt: 'x', firstSeen: 'x', tailoredAssets: {} }))).not.toEqual(expect.arrayContaining(['notes', 'status', 'firstSeen', 'tailoredAssets']))
  })
})

describe('syncManualJobs', () => {
  it('hands over the manual jobs only, with the scoring fields', async () => {
    createJob(buildManualJob(FORM, { id: ID, now: NOW }))
    const fetchFn = fetchStub(() => json(200, { ok: true }))
    expect(await syncManualJobs({ fetchFn })).toEqual({ ok: true, sent: 1 })
    const [url, init] = fetchFn.mock.calls[0]
    expect(url).toBe('/api/jobs/manual/sync')
    const sent = JSON.parse(init.body).jobs
    expect(sent.map((j) => j.jobId)).toEqual([ID])
    expect(init.body).not.toMatch(/CANARY|canary|Backend/)
  })

  it('sends nothing without manual jobs, and never throws', async () => {
    const quiet = fetchStub(() => json(200, {}))
    expect(await syncManualJobs({ fetchFn: quiet })).toEqual({ ok: true, sent: 0 })
    expect(quiet).not.toHaveBeenCalled()
    createJob(buildManualJob(FORM, { id: ID, now: NOW }))
    expect(await syncManualJobs({ fetchFn: fetchStub(() => { throw new Error('offline') }) })).toMatchObject({ ok: false })
  })
})

// --- the browser list after a re-import ----------------------------------------------------------------------------

describe('importJobsFromFile with manual jobs', () => {
  beforeEach(() => { createJob(buildManualJob(FORM, { id: ID, now: NOW })) })

  it('keeps a manual job the file lacks, and its notes and links', () => {
    const next = importJobsFromFile({ jobs: [{ jobId: 'd-2', title: 'New', jobUrl: 'https://jobs.example/2' }] }, loadJobs())
    expect(next.jobs.map((j) => j.jobId)).toEqual(['d-2', ID])
    expect(next.jobs[1]).toMatchObject({ notes: NOTE, extraLinks: [{ url: LINK, label: LABEL }] })
  })

  it('carries notes and links onto the file row with the same id, even without a URL match', () => {
    const next = importJobsFromFile({ jobs: [{ ...SCORED, jobUrl: '', status: 'new' }] }, loadJobs())
    expect(next.jobs.filter((j) => j.jobId === ID)).toHaveLength(1)
    expect(next.jobs.find((j) => j.jobId === ID)).toMatchObject({ matchScore: 71, notes: NOTE, manualEntry: true, sourceUrl: SOURCE_URL })
  })

  it('shows one row when a discovery run finds the same posting under its own id', () => {
    const next = importJobsFromFile({ jobs: [{ jobId: 'd-9', title: 'Product Manager', jobUrl: 'https://ACME.example/jobs/9/' }] }, loadJobs())
    expect(next.jobs.map((j) => j.jobId)).toEqual([ID])
    expect(next.jobs[0].notes).toBe(NOTE)
  })

  it('drops only the sibling with the same identifying parameter, never the board\'s other postings', () => {
    saveJobs({ ...loadJobs(), jobs: [] })
    invalidateJobs()
    createJob(buildManualJob({ ...FORM, jobUrl: 'https://careers.example/job?gh_jid=2&utm_source=mail' }, { id: ID, now: NOW }))
    const board = (n) => ({ jobId: `g-${n}`, title: `Role ${n}`, jobUrl: `https://careers.example/job?gh_jid=${n}` })
    const next = importJobsFromFile({ jobs: [board(1), board(2), board(3)] }, loadJobs())
    expect(next.jobs.map((j) => j.jobId).sort()).toEqual([ID, 'g-1', 'g-3'].sort())
  })

  it('does not touch the other jobs', () => {
    const next = importJobsFromFile({ jobs: [{ jobId: 'd-1', title: 'Backend', jobUrl: 'https://jobs.example/1' }] }, loadJobs())
    expect(next.jobs.find((j) => j.jobId === 'd-1')).toMatchObject({ status: 'saved' })
  })
})

// --- no AI request, no log line ---------------------------------------------------------------------------------

describe('owner-only fields stay local on the new path', () => {
  it('never reach an AI context built after the job is scored', async () => {
    await addManualJob(FORM, { fetchFn: fetchStub(() => json(200, { ok: true, jobs: [SCORED] })), id: ID, now: NOW })
    const context = JSON.stringify(buildAiContext({ featureId: 'jobAnalysis', job: getStoredJob(ID) }))
    expect(context).not.toMatch(/CANARY|canary/)
    expect(context).toContain('Own the roadmap')
  })

  it('are not written to the console by any step', async () => {
    const spies = ['log', 'info', 'warn', 'error', 'debug'].map((m) => vi.spyOn(console, m).mockImplementation(() => {}))
    await addManualJob(FORM, { fetchFn: fetchStub(() => json(500, {})), id: ID, now: NOW })
    await scoreStoredJob(ID, { fetchFn: fetchStub(() => json(200, { ok: true, jobs: [SCORED] })) })
    await syncManualJobs({ fetchFn: fetchStub(() => json(200, {})) })
    await runManualJobs([getStoredJob(ID)], { spawnFn: fakeSpawn({ code: 5, stderr: NOTE, stdout: '{"ok":false}' }) })
    const logged = spies.flatMap((s) => s.mock.calls).flat().join(' ')
    spies.forEach((s) => s.mockRestore())
    expect(logged).not.toMatch(/CANARY|canary/)
  })
})

describe('every place that replaces the job list goes through importJobsFromFile', () => {
  it.each([
    'src/components/jobs/PipelineOrchestrator.jsx',
    'src/modules/jobs/usePipelineAutoRefresh.js',
    'src/components/jobs/JobImportPanel.jsx',
    'src/components/settings/SettingsHome.jsx',
    'src/components/jobs/JobDiscoveryScreen.jsx',
    'src/modules/jobs/autoLoadJobs.js',
  ])('%s', (file) => {
    expect(fs.readFileSync(path.resolve(file), 'utf-8')).toMatch(/importJobsFromFile\(/)
  })
})

describe('backup', () => {
  it('exports the manual jobs file with the rest of data/jobs', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'holojob-backup-'))
    fs.mkdirSync(path.join(root, 'data/jobs'), { recursive: true })
    fs.writeFileSync(path.join(root, 'data/jobs/manual_jobs.json'), JSON.stringify({ jobs: [{ jobId: ID }] }))
    const chunks = []
    for await (const chunk of createBackupStream(root)) chunks.push(chunk)
    const names = new AdmZip(Buffer.concat(chunks)).getEntries().map((e) => e.entryName)
    expect(names).toContain('data/jobs/manual_jobs.json')
    fs.rmSync(root, { recursive: true, force: true })
  })
})
