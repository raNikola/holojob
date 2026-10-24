import { describe, expect, it } from 'vitest'
import {
  addCv, canRemoveCv, cvFilesToDiscard, ensureCvLibrary, registerActiveUpload, removeCv, renameCv, setDefaultCv, syncDefaultEntry,
} from '../../src/utils/cvLibrary'

const parsed = (skill) => ({ skills: [skill], projects: [], education: [], workExperience: [], certifications: [], links: [] })

const profile = () => ({
  basicProfile: { fullName: 'A' },
  resume: { fileName: 'Full CV.pdf', uploadedAt: '2026-10-20T00:00:00Z', rawText: 'full text', parsedData: parsed('Go'), importSource: 'resume_pdf' },
})

const second = { id: 'b', fileName: 'ATS.pdf', uploadedAt: '2026-10-22T00:00:00Z', rawText: 'ats text', parsedData: parsed('SQL'), filePath: 'profile/cvs/b.pdf' }

describe('ensureCvLibrary (first run)', () => {
  it('moves the existing résumé into the library as the default and loses nothing', () => {
    const p = ensureCvLibrary(profile())
    expect(p.cvLibrary).toHaveLength(1)
    expect(p.defaultCvId).toBe(p.cvLibrary[0].id)
    expect(p.cvLibrary[0]).toMatchObject({ fileName: 'Full CV.pdf', label: 'Full CV', filePath: null, rawText: 'full text', parsedData: parsed('Go') })
    expect(p.resume).toEqual(profile().resume)
  })
  it('is idempotent and gives the same id every time', () => {
    const once = ensureCvLibrary(profile())
    expect(ensureCvLibrary(once)).toBe(once)
    expect(ensureCvLibrary(profile()).defaultCvId).toBe(once.defaultCvId)
  })
  it('gives an empty library to a profile with no résumé', () => {
    expect(ensureCvLibrary({ resume: { fileName: '' } })).toMatchObject({ cvLibrary: [], defaultCvId: null })
  })
})

describe('library actions', () => {
  it('adds a new CV without touching the active résumé', () => {
    const base = ensureCvLibrary(profile())
    const next = addCv(base, second)
    expect(next.cvLibrary.map((c) => c.id)).toEqual([base.defaultCvId, 'b'])
    expect(next.defaultCvId).toBe(base.defaultCvId)
    expect(next.resume).toEqual(base.resume)
  })
  it('makes a CV the default by copying it into profile.resume, and keeps form edits of the old one', () => {
    let p = addCv(ensureCvLibrary(profile()), second)
    const firstId = p.defaultCvId
    p = { ...p, resume: { ...p.resume, parsedData: parsed('Go, edited in the form') } }
    p = setDefaultCv(p, 'b')
    expect(p.defaultCvId).toBe('b')
    expect(p.resume).toMatchObject({ fileName: 'ATS.pdf', rawText: 'ats text', parsedData: parsed('SQL'), importSource: 'resume_pdf' })
    expect(p.cvLibrary.find((c) => c.id === firstId).parsedData).toEqual(parsed('Go, edited in the form'))
    p = setDefaultCv(p, firstId)
    expect(p.resume.parsedData).toEqual(parsed('Go, edited in the form'))
  })
  it('renames, ignoring an empty label', () => {
    const p = addCv(ensureCvLibrary(profile()), second)
    expect(renameCv(p, 'b', '  ATS version ').cvLibrary[1].label).toBe('ATS version')
    expect(renameCv(p, 'b', '   ')).toBe(p)
  })
  it('never removes the default, and removes any other', () => {
    const p = addCv(ensureCvLibrary(profile()), second)
    expect(canRemoveCv(p, p.defaultCvId)).toBe(false)
    expect(removeCv(p, p.defaultCvId)).toBe(p)
    expect(removeCv(p, 'b').cvLibrary.map((c) => c.id)).toEqual([p.defaultCvId])
  })
  it('the first CV added to an empty library becomes the default', () => {
    const p = addCv(ensureCvLibrary({ resume: { fileName: '', parsedData: parsed('x') } }), second)
    expect(p.defaultCvId).toBe('b')
    expect(p.resume.fileName).toBe('ATS.pdf')
  })
})

describe('an Edit Profile upload', () => {
  it('lists the new active CV as default and keeps the outgoing one with its edits', () => {
    let p = ensureCvLibrary(profile())
    p = { ...p, resume: { ...p.resume, parsedData: parsed('edited') } }
    p = syncDefaultEntry(p)
    p = { ...p, resume: { fileName: 'New.pdf', uploadedAt: '2026-10-24T00:00:00Z', rawText: 'new', parsedData: parsed('New'), importSource: 'resume_pdf' } }
    p = registerActiveUpload(p, { id: 'n', filePath: 'profile/cvs/n.pdf' })
    expect(p.defaultCvId).toBe('n')
    expect(p.cvLibrary).toHaveLength(2)
    expect(p.cvLibrary[0].parsedData).toEqual(parsed('edited'))
    expect(p.cvLibrary[1]).toMatchObject({ id: 'n', fileName: 'New.pdf', rawText: 'new' })
  })
})

describe('loadProfile migration', () => {
  it('lists the stored résumé on load when the profile has no library yet', async () => {
    const store = new Map()
    globalThis.localStorage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: (k) => store.delete(k) }
    const { loadProfile, STORAGE_KEY } = await import('../../src/utils/storage')
    store.set(STORAGE_KEY, JSON.stringify(profile()))
    const loaded = loadProfile()
    expect(loaded.cvLibrary).toHaveLength(1)
    expect(loaded.defaultCvId).toBe(loaded.cvLibrary[0].id)
    expect(JSON.parse(store.get(STORAGE_KEY)).cvLibrary).toHaveLength(1)
    expect(loaded.resume.fileName).toBe('Full CV.pdf')
    delete globalThis.localStorage
  })
})

describe('cvFilesToDiscard (Cancel in Edit Profile)', () => {
  it('names only the PDFs of CVs added during the session', () => {
    const before = addCv(ensureCvLibrary(profile()), second)
    let during = renameCv(setDefaultCv(before, 'b'), 'b', 'Renamed')
    during = registerActiveUpload(
      { ...during, resume: { fileName: 'New.pdf', rawText: 'n', parsedData: parsed('n') } },
      { id: 'n', filePath: 'profile/cvs/n.pdf' },
    )
    expect(cvFilesToDiscard(before, during)).toEqual(['n'])
  })
  it('deletes nothing when no CV was added, and skips an entry with no file', () => {
    const before = ensureCvLibrary(profile())
    expect(cvFilesToDiscard(before, renameCv(before, before.defaultCvId, 'x'))).toEqual([])
    const during = addCv(before, { ...second, filePath: null })
    expect(cvFilesToDiscard(before, during)).toEqual([])
  })
})
