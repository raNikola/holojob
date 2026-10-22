import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import {
  normalizeAllowedLocations,
  normalizeRelocation,
  normalizeWorkAuthorization,
} from '../../src/utils/workAuthorization.js'
import { generateCandidateIntelligence } from '../../src/modules/intelligence/candidateIntelligenceEngine.js'
import { getDefaultProfile, loadProfile, STORAGE_KEY } from '../../src/utils/storage.js'
import geography from '../../src/data/geography.json'
import sampleProfile from '../../fixtures/candidate-profile.sample.json'

describe('normalizers', () => {
  it('keep entered work rights and drop empty rows', () => {
    expect(
      normalizeWorkAuthorization({
        holds: [{ jurisdiction: 'pl', basis: 'citizen' }, { jurisdiction: '', basis: 'other' }, { jurisdiction: 'EU', basis: 'nope' }],
        openToSponsorship: true,
      }),
    ).toEqual({ holds: [{ jurisdiction: 'PL', basis: 'citizen' }, { jurisdiction: 'EU', basis: '' }], openToSponsorship: true })
  })

  it('read anything missing or malformed as nothing set, never a default place', () => {
    for (const bad of [undefined, null, 'PL', { holds: 'PL' }]) {
      expect(normalizeWorkAuthorization(bad)).toEqual({ holds: [], openToSponsorship: false })
    }
    expect(normalizeAllowedLocations(undefined)).toEqual([])
    expect(normalizeAllowedLocations(['europe', 'REMOTE', 'europe', 3])).toEqual(['EUROPE', 'REMOTE'])
    expect(normalizeRelocation('sideways')).toBe('none')
    expect(normalizeRelocation('abroad')).toBe('abroad')
  })
})

describe('geography table', () => {
  it('has unique codes and every country region is a declared region', () => {
    const codes = geography.countries.map((c) => c.code)
    expect(new Set(codes).size).toBe(codes.length)
    for (const country of geography.countries) {
      for (const region of country.regions) expect(Object.keys(geography.regions)).toContain(region)
    }
  })
})

describe('generateCandidateIntelligence', () => {
  it('copies the candidate\'s own values into jobFitPreferences', () => {
    const profile = {
      ...sampleProfile,
      basicProfile: {
        ...sampleProfile.basicProfile,
        workAuthorization: { holds: [{ jurisdiction: 'PL', basis: 'citizen' }], openToSponsorship: true },
        allowedLocations: [],
        relocation: 'abroad',
      },
    }
    const prefs = generateCandidateIntelligence(profile).jobFitPreferences
    expect(prefs.workAuthorization).toEqual({ holds: [{ jurisdiction: 'PL', basis: 'citizen' }], openToSponsorship: true })
    expect(prefs.allowedLocations).toEqual([])
    expect(prefs.relocation).toBe('abroad')
  })

  it('gives empty values, not assumptions, for a profile without them', () => {
    const prefs = generateCandidateIntelligence(sampleProfile).jobFitPreferences
    expect(prefs.workAuthorization).toEqual({ holds: [], openToSponsorship: false })
    expect(prefs.allowedLocations).toEqual([])
    expect(prefs.relocation).toBe('none')
  })
})

describe('loadProfile', () => {
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

  it('defaults to nothing set', () => {
    const bp = getDefaultProfile().basicProfile
    expect(bp.workAuthorization).toEqual({ holds: [], openToSponsorship: false })
    expect(bp.allowedLocations).toEqual([])
    expect(bp.relocation).toBe('none')
  })

  it('reads a profile saved before these fields existed as nothing set', () => {
    const { workAuthorization, allowedLocations, relocation, ...old } = getDefaultProfile().basicProfile
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...getDefaultProfile(), basicProfile: { ...old, fullName: 'Jo' } }))
    const bp = loadProfile().basicProfile
    expect(bp.workAuthorization).toEqual({ holds: [], openToSponsorship: false })
    expect(bp.allowedLocations).toEqual([])
    expect(bp.relocation).toBe('none')
    expect(bp.fullName).toBe('Jo')
    expect([workAuthorization, allowedLocations, relocation]).toBeTruthy()
  })
})
