import { describe, expect, it } from 'vitest'
import {
  BASIC_FIELDS,
  addEntry,
  applyImportDraft,
  defaultChoices,
  deriveWorkExperience,
  effectiveSectionChoice,
  removeEntry,
  willBeActive,
  withBasic,
  withEntry,
  withSection,
} from '../../src/modules/profile/importDraft.js'
import { ensureCvLibrary } from '../../src/utils/cvLibrary.js'

const NOW = new Date('2026-10-31T09:00:00Z')
const options = { now: NOW, makeId: () => 'cv-new' }

function emptyProfile() {
  return {
    basicProfile: { fullName: '', email: '', phone: '', location: '', currentRole: '', languages: [] },
    resume: { fileName: '', uploadedAt: '', rawText: '', parsedData: { skills: [], projects: [], education: [], workExperience: [], certifications: [], links: [] } },
    repositories: { githubLinks: [], localRepoPaths: [] },
    questionnaire: { answers: [] },
    _confidence: {},
    _editedFields: {},
  }
}

function profileWithCv(patch = {}) {
  const base = emptyProfile()
  const profile = {
    ...base,
    basicProfile: { ...base.basicProfile, fullName: 'Existing Person', email: 'existing@example.com', currentRole: 'Engineer' },
    resume: {
      fileName: 'old.pdf', uploadedAt: '2026-01-01T00:00:00Z', rawText: 'old text', importSource: 'resume_pdf',
      parsedData: { ...base.resume.parsedData, skills: ['Go'], workExperience: ['Engineer — Old Co | 2018 – 2020 | Built things.'] },
    },
    ...patch,
  }
  return ensureCvLibrary(profile)
}

const draft = () => ({
  source: 'paste',
  fileName: '',
  rawText: 'Jane Sample\nSKILLS\nPython, Go',
  basicProfile: { fullName: 'Jane Sample', email: 'jane@example.com', phone: '+1 415 555 0132', location: 'Springfield, Ohio', currentRole: 'Product Manager' },
  parsedData: {
    skills: ['Python', 'go'],
    projects: [],
    education: ['BSc — Springfield University, 2012 - 2016'],
    workExperience: [],
    certifications: [],
    experienceDetail: [{ title: 'Product Manager', company: 'Acme', start: 'Jan 2020', end: 'Present', bullets: ['Led a team', 'Grew revenue.'] }],
    competencyGroups: [{ label: 'Tools', items: ['SQL', 'Jira'] }],
  },
  languages: [{ language: 'English', proficiency: 'native' }],
  links: ['https://www.linkedin.com/in/jane-sample', 'github.com/janesample'],
  confidence: { fullName: 'medium', email: 'high', skills: 'medium', workExperience: 'medium', links: 'high' },
  unplaced: [{ label: 'Interests', text: 'Chess' }],
  ignored: [],
  warnings: [],
})

describe('deriveWorkExperience', () => {
  it('writes the line the evidence index reads', () => {
    expect(deriveWorkExperience(draft().parsedData.experienceDetail)).toEqual(['Product Manager — Acme | Jan 2020 – Present | Led a team. Grew revenue.'])
  })
})

