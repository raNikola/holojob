import fs from 'node:fs'
import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QUESTIONS } from '../../src/data/questions'
import CompleteProfileCard, { shouldShowCompleteProfile } from '../../src/components/profile/CompleteProfileCard'
import { generateCandidateIntelligence } from '../../src/modules/intelligence/candidateIntelligenceEngine'
import { validateProfileForIntelligence } from '../../src/modules/intelligence/intelligenceValidators'
import { checkFinishReadiness } from '../../src/modules/profile/finishReadiness'
import { describeAnswer } from '../../src/modules/profile/answerDisplay'
import {
  HIGH_IMPACT_QUESTION_IDS, answeredQuestionIds, derivedEntry, isDerivedAnswer, orderedQuestions, unansweredQuestionIds,
} from '../../src/modules/profile/questionnaireStatus'
import { joinAnswerList } from '../../src/utils/answerList'
import { STORAGE_KEY, getDefaultProfile, loadProfile } from '../../src/utils/storage'
import { validateStep } from '../../src/utils/validators'

function profile(over = {}) {
  const base = getDefaultProfile()
  return {
    ...base,
    basicProfile: {
      ...base.basicProfile, fullName: 'Jane Sample', email: 'jane@example.com', currentRole: 'Product Manager',
      experienceYears: '8', targetRoles: ['Product Manager'],
    },
    resume: { ...base.resume, rawText: 'Product manager with eight years of experience.', parsedData: { ...base.resume.parsedData, skills: ['Roadmapping'] } },
    ...over,
  }
}
const answers = (ids, text = 'Startup') => ids.map((id) => ({ id, question: `Q${id}`, answer: text }))
// One valid answer per question, list answers stored the way the app stores them.
const validAnswer = (q) => {
  if (q.type === 'textarea') return 'I build products. I lead teams.'
  return q.type === 'single' ? q.options[0] : joinAnswerList([q.options?.[0] || 'Python'])
}
const allAnswers = () => QUESTIONS.map((q) => ({ id: q.id, question: q.text, answer: validAnswer(q) }))

afterEach(() => vi.unstubAllGlobals())

describe('optional questionnaire', () => {
  it('validates a complete profile with no answers, warning about the unanswered', () => {
    const result = validateProfileForIntelligence(profile())
    expect(result.valid).toBe(true)
    expect(result.warnings.join(' ')).toContain('17 questionnaire questions unanswered')
    expect(validateStep(4, profile()).valid).toBe(true)
  })

  it('still requires target roles and a résumé or skills', () => {
    const noRoles = profile()
    noRoles.basicProfile.targetRoles = []
    expect(validateProfileForIntelligence(noRoles).valid).toBe(false)
    const noResume = profile()
    noResume.resume = { ...noResume.resume, rawText: '', parsedData: { ...noResume.resume.parsedData, skills: [] } }
    expect(validateProfileForIntelligence(noResume).valid).toBe(false)
  })

  it('derives the unknown list and ignores empty entries', () => {
    const p = profile({ questionnaire: { answers: [...answers([1, 2]), { id: 3, question: 'Q3', answer: '  ' }] } })
    expect(answeredQuestionIds(p)).toEqual([1, 2])
    expect(unansweredQuestionIds(p)).toHaveLength(15)
    expect(unansweredQuestionIds(p)).toContain(3)
  })

  it('asks the high-impact questions first and keeps every question', () => {
    const ordered = orderedQuestions()
    expect(ordered.slice(0, HIGH_IMPACT_QUESTION_IDS.length).map((q) => q.id)).toEqual(HIGH_IMPACT_QUESTION_IDS)
    expect(ordered.map((q) => q.id).sort((a, b) => a - b)).toEqual(QUESTIONS.map((q) => q.id))
  })

  it('stores no filler text when nothing is answered, and flags the summary fields unknown', () => {
    const p = profile()
    p.basicProfile.currentRole = ''
    p.resume.parsedData.skills = []
    const intelligence = generateCandidateIntelligence(p)
    const summary = intelligence.candidateSummary
    expect(JSON.stringify(intelligence)).not.toMatch(/pending|will improve with questionnaire/i)
    expect(summary.positioningStatement).toBe('')
    expect(summary.unknown).toContain('positioningStatement')
    expect(summary.unknown).toContain('careerNarrative')
  })

  it('leaves the unknown flags empty when the questions are answered', () => {
    const p = profile({ questionnaire: { answers: allAnswers() } })
    expect(generateCandidateIntelligence(p).candidateSummary.unknown).toEqual([])
  })
})

