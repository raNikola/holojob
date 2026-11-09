import { describe, expect, it, vi } from 'vitest'
import { cvEntryParsedData, readPdfDraft, readTextFileDraft, sourceForFile } from '../../src/modules/profile/importFlow.js'
import { applyReviewedImport } from '../../src/modules/profile/importApply.js'
import { defaultChoices } from '../../src/modules/profile/importDraft.js'
import { ensureCvLibrary } from '../../src/utils/cvLibrary.js'

const file = { name: 'jane-sample.pdf', type: 'application/pdf', size: 1234 }

function emptyProfile() {
  return ensureCvLibrary({
    basicProfile: { fullName: '', email: '', phone: '', location: '', currentRole: '', experienceYears: '', languages: [] },
    resume: { fileName: '', uploadedAt: '', rawText: '', parsedData: { skills: [], projects: [], education: [], workExperience: [], certifications: [], links: [] } },
    repositories: { githubLinks: [], localRepoPaths: [] },
    questionnaire: { answers: [] },
    _confidence: {},
    _editedFields: {},
  })
}

const parsed = (source) => ({
  source,
  fileName: '',
  rawText: 'JANE\nSAMPLE\n10+ years',
  headline: 'TECHNICAL PRODUCT LEADER',
  basicProfile: { fullName: 'Jane Sample', email: 'jane@example.com', currentRole: 'Head of Product', experienceYears: '10' },
  confidence: { experienceYears: 'derived' },
  parsedData: {
    skills: ['Product Strategy', 'Node.js'], projects: [], education: ['MSc Information Systems, University of Springfield, 2012'], certifications: ['CSPO, Scrum Alliance, 2019'],
    workExperience: [],
    experienceDetail: [{ title: 'Head of Product', company: 'Northwind', location: 'Remote', start: 'April 2024', end: 'Present', description: 'Own the portfolio', bullets: ['Grew ARR by 40%.'] }],
    competencyGroups: [],
  },
  languages: [],
  links: ['github.com/janesample'],
  unplaced: [],
  ignored: [],
  warnings: [],
})

describe('reading a PDF', () => {
  it('extracts the text, parses it as the chosen source and writes nothing', async () => {
    const extract = vi.fn(async () => 'JANE\nSAMPLE')
    const parse = vi.fn(async (source) => parsed(source))
    const upload = vi.fn()
    const updateProfile = vi.fn()
    const draft = await readPdfDraft(file, 'resume_pdf', { extract, parse })
    expect(extract).toHaveBeenCalledWith(file)
    expect(parse).toHaveBeenCalledWith('resume_pdf', 'JANE\nSAMPLE')
    expect(draft.source).toBe('resume_pdf')
    expect(draft.fileName).toBe('jane-sample.pdf')
    expect(upload).not.toHaveBeenCalled()
    expect(updateProfile).not.toHaveBeenCalled()
  })

  it('does the same for a LinkedIn PDF', async () => {
    const parse = vi.fn(async (source) => parsed(source))
    const draft = await readPdfDraft(file, 'linkedin_pdf', { extract: async () => 'x', parse })
    expect(parse).toHaveBeenCalledWith('linkedin_pdf', 'x')
    expect(draft.source).toBe('linkedin_pdf')
  })

  it('refuses a source that is not a PDF source before reading anything', async () => {
    const extract = vi.fn()
    await expect(readPdfDraft(file, 'paste', { extract, parse: vi.fn() })).rejects.toThrow()
    expect(extract).not.toHaveBeenCalled()
  })

  it('passes a read or parse failure on and leaves no draft', async () => {
    await expect(readPdfDraft(file, 'resume_pdf', { extract: async () => { throw new Error('No text could be extracted') }, parse: vi.fn() })).rejects.toThrow('No text')
    const parse = vi.fn(async () => { throw new Error('The text could not be read.') })
    await expect(readPdfDraft(file, 'resume_pdf', { extract: async () => 'x', parse })).rejects.toThrow('could not be read')
  })
})

