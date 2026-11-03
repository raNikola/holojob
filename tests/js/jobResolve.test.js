import { describe, expect, it, vi } from 'vitest'
import { hasFallback, loadJobSources, resolveJob } from '../../src/modules/jobs/jobResolve.js'
import { jobFromPosting } from '../../src/modules/applications/trackingView.js'
import { applicationOpenTarget, canOpenJobPage } from '../../src/modules/jobs/jobRoute.js'

const ID = 'aaaaaaaaaaaaaaaa'
const stored = (extra = {}) => ({ jobId: ID, title: 'From browser', company: 'B', status: 'saved', ...extra })
const fileJob = (extra = {}) => ({ jobId: ID, title: 'From file', company: 'F', description: 'file ad', ...extra })
const ledger = (extra = {}) => ({
  found: true, jobId: ID, firstSeen: '2026-10-01T00:00:00+00:00', lastSeen: '2026-10-20T08:00:00+00:00', closedAt: null,
  job: { jobId: ID, title: 'From ledger', company: 'L', description: 'ledger ad', jobUrl: 'https://l.example' },
  ...extra,
})
const posting = (extra = {}) => ({
  jobId: ID, title: 'From posting', company: 'P', location: 'Remote', url: 'https://p.example/job', provider: 'lever', source: 'acme',
  salary: '100', isRemote: true, description: 'frozen ad', capturedFrom: 'scored_jobs', capturedAt: '2026-09-15T10:00:00.000Z', ...extra,
})
const app = (extra = {}) => ({ id: 'app1', createdAt: '2026-09-15T10:00:00.000Z', posting: posting(), events: [{ type: 'applied' }], ...extra })

describe('resolveJob order', () => {
  const all = { stored: stored(), fileJob: fileJob(), ledger: ledger(), applications: [app()], fileChecked: true, inFile: true }

  it('takes the stored row first', () => {
    expect(resolveJob(all)).toMatchObject({ status: 'found', source: 'stored', readOnly: false, job: { title: 'From browser' } })
  })

  it('then the file', () => {
    expect(resolveJob({ ...all, stored: null })).toMatchObject({ source: 'file', readOnly: true, notInLatest: false, job: { title: 'From file' } })
  })

  it('then the ledger', () => {
    const r = resolveJob({ ...all, stored: null, fileJob: null, inFile: false })
    expect(r).toMatchObject({ source: 'ledger', readOnly: true, notInLatest: true, job: { title: 'From ledger', firstSeen: ledger().firstSeen, lastSeen: ledger().lastSeen, isClosed: false } })
  })

  it('then the frozen posting of the application', () => {
    const r = resolveJob({ ...all, stored: null, fileJob: null, inFile: false, ledger: null })
    expect(r).toMatchObject({ source: 'application', readOnly: true, notInLatest: true, job: { title: 'From posting', jobUrl: 'https://p.example/job', description: 'frozen ad' } })
  })

  it('and otherwise nothing', () => {
    expect(resolveJob({ fileChecked: true })).toEqual({ status: 'missing', job: null, source: null, readOnly: true, notInLatest: false, lastSeen: null, capturedAt: null })
  })

  it('a ledger entry reads a closed ad as closed', () => {
    expect(resolveJob({ ledger: ledger({ closedAt: '2026-10-21' }) }).job.isClosed).toBe(true)
    expect(resolveJob({ ledger: ledger({ closedAt: '2026-10-21', absentRuns: 2 }) }).job.closedAfterChecks).toBe(2)
    expect(resolveJob({ ledger: ledger({ closedAt: '2026-10-21' }) }).job.closedAfterChecks).toBeUndefined()
    const absent = resolveJob({ ledger: ledger({ absentSince: '2026-10-22', absentRuns: 1 }) }).job
    expect(absent.isAbsent).toBe(true)
    expect(absent.absentSince).toBe('2026-10-22')
  })

  it('an application only: the job reads as applied, and its status is not invented otherwise', () => {
    expect(resolveJob({ ledger: ledger(), applications: [app()] }).job.status).toBe('applied_manually')
    expect(resolveJob({ applications: [app()] }).job.status).toBe('applied_manually')
    expect(resolveJob({ ledger: ledger() }).job.status).toBeUndefined()
  })
})