describe('finish readiness', () => {
  it('is ready with the profile fields and a résumé, whatever is answered', () => {
    expect(checkFinishReadiness(profile())).toMatchObject({ ready: true })
  })

  it('sends the user to the profile step when a required field is missing', () => {
    const p = profile()
    p.basicProfile.email = ''
    const result = checkFinishReadiness(p)
    expect(result).toMatchObject({ ready: false, step: 2 })
    expect(Object.keys(result.fieldErrors)).toEqual(['email'])
  })

  it('sends the user to the import step when there is no résumé or skills', () => {
    const p = profile()
    p.resume = { ...p.resume, rawText: '', parsedData: { ...p.resume.parsedData, skills: [] } }
    expect(checkFinishReadiness(p)).toMatchObject({ ready: false, step: 1 })
  })

  it('is wired to a Finish button in the wizard footer', () => {
    const source = fs.readFileSync('src/components/onboarding/OnboardingWizard.jsx', 'utf8')
    expect(source).toContain('checkFinishReadiness(profile)')
    expect(source).toMatch(/onClick=\{finish\}[\s\S]*Finish/)
  })
})

describe('derived answers', () => {
  it('marks a seeded answer and shows it as not confirmed', () => {
    const entry = derivedEntry(2, 'Q2', 'SQL\n')
    expect(isDerivedAnswer(entry)).toBe(true)
    expect(isDerivedAnswer({ id: 2, question: 'Q2', answer: 'SQL\n' })).toBe(false)
    expect(describeAnswer(entry, profile()).derived).toBe(true)
    expect(describeAnswer({ id: 2, question: 'Q2', answer: 'SQL\n' }, profile()).derived).toBe(false)
  })
})

describe('complete your profile card', () => {
  const html = (p) => renderToStaticMarkup(h(CompleteProfileCard, { profile: p, onAnswer() {}, onDismiss() {} }))

  it('shows the number of questions left', () => {
    expect(html(profile({ questionnaire: { answers: answers([1, 2, 3]) } }))).toContain('Complete your profile (14 questions left)')
  })

  it('is hidden when everything is answered or after "Not now"', () => {
    expect(html(profile({ questionnaire: { answers: allAnswers() } }))).toBe('')
    const dismissed = profile()
    dismissed.meta = { ...dismissed.meta, completeProfileDismissedAt: '2026-11-01T10:00:00.000Z' }
    expect(shouldShowCompleteProfile(dismissed)).toBe(false)
  })
})

describe('existing profiles', () => {
  it('load unchanged with all 17 answers', () => {
    const stored = { ...profile({ questionnaire: { answers: allAnswers() } }) }
    stored.meta = { ...stored.meta, questionnaireVersion: '17', onboardingComplete: true }
    const store = new Map([[STORAGE_KEY, JSON.stringify(stored)]])
    vi.stubGlobal('localStorage', {
      getItem: (k) => store.get(k) ?? null,
      setItem: (k, v) => store.set(k, v),
      removeItem: (k) => store.delete(k),
    })
    const loaded = loadProfile()
    expect(loaded.questionnaire.answers).toEqual(stored.questionnaire.answers)
    expect(unansweredQuestionIds(loaded)).toEqual([])
    expect(validateProfileForIntelligence(loaded).warnings.join(' ')).not.toContain('unanswered')
  })
})
