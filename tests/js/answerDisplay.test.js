import { describe, expect, it } from 'vitest'
import { describeAnswer, splitListAnswer } from '../../src/modules/profile/answerDisplay'

const SENTENCE = 'RUTE INC — TMS: Led product strategy, MVP definition, roadmap, and launch.'

describe('splitListAnswer', () => {
  it('keeps a known sentence whole and drops repeats', () => {
    const stored = [SENTENCE, SENTENCE, 'Cost optimization', 'Cost optimization'].join(', ')
    expect(splitListAnswer(stored, [SENTENCE])).toEqual([SENTENCE, 'Cost optimization'])
  })
  it('splits plain tags', () => {
    expect(splitListAnswer('Python, SQL, python', [])).toEqual(['Python', 'SQL'])
  })
  it('is empty for no answer', () => {
    expect(splitListAnswer('', [])).toEqual([])
  })
})

describe('describeAnswer', () => {
  it('draws skills as chips, projects as bullets, the summary as prose', () => {
    const profile = { resume: { parsedData: { projects: [SENTENCE] } } }
    expect(describeAnswer({ id: 2, answer: 'Python, SQL' }, profile).kind).toBe('chips')
    expect(describeAnswer({ id: 4, answer: SENTENCE }, profile).kind).toBe('bullets')
    expect(describeAnswer({ id: 17, answer: 'I build things.' }, profile).kind).toBe('prose')
    expect(describeAnswer({ id: 1, answer: 'Startup' }, profile).kind).toBe('text')
  })
  it('skips an empty answer', () => {
    expect(describeAnswer({ id: 2, answer: '  ' }, {})).toBeNull()
  })
})
