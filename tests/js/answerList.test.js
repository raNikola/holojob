import { describe, expect, it } from 'vitest'
import { joinAnswerList, parseAnswerList, repairCommaAnswer } from '../../src/utils/answerList'
import { repairProjectsAnswer } from '../../src/utils/storage'
import { normalizeProfile } from '../../src/modules/intelligence/profileNormalizer'

const RUTE = 'RUTE INC — TMS: Led strategy, MVP definition, roadmap, and launch.'
const BC = 'Better Collective — Platform: reached approximately 3,000 WordPress websites.'

describe('answer lists', () => {
  it('keeps a sentence with commas as one entry through a round trip', () => {
    const stored = joinAnswerList([RUTE, 'Cost optimization'])
    expect(parseAnswerList(stored)).toEqual([RUTE, 'Cost optimization'])
  })
  it('reads an old comma answer and drops repeats', () => {
    expect(parseAnswerList('Python, SQL, python')).toEqual(['Python', 'SQL'])
  })
  it('selecting the same sentence twice cannot add a second copy', () => {
    let answer = joinAnswerList([RUTE])
    for (let i = 0; i < 5; i += 1) {
      const selected = parseAnswerList(answer)
      answer = joinAnswerList(selected.includes(RUTE) ? selected : [...selected, RUTE])
    }
    expect(parseAnswerList(answer)).toEqual([RUTE])
  })
  it('repairs a comma answer holding a repeated sentence', () => {
    const corrupt = [RUTE, 'Cost optimization', RUTE, BC, RUTE, BC].join(', ')
    expect(repairCommaAnswer(corrupt, [RUTE, BC])).toEqual([RUTE, 'Cost optimization', BC])
  })
})

describe('split numbers', () => {
  it('drops the tail a thousands comma left behind', () => {
    const cut = [BC, 'Cost optimization', '000 WordPress websites.'].join(', ')
    expect(repairCommaAnswer(cut, [BC])).toEqual([BC, 'Cost optimization'])
  })
})

describe('repairProjectsAnswer', () => {
  const profile = (answer) => ({
    resume: { parsedData: { projects: [RUTE, BC] } },
    questionnaire: { answers: [{ id: 4, answer }, { id: 2, answer: 'Python, SQL' }] },
  })
  it('rewrites question 4 only, once', () => {
    const fixed = repairProjectsAnswer(profile([RUTE, RUTE, BC, 'Legacy modernization'].join(', ')))
    expect(fixed.questionnaire.answers[0].answer).toBe([RUTE, BC, 'Legacy modernization'].map((e) => `${e}\n`).join(''))
    expect(fixed.questionnaire.answers[1].answer).toBe('Python, SQL')
    expect(repairProjectsAnswer(fixed)).toBe(fixed)
  })
  it('lets the project sentences reach the normalized profile', () => {
    const fixed = repairProjectsAnswer(profile([RUTE, RUTE].join(', ')))
    expect(normalizeProfile(fixed).questionnaire.projectHighlights).toEqual([RUTE])
  })
})