describe('experience entries with a location and a description', () => {
  it('writes the same line as the Python parser for the synthetic PDF fixture', () => {
    const entries = [
      { title: 'Product Owner', company: 'Initech', location: '', start: '2014', end: '2021', description: 'Maintained the backlog for an internal tooling suite used by 300 employees.', bullets: [] },
      { title: 'Senior Product Manager', company: 'Globex Corp', location: 'Belgrade, Serbia', start: 'June 2021', end: 'July 2023', description: 'Led the payments squad through a migration from a monolith to services.', bullets: ['Cut checkout failures by 22%.', 'Mentored three junior product managers.'] },
    ]
    expect(deriveWorkExperience(entries)).toEqual([
      'Product Owner — Initech | 2014 – 2021 | Maintained the backlog for an internal tooling suite used by 300 employees.',
      'Senior Product Manager — Globex Corp | June 2021 – July 2023 | Led the payments squad through a migration from a monolith to services. Cut checkout failures by 22%. Mentored three junior product managers.',
    ])
  })

  it('keeps location and description when a draft is saved', () => {
    const d = draft()
    d.parsedData.experienceDetail = [{ title: 'PM', company: 'Acme', location: 'Remote', start: '2020', end: '', description: 'Owned billing', bullets: [] }]
    const next = applyImportDraft(emptyProfile(), d, { basics: {}, sections: { experience: 'add' } }, options)
    expect(next.resume.parsedData.experienceDetail[0]).toMatchObject({ location: 'Remote', description: 'Owned billing' })
    expect(next.resume.parsedData.workExperience).toEqual(['PM — Acme | 2020 | Owned billing.'])
  })

  it('never writes target roles', () => {
    const d = draft()
    d.basicProfile.targetRoles = ['Project Manager']
    const next = applyImportDraft(emptyProfile(), d, { basics: { fullName: 'use' }, sections: {} }, options)
    expect(next.basicProfile.targetRoles).toBeUndefined()
  })
})

describe('defaultChoices', () => {
  it('fills only what is empty', () => {
    const choices = defaultChoices(profileWithCv(), draft())
    expect(choices.basics).toEqual({ fullName: 'keep', email: 'keep', phone: 'use', location: 'use', currentRole: 'keep', experienceYears: 'keep' })
    expect(choices.sections).toMatchObject({ experience: 'keep', skills: 'keep', education: 'add', languages: 'add', links: 'add', projects: 'keep' })
  })

  it('does not fill a field the user edited, even when it is empty now', () => {
    const profile = { ...emptyProfile(), _editedFields: { phone: true, skills: true } }
    const choices = defaultChoices(profile, draft())
    expect(choices.basics.phone).toBe('keep')
    expect(choices.basics.fullName).toBe('use')
    expect(choices.sections.skills).toBe('keep')
  })
})

