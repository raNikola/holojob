import { beforeEach, describe, expect, it } from 'vitest'
import { mergeCachedTexts, rememberTexts, resetJobTexts } from '../../src/modules/jobs/jobTexts.js'

beforeEach(resetJobTexts)

describe('the text cache', () => {
  it('puts a text back into a row stored without one, and only into that row', () => {
    rememberTexts([{ jobId: 'a', description: 'A TEXT' }, { jobId: 'b', description: 'B TEXT' }])
    const merged = mergeCachedTexts([{ jobId: 'a' }, { jobId: 'b', description: 'OWN' }, { jobId: 'c' }])
    expect(merged.map((j) => j.description)).toEqual(['A TEXT', 'OWN', undefined])
  })
  it('never writes into a hand-entered job, which keeps its own text even when that is empty', () => {
    rememberTexts([{ jobId: 'm', description: 'SERVER TEXT' }])
    expect(mergeCachedTexts([{ jobId: 'm', manualEntry: true, description: '' }])[0].description).toBe('')
  })
})
