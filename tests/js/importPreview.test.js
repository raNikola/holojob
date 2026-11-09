import { describe, expect, it } from 'vitest'
import { defaultChoices } from '../../src/modules/profile/importDraft.js'
import { buildImportPreview } from '../../src/modules/profile/importPreview.js'

const entry = (title, company, start, bullets) => ({ title, company, location: '', start, end: '2022', description: '', bullets })
const draft = () => ({
  source: 'paste', rawText: 'x', summary: 'New summary.',
  basicProfile: { fullName: 'New Name', email: 'n@example.invalid', phone: '', location: '', currentRole: 'Head of Product', experienceYears: '' },
  languages: [], links: [],
  parsedData: { skills: ['SQL', 'Go'], projects: [], education: [], certifications: [], workExperience: [], competencyGroups: [], experienceDetail: [entry('PM', 'Acme', '2019', ['Led.']), entry('Analyst', 'Beta', '2016', ['Built.'])] },
  confidence: {},
})
const profile = () => ({
  basicProfile: { fullName: 'Hand Typed', currentRole: '', languages: [] },
  resume: { fileName: 'o.pdf', parsedData: { summary: 'Old summary.', skills: ['SQL', 'Excel'], experienceDetail: [entry('Old', 'Old Co', '2010', ['Did.']), entry('PM', 'Acme', '2019', ['Led.'])], workExperience: [] } },
  repositories: { githubLinks: [] }, cvLibrary: [{ id: 'cv-old', fileName: 'o.pdf', parsedData: {} }], defaultCvId: 'cv-old', meta: {}, _editedFields: {},
})
const choose = (p, sections = {}, extra = {}) => {
  const c = defaultChoices(p, draft())
  return { ...c, ...extra, sections: { ...c.sections, ...sections } }
}
const row = (preview, id) => preview.sections.find((s) => s.id === id)

describe('buildImportPreview', () => {
  it('Merge: counts what is added and kept, removes nothing, and needs no replace confirm', () => {
    const p = profile()
    const preview = buildImportPreview(p, draft(), choose(p, { experience: 'add', skills: 'add' }))
    expect(row(preview, 'experience')).toMatchObject({ choice: 'add', added: 1, removed: 0, kept: 2 })
    expect(row(preview, 'skills')).toMatchObject({ added: 1, removed: 0, kept: 2 })
    expect(preview.removals).toBe(0)
    expect(preview.needsReplaceConfirm).toBe(false)
    expect(preview.becomesActive).toBe(false)
  })

  it('Replace: counts the entries it removes and asks for the second confirm', () => {
    const p = profile()
    const preview = buildImportPreview(p, draft(), choose(p, { experience: 'replace' }))
    expect(row(preview, 'experience')).toMatchObject({ choice: 'replace', added: 1, removed: 1, kept: 1 })
    expect(preview.removals).toBe(1)
    expect(preview.needsReplaceConfirm).toBe(true)
  })

  it('an edited section is kept even if Replace was chosen, so nothing is removed', () => {
    const p = { ...profile(), _editedFields: { workExperience: true } }
    const preview = buildImportPreview(p, draft(), choose(p, { experience: 'replace' }))
    expect(row(preview, 'experience')).toMatchObject({ choice: 'keep', added: 0, removed: 0 })
    expect(preview.needsReplaceConfirm).toBe(false)
  })

  it('lists basic fields and the summary as filled or changed, never their values', () => {
    const p = profile()
    const preview = buildImportPreview(p, draft(), choose(p, {}, { basics: { fullName: 'use', currentRole: 'use', email: 'use', phone: 'keep', location: 'keep', experienceYears: 'keep' }, summary: 'use' }))
    expect(preview.basics).toEqual(expect.arrayContaining([
      { field: 'fullName', action: 'changes' }, { field: 'currentRole', action: 'fills' }, { field: 'email', action: 'fills' },
    ]))
    expect(preview.summary).toBe('changes')
    expect(JSON.stringify({ ...preview, planned: undefined })).not.toContain('New Name')
  })

  it('keeping everything is "unchanged" apart from the My CVs entry it still adds', () => {
    const p = profile()
    const keepAll = { basics: {}, sections: Object.fromEntries(['experience', 'education', 'skills', 'languages', 'certifications', 'projects', 'links'].map((id) => [id, 'keep'])), summary: 'keep' }
    const preview = buildImportPreview(p, draft(), keepAll)
    expect(preview.sections.every((s) => s.added === 0 && s.removed === 0)).toBe(true)
    expect(preview.unchanged).toBe(false)
    expect(preview.planned.cvLibrary).toHaveLength(2)
  })

  it('reports that the first CV of an empty profile becomes active', () => {
    const empty = { basicProfile: { languages: [] }, resume: { parsedData: {} }, repositories: { githubLinks: [] }, cvLibrary: [], defaultCvId: null, meta: {}, _editedFields: {} }
    expect(buildImportPreview(empty, draft(), defaultChoices(empty, draft())).becomesActive).toBe(true)
  })

  it('does not change the profile it was given', () => {
    const p = profile()
    const before = JSON.stringify(p)
    buildImportPreview(p, draft(), choose(p, { experience: 'replace' }))
    expect(JSON.stringify(p)).toBe(before)
  })
})