describe('applyImportDraft', () => {
  it('fills empty fields and leaves existing values alone by default', () => {
    const profile = profileWithCv()
    const next = applyImportDraft(profile, draft(), defaultChoices(profile, draft()), options)
    expect(next.basicProfile).toMatchObject({ fullName: 'Existing Person', email: 'existing@example.com', phone: '+1 415 555 0132', location: 'Springfield, Ohio', currentRole: 'Engineer' })
    expect(next.resume.parsedData.skills).toEqual(['Go'])
    expect(next.resume.parsedData.education).toEqual(['BSc — Springfield University, 2012 - 2016'])
    expect(next.basicProfile.languages).toEqual([{ language: 'English', proficiency: 'native' }])
  })

  it('never overwrites a field the user edited: use falls back to keep', () => {
    const profile = profileWithCv({ _editedFields: { fullName: true, skills: true } })
    const choices = { basics: { fullName: 'use' }, sections: { skills: 'replace' } }
    const next = applyImportDraft(profile, draft(), choices, options)
    expect(next.basicProfile.fullName).toBe('Existing Person')
    expect(next.resume.parsedData.skills).toEqual(['Go'])
  })

  it('still allows Add on an edited section and skips duplicates', () => {
    const profile = profileWithCv({ _editedFields: { skills: true } })
    expect(effectiveSectionChoice(profile, 'skills', 'replace')).toBe('keep')
    const next = applyImportDraft(profile, draft(), { basics: {}, sections: { skills: 'add' } }, options)
    expect(next.resume.parsedData.skills).toEqual(['Go', 'Python'])
    expect(next.resume.parsedData.competencyGroups).toEqual([{ label: 'Tools', items: ['SQL', 'Jira'] }])
  })

  it('replaces a section the user did not edit', () => {
    const profile = profileWithCv()
    const next = applyImportDraft(profile, draft(), { basics: {}, sections: { skills: 'replace', experience: 'replace' } }, options)
    expect(next.resume.parsedData.skills).toEqual(['Python', 'go'])
    expect(next.resume.parsedData.experienceDetail).toHaveLength(1)
    expect(next.resume.parsedData.workExperience).toEqual(['Product Manager — Acme | Jan 2020 – Present | Led a team. Grew revenue.'])
  })

  it('keeps everything when every choice is keep', () => {
    const profile = profileWithCv()
    const all = { basics: Object.fromEntries(BASIC_FIELDS.map((f) => [f, 'keep'])), sections: {} }
    const next = applyImportDraft(profile, draft(), all, options)
    expect(next.basicProfile).toEqual(profile.basicProfile)
    expect(next.resume.parsedData).toEqual(profile.resume.parsedData)
    expect(next.repositories).toEqual(profile.repositories)
  })

  it('sends GitHub links to the repositories list with a scheme, once', () => {
    const profile = profileWithCv()
    const choices = { basics: {}, sections: { links: 'add' } }
    const once = applyImportDraft(profile, draft(), choices, options)
    expect(once.repositories.githubLinks).toEqual(['https://github.com/janesample'])
    expect(once.resume.parsedData.links).toEqual(['https://www.linkedin.com/in/jane-sample', 'github.com/janesample'])
    const twice = applyImportDraft(once, draft(), choices, options)
    expect(twice.repositories.githubLinks).toEqual(['https://github.com/janesample'])
  })

  it('adds a labelled My CVs entry that is not the active CV', () => {
    const profile = profileWithCv()
    const next = applyImportDraft(profile, draft(), defaultChoices(profile, draft()), options)
    const entry = next.cvLibrary.find((c) => c.id === 'cv-new')
    expect(entry).toMatchObject({ label: 'Pasted text 2026-10-31', filePath: null, importSource: 'pasted_text', rawText: draft().rawText })
    expect(next.defaultCvId).toBe(profile.defaultCvId)
    expect(next.resume.fileName).toBe('old.pdf')
    expect(entry.parsedData.skills).toEqual(['Python', 'go'])
    expect(entry.parsedData.workExperience[0]).toContain('Product Manager — Acme')
  })

  it('makes the entry the active CV only when the profile has none', () => {
    const profile = emptyProfile()
    const next = applyImportDraft(profile, draft(), defaultChoices(profile, draft()), options)
    expect(next.defaultCvId).toBe('cv-new')
    expect(next.resume).toMatchObject({ fileName: 'Pasted text 2026-10-31', rawText: draft().rawText, importSource: 'pasted_text' })
    expect(next.resume.parsedData.skills).toEqual(['Python', 'go'])
    expect(next.cvLibrary).toHaveLength(1)
  })

  it('on a profile with no CV, a keep choice still wins over the entry for the live fields', () => {
    const profile = emptyProfile()
    const keepSkills = { basics: {}, sections: { skills: 'keep' } }
    const next = applyImportDraft(profile, draft(), keepSkills, options)
    expect(next.resume.parsedData.skills).toEqual([])
  })

  it('does not touch the questionnaire or mark any field as edited', () => {
    const profile = profileWithCv()
    const next = applyImportDraft(profile, draft(), defaultChoices(profile, draft()), options)
    expect(next.questionnaire).toEqual(profile.questionnaire)
    expect(next._editedFields).toEqual(profile._editedFields)
  })

  it('carries the parser confidence of what it filled, and drops it for a user-edited value', () => {
    const profile = emptyProfile()
    const edited = withBasic(withSection(draft(), 'skills', ['Rust']), 'email', 'typed@example.com')
    const next = applyImportDraft(profile, edited, defaultChoices(profile, edited), options)
    expect(next._confidence.fullName).toBe('medium')
    expect(next._confidence.email).toBeUndefined()
    expect(next._confidence.skills).toBeUndefined()
    expect(next.basicProfile.email).toBe('typed@example.com')
    expect(next.resume.parsedData.skills).toEqual(['Rust'])
  })

  it('does not mutate its inputs', () => {
    const profile = profileWithCv()
    const frozen = JSON.stringify(profile)
    const d = draft()
    const frozenDraft = JSON.stringify(d)
    applyImportDraft(profile, d, defaultChoices(profile, d), options)
    expect(JSON.stringify(profile)).toBe(frozen)
    expect(JSON.stringify(d)).toBe(frozenDraft)
  })
})

