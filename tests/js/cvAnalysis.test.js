import { describe, expect, it } from 'vitest'
import { applySuggestions, applyToDefaultCv, buildSuggestions, defaultSelection, looksCutOff } from '../../src/utils/cvAnalysis'
import { parseAnswerList } from '../../src/utils/answerList'

const facts = {
  skills: ['PHP', 'Jira', 'Cursor'],
  keyProjects: [
    { name: 'Acme — Billing', summary: 'Launched a billing platform used by 40 customers.' },
    { name: 'Globex — Portal', summary: 'Built the customer portal.' },
  ],
  experience: [
    { title: 'Senior PM', company: 'Acme Corp', start: 'Mar 2021', end: 'Present', bullets: ['Launched billing.'] },
    { title: 'Project Manager', company: 'Globex', start: '2016', end: '2021', bullets: ['Delivered 30 projects.'] },
  ],
  competencyGroups: [{ label: 'Product Leadership', items: ['Roadmapping'] }],
  toolGroups: [{ label: 'AI Tooling', items: ['ChatGPT', 'Cursor'] }],
  education: [
    { degree: 'B. Sc. Software Engineering', school: 'Faculty of Electronic Engineering, University of Niš', year: '2016' },
    { degree: 'MSc Product', school: 'Open University', year: '2020' },
  ],
  certifications: [{ name: 'Professional Scrum Master I', issuer: 'Scrum.org', year: '2021' }],
  draftCareerSummary: 'I lead B2B products.',
}

const profile = () => ({
  resume: {
    fileName: 'cv.pdf',
    parsedData: {
      skills: ['PHP', 'Jira'],
      workExperience: ['Senior PM — Acme Corp | Mar 2021–Present | product work'],
      education: ['.Sc. Software Engineering — Faculty of Electronic Engineering, University of Niš | 2016'],
      certifications: ['Professional Scrum Master I (PSM I) — Scrum.org | 2021'],
    },
  },
  questionnaire: { answers: [
    { id: 4, answer: 'Launched a billing platform used by 40 customers.\n' },
    { id: 17, answer: 'My own words.' },
  ] },
})

describe('buildSuggestions', () => {
  const s = buildSuggestions(profile(), facts)
  it('marks what the profile already has', () => {
    expect(s.skills.map((i) => i.status)).toEqual(['have', 'have', 'new'])
    expect(s.projects.map((i) => i.status)).toEqual(['have', 'new'])
    expect(s.experience.map((i) => [i.status, i.listed])).toEqual([['new', true], ['new', false]])
  })
  it('catches an outdated education entry and a cert that matches', () => {
    expect(s.education.map((i) => i.status)).toEqual(['differs', 'new'])
    expect(s.education[0].existing).toContain('.Sc. Software Engineering')
    expect(s.certifications[0].status).toBe('have')
  })
  it('compares the summary with the current answer and the groups with the saved ones', () => {
    expect(s.summary.status).toBe('differs')
    expect(s.competencyGroups.status).toBe('new')
  })
  it('ticks only what is new; replacements are left to the user', () => {
    const picked = defaultSelection(s)
    expect(picked.has('skill:cursor')).toBe(true)
    expect(picked.has('edu:0')).toBe(false)
    expect(picked.has('summary')).toBe(false)
    expect(picked.has('competencyGroups')).toBe(true)
  })
})

describe('applySuggestions', () => {
  it('changes nothing for an empty selection', () => {
    const p = profile()
    expect(applySuggestions(p, facts, new Set())).toEqual(p)
  })
  it('writes only the ticked items, into the fields the app already reads', () => {
    const s = buildSuggestions(profile(), facts)
    const out = applySuggestions(profile(), facts, new Set(['skill:cursor', 'edu:0', 'role:1', 'competencyGroups', 'project:' + s.projects[1].id.slice(8), 'summary']))
    const pd = out.resume.parsedData
    expect(pd.skills).toEqual(['PHP', 'Jira', 'Cursor'])
    expect(pd.education).toEqual(['B. Sc. Software Engineering — Faculty of Electronic Engineering, University of Niš | 2016'])
    expect(pd.workExperience).toHaveLength(2)
    expect(pd.experienceDetail).toEqual([facts.experience[1]])
    expect(pd.competencyGroups).toEqual(facts.competencyGroups)
    expect(pd.toolGroups).toBeUndefined()
    expect(parseAnswerList(out.questionnaire.answers[0].answer)).toEqual([
      'Launched a billing platform used by 40 customers.', 'Globex — Portal — Built the customer portal.',
    ])
    expect(out.questionnaire.answers[1].answer).toBe('I lead B2B products.')
  })
  it('adds a missing answer for question 17', () => {
    const p = { ...profile(), questionnaire: { answers: [] } }
    const out = applySuggestions(p, facts, new Set(['summary']))
    expect(out.questionnaire.answers).toEqual([expect.objectContaining({ id: 17, answer: 'I lead B2B products.' })])
  })
})

describe('applyToDefaultCv', () => {
  const withLibrary = () => ({
    ...profile(),
    defaultCvId: 'a',
    cvLibrary: [{ id: 'a', analysis: { facts, applied: [] }, parsedData: {} }],
  })

  it('applies the ticked, usable items and remembers which ones', () => {
    const result = applyToDefaultCv(withLibrary(), 'a', new Set(['skill:cursor', 'skill:php', 'edu:1']))
    expect(result.count).toBe(2)
    const analysis = result.profile.cvLibrary[0].analysis
    expect(new Set(analysis.applied)).toEqual(new Set(['skill:cursor', 'edu:1']))
    expect(analysis.lastApply).toMatchObject({ count: 2, state: 'pending' })
    expect(result.profile.resume.parsedData.skills).toContain('Cursor')
  })
  it('tells an applied item from one that was already there', () => {
    const { profile: after } = applyToDefaultCv(withLibrary(), 'a', new Set(['skill:cursor']))
    const skills = buildSuggestions(after, facts).skills
    expect(skills.map((i) => i.status)).toEqual(['have', 'have', 'have'])
    expect(new Set(after.cvLibrary[0].analysis.applied)).toEqual(new Set(['skill:cursor']))
  })
  it('does not count groups or the summary again once they are in the profile', () => {
    const first = applyToDefaultCv(withLibrary(), 'a', new Set(['competencyGroups', 'toolGroups', 'summary']))
    expect(first.count).toBe(3)
    const again = applyToDefaultCv(first.profile, 'a', new Set(['competencyGroups', 'toolGroups', 'summary']))
    expect(again.count).toBe(0)
  })
  it('does nothing for a CV that is not the default, or when nothing usable is ticked', () => {
    expect(applyToDefaultCv({ ...withLibrary(), defaultCvId: 'b' }, 'a', new Set(['skill:cursor']))).toBeNull()
    const noop = applyToDefaultCv(withLibrary(), 'a', new Set(['skill:php']))
    expect(noop.count).toBe(0)
  })
})

describe('a cut-off education entry', () => {
  it('is spotted, and its replacement stays unticked', () => {
    expect(looksCutOff('.Sc. Software Engineering — Uni | 2016')).toBe(true)
    expect(looksCutOff('B. Sc. Software Engineering')).toBe(false)
    const s = buildSuggestions(profile(), facts)
    expect(s.education[0]).toMatchObject({ status: 'differs', existingCutOff: true })
    expect(defaultSelection(s).has('edu:0')).toBe(false)
  })
})