describe('applying a reviewed PDF draft', () => {
  const NOW = { now: new Date('2026-11-01T09:00:00Z') }

  async function review(source = 'resume_pdf') {
    const draft = await readPdfDraft(file, source, { extract: async () => 'text', parse: async (s) => parsed(s) })
    return { draft, choices: defaultChoices(emptyProfile(), draft) }
  }

  /** The guarded apply with in-memory effects; `calls` records the order of effects. */
  async function apply({ draft, choices, file: pdf, upload }) {
    const calls = []
    let stored = null
    const deps = {
      backup: async () => { calls.push('backup'); return true },
      snapshot: { saveBefore: () => {}, saveAfter: () => {}, load: () => null, clear: () => {} },
      upload: upload && (async (f) => { calls.push('upload'); return upload(f) }),
      discardUpload: async () => {},
      commit: (p) => { calls.push('commit'); stored = p; return p },
      syncMirror: async () => true,
      setSyncPending: () => {},
    }
    const done = await applyReviewedImport({ profile: emptyProfile(), draft, choices, file: pdf, deps, options: NOW })
    return { done, calls, result: stored }
  }

  it('stores nothing and updates nothing until Apply', async () => {
    const upload = vi.fn(async () => 'cv-stored1')
    await review()
    expect(upload).not.toHaveBeenCalled()
  })

  it('backs up, uploads the PDF, then adds a My CVs entry that points at the stored file', async () => {
    const { draft, choices } = await review()
    const { done, calls, result } = await apply({ draft, choices, file, upload: async (f) => { expect(f).toBe(file); return 'cv-stored1' } })
    expect(calls).toEqual(['backup', 'upload', 'commit'])
    expect(done).toMatchObject({ ok: true, applied: true })
    const entry = result.cvLibrary.find((c) => c.id === 'cv-stored1')
    expect(entry).toMatchObject({ filePath: 'profile/cvs/cv-stored1.pdf', fileName: 'jane-sample.pdf', label: 'jane-sample', importSource: 'resume_pdf' })
    expect(entry.rawText).toContain('10+ years')
    expect(result.defaultCvId).toBe('cv-stored1') // the first CV of a profile is its active one
  })

  it('fills the basics, experience years and entry fields the review showed', async () => {
    const { draft, choices } = await review('linkedin_pdf')
    const { result } = await apply({ draft, choices, file, upload: async () => 'cv-2' })
    expect(result.basicProfile).toMatchObject({ fullName: 'Jane Sample', currentRole: 'Head of Product', experienceYears: '10' })
    expect(result._confidence.experienceYears).toBe('derived')
    expect(result.basicProfile.targetRoles).toBeUndefined()
    const [entry] = result.resume.parsedData.experienceDetail
    expect(entry).toMatchObject({ location: 'Remote', description: 'Own the portfolio', bullets: ['Grew ARR by 40%.'] })
    expect(result.resume.parsedData.workExperience[0]).toBe('Head of Product — Northwind | April 2024 – Present | Own the portfolio. Grew ARR by 40%.')
    expect(result.cvLibrary[0].importSource).toBe('linkedin_pdf')
  })

  it('keeps the entry without a file when the upload fails or the API is away', async () => {
    for (const upload of [async () => { throw new Error('refused') }, async () => null]) {
      const { draft, choices } = await review()
      const { result } = await apply({ draft, choices, file, upload })
      expect(result.cvLibrary[0].filePath).toBeNull()
      expect(result.cvLibrary[0].fileName).toBe('jane-sample.pdf')
    }
  })

  it('does not upload anything for a draft that did not come from a file', async () => {
    const { draft, choices } = await review()
    const upload = vi.fn()
    await apply({ draft: { ...draft, source: 'paste', fileName: '' }, choices, file: null, upload })
    expect(upload).not.toHaveBeenCalled()
  })
})

