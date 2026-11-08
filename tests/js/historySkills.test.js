import { describe, expect, it } from 'vitest'
import { deriveHistorySkills, vocabularyCategory } from '../../src/modules/intelligence/historySkills.js'
import { generateCandidateIntelligence } from '../../src/modules/intelligence/candidateIntelligenceEngine.js'
import { isKeywordShaped } from '../../src/modules/intelligence/keywordShape.js'

// A made-up profile: the current role is a headline only; the skills live in older roles and in a second CV.
function profile() {
  return {
    basicProfile: { fullName: 'Test Person', email: 't@example.com', targetRoles: ['Product Manager'], currentRole: 'Product Manager', experienceYears: '10' },
    questionnaire: { answers: [] },
    resume: {
      rawText: 'text',
      parsedData: {
        skills: ['Roadmapping', 'SQL', 'Vendor Management'],
        projects: [], education: [], certifications: [], links: [], summary: '',
        workExperience: [],
        experienceDetail: [
          { title: 'Product Manager', company: 'Alpha', start: '2022', end: 'now', bullets: ['Owned the roadmap and stakeholder management for a payments product'] },
          { title: 'Program Manager', company: 'Beta', start: '2018', end: '2022', bullets: ['Ran vendor management and risk management for a multi-year program', 'Stakeholder management with regulators'] },
          { title: 'Delivery Lead', company: 'Gamma', start: '2014', end: '2018', bullets: ['Release management with Scrum and Jira'] },
        ],
        competencyGroups: [{ label: 'Core', items: ['Negotiation'] }],
      },
    },
    cvLibrary: [{ id: 'a', parsedData: { skills: ['Kanban'], experienceDetail: [{ title: 'Analyst', bullets: ['Budgeting and process improvement'] }] } }],
  }
}

describe('historySkills', () => {
  const skills = deriveHistorySkills({ profile: profile() })
  const byTerm = Object.fromEntries(skills.map((s) => [s.term, s]))

  it('reads every history entry of every CV, not only the current role', () => {
    expect(byTerm['Stakeholder Management'].entries).toBe(2)
    expect(byTerm['Vendor Management'].entries).toBe(1)
    expect(byTerm['Release Management'].entries).toBe(1)
    expect(byTerm.Budgeting.entries).toBe(1)
  })

  it('keeps skills a CV only lists, with no entry behind them, as listed', () => {
    expect(byTerm.Negotiation).toEqual({ term: 'Negotiation', entries: 0, listed: true })
    expect(byTerm.Kanban.listed).toBe(true)
  })

  it('counts a duplicated entry (the default CV is copied into cvLibrary) once', () => {
    const p = profile()
    p.cvLibrary.push({ id: 'copy', parsedData: p.resume.parsedData })
    expect(deriveHistorySkills({ profile: p }).find((s) => s.term === 'Stakeholder Management').entries).toBe(2)
  })

  it('returns short terms only, most evidenced first', () => {
    expect(skills.every((s) => isKeywordShaped(s.term))).toBe(true)
    expect(skills[0].entries).toBeGreaterThanOrEqual(skills[skills.length - 1].entries)
  })

  it('empty profile gives nothing', () => {
    expect(deriveHistorySkills({ profile: {} })).toEqual([])
  })

  it('knows the category of a vocabulary term', () => {
    expect(vocabularyCategory('Vendor Management')).toBe('delivery')
    expect(vocabularyCategory('Roadmapping')).toBe('productBusiness')
    expect(vocabularyCategory('Python')).toBeNull()
  })
})

describe('intelligence built from the whole history', () => {
  const intelligence = generateCandidateIntelligence(profile(), { validateMapping: false, qualityChecks: false })
  const bank = intelligence.atsKeywordBank

  it('carries the history skills', () => {
    expect(intelligence.historySkills.length).toBeGreaterThan(0)
  })

  it('puts skills proven by two entries in the high bucket, one entry in medium, list-only in supporting', () => {
    expect(bank.highPriority).toContain('Stakeholder Management')
    expect(bank.mediumPriority).toContain('Vendor Management')
    expect(bank.supportingKeywords).toContain('Negotiation')
  })

  it('routes non-technical history skills into the skills map instead of dropping them', () => {
    expect(intelligence.skillsMap.productBusiness).toEqual(expect.arrayContaining(['Stakeholder Management', 'Vendor Management']))
    expect(intelligence.skillsMap.leadership).toContain('Negotiation')
  })

  it('every bank entry is a keyword', () => {
    for (const value of Object.values(bank).flat()) expect(isKeywordShaped(value)).toBe(true)
  })
})
