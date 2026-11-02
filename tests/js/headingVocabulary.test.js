import { describe, expect, it } from 'vitest'
import vocabulary from '../../src/data/sectionHeadings.json'
import { foldText, headingOf, labeledField, languageLevel, normalizePhrase } from '../../src/utils/headingVocabulary'
import { extractProfileFromResume } from '../../src/utils/profileExtractor'
import { ENGLISH, SERBIAN_CYRILLIC, SERBIAN_LATIN } from './fixtures/serbianCv'

const LATIN_TO_CYRILLIC = Object.fromEntries(Object.entries(vocabulary.transliteration.cyrillicToLatin).map(([c, l]) => [l, c]))
// Longest Latin digraphs first, so "lj" becomes љ and not л + ј.
const toCyrillic = (text) => text.replace(/dj|lj|nj|dz|./g, (m) => LATIN_TO_CYRILLIC[m] ?? m)
const spellings = (phrase) => [phrase, phrase.toUpperCase(), foldText(phrase), toCyrillic(foldText(phrase))]

describe('the heading vocabulary', () => {
  it('folds case, diacritics and Cyrillic to one form', () => {
    expect(foldText('VEŠTINE')).toBe('vestine')
    expect(foldText('ВЕШТИНЕ')).toBe('vestine')
    expect(foldText('Đorđe')).toBe('djordje')
  })

  it('recognises every section phrase in the file in four spellings', () => {
    for (const lang of Object.values(vocabulary.languages)) {
      for (const [key, phrases] of Object.entries(lang.sections)) {
        for (const phrase of phrases) {
          for (const spelling of spellings(phrase)) {
            expect(headingOf(spelling)?.key, `${key}: ${spelling}`).toBe(key)
            expect(headingOf(`${spelling}:`)?.key, `${key}: ${spelling}:`).toBe(key)
          }
        }
      }
      for (const phrase of lang.unplacedSections) {
        for (const spelling of spellings(phrase)) expect(headingOf(spelling)?.key, spelling).toBe('unplaced')
      }
    }
  })

  it('maps the Serbian headings to the sections the owner named', () => {
    const key = (line) => headingOf(line)?.key
    expect(key('OBRAZOVANJE')).toBe('education')
    expect(key('RADNO ISKUSTVO')).toBe('experience')
    expect(key('Dodatna znanja i veštine')).toBe('skills')
    expect(key('STRUČNO USAVRŠAVANJE (izbor):')).toBe('certifications')
    expect(key('Poznavanje jezika')).toBe('languages')
    expect(key('LIČNI PODACI')).toBe('personal')
    expect(key('Projekti')).toBe('projects')
    expect(key('Linkovi')).toBe('links')
    expect(key('Education & Training')).toBe('education')
  })

  it('does not read ordinary lines as headings', () => {
    expect(headingOf('Led the experience team across three markets, shipping weekly')).toBeNull()
    expect(headingOf('Stručni saradnik-pedagog, OŠ "Prvi maj", Trupale, 2026')).toBeNull()
    expect(headingOf('')).toBeNull()
  })

  it('reads labelled fields in both languages', () => {
    expect(labeledField('Ime i prezime: Marija Testić')).toEqual({ field: 'fullName', value: 'Marija Testić' })
    expect(labeledField('Име и презиме: Марија')).toEqual({ field: 'fullName', value: 'Марија' })
    expect(labeledField('Broj telefona: 064 123 4567').field).toBe('phone')
    expect(labeledField('Adresa: Ulica 1').field).toBe('address')
    expect(labeledField('Phone: 1').field).toBe('phone')
    expect(labeledField('Random note: x')).toBeNull()
  })

  it('maps language levels and treats "i", "&" and "and" alike', () => {
    expect(languageLevel('srednji')).toBe('intermediate')
    expect(languageLevel('početni')).toBe('basic')
    expect(normalizePhrase('Znanja & veštine')).toBe(normalizePhrase('Znanja i veštine'))
  })
})

describe('extractProfileFromResume on a CV with Serbian headings', () => {
  const result = extractProfileFromResume(SERBIAN_LATIN)

  it('takes the name from the labelled line, not the section title', () => {
    expect(result.basicProfile.fullName).toBe('Marija Testić')
  })

  it('reads the labelled phone, e-mail and address', () => {
    expect(result.basicProfile.phone).toBe('064 123 4567')
    expect(result.basicProfile.email).toBe('marija.testic@example.invalid')
    expect(result.basicProfile.location).toBe('Ulica Primer 1, Niš')
  })

  it('places the sections', () => {
    expect(result.parsedData.education).toHaveLength(2)
    expect(result.parsedData.workExperience).toHaveLength(2)
    expect(result.parsedData.certifications).toEqual(['Tehnike terapije igrom, 2025', 'Agile Scrum Practitioner, 2019'])
  })

  it('keeps skills and hobby lines out of the section before them', () => {
    const everything = JSON.stringify(result.parsedData)
    expect(everything).not.toContain('Planinarenje')
    expect(everything).not.toContain('MS Office')
  })

  it('reads the same CV in Cyrillic', () => {
    const cyr = extractProfileFromResume(SERBIAN_CYRILLIC)
    expect(cyr.basicProfile.fullName).toBe('Марија Тестић')
    expect(cyr.parsedData.education).toHaveLength(1)
    expect(cyr.parsedData.workExperience).toHaveLength(1)
  })
})

describe('extractProfileFromResume on an English CV', () => {
  const result = extractProfileFromResume(ENGLISH)
  it('still reads the name and the sections', () => {
    expect(result.basicProfile.fullName).toBe('Jane Sample')
    expect(result.parsedData.workExperience).toEqual(['Product Manager, Acme, 2020 - 2024'])
    expect(result.parsedData.education).toEqual(['BSc Computer Science, Example University, 2015'])
  })
  it('no longer files the skills line under experience', () => {
    expect(result.parsedData.workExperience.join(' ')).not.toContain('Agile')
  })
})
