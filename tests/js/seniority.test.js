import { describe, it, expect } from 'vitest'
import { inferCandidateType, inferSeniorityLevel } from '../../src/modules/intelligence/candidateNarrativeBuilder.js'

const ctx = (extra = {}) => ({
  currentRole: 'Technical Product Lead',
  targetRoles: ['Product Manager'],
  experienceYears: 10,
  questionnaire: { leadershipExamples: [], ownershipExamples: [] },
  ...extra,
})
const skills = { productBusiness: ['roadmap'], frontend: ['React'], backend: ['Go'], leadership: [], database: [], aiAutomation: [] }
const ASPIRATIONAL = ['Head of Product', 'Director of Product', 'VP Product', 'CTO', 'Founder']

describe('seniority reads the current role, never the target roles', () => {
  it('does not change when aspirational titles are added to targetRoles', () => {
    const before = inferSeniorityLevel(ctx())
    const after = inferSeniorityLevel(ctx({ targetRoles: ['Product Manager', ...ASPIRATIONAL] }))
    expect(after).toBe(before)
    expect(after).not.toBe('Executive / Founder-Level')
  })

  it('still reads an executive title when it is the current role', () => {
    expect(inferSeniorityLevel(ctx({ currentRole: 'Head of Product' }))).toBe('Executive / Founder-Level')
    expect(inferSeniorityLevel(ctx({ currentRole: 'Founder & CEO' }))).toBe('Executive / Founder-Level')
  })

  it('falls back to years of experience when there is no current role', () => {
    expect(inferSeniorityLevel(ctx({ currentRole: '', targetRoles: ASPIRATIONAL, experienceYears: 4 }))).toBe('Mid-Level')
  })
})

describe('candidate type reads the current role, never the target roles', () => {
  it('does not become an operator because the targets name a Head of or CTO', () => {
    const before = inferCandidateType(ctx(), skills)
    const after = inferCandidateType(ctx({ targetRoles: ['Product Manager', ...ASPIRATIONAL] }), skills)
    expect(after).toBe(before)
    expect(after).not.toBe('Early CTO / Product-Tech Operator')
  })
})
