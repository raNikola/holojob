import { describe, expect, it } from 'vitest'
import { decodeEntities, fixHyphenSpacing, pagesToText } from '../../src/utils/pdfTextLayout'
import { extractProfileFromResume } from '../../src/utils/profileExtractor'

const H = 10
const CHAR = 5

// Fake pdf.js text items. A line is a list of [x, str] pieces; width is derived.
function line(y, pieces) {
  return pieces.map(([x, str]) => ({ str, width: str.length * CHAR, height: H, transform: [H, 0, 0, H, x, y] }))
}

const fixture = [
  ...line(780, [[50, 'Jane Example']]),
  ...line(765, [[50, 'Senior Product Manager']]),
  ...line(750, [[50, 'jane@example.com'], [150, ' | '], [165, '+00 000 000 000']]),
  ...line(715, [[50, 'PROFESSIONAL SUMMARY']]),
  ...line(700, [[50, 'Product leader building large -scale platforms and AI- assisted tools.']]),
  ...line(665, [[50, 'WORK EXPERIENCE']]),
  ...line(650, [[50, 'Senior Product Manager, Acme Corp'], [300, '2020 - Present']]),
  ...line(638, [[50, '•'], [60, 'Led revenue- critical roadmap for payments & billing']]),
  ...line(626, [[50, '•'], [60, 'Helped co'], [104, 'nfigure the rollout with &amp; for partners']]),
  ...line(591, [[50, 'SKILLS']]),
  ...line(576, [[50, 'Roadmapping'], [105, ', '], [115, 'Analytics'], [160, ', '], [170, 'SQL']]),
  ...line(541, [[50, 'EDUCATION']]),
  ...line(526, [[50, 'BSc Computer Science, Example University']]),
]
// pdf.js does not promise any item order
const shuffled = [...fixture].reverse()

describe('pageItemsToText', () => {
  const text = pagesToText([shuffled])
  const lines = text.split('\n')

  it('keeps one entry per line, top to bottom', () => {
    expect(lines[0]).toBe('Jane Example')
    expect(lines[1]).toBe('Senior Product Manager')
    expect(lines).toContain('PROFESSIONAL SUMMARY')
    expect(lines).toContain('WORK EXPERIENCE')
    expect(lines).toContain('SKILLS')
    expect(lines).toContain('EDUCATION')
    expect(lines.indexOf('SKILLS')).toBeGreaterThan(lines.indexOf('WORK EXPERIENCE'))
  })

  it('joins pieces on a line only across a real gap', () => {
    expect(lines).toContain('Senior Product Manager, Acme Corp 2020 - Present')
    expect(text).toContain('Helped configure the rollout')
  })

  it('keeps bullets at the line start and separates blocks with a blank line', () => {
    expect(lines.filter((l) => l.startsWith('• '))).toHaveLength(2)
    expect(lines[lines.indexOf('PROFESSIONAL SUMMARY') - 1]).toBe('')
  })

  it('repairs wrap hyphen artifacts and leaves dashes alone', () => {
    expect(text).toContain('large-scale')
    expect(text).toContain('AI-assisted')
    expect(text).toContain('revenue-critical')
    expect(text).toContain('2020 - Present')
  })

  it('decodes entities exactly once', () => {
    expect(text).toContain('with & for partners')
    expect(text).not.toContain('&amp;')
    expect(decodeEntities('&amp;lt;')).toBe('&lt;')
  })

  it('keeps every word of the fixture', () => {
    const words = (s) => s.replace(/&amp;/g, '&').replace(/[^\p{L}\d&]+/gu, ' ').toLowerCase().split(' ').filter(Boolean)
    const source = words(fixture.map((i) => i.str).join(' ').replace(/co nfigure/, 'configure'))
    const out = new Set(words(text.replace(/-/g, ' ')))
    for (const w of source.join(' ').replace(/-/g, ' ').split(' ')) {
      if (w === 'large' || w === 'scale' || w === 'ai' || w === 'assisted' || w === 'revenue' || w === 'critical') continue
      expect(out.has(w), w).toBe(true)
    }
  })

  it('lets extractProfileFromResume find sections on the multi-line output', () => {
    const result = extractProfileFromResume(pagesToText([shuffled]))
    expect(result.parsedData.workExperience.length).toBeGreaterThan(0)
    expect(result.parsedData.education.length).toBeGreaterThan(0)
    expect(result.basicProfile.email).toBe('jane@example.com')
  })
})

describe('fixHyphenSpacing', () => {
  it('leaves uncertain patterns unchanged', () => {
    expect(fixHyphenSpacing('front- and back-end')).toBe('front- and back-end')
    expect(fixHyphenSpacing('Product - Manager')).toBe('Product - Manager')
    expect(fixHyphenSpacing('configu-')).toBe('configu-')
  })
})
