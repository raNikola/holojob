import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { loadJobs, saveJobs, importJobsFromFile } from '../../src/modules/jobs/jobStorage.js'
import { createJob, invalidateJobs } from '../../src/modules/jobs/jobsStore.js'
import {
  buildManualJob, cleanExtraLinks, findDuplicateByUrl, jobStatusLabel, normalizeJobUrl, validateManualJob,
} from '../../src/modules/jobs/manualJob.js'
import { buildAiContext, buildAiRedactionHints } from '../../src/modules/ai/aiContextBuilder.js'

const items = new Map()

beforeEach(() => {
  items.clear()
  vi.stubGlobal('localStorage', {
    getItem: (k) => items.get(k) ?? null,
    setItem: (k, v) => { items.set(k, v) },
    removeItem: (k) => { items.delete(k) },
  })
  vi.stubGlobal('window', new EventTarget())
  saveJobs({ meta: null, jobs: [{ jobId: 'a', status: 'saved', title: 'PM', jobUrl: 'https://Example.com/jobs/1/?utm_source=x#top' }, { jobId: 'b', status: 'new', title: 'Other' }], filters: {}, importedAt: null })
  invalidateJobs()
})

afterEach(() => vi.unstubAllGlobals())

const FORM = { title: 'Product Manager', company: 'Acme', description: 'Own the roadmap.', jobUrl: 'https://acme.example/jobs/9', sourceChoice: 'Referral' }

describe('validateManualJob', () => {
  it('requires title, company and description', () => {
    expect(Object.keys(validateManualJob({ title: ' ', company: '', description: '' })).sort()).toEqual(['company', 'description', 'title'])
    expect(validateManualJob(FORM)).toEqual({})
  })

  it('accepts an empty URL but not a malformed or non-http one', () => {
    expect(validateManualJob({ ...FORM, jobUrl: '' })).toEqual({})
    expect(validateManualJob({ ...FORM, jobUrl: 'acme.example/jobs' }).jobUrl).toBeTruthy()
    expect(validateManualJob({ ...FORM, jobUrl: 'javascript:alert(1)' }).jobUrl).toBeTruthy()
  })

  it('numbers extra link errors by the non-blank rows and ignores blank rows', () => {
    const errors = validateManualJob({ ...FORM, extraLinks: [{ url: '', label: '' }, { url: 'https://ok.example', label: 'ok' }, { url: 'nope', label: 'bad' }] })
    expect(errors.extraLinks).toEqual({ 1: expect.any(String) })
    expect(cleanExtraLinks([{ url: ' ', label: '' }])).toEqual([])
  })
})

describe('URL de-duplication', () => {
  it('normalises host case, query, hash and trailing slash', () => {
    expect(normalizeJobUrl('HTTPS://Example.COM/jobs/1/?utm=x#top')).toBe('https://example.com/jobs/1')
    expect(normalizeJobUrl('ftp://example.com/x')).toBeNull()
    expect(normalizeJobUrl('')).toBeNull()
  })

  it('finds the stored job with the same URL, and none for a different one', () => {
    const jobs = loadJobs().jobs
    expect(findDuplicateByUrl(jobs, 'https://example.com/jobs/1')?.jobId).toBe('a')
    expect(findDuplicateByUrl(jobs, 'https://example.com/jobs/2')).toBeNull()
    expect(findDuplicateByUrl(jobs, '')).toBeNull()
  })

  it('keeps identifying parameters: sibling ?gh_jid= postings are not duplicates, tracking parameters are ignored', () => {
    const board = (n, extra = '') => `https://careers.example/job/?gh_jid=${n}${extra}#apply`
    expect(createJob(buildManualJob({ ...FORM, jobUrl: board(1) }, { id: 'manual-1' }))).toMatchObject({ ok: true })
    expect(createJob(buildManualJob({ ...FORM, jobUrl: board(2) }, { id: 'manual-2' }))).toMatchObject({ ok: true })
    const again = createJob(buildManualJob({ ...FORM, jobUrl: board(1, '&utm_source=mail&fbclid=z&gclid=y&ref=x') }, { id: 'manual-3' }))
    expect(again).toMatchObject({ ok: false, reason: 'duplicate', existing: { jobId: 'manual-1' } })
    expect(loadJobs().jobs.map((j) => j.jobId)).toEqual(['a', 'b', 'manual-1', 'manual-2'])
  })
})

