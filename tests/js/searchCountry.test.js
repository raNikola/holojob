import { describe, it, expect } from 'vitest'
import { searchCountry } from '../../src/utils/searchCountry.js'
import { extractProfileFromResume } from '../../src/utils/profileExtractor.js'

describe('searchCountry', () => {
  it('prefers the intelligence file, then the end of the profile location', () => {
    const profile = { basicProfile: { location: 'Kraków, Poland' } }
    expect(searchCountry(profile, { searchStrategy: { country: 'Germany' } })).toBe('Germany')
    expect(searchCountry(profile, { jobFitPreferences: { country: 'Austria' } })).toBe('Austria')
    expect(searchCountry(profile, {})).toBe('Poland')
    expect(searchCountry({ basicProfile: { location: 'Kraków, Poland, EU' } }, null)).toBe('EU')
  })

  it('is empty, never a default, when nothing says', () => {
    expect(searchCountry(null, null)).toBe('')
    expect(searchCountry({ basicProfile: {} }, {})).toBe('')
    expect(searchCountry({ basicProfile: { location: 'Kraków' } }, {})).toBe('')
  })
})

describe('extractProfileFromResume location', () => {
  const location = (text) => extractProfileFromResume(text).basicProfile.location

  it('reads "City, Country" from the header, with any letters', () => {
    expect(location('JANE ROE PRODUCT LEADER DETAILS Kraków, Poland +48 22 000 0000 | a@b.co')).toBe('Kraków, Poland')
    expect(location('Jo Doe\nSão Paulo, Brazil\njo@example.com')).toBe('São Paulo, Brazil')
    expect(location('Jo Doe | Berlin, Germany | jo@example.com')).toBe('Berlin, Germany')
  })

  it('does not take a job title and company further down for a place', () => {
    const filler = 'Product leader with a long record of shipping platforms. '.repeat(14)
    expect(location(`Jo Doe jo@example.com ${filler} Product Lead, Acme | Remote`)).toBe('')
  })

  it('does not name a city it was not given', () => {
    expect(location('Jo Doe jo@example.com')).toBe('')
  })
})

describe('countryOfLocation and the intelligence generator', () => {
  it('takes the last part of a location', async () => {
    const { countryOfLocation } = await import('../../src/utils/searchCountry.js')
    expect(countryOfLocation('Kraków, Poland')).toBe('Poland')
    expect(countryOfLocation('Kraków')).toBe('')
    expect(countryOfLocation('')).toBe('')
    expect(countryOfLocation(undefined)).toBe('')
  })

  it('records the candidate\'s country in jobFitPreferences', async () => {
    const { generateCandidateIntelligence } = await import('../../src/modules/intelligence/candidateIntelligenceEngine.js')
    const { default: sample } = await import('../../fixtures/candidate-profile.sample.json')
    const profile = { ...sample, basicProfile: { ...sample.basicProfile, location: 'Kraków, Poland' } }
    expect(generateCandidateIntelligence(profile).jobFitPreferences.country).toBe('Poland')
    const noCountry = { ...sample, basicProfile: { ...sample.basicProfile, location: 'Kraków' } }
    expect(generateCandidateIntelligence(noCountry).jobFitPreferences.country).toBe('')
  })
})
