// A generated document is attached to an application only if the server's fact-gate verdict passed and the file is unchanged.
// Nothing under data/applications changes when a document is refused, voided applications included.
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as store from '../../scripts/application-store.js'
import { GATE_VERSION, verdictPath } from '../../scripts/document-verdicts.js'
import { writeVerdict } from './helpers/documentVerdict.js'

const JOB = {
  jobId: 'a1b2c3d4e5f60718', provider: 'greenhouse', source: 'greenhouse', title: 'Senior Product Manager', company: 'Acme',
  location: 'Remote', jobUrl: 'https://boards.greenhouse.io/acme/jobs/123', description: 'A role.', isRemote: true,
}
const OTHER = { ...JOB, jobId: 'ffff000011112222', jobUrl: 'https://boards.greenhouse.io/acme/jobs/999', title: 'Other role' }
const CV = '0123456789abcdef'
const PDF = Buffer.from('%PDF-1.4\ntailored resume')
const LETTER = Buffer.from('%PDF-1.4\ncover letter')
const NOW = () => new Date('2026-11-03T10:00:00.000Z')

let root
let seq = 0
const folder = (jobId = JOB.jobId) => path.join(root, 'data/resumes', jobId)
const put = (name, data, jobId = JOB.jobId) => { fs.mkdirSync(folder(jobId), { recursive: true }); fs.writeFileSync(path.join(folder(jobId), name), data) }

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'verdict-'))
  fs.mkdirSync(path.join(root, 'data/jobs'), { recursive: true })
  fs.writeFileSync(path.join(root, 'data/jobs/scored_jobs.json'), JSON.stringify({ meta: {}, jobs: [JOB, OTHER] }))
  fs.mkdirSync(path.join(root, 'data/profile/cvs'), { recursive: true })
  fs.writeFileSync(path.join(root, `data/profile/cvs/${CV}.pdf`), '%PDF-library')
  put('Acme_Resume.pdf', PDF)
  put('Acme_CoverLetter.pdf', LETTER)
})
afterEach(() => { vi.restoreAllMocks(); fs.rmSync(root, { recursive: true, force: true }) })

const body = (attempt = {}, jobId = JOB.jobId) => ({
  requestId: `req-${(seq += 1)}-${crypto.randomUUID()}`,
  jobId,
  attempt: { channel: 'company_site', channelDetail: 'form', applicationUrl: '', appliedDate: '2026-11-03', cv: { kind: 'tailored', fileName: 'Acme_Resume.pdf', label: 'Tailored' }, ...attempt },
})
const create = (attempt, jobId) => store.createApplication(root, body(attempt, jobId), { now: NOW })

/** Every file under data/applications with its bytes' hash: what "nothing changed" means. */
function tree() {
  const out = {}
  const walk = (dir) => {
    if (!fs.existsSync(dir)) return
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name)
      if (e.isDirectory()) { out[`${p}/`] = ''; walk(p) } else out[p] = crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')
    }
  }
  walk(path.join(root, 'data/applications'))
  return out
}
const refusal = async (fn) => { try { await fn(); return null } catch (e) { return e } }