describe('createJob', () => {
  it('appends the new job and leaves the other records byte for byte as stored', () => {
    const before = loadJobs().jobs
    const job = buildManualJob(FORM, { id: 'manual-1', now: new Date('2026-10-30T10:00:00Z') })
    expect(createJob(job)).toMatchObject({ ok: true })
    const after = loadJobs().jobs
    expect(after).toHaveLength(3)
    expect(JSON.stringify(after.slice(0, 2))).toBe(JSON.stringify(before))
    expect(after[2]).toMatchObject({ jobId: 'manual-1', status: 'new', manualEntry: true, provider: 'manual', sourceChoice: 'Referral', firstSeen: '2026-10-30T10:00:00.000Z', createdAt: '2026-10-30T10:00:00.000Z' })
  })

  it('refuses a second job with the same normalised URL and points at the existing one', () => {
    const result = createJob(buildManualJob({ ...FORM, jobUrl: 'https://example.com/jobs/1' }, { id: 'manual-2' }))
    expect(result).toMatchObject({ ok: false, reason: 'duplicate', existing: { jobId: 'a' } })
    expect(loadJobs().jobs).toHaveLength(2)
  })

  it('does not guess: no score, no parsed salary, no remote flag, location empty', () => {
    const job = buildManualJob({ ...FORM, salary: '2500-3000 EUR' })
    expect(job.salary).toBe('2500-3000 EUR')
    for (const key of ['matchScore', 'salaryMonthlyEur', 'isRemote']) expect(key in job).toBe(false)
    expect(job.location).toBe('')
    expect(job.jobId).toMatch(/^manual-/)
  })

  it('shows status new as Unreviewed', () => {
    expect(jobStatusLabel('new')).toBe('Unreviewed')
    expect(jobStatusLabel(undefined)).toBe('Unreviewed')
    expect(jobStatusLabel('applied_manually')).toBe('applied manually')
  })
})

describe('re-import of the scored-jobs file', () => {
  it('keeps a hand-entered job, its notes and links, when the file lacks it', () => {
    createJob(buildManualJob({ ...FORM, notes: 'call Mia', extraLinks: [{ url: 'https://acme.example/about', label: 'About' }] }, { id: 'manual-3' }))
    const next = importJobsFromFile({ meta: null, jobs: [{ jobId: 'z', title: 'From file' }] }, loadJobs())
    const kept = next.jobs.find((j) => j.jobId === 'manual-3')
    expect(kept).toMatchObject({ notes: 'call Mia', extraLinks: [{ url: 'https://acme.example/about', label: 'About' }], manualEntry: true })
    expect(next.jobs.map((j) => j.jobId)).toEqual(['z', 'manual-3'])
  })

  it('keeps the manual row, with its notes, when the file has the same address under another id', () => {
    createJob(buildManualJob({ ...FORM, notes: 'secret-ish' }, { id: 'manual-4' }))
    const next = importJobsFromFile({ jobs: [{ jobId: 'f1', title: 'Product Manager', jobUrl: FORM.jobUrl }] }, loadJobs())
    expect(next.jobs.find((j) => j.jobId === 'f1')).toBeUndefined()
    expect(next.jobs.find((j) => j.jobId === 'manual-4')).toMatchObject({ notes: 'secret-ish', manualEntry: true })
  })
})

describe('owner-only fields never reach an AI context', () => {
  const NOTE = 'NOTE-CANARY-7731'
  const LINK = 'https://canary-7731.acme.example/private'
  const LABEL = 'LABEL-CANARY-7731'
  const FEATURES = ['jobAnalysis', 'resumeEnhancement', 'coverLetter', 'interviewPrep', 'outreach', 'companyIntelligence',
    'careerStrategy', 'skillGap', 'applicationStrategy', 'chat']

  it.each(FEATURES)('%s: neither the notes nor the extra links are in the context or the redaction hints', (featureId) => {
    const job = { ...buildManualJob({ ...FORM, notes: NOTE, extraLinks: [{ url: LINK, label: LABEL }] }, { id: 'manual-5' }), matchScore: 70 }
    createJob(job)
    const context = buildAiContext({ featureId, job, message: 'hello' })
    const text = JSON.stringify({ context, hints: buildAiRedactionHints({ job }) })
    for (const secret of [NOTE, LINK, LABEL, 'canary-7731']) expect(text).not.toContain(secret)
    if (featureId === 'jobAnalysis') expect(text).toContain('Own the roadmap')
  })
})