describe('resolveJob gaps', () => {
  it('a slimmed stored row gets its ad text from the ledger, and its own fields stay on top', () => {
    const r = resolveJob({ stored: stored({ offList: true }), ledger: ledger(), fileChecked: true })
    expect(r.job).toMatchObject({ title: 'From browser', status: 'saved', description: 'ledger ad' })
  })

  it('or from the posting when the ledger has pruned it', () => {
    expect(resolveJob({ stored: stored({ offList: true }), applications: [app()] }).job.description).toBe('frozen ad')
  })

  it('file fields fill the stored row first', () => {
    const r = resolveJob({ stored: stored(), fileFields: { description: 'file ad', llmFacts: { a: 1 } }, ledger: ledger(), fileChecked: true, inFile: true })
    expect(r.job).toMatchObject({ description: 'file ad', llmFacts: { a: 1 } })
  })

  it('a stored description is never replaced', () => {
    expect(resolveJob({ stored: stored({ description: 'mine' }), ledger: ledger() }).job.description).toBe('mine')
  })

  it('a hand-entered job with no ad text stays without one', () => {
    const r = resolveJob({ stored: stored({ manualEntry: true }), applications: [app()], fileChecked: true })
    expect(r.job.description).toBeUndefined()
  })

  it('a ledger entry with an empty ad takes the frozen text', () => {
    const r = resolveJob({ ledger: ledger({ job: { jobId: ID, title: 'L', company: 'L', description: '' } }), applications: [app()] })
    expect(r).toMatchObject({ source: 'ledger', job: { title: 'L', description: 'frozen ad' } })
  })
})

describe('resolveJob: the notice', () => {
  it('a stored row in the loaded file has none', () => {
    expect(resolveJob({ stored: stored(), fileChecked: true, inFile: true }).notInLatest).toBe(false)
  })

  it('an offList row has it, with the date from the ledger', () => {
    expect(resolveJob({ stored: stored({ offList: true }), ledger: ledger(), fileChecked: true })).toMatchObject({ notInLatest: true, lastSeen: ledger().lastSeen })
  })

  it('an offList row keeps it while the server cannot be asked', () => {
    expect(resolveJob({ stored: stored({ offList: true }), fileChecked: false }).notInLatest).toBe(true)
  })

  it('a stored row the file lacks has it, before the next import marks the row', () => {
    expect(resolveJob({ stored: stored(), fileChecked: true, inFile: false }).notInLatest).toBe(true)
  })

  it('says nothing when the file could not be read: it cannot know', () => {
    expect(resolveJob({ stored: stored(), fileChecked: false }).notInLatest).toBe(false)
    expect(resolveJob({ applications: [app()], fileChecked: false }).notInLatest).toBe(false)
  })

  it('never on a hand-entered job, which discovery does not list', () => {
    expect(resolveJob({ stored: stored({ manualEntry: true }), fileChecked: true, inFile: false }).notInLatest).toBe(false)
  })

  it('a posting is not a last-seen date: the capture date is reported apart', () => {
    expect(resolveJob({ applications: [app()], fileChecked: true })).toMatchObject({ lastSeen: null, capturedAt: '2026-09-15T10:00:00.000Z' })
  })

  it('a row date is used when the ledger has none', () => {
    expect(resolveJob({ stored: stored({ offList: true, lastSeen: '2026-10-05' }), fileChecked: true }).lastSeen).toBe('2026-10-05')
  })
})

describe('resolveJob: which attempt', () => {
  const voided = app({ id: 'v', createdAt: '2026-10-20T00:00:00.000Z', posting: posting({ title: 'Voided attempt' }), events: [{ type: 'applied' }, { type: 'application_voided' }] })

  it('the latest attempt that is not voided, else the latest', () => {
    const live = app({ id: 'live', createdAt: '2026-09-01T00:00:00.000Z' })
    expect(resolveJob({ applications: [live, voided] }).job.title).toBe('From posting')
    expect(resolveJob({ applications: [voided] }).job.title).toBe('Voided attempt')
  })
})

describe('jobFromPosting', () => {
  it('maps the frozen record to the job shape and carries only ad fields', () => {
    const job = jobFromPosting(posting({ snapshotSha256: 'x', postingKey: 'y' }))
    expect(job).toMatchObject({ jobId: ID, title: 'From posting', company: 'P', jobUrl: 'https://p.example/job', provider: 'lever', isRemote: true })
    expect(job).not.toHaveProperty('url')
    expect(job).not.toHaveProperty('snapshotSha256')
    expect(job).not.toHaveProperty('capturedAt')
  })
})

