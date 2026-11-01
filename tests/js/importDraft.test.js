import { describe, expect, it } from 'vitest'
import {
  BASIC_FIELDS,
  addEntry,
  applyImportDraft,
  basicNeedsChoice,
  resolveChoices,
  sectionNeedsChoice,
  summaryNeedsChoice,
  defaultChoices,
  deriveWorkExperience,
  educationReading,
  effectiveSectionChoice,
  removeEntry,
  willBeActive,
  withBasic,
  withEntry,
  withSection,
  withSummary,
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

describe('summary', () => {
  const withSummaryDraft = () => ({ ...draft(), summary: 'Product leader with 12 years in B2B software.', confidence: { ...draft().confidence, summary: 'medium' } })

  it('is filled by default only when the profile has none', () => {
    expect(defaultChoices(emptyProfile(), withSummaryDraft()).summary).toBe('use')
    const has = emptyProfile()
    has.resume.parsedData.summary = 'My own words.'
    expect(defaultChoices(has, withSummaryDraft()).summary).toBe('keep')
    expect(defaultChoices(emptyProfile(), draft()).summary).toBe('keep')
  })

  it('is saved to the profile and to the new My CVs entry like other fields', () => {
    const profile = emptyProfile()
    const next = applyImportDraft(profile, withSummaryDraft(), defaultChoices(profile, withSummaryDraft()), options)
    expect(next.resume.parsedData.summary).toBe('Product leader with 12 years in B2B software.')
    expect(next._confidence.summary).toBe('medium')
    expect(next.cvLibrary.find((c) => c.id === 'cv-new').parsedData.summary).toBe('Product leader with 12 years in B2B software.')
  })

  it('keeps the current summary on keep and replaces it on use', () => {
    const profile = emptyProfile()
    profile.resume.parsedData.summary = 'My own words.'
    const kept = applyImportDraft(profile, withSummaryDraft(), { basics: {}, sections: {}, summary: 'keep' }, options)
    expect(kept.resume.parsedData.summary).toBe('My own words.')
    const replaced = applyImportDraft(profile, withSummaryDraft(), { basics: {}, sections: {}, summary: 'use' }, options)
    expect(replaced.resume.parsedData.summary).toBe('Product leader with 12 years in B2B software.')
  })

  it('never replaces a summary the user edited', () => {
    const profile = { ...emptyProfile(), _editedFields: { summary: true } }
    profile.resume.parsedData.summary = 'My own words.'
    const next = applyImportDraft(profile, withSummaryDraft(), { basics: {}, sections: {}, summary: 'use' }, options)
    expect(next.resume.parsedData.summary).toBe('My own words.')
  })

  it('an edit on the review screen drops the parser confidence', () => {
    const next = withSummary(withSummaryDraft(), 'Edited.')
    expect(next.summary).toBe('Edited.')
    expect(next.confidence.summary).toBeUndefined()
  })
})

describe('education reading', () => {
  const withDetail = () => {
    const d = draft()
    d.parsedData.educationDetail = [{ text: 'BSc — Springfield University, 2012 - 2016', degree: 'BSc', school: 'Springfield University', year: '2012 - 2016' }]
    return d
  }

  it('is shown for a line as the parser read it', () => {
    expect(educationReading(withDetail(), 'BSc — Springfield University, 2012 - 2016')).toEqual({ degree: 'BSc', school: 'Springfield University', year: '2012 - 2016' })
  })

  it('is gone once the line is edited, so a stale reading is never shown', () => {
    expect(educationReading(withDetail(), 'BSc — Springfield University, 2012 - 2017')).toBeNull()
  })

  it('is display only: saving keeps the lines and writes no reading', () => {
    const next = applyImportDraft(emptyProfile(), withDetail(), { basics: {}, sections: { education: 'add' } }, options)
    expect(next.resume.parsedData.education).toEqual(['BSc — Springfield University, 2012 - 2016'])
    expect(JSON.stringify(next)).not.toContain('educationDetail')
  })
})

describe('when the review screen offers a decision', () => {
  it('basic field: none for an empty profile field, one for a different value, none for an equal one', () => {
    const d = draft()
    expect(basicNeedsChoice(emptyProfile(), d, 'fullName')).toBe(false)
    expect(basicNeedsChoice(profileWithCv(), d, 'fullName')).toBe(true)
    const same = profileWithCv({ basicProfile: { ...profileWithCv().basicProfile, fullName: ' jane  sample ' } })
    expect(basicNeedsChoice(same, d, 'fullName')).toBe(false)
  })

  it('summary follows the same rule', () => {
    const d = { ...draft(), summary: 'New summary' }
    const withSummary = (text) => ({ ...emptyProfile(), resume: { ...emptyProfile().resume, parsedData: { summary: text } } })
    expect(summaryNeedsChoice(emptyProfile(), d)).toBe(false)
    expect(summaryNeedsChoice(withSummary('Old summary'), d)).toBe(true)
    expect(summaryNeedsChoice(withSummary('New summary'), d)).toBe(false)
  })

  it('section: none while the profile holds 0 entries, one once it holds some', () => {
    expect(sectionNeedsChoice(emptyProfile(), 'skills')).toBe(false)
    expect(sectionNeedsChoice(profileWithCv(), 'skills')).toBe(true)
  })
})

describe('resolveChoices and the saved output', () => {
  it('applies a value typed into a field that was empty in the draft, with no dropdown', () => {
    const profile = emptyProfile()
    const d = withBasic({ ...draft(), basicProfile: { ...draft().basicProfile, phone: '' } }, 'phone', '+381 60 000 000')
    const stored = defaultChoices(profile, { ...d, basicProfile: { ...d.basicProfile, phone: '' } })
    expect(stored.basics.phone).toBe('keep')
    const next = applyImportDraft(profile, d, resolveChoices(profile, d, stored), options)
    expect(next.basicProfile.phone).toBe('+381 60 000 000')
  })

  it('output for an empty profile equals the old "Fill" / "Add" output', () => {
    const profile = emptyProfile()
    const old = applyImportDraft(profile, draft(), defaultChoices(profile, draft()), options)
    const now = applyImportDraft(profile, draft(), resolveChoices(profile, draft(), defaultChoices(profile, draft())), options)
    expect(now).toEqual(old)
  })

  it('leaves the choice alone where there is a decision: keep stays keep, replace stays replace', () => {
    const profile = profileWithCv()
    const keep = defaultChoices(profile, draft())
    // Only fields with nothing to decide change (empty in the profile); the saved output is the same.
    expect(applyImportDraft(profile, draft(), resolveChoices(profile, draft(), keep), options)).toEqual(applyImportDraft(profile, draft(), keep, options))
    expect(resolveChoices(profile, draft(), keep).basics).toMatchObject({ fullName: 'keep', email: 'keep', currentRole: 'keep' })
    expect(resolveChoices(profile, draft(), keep).sections.skills).toBe('keep')
    const replace = { ...keep, basics: { ...keep.basics, fullName: 'use' }, sections: { ...keep.sections, skills: 'replace' } }
    expect(applyImportDraft(profile, draft(), resolveChoices(profile, draft(), replace), options))
      .toEqual(applyImportDraft(profile, draft(), replace, options))
    const next = applyImportDraft(profile, draft(), resolveChoices(profile, draft(), keep), options)
    expect(next.basicProfile.fullName).toBe('Existing Person')
  })

  it('equal value: no decision, the default keeps the identical value', () => {
    const base = profileWithCv()
    const profile = { ...base, basicProfile: { ...base.basicProfile, fullName: 'Jane Sample' } }
    expect(basicNeedsChoice(profile, draft(), 'fullName')).toBe(false)
    const keep = defaultChoices(profile, draft())
    expect(keep.basics.fullName).toBe('keep')
    const next = applyImportDraft(profile, draft(), resolveChoices(profile, draft(), keep), options)
    expect(next.basicProfile.fullName).toBe('Jane Sample')
  })
})