describe('withSection', () => {
  it('keeps the derived experience lines in step with edited entries', () => {
    const entries = [{ title: 'Lead', company: 'Initech', start: '2019', end: '2021', bullets: ['Shipped it'] }]
    const next = withSection(draft(), 'experience', entries)
    expect(next.parsedData.workExperience).toEqual(['Lead — Initech | 2019 – 2021 | Shipped it.'])
  })

  it('stores plain experience lines when there are no entries', () => {
    const next = withSection(draft(), 'experience', ['Engineer at Acme'])
    expect(next.parsedData.experienceDetail).toEqual([])
    expect(next.parsedData.workExperience).toEqual(['Engineer at Acme'])
  })
})

describe('experience entry helpers', () => {
  const twoEntries = () => ({
    ...draft(),
    parsedData: { ...draft().parsedData, experienceDetail: [
      { title: 'A', company: 'One', start: '2019', end: '2020', bullets: ['x'] },
      { title: 'B', company: 'Two', start: '2020', end: '2021', bullets: ['y'] },
      { title: 'C', company: 'Three', start: '2021', end: '2022', bullets: ['z'] },
    ] },
    confidence: { 'experienceDetail.0': 'medium', 'experienceDetail.1': 'low', 'experienceDetail.2': 'medium', skills: 'medium' },
  })

  it('withEntry drops the confidence of the edited entry only', () => {
    const next = withEntry(twoEntries(), 1, { title: 'B2', company: 'Two', start: '2020', end: '2021', bullets: ['y'] })
    expect(next.confidence).toEqual({ 'experienceDetail.0': 'medium', 'experienceDetail.2': 'medium', skills: 'medium' })
    expect(next.parsedData.workExperience[1]).toBe('B2 — Two | 2020 – 2021 | y.')
  })

  it('removeEntry moves the later confidence up with its entry', () => {
    const next = removeEntry(twoEntries(), 0)
    expect(next.parsedData.experienceDetail.map((e) => e.title)).toEqual(['B', 'C'])
    expect(next.confidence).toEqual({ 'experienceDetail.0': 'low', 'experienceDetail.1': 'medium', skills: 'medium' })
  })

  it('addEntry appends a blank entry that saving then leaves out', () => {
    const added = addEntry(twoEntries())
    expect(added.parsedData.experienceDetail).toHaveLength(4)
    const profile = emptyProfile()
    const next = applyImportDraft(profile, added, { basics: {}, sections: { experience: 'add' } }, options)
    expect(next.resume.parsedData.experienceDetail.map((e) => e.title)).toEqual(['A', 'B', 'C'])
  })
})

describe('saving cleans what the user typed', () => {
  it('trims lines and drops empty ones and empty bullets', () => {
    const typed = withSection(withSection(draft(), 'skills', ['  Rust ', '', 'Zig']), 'experience', [
      { title: ' Lead ', company: '', start: '2020', end: '', bullets: ['', ' shipped ', ''] },
    ])
    const profile = emptyProfile()
    const next = applyImportDraft(profile, typed, { basics: {}, sections: { skills: 'add', experience: 'add' } }, options)
    expect(next.resume.parsedData.skills).toEqual(['Rust', 'Zig'])
    expect(next.resume.parsedData.experienceDetail).toEqual([{ title: 'Lead', company: '', location: '', start: '2020', end: '', description: '', bullets: ['shipped'] }])
  })
})

describe('willBeActive', () => {
  it('is true only for a profile with no CV', () => {
    expect(willBeActive(emptyProfile())).toBe(true)
    expect(willBeActive(profileWithCv())).toBe(false)
  })
})