describe('loadJobSources', () => {
  const deps = (over = {}) => ({
    autoLoad: vi.fn(async () => ({ state: { jobs: [] }, source: 'scored' })),
    loadDiscovered: vi.fn(async () => ({ jobs: [] })),
    loadHistory: vi.fn(async () => ledger()),
    ...over,
  })
  const state = { jobs: [] }

  it('a job in the scored file asks nothing further', async () => {
    const d = deps({ autoLoad: async () => ({ state: { jobs: [fileJob()] }, source: 'scored' }) })
    expect(await loadJobSources(ID, state, d)).toMatchObject({ fileChecked: true, inFile: true, ledger: null, addable: fileJob() })
    expect(d.loadDiscovered).not.toHaveBeenCalled()
    expect(d.loadHistory).not.toHaveBeenCalled()
  })

  it('a discovered job the scored file dropped counts as in the file, and is not added to the browser', async () => {
    const d = deps({ loadDiscovered: async () => ({ jobs: [fileJob()] }) })
    const out = await loadJobSources(ID, state, d)
    expect(out).toMatchObject({ fileChecked: true, inFile: true, fileJob: fileJob(), addable: null })
    expect(d.loadHistory).not.toHaveBeenCalled()
  })

  it('a job in neither file goes to the ledger, and a fallback is never addable', async () => {
    const d = deps()
    expect(await loadJobSources(ID, state, d)).toMatchObject({ fileChecked: true, inFile: false, fileJob: null, ledger: ledger(), addable: null })
    expect(d.loadHistory).toHaveBeenCalledWith(ID)
  })

  it('an offList row of the merged list is not in the file', async () => {
    const d = deps({ autoLoad: async () => ({ state: { jobs: [stored({ offList: true })] }, source: 'scored' }) })
    expect(await loadJobSources(ID, state, d)).toMatchObject({ inFile: false, ledger: ledger(), addable: null })
  })

  it('a row in the file without ad text asks the ledger for it', async () => {
    const d = deps({ autoLoad: async () => ({ state: { jobs: [stored()] }, source: 'scored' }) })
    expect(await loadJobSources(ID, state, d)).toMatchObject({ inFile: true, ledger: ledger() })
  })

  it('no file answer leaves "in the latest run" unknown', async () => {
    const d = deps({ autoLoad: async () => ({ state, source: 'local' }), loadHistory: async () => null })
    expect(await loadJobSources(ID, state, d)).toMatchObject({ fileChecked: false, inFile: false, ledger: null })
    expect(d.loadDiscovered).not.toHaveBeenCalled()
  })

  it('a failed read of the discovered file also leaves it unknown', async () => {
    const d = deps({ loadDiscovered: async () => { throw new Error('down') } })
    expect(await loadJobSources(ID, state, d)).toMatchObject({ fileChecked: false, inFile: false, ledger: ledger() })
  })
})

describe('opening', () => {
  it('the drawer button is enabled by a stored row or any fallback, and only then', () => {
    expect(canOpenJobPage(stored())).toBe(true)
    expect(canOpenJobPage(null, { hasFallback: true })).toBe(true)
    expect(canOpenJobPage(null, { hasFallback: false })).toBe(false)
    expect(canOpenJobPage(null)).toBe(false)
  })

  it('hasFallback: an application for the job, or a ledger entry', () => {
    const store = { applications: { a: app() } }
    expect(hasFallback(ID, store, null)).toBe(true)
    expect(hasFallback('other', store, null)).toBe(false)
    expect(hasFallback('other', store, ledger())).toBe(true)
    expect(hasFallback('other', null, null)).toBe(false)
  })

  it('a board card with a row opens the drawer on that row', () => {
    const row = stored()
    expect(applicationOpenTarget([row], ID)).toEqual({ kind: 'drawer', job: row })
  })

  it('a board card without a row opens Job Details by its id', () => {
    expect(applicationOpenTarget([], ID)).toEqual({ kind: 'page', jobId: ID })
    expect(applicationOpenTarget([{ jobId: 'other' }], ID)).toEqual({ kind: 'page', jobId: ID })
  })

  it('an application that has no job id has nothing to route to', () => {
    expect(applicationOpenTarget([], null)).toEqual({ kind: 'none' })
  })
})
