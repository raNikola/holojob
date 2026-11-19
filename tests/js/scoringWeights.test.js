import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import fs from 'node:fs'
import defaults from '../../src/data/scoringWeights.json'
import {
  DEFAULT_SCORING_WEIGHTS,
  generateCandidateIntelligence,
  resolveScoringWeights,
} from '../../src/modules/intelligence/candidateIntelligenceEngine.js'
import { loadIntelligence, regenerateIntelligence, saveIntelligence } from '../../src/modules/intelligence/intelligenceExport.js'
import sampleProfile from '../../fixtures/candidate-profile.sample.json'

const CUSTOM = { roleMatch: 30, skillMatch: 20, locationMatch: 25, experienceMatch: 10, industryMatch: 10, cultureMatch: 5 }

describe('the one set of default weights', () => {
  it('is the documented 25/25/20/15/10/5', () => {
    expect(defaults).toEqual({ roleMatch: 25, skillMatch: 25, locationMatch: 20, experienceMatch: 15, industryMatch: 10, cultureMatch: 5 })
    expect(DEFAULT_SCORING_WEIGHTS).toEqual(defaults)
  })

  it('is what the example and sample intelligence files carry', () => {
    for (const file of ['data/examples/candidate-intelligence.example.json', 'fixtures/candidate-intelligence.json']) {
      expect(JSON.parse(fs.readFileSync(file, 'utf8')).scoringWeights, file).toEqual(defaults)
    }
  })
})

describe('resolveScoringWeights', () => {
  it('gives the defaults when nothing is saved', () => {
    expect(resolveScoringWeights(undefined)).toEqual(defaults)
    expect(resolveScoringWeights(null)).toEqual(defaults)
  })

  it('keeps saved values as they are and fills missing or malformed keys from the defaults', () => {
    expect(resolveScoringWeights({ roleMatch: 40, skillMatch: 'lots', locationMatch: -5, bogus: 99 })).toEqual({
      ...defaults,
      roleMatch: 40,
    })
  })
})

describe('regenerating intelligence keeps the saved weights', () => {
  const real = globalThis.localStorage
  beforeEach(() => {
    const store = new Map()
    globalThis.localStorage = {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    }
  })
  afterEach(() => { globalThis.localStorage = real })

  it('survives a second regeneration with custom weights saved in between', () => {
    const first = regenerateIntelligence(sampleProfile)
    expect(first.scoringWeights).toEqual(defaults)
    saveIntelligence(first)

    // What the Settings panel does: save the intelligence with new weights.
    saveIntelligence({ ...loadIntelligence(), scoringWeights: CUSTOM })

    const second = regenerateIntelligence(sampleProfile)
    expect(second.scoringWeights).toEqual(CUSTOM)

    saveIntelligence(second)
    expect(regenerateIntelligence(sampleProfile).scoringWeights).toEqual(CUSTOM)
  })

  it('falls back to the defaults on a first-ever generation', () => {
    expect(loadIntelligence()).toBeNull()
    expect(regenerateIntelligence(sampleProfile).scoringWeights).toEqual(defaults)
  })

  it('does not change anything else about the intelligence', () => {
    const plain = generateCandidateIntelligence(sampleProfile)
    saveIntelligence({ ...plain, scoringWeights: CUSTOM })
    const again = regenerateIntelligence(sampleProfile)
    expect({ ...again, scoringWeights: undefined, meta: undefined }).toEqual({ ...plain, scoringWeights: undefined, meta: undefined })
  })
})
