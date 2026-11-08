import { describe, expect, it } from 'vitest'
import { fitScoreOf, formatMatchScore, hasMatchScores, isInsufficientData } from '../../src/modules/jobs/matchScore.js'
import { scoreRowChips } from '../../src/modules/jobs/fitScore.js'
import { filterJobs } from '../../src/modules/jobs/jobFilters.js'
import { computeJobStats } from '../../src/modules/jobs/jobStats.js'
import { sortRows } from '../../src/modules/tableSort.js'

const insufficient = { jobId: 'i', matchScore: 5, matchLabel: 'Insufficient data', priority: 'Unrated', applyRecommendation: 'Not assessed', dataStatus: 'insufficient' }
const weak = { jobId: 'w', matchScore: 42, matchLabel: 'Weak', priority: 'P3', applyRecommendation: 'Maybe' }

describe('Insufficient data is a state, not a score of 5', () => {
  it('has no Fit Score', () => {
    expect(isInsufficientData(insufficient)).toBe(true)
    expect(fitScoreOf(insufficient)).toBeNull()
    expect(formatMatchScore(insufficient)).toBeNull()
    expect(fitScoreOf(weak)).toBe(42)
    expect(hasMatchScores([insufficient])).toBe(true)
  })

  it('shows no priority or apply chip', () => {
    expect(scoreRowChips(insufficient)).toEqual([])
  })

  it('is not treated as 5 by the minimum-score filter or the sort', () => {
    const rows = [insufficient, weak]
    const base = { searchText: '' }
    const atLeast = (min) => filterJobs(rows, { ...base, minScore: min }).map((j) => j.jobId)
    expect(atLeast('1')).toEqual(['w'])
    expect(sortRows(rows, { key: 'score', dir: 'asc' }, { score: { type: 'number', value: fitScoreOf } }).map((j) => j.jobId)).toEqual(['w', 'i'])
    expect(sortRows(rows, { key: 'score', dir: 'desc' }, { score: { type: 'number', value: fitScoreOf } }).map((j) => j.jobId)).toEqual(['w', 'i'])
  })

  it('stays out of the average', () => {
    expect(computeJobStats([insufficient, weak]).avgScore).toBe(42)
  })
})
