import { describe, expect, it } from 'vitest'
import { applySuggestions, buildSuggestions, defaultSelection } from '../../src/utils/cvAnalysis'
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
