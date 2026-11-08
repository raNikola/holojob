import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { isKeywordShaped } from '../../src/modules/intelligence/keywordShape.js'
import { cleanKeywordBank, extractMeaningfulPhrases } from '../../src/modules/intelligence/keywordCleaner.js'
import { generateAtsKeywords } from '../../src/modules/intelligence/atsKeywordGenerator.js'

const cases = JSON.parse(fs.readFileSync(path.resolve('tests/fixtures/keyword-shape.json'), 'utf-8'))
const PROSE = 'Led a team of twelve engineers and shipped the new billing platform across three markets in under a year'

describe('keyword shape (shared fixture with python/job_scoring/keyword_shape.py)', () => {
  it.each(cases.accept)('accepts %s', (value) => expect(isKeywordShaped(value)).toBe(true))
  it.each(cases.reject)('rejects %j', (value) => expect(isKeywordShaped(value)).toBe(false))
  it('rejects non-strings', () => {
    expect(isKeywordShaped(null)).toBe(false)
    expect(isKeywordShaped(7)).toBe(false)
  })
})

describe('the bank holds keywords, not CV prose', () => {
  it('cleanKeywordBank drops multi-word prose that used to pass as a phrase', () => {
    expect(cleanKeywordBank(['Stakeholder management', PROSE, `Senior PM at Acme. ${PROSE}`])).toEqual(['Stakeholder management'])
  })

  it('extractMeaningfulPhrases takes the role from "Role at Company" and skips prose', () => {
    const entries = [`Senior Product Manager at Acme. ${PROSE}`, `Program Manager at Example Corp`, PROSE, 'Product Operations']
    expect(extractMeaningfulPhrases(entries)).toEqual(['Senior Product Manager', 'Program Manager', 'Product Operations'])
  })

  it('no generated bank bucket holds a sentence', () => {
    const ctx = {
      targetRoles: ['Product Manager'],
      currentRole: 'Senior Product Manager',
      parsedData: {
        workExperience: [`Senior Product Manager at Acme. ${PROSE}`, PROSE],
        projects: [PROSE],
        certifications: ['PMP', PROSE],
        education: ['BSc in Computer Science, University of Example, 2010-2014, graduated with honours'],
      },
      questionnaire: { preferredIndustries: [] },
    }
    const skills = { technicalSkills: ['SQL'], productBusiness: ['Roadmapping'], softSkills: [] }
    const { atsKeywordBank, resumeKeywords } = generateAtsKeywords(ctx, { secondaryTargetRoles: [] }, skills)
    for (const value of [...Object.values(atsKeywordBank).flat(), ...resumeKeywords]) {
      expect(isKeywordShaped(value)).toBe(true)
    }
    expect(atsKeywordBank.mediumPriority).toContain('Senior Product Manager')
  })
})
