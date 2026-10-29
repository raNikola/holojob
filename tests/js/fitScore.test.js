import { describe, expect, it } from 'vitest'
import { fitScoreStyle } from '../../src/modules/jobs/fitScore'
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
