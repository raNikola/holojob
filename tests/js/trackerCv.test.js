import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import * as store from '../../scripts/application-store.js'
import * as client from '../../src/modules/applications/applicationsClient.js'
import { foldApplication } from '../../src/modules/applications/foldApplication.js'
import { buildAiContext } from '../../src/modules/ai/aiContextBuilder.js'
import {
  cvOptions, defaultCvOption, frozenFileUrl, markApplied, newRequestId, recordCv, timeline,
} from '../../src/modules/applications/trackerController.js'

const id16 = (n) => crypto.createHash('sha256').update(`cv-${n}`).digest('hex').slice(0, 16)
const JOB_ID = id16('job')
const LIB_ID = id16('lib')
const OTHER_LIB_ID = id16('lib2')
const TAILORED = 'Resume_Acme.pdf'
const job = (extra = {}) => ({ jobId: JOB_ID, title: 'PM', company: 'Acme', jobUrl: 'https://acme.example/pm', ...extra })
const profile = {
  defaultCvId: LIB_ID,
  cvLibrary: [
    { id: LIB_ID, label: 'Main CV', fileName: 'main.pdf', filePath: `profile/cvs/${LIB_ID}.pdf` },
    { id: OTHER_LIB_ID, label: 'Short CV', fileName: 'short.pdf', filePath: `profile/cvs/${OTHER_LIB_ID}.pdf` },
    { id: 'cv-1a2b3c', label: 'Migrated, never stored', fileName: 'old.pdf', filePath: null },
  ],
}
const form = (extra = {}) => ({ requestId: newRequestId(), channel: 'company_site', appliedDate: '2026-11-01', ...extra })

let root
let server
const cache = () => client.getApplicationsState()
const write = (rel, text) => {
  const file = path.join(root, rel)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, text)
}

beforeEach(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'cvpick-'))
  write(`data/profile/cvs/${LIB_ID}.pdf`, '%PDF-main')
  write(`data/profile/cvs/${OTHER_LIB_ID}.pdf`, '%PDF-short')
  write(`data/resumes/${JOB_ID}/${TAILORED}`, '%PDF-tailored')
  const now = () => new Date('2026-11-03T10:00:00.000Z')
  server = http.createServer(async (req, res) => {
    if (!(await store.handleApplicationsRequest(req, res, req.url.split('?')[0], { root, now }))) { res.statusCode = 418; res.end() }
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  client.configureClient({ base: `http://127.0.0.1:${server.address().port}`, ensure: async () => true })
  await client.refreshApplications()
})

afterEach(async () => {
  client.configureClient()
  await new Promise((resolve) => server.close(resolve))
  fs.rmSync(root, { recursive: true, force: true })
})

describe('the CV picker options', () => {
  it('offers tailored (bare name), stored library CVs, external and not recorded; never a library CV without a file', () => {
    const tailored = { resumePdf: `data/resumes/${JOB_ID}/${TAILORED}` }
    const options = cvOptions(job({ tailoredAssets: tailored }), profile)
    expect(options.map((o) => o.key)).toEqual(['tailored', `library:${LIB_ID}`, `library:${OTHER_LIB_ID}`, 'external', 'unknown'])
    expect(options[0]).toMatchObject({ kind: 'tailored', fileName: TAILORED })
    expect(options[1].label).toBe('Main CV (default)')
  })

  it('preselects the tailored CV, else the default library CV, else not recorded', () => {
    const withTailored = job({ tailoredAssets: { resumePdf: `x/${TAILORED}` } })
    expect(defaultCvOption(withTailored, profile).key).toBe('tailored')
    expect(defaultCvOption(job(), profile).key).toBe(`library:${LIB_ID}`)
    expect(defaultCvOption(job(), { ...profile, defaultCvId: 'cv-1a2b3c' }).key).toBe('unknown')
    expect(defaultCvOption(job(), null).key).toBe('unknown')
  })
})