describe('a generated document is attached only with a passing, current verdict', () => {
  it('attaches a CV and a cover letter that passed, and freezes exactly what was judged', async () => {
    writeVerdict(folder(), 'Acme_Resume.pdf')
    writeVerdict(folder(), 'Acme_CoverLetter.pdf')
    const { application } = await create({ coverLetter: { fileName: 'Acme_CoverLetter.pdf' } })
    expect(application.attempt.cv.sha256).toBe(crypto.createHash('sha256').update(PDF).digest('hex'))
    expect(application.attempt.coverLetter.sha256).toBe(crypto.createHash('sha256').update(LETTER).digest('hex'))
  })

  it.each([
    ['never judged', () => {}, 'missing'],
    ['judged and failed', () => writeVerdict(folder(), 'Acme_Resume.pdf', { passed: false, issues: ['Unverified number: 47'] }), 'failed'],
    ['changed after it was judged', () => { writeVerdict(folder(), 'Acme_Resume.pdf'); put('Acme_Resume.pdf', 'edited afterwards') }, 'changed'],
    ['judged by an older gate', () => writeVerdict(folder(), 'Acme_Resume.pdf', { gateVersion: GATE_VERSION - 1 }), 'old_gate'],
    ['a verdict that names another file', () => { writeVerdict(folder(), 'Acme_CoverLetter.pdf'); fs.copyFileSync(verdictPath(folder(), 'Acme_CoverLetter.pdf'), verdictPath(folder(), 'Acme_Resume.pdf')) }, 'changed'],
    ['a verdict with the wrong hash', () => writeVerdict(folder(), 'Acme_Resume.pdf', { sha256: 'a'.repeat(64) }), 'changed'],
    ['a corrupt verdict', () => fs.writeFileSync(verdictPath(folder(), 'Acme_Resume.pdf'), '{ nope'), 'missing'],
    ['a verdict that says passed as text', () => { writeVerdict(folder(), 'Acme_Resume.pdf', { passed: 'true' }) }, 'failed'],
  ])('refuses a CV that was %s, with 409, and creates nothing', async (_name, arrange, code) => {
    arrange()
    const before = tree()
    const error = await refusal(() => create())
    expect(error?.status).toBe(409)
    expect(error.extra).toMatchObject({ reason: 'unverified_document', code })
    expect(tree()).toEqual(before)
    expect(fs.existsSync(path.join(root, 'data/applications/files'))).toBe(false)
  })

  it('reports the failed claims so the owner can see why', async () => {
    writeVerdict(folder(), 'Acme_Resume.pdf', { passed: false, issues: ['Unverified number: 47'] })
    expect((await refusal(() => create())).extra.issues).toEqual(['Unverified number: 47'])
  })

  it('refuses a cover letter that did not pass even when the CV did, and removes the CV copy it had made', async () => {
    writeVerdict(folder(), 'Acme_Resume.pdf')
    const error = await refusal(() => create({ coverLetter: { fileName: 'Acme_CoverLetter.pdf' } }))
    expect(error?.status).toBe(409)
    expect(tree()).toEqual({})
  })

  it('refuses and removes the copy when the file is replaced between the check and the copy', async () => {
    writeVerdict(folder(), 'Acme_Resume.pdf')
    const target = path.join(folder(), 'Acme_Resume.pdf')
    const real = fs.readFileSync
    let reads = 0
    // The first read is the verdict check; the second is the copy, which now sees other bytes.
    vi.spyOn(fs, 'readFileSync').mockImplementation((file, ...rest) => (String(file) === target && (reads += 1) === 2 ? Buffer.from('swapped in') : real(file, ...rest)))
    const before = tree()
    const error = await refusal(() => create())
    expect(error?.status).toBe(409)
    expect(error.extra).toMatchObject({ reason: 'unverified_document', code: 'changed' })
    // No file is left; the empty `files` parent folder the copy step creates is not a record.
    const filesOnly = (t) => Object.fromEntries(Object.entries(t).filter(([, hash]) => hash !== ''))
    expect(filesOnly(tree())).toEqual(filesOnly(before))
    expect(fs.readdirSync(path.join(root, 'data/applications/files'))).toEqual([])
  })

  it('does not ask for a verdict on a library CV', async () => {
    const { application } = await create({ cv: { kind: 'library', cvLibraryId: CV, label: 'Main', fileName: 'CV.pdf' } })
    expect(application.attempt.cv.kind).toBe('library')
  })

  it('a document the browser says passed is still checked on the server: no field of the request can stand in for the verdict', async () => {
    const forged = body({ cv: { kind: 'tailored', fileName: 'Acme_Resume.pdf', passed: true, provenancePassed: true, verdict: { passed: true } } })
    expect((await refusal(() => store.createApplication(root, { ...forged, provenancePassed: true }, { now: NOW })))?.status).toBe(409)
  })

  it('the ai cover letter draft folder cannot be reached by name', async () => {
    fs.mkdirSync(path.join(folder(), 'drafts'), { recursive: true })
    fs.writeFileSync(path.join(folder(), 'drafts', 'ai_cover_letter.md'), 'draft')
    expect((await refusal(() => create({ cv: { kind: 'tailored', fileName: 'drafts/ai_cover_letter.md' } })))?.status).toBe(400)
  })
})

describe('refusing a document leaves every application record alone, voided ones included', () => {
  async function withExistingApplications() {
    writeVerdict(folder(), 'Acme_Resume.pdf')
    const first = (await create()).application
    await store.appendEvent(root, first.id, { type: 'application_voided', date: '2026-11-03', data: { reason: 'entered by mistake' } }, { now: NOW })
    put('Other_Resume.pdf', PDF, OTHER.jobId)
    writeVerdict(folder(OTHER.jobId), 'Other_Resume.pdf')
    const second = (await create({ cv: { kind: 'tailored', fileName: 'Other_Resume.pdf' } }, OTHER.jobId)).application
    return { first, second }
  }

  it('a refused create changes no byte of the store or of any frozen file', async () => {
    await withExistingApplications()
    put('Acme_Resume.pdf', 'changed after the check')
    const before = tree()
    expect(Object.keys(before).some((p) => p.endsWith('applications.json'))).toBe(true)
    expect((await refusal(() => create()))?.status).toBe(409)
    expect(tree()).toEqual(before)
  })

  it('a refused cv_recorded on a voided and on an open application changes nothing and copies nothing', async () => {
    const { first, second } = await withExistingApplications()
    put('Other_Resume.pdf', 'changed after the check', OTHER.jobId)
    const before = tree()
    for (const id of [first.id, second.id]) {
      const error = await refusal(() => store.appendEvent(root, id, { type: 'cv_recorded', date: '2026-11-03', data: { kind: 'tailored', fileName: 'Other_Resume.pdf', label: 'x' } }, { now: NOW }))
      expect(error).not.toBeNull()
      expect(tree()).toEqual(before)
    }
  })

  it('a document that passes is frozen as a copy: later changes to the original never reach the application', async () => {
    const { second } = await withExistingApplications()
    const frozen = path.join(root, 'data/applications/files', second.id, 'Other_Resume.pdf')
    const sha = crypto.createHash('sha256').update(fs.readFileSync(frozen)).digest('hex')
    put('Other_Resume.pdf', 'regenerated later', OTHER.jobId)
    expect(crypto.createHash('sha256').update(fs.readFileSync(frozen)).digest('hex')).toBe(sha)
  })
})

describe('the verdict format is shared with Python', () => {
  it('uses the same gate version as verdicts.py', async () => {
    const python = fs.readFileSync(path.resolve(__dirname, '../../python/resume_generator/verdicts.py'), 'utf-8')
    expect(Number(/^GATE_VERSION = (\d+)/m.exec(python)[1])).toBe(GATE_VERSION)
  })

  it('names the verdict file the way Python does', async () => {
    expect(path.basename(verdictPath('/x', 'Acme_Resume.pdf'))).toBe('.Acme_Resume.pdf.verdict.json')
  })
})
