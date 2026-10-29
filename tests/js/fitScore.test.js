import { describe, expect, it } from 'vitest'
import { fitScoreStyle, scoreRowChips } from '../../src/modules/jobs/fitScore'
import { MATCH_LABELS, MATCH_LABEL_VARIANT } from '../../src/modules/jobs/matchScore'

describe('fitScoreStyle', () => {
  it('uses the existing label-to-variant map for every band', () => {
    for (const label of MATCH_LABELS) {
      expect(fitScoreStyle(label).variant).toBe(MATCH_LABEL_VARIANT[label])
    }
  })

  it('gives each band a score colour', () => {
    for (const label of MATCH_LABELS) {
      expect(fitScoreStyle(label).scoreClass).toMatch(/^text-/)
    }
    expect(fitScoreStyle('Excellent').scoreClass).toContain('emerald')
    expect(fitScoreStyle('Good').scoreClass).toContain('amber')
  })

  it('falls back to the neutral style for a missing or unknown label', () => {
    expect(fitScoreStyle('').variant).toBe('default')
    expect(fitScoreStyle(undefined).variant).toBe('default')
    expect(fitScoreStyle('Nonsense').variant).toBe('default')
  })
})

describe('scoreRowChips', () => {
  it('lists priority then apply recommendation, with the badge variants unchanged', () => {
    const chips = scoreRowChips({ priority: 'P2', applyRecommendation: 'Maybe' })
    expect(chips.map((c) => c.text)).toEqual(['P2', 'Maybe'])
    expect(chips.map((c) => c.kind)).toEqual(['priority', 'apply'])
  })
  it('leaves out a Reject priority and missing values', () => {
    expect(scoreRowChips({ priority: 'Reject' })).toEqual([])
    expect(scoreRowChips({})).toEqual([])
    expect(scoreRowChips(null)).toEqual([])
    expect(scoreRowChips({ applyRecommendation: 'Apply' }).map((c) => c.text)).toEqual(['Apply'])
  })
})
