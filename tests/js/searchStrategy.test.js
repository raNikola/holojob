import { describe, it, expect } from 'vitest'
import { generateSearchStrategy } from '../../src/modules/intelligence/searchStrategyGenerator.js'
import { normalizeProfile } from '../../src/modules/intelligence/profileNormalizer.js'

const roles = (primary, secondary = []) => ({ primaryTargetRoles: primary, secondaryTargetRoles: secondary })
const skills = { technicalSkills: ['JavaScript'], frontend: [], backend: [] }
const ctx = (extra = {}) => ({ location: 'Niš, Serbia', preferredLocations: ['Serbia'], remotePreference: 'flexible', relocation: 'none', ...extra })

describe('search terms', () => {
  it('search every target role, not just the first eight', () => {
    const targets = ['A PM', 'B PM', 'C PM', 'D PM', 'E PM', 'F PM', 'G PM', 'H PM', 'I PM', 'J PM']
    const terms = generateSearchStrategy(ctx(), roles(targets), skills).jobSpySearchTerms
    expect(terms).toEqual(expect.arrayContaining(targets))
  })

  it('include the goal titles when the profile names them', () => {
    const goal = ['Senior Product Manager', 'Group Product Manager', 'Lead Product Manager', 'Platform Product Manager', 'Head of Product']
    const terms = generateSearchStrategy(ctx(), roles(goal), skills).jobSpySearchTerms
    expect(terms).toEqual(goal)
  })
})

describe('locations', () => {
  it('add Europe and the United States when the candidate would relocate abroad', () => {
    const { locationFilters } = generateSearchStrategy(ctx({ relocation: 'abroad' }), roles(['PM']), skills)
    expect(locationFilters).toEqual(['Niš, Serbia', 'Serbia', 'Europe', 'United States'])
  })

  it('add both for anywhere too, and neither for none', () => {
    expect(generateSearchStrategy(ctx({ relocation: 'anywhere' }), roles(['PM']), skills).locationFilters).toEqual(
      expect.arrayContaining(['Europe', 'United States']),
    )
    const none = generateSearchStrategy(ctx({ relocation: 'none' }), roles(['PM']), skills).locationFilters
    expect(none).not.toContain('Europe')
    expect(none).not.toContain('United States')
  })

  it('reads relocation from the profile, and treats a missing value as none', () => {
    const profile = (relocation) => ({
      basicProfile: { fullName: 'X', targetRoles: ['PM'], preferredLocations: ['Serbia'], location: 'Niš, Serbia', ...(relocation ? { relocation } : {}) },
    })
    expect(normalizeProfile(profile('abroad')).relocation).toBe('abroad')
    expect(normalizeProfile(profile()).relocation).toBe('none')
    expect(normalizeProfile(profile('sideways')).relocation).toBe('none')
  })
})
