import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import {
  LANGUAGE_PROFICIENCIES,
  formatLanguages,
  normalizeLanguages,
} from '../../src/utils/languages.js'
import { generateCandidateIntelligence } from '../../src/modules/intelligence/candidateIntelligenceEngine.js'
import { getDefaultProfile, loadProfile, STORAGE_KEY } from '../../src/utils/storage.js'
import sampleProfile from '../../fixtures/candidate-profile.sample.json'

const LANGS = [
  { language: 'Serbian', proficiency: 'native' },
  { language: 'English', proficiency: 'fluent' },
]

describe('normalizeLanguages', () => {
  it('reads a missing or malformed value as an empty list', () => {
    for (const bad of [undefined, null, 'Serbian', 5, {}, [null, 'x', 3]]) {
      expect(normalizeLanguages(bad)).toEqual([])
    }
  })

  it('trims names, drops blank rows and leaves an unknown level unstated', () => {
    expect(
      normalizeLanguages([
        { language: ' Serbian ', proficiency: 'native' },
        { language: 'German', proficiency: 'good-ish' },
        { language: '', proficiency: 'fluent' },
      ]),
    ).toEqual([
      { language: 'Serbian', proficiency: 'native' },
      { language: 'German', proficiency: '' },
    ])
  })

  it('offers the fixed proficiency set', () => {
    expect(LANGUAGE_PROFICIENCIES).toEqual(['native', 'fluent', 'advanced', 'intermediate', 'basic'])
  })
})

describe('formatLanguages', () => {
  it('derives the strings the fit judge reads', () => {
    expect(formatLanguages(LANGS)).toEqual(['Serbian (native)', 'English (fluent)'])
  })

  it('gives just the name when no proficiency is stated', () => {
    expect(formatLanguages([{ language: 'German', proficiency: '' }])).toEqual(['German'])
  })
})

describe('generateCandidateIntelligence', () => {
  const withLanguages = (languages) => ({
    ...sampleProfile,
    basicProfile: { ...sampleProfile.basicProfile, languages },
  })

  it('derives the languages list from the profile', () => {
    const intelligence = generateCandidateIntelligence(withLanguages(LANGS))
    expect(intelligence.languages).toEqual(['Serbian (native)', 'English (fluent)'])
  })

  it('emits an empty list, not a missing key, when the profile has none', () => {
    expect(generateCandidateIntelligence(sampleProfile).languages).toEqual([])
    expect(generateCandidateIntelligence(withLanguages('Serbian')).languages).toEqual([])
  })
})

describe('loadProfile', () => {
  const realLocalStorage = globalThis.localStorage

  beforeEach(() => {
    const store = new Map()
    globalThis.localStorage = {
      getItem: (key) => (store.has(key) ? store.get(key) : null),
      setItem: (key, value) => store.set(key, String(value)),
      removeItem: (key) => store.delete(key),
    }
  })

  afterEach(() => {
    globalThis.localStorage = realLocalStorage
  })

  const store = (profile) => localStorage.setItem(STORAGE_KEY, JSON.stringify(profile))

  it('defaults to an empty languages list', () => {
    expect(getDefaultProfile().basicProfile.languages).toEqual([])
    expect(loadProfile().basicProfile.languages).toEqual([])
  })

  it('treats a profile saved before the field existed as having none, keeping its other fields', () => {
    const { languages, ...oldBasic } = getDefaultProfile().basicProfile
    store({ ...getDefaultProfile(), basicProfile: { ...oldBasic, fullName: 'Test Person' } })
    const loaded = loadProfile()
    expect(languages).toEqual([])
    expect(loaded.basicProfile.languages).toEqual([])
    expect(loaded.basicProfile.fullName).toBe('Test Person')
  })

  it('does not break on a malformed stored value', () => {
    store({ ...getDefaultProfile(), basicProfile: { ...getDefaultProfile().basicProfile, languages: 'Serbian' } })
    expect(loadProfile().basicProfile.languages).toEqual([])
  })

  it('keeps stored languages', () => {
    store({ ...getDefaultProfile(), basicProfile: { ...getDefaultProfile().basicProfile, languages: LANGS } })
    expect(loadProfile().basicProfile.languages).toEqual(LANGS)
  })
})