describe('cvEntryParsedData (My CVs > Add)', () => {
  const draft = {
    source: 'resume_pdf', summary: 'Product leader.',
    parsedData: {
      skills: ['SQL'], projects: [], education: ['BSc, Springfield University, 2016'], workExperience: [], certifications: [],
      experienceDetail: [{ title: 'Head of Product', company: 'Acme', start: '2020', end: 'Present', bullets: ['Grew revenue.'] }],
      educationDetail: [{ text: 'BSc, Springfield University, 2016', degree: 'BSc', school: 'Springfield University', year: '2016' }],
      competencyGroups: [],
    },
    links: [],
  }

  it('uses the server parser and keeps its entries, but not the parser-only reading', async () => {
    const parse = vi.fn().mockResolvedValue(draft)
    const fallback = vi.fn()
    const result = await cvEntryParsedData('cv text', { parse, fallback })
    expect(parse).toHaveBeenCalledWith('resume_pdf', 'cv text')
    expect(fallback).not.toHaveBeenCalled()
    expect(result.usedFallback).toBe(false)
    expect(result.parsedData.experienceDetail[0].title).toBe('Head of Product')
    expect(result.parsedData.summary).toBe('Product leader.')
    expect(result.parsedData.workExperience).toEqual(['Head of Product — Acme | 2020 – Present | Grew revenue.'])
    expect(JSON.stringify(result.parsedData)).not.toContain('educationDetail')
  })

  it('falls back to the older reader, and says so, when the parser fails', async () => {
    const parse = vi.fn().mockRejectedValue(new Error('offline'))
    const fallback = vi.fn().mockReturnValue({ skills: ['Go'] })
    expect(await cvEntryParsedData('cv text', { parse, fallback })).toEqual({ parsedData: { skills: ['Go'] }, usedFallback: true })
    expect(fallback).toHaveBeenCalledWith('cv text')
  })
})

describe('reading a text or Markdown file', () => {
  const md = (name = 'cv.md', size = 100) => ({ name, type: '', size })
  const parse = vi.fn(async (source, text) => ({ source, rawText: text, parsedData: {} }))

  it('maps file names and types to import sources', () => {
    expect(sourceForFile({ name: 'CV.PDF', type: '' })).toBe('resume_pdf')
    expect(sourceForFile({ name: 'cv.txt', type: '' })).toBe('text_file')
    expect(sourceForFile({ name: 'cv.MD', type: '' })).toBe('text_file')
    expect(sourceForFile({ name: 'cv.markdown', type: 'text/markdown' })).toBe('text_file')
    expect(sourceForFile({ name: 'noext', type: 'text/plain' })).toBe('text_file')
    expect(sourceForFile({ name: 'cv.docx', type: '' })).toBeNull()
    expect(sourceForFile({ name: 'cv.exe', type: 'application/octet-stream' })).toBeNull()
  })

  it('reads the text in the browser, parses it as a text file, keeps the file name and writes nothing', async () => {
    const draft = await readTextFileDraft(md('jane.md'), { parse, read: async () => '# Jane\nSQL' })
    expect(parse).toHaveBeenCalledWith('text_file', '# Jane\nSQL')
    expect(draft).toMatchObject({ source: 'text_file', fileName: 'jane.md' })
  })

  it('refuses a binary, a non-UTF-8 or an oversized file before anything is sent', async () => {
    const send = vi.fn(async () => ({}))
    await expect(readTextFileDraft(md(), { parse: send, read: async () => 'ab\u0000cd' })).rejects.toThrow(/not UTF-8 text/)
    await expect(readTextFileDraft(md(), { parse: send, read: async () => '�'.repeat(50) + 'x'.repeat(100) })).rejects.toThrow(/not UTF-8 text/)
    await expect(readTextFileDraft(md('big.txt', 300 * 1024), { parse: send, read: async () => 'x' })).rejects.toThrow(/too large/)
    await expect(readTextFileDraft({ name: 'a.pdf', type: 'application/pdf', size: 5 }, { parse: send, read: async () => 'x' })).rejects.toThrow(/not a text file/)
    expect(send).not.toHaveBeenCalled()
  })

  it('a few stray replacement characters do not make a file "not text"', async () => {
    await expect(readTextFileDraft(md(), { parse, read: async () => `Name ��\n${'text '.repeat(200)}` })).resolves.toBeTruthy()
  })
})
