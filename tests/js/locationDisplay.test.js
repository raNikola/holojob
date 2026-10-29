import { describe, it, expect } from 'vitest'
import { displayLocation } from '../../src/modules/jobs/locationDisplay.js'

describe('displayLocation', () => {
  it('shows a repeated segment once', () => {
    expect(displayLocation('Remote - Europe, Remote - Europe')).toBe('Remote - Europe')
    expect(displayLocation('Palo Alto, California, United States, Palo Alto')).toBe('Palo Alto, California, United States')
  })

  it('treats semicolons as separators', () => {
    expect(displayLocation('Berlin; Germany; Berlin')).toBe('Berlin, Germany')
  })

  it('keeps the " - " joiner and only drops repeats inside a segment', () => {
    expect(displayLocation('Remote - Europe')).toBe('Remote - Europe')
    expect(displayLocation('Remote - Remote')).toBe('Remote')
    expect(displayLocation('Remote - Europe, Remote - Asia')).toBe('Remote - Europe, Remote - Asia')
  })

  it('ignores case and spacing when comparing, keeps the first spelling', () => {
    expect(displayLocation('Niš,  niš , NIŠ')).toBe('Niš')
    expect(displayLocation('Remote -  Europe, remote - europe')).toBe('Remote - Europe')
  })

  it('returns an empty string for empty or missing values', () => {
    expect(displayLocation('')).toBe('')
    expect(displayLocation('  ,; ')).toBe('')
    expect(displayLocation(null)).toBe('')
    expect(displayLocation(undefined)).toBe('')
    expect(displayLocation(42)).toBe('')
  })
})