describe('Mark Applied with a CV', () => {
  it('freezes the tailored CV and the override to a library CV, with the file served back', async () => {
    const tailored = cvOptions(job({ tailoredAssets: { resumePdf: TAILORED } }), profile)[0]
    const a = (await markApplied(job(), cache(), form({ cv: tailored }))).application
    expect(a.attempt.cv).toMatchObject({ kind: 'tailored', fileName: TAILORED, sha256: expect.any(String) })
    expect(fs.readFileSync(path.join(root, 'data/applications/files', a.id, TAILORED), 'utf-8')).toBe('%PDF-tailored')

    // a second job, the user overrides the preselect with the other library CV
    const jobB = { ...job(), jobId: id16('jobB'), jobUrl: 'https://acme.example/b' }
    const override = cvOptions(jobB, profile).find((o) => o.key === `library:${OTHER_LIB_ID}`)
    const b = (await markApplied(jobB, cache(), form({ cv: override }))).application
    expect(b.attempt.cv).toMatchObject({ kind: 'library', cvLibraryId: OTHER_LIB_ID, label: 'Short CV', fileName: 'short.pdf' })
    const res = await fetch(`http://127.0.0.1:${server.address().port}${frozenFileUrl(b.id, b.attempt.cv.fileName)}`)
    expect(res.status).toBe(200)
    expect(await res.text()).toBe('%PDF-short')
  })

  it('records no CV when the user picks none, and sends the typed name for an external CV', async () => {
    const none = (await markApplied(job(), cache(), form())).application
    expect(none.attempt.cv).toMatchObject({ kind: 'unknown', fileName: null, sha256: null })
    const jobB = { ...job(), jobId: id16('jobB'), jobUrl: 'https://acme.example/b' }
    const external = cvOptions(jobB, profile).find((o) => o.key === 'external')
    const b = (await markApplied(jobB, cache(), form({ cv: external, cvLabel: 'CV from a recruiter' }))).application
    expect(b.attempt.cv).toMatchObject({ kind: 'external', label: 'CV from a recruiter', fileName: null })
  })

  it('a missing tailored file is refused by the store and nothing is created', async () => {
    const ghost = { key: 'tailored', kind: 'tailored', fileName: 'nope.pdf', label: 'Tailored for this job' }
    await expect(markApplied(job(), cache(), form({ cv: ghost }))).rejects.toMatchObject({ status: 400 })
    expect(Object.keys(store.loadStore(root).applications)).toEqual([])
  })
})

describe('recording and correcting the CV later (O4)', () => {
  it('records once without a reason, then a correction needs one and keeps the earlier copy', async () => {
    const app = (await markApplied(job(), cache(), form())).application
    const [main, short] = cvOptions(job(), profile)
    await recordCv(app.id, main, {})
    expect(foldApplication(cache().store.applications[app.id]).cv).toMatchObject({ kind: 'library', fileName: 'main.pdf' })

    await expect(recordCv(app.id, short, {})).rejects.toMatchObject({ message: expect.stringContaining('reason') })
    await recordCv(app.id, short, { reason: 'sent the short one' })
    const saved = store.loadStore(root).applications[app.id]
    expect(foldApplication(saved).cv).toMatchObject({ cvLibraryId: OTHER_LIB_ID })
    const dir = path.join(root, 'data/applications/files', app.id)
    expect(fs.readdirSync(dir).sort()).toEqual(['main.pdf', 'short.pdf'])
    await expect(recordCv(app.id, { kind: 'unknown' }, {})).rejects.toThrow('Pick the CV')
  })
})

describe('frozen file route is traversal safe', () => {
  it('serves only names recorded on the application', async () => {
    const app = (await markApplied(job(), cache(), form({ cv: cvOptions(job(), profile)[0] }))).application
    write('data/applications/secret.txt', 'private')
    const base = `http://127.0.0.1:${server.address().port}/api/applications/${app.id}/files`
    for (const name of ['..%2Fsecret.txt', '%2e%2e%2fsecret.txt', 'secret.txt', encodeURIComponent('../../../applications.json')]) {
      const res = await fetch(`${base}/${name}`)
      expect([400, 404], name).toContain(res.status)
      expect(await res.text(), name).not.toContain('private')
    }
    expect((await fetch(`http://127.0.0.1:${server.address().port}/api/applications/..%2F..%2Fx/files/a.pdf`)).status).toBeGreaterThanOrEqual(400)
  })
})

describe('history', () => {
  it('lists every event newest first and renders for a job that is not in discovery', async () => {
    const app = (await markApplied(job(), cache(), form())).application
    await client.addEvent(app.id, { type: 'note_added', data: { text: 'Intro call' } })
    const lines = timeline(cache().store.applications[app.id], cache().settings)
    expect(lines.map((l) => l.title)).toEqual(['Note added', 'Applied'])
    expect(lines[0].detail).toBe('Intro call')
    // the timeline reads the application alone: no job record is passed in
    expect(timeline.length).toBe(2)
  })
})

describe('AI context carries no contact fields', () => {
  it('leaves recruiter name, e-mail, LinkedIn, notes and link out of the job and the application context', () => {
    const tracking = {
      applied: true, interviewStage: 'HR Screen', followUpDate: '2026-11-10', recruiterName: 'Mirela Fakeson', recruiterEmail: 'mirela@recruit-test.example',
      recruiterLinkedIn: 'https://www.linkedin.com/in/mirela-fakeson', notes: 'phoned Mirela', applicationUrl: 'https://acme.example/apply/9',
    }
    const j = job({ applicationTracking: tracking })
    const data = new Map([['job-dashboard-discovered-jobs', JSON.stringify({ jobs: [j] })]])
    globalThis.localStorage = { getItem: (k) => data.get(k) ?? null, setItem() {}, removeItem() {} }
    try {
      const json = JSON.stringify([buildAiContext({ featureId: 'jobAnalysis', job: j }), buildAiContext({ featureId: 'applicationStrategy' })])
      for (const leak of ['Mirela', 'recruit-test', 'linkedin.com', 'phoned', 'apply/9', 'recruiterName']) expect(json).not.toContain(leak)
      expect(json).toContain('HR Screen')
    } finally {
      delete globalThis.localStorage
    }
  })
})
