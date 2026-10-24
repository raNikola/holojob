import { describe, it, expect } from 'vitest'
import { inlineRuns, parseDescription, toPlainLines, truncateDescription } from '../../src/modules/jobs/descriptionFormat.js'

const text = (runs) => runs.map((r) => r.text).join('')

describe('job description formatting', () => {
  it('renders bold runs and drops the markers', () => {
    expect(inlineRuns('a **bold** word')).toEqual([{ text: 'a ', bold: false }, { text: 'bold', bold: true }, { text: ' word', bold: false }])
  })

  it('drops an unmatched marker left by a cut-off ad instead of showing asterisks', () => {
    const runs = inlineRuns('start **cut off here')
    expect(text(runs)).toBe('start cut off here')
    expect(runs.every((r) => !r.bold)).toBe(true)
  })

  it('splits a markdown ad into heading, paragraph and bullet list', () => {
    const blocks = parseDescription("**About the role:**\n\nYou will shape the roadmap.\n\n**What you'll be doing:**\n\n* Lead discovery\n* Ship **fast**\n* Talk to users\n\nApply now.")
    expect(blocks.map((b) => b.type)).toEqual(['h', 'p', 'h', 'ul', 'p'])
    expect(text(blocks[0].runs)).toBe('About the role:')
    expect(blocks[3].items).toHaveLength(3)
    expect(blocks[3].items[1].some((r) => r.bold && r.text === 'fast')).toBe(true)
    expect(JSON.stringify(blocks)).not.toContain('*')
  })

  it('keeps a bold phrase in the middle of a sentence in that sentence', () => {
    const blocks = parseDescription("We're looking for a new\n**Product Manager**\nto join our team.")
    expect(blocks).toHaveLength(1)
    expect(blocks[0].type).toBe('p')
    expect(text(blocks[0].runs)).toBe("We're looking for a new Product Manager to join our team.")
  })

  it('starts a list after a line that ends with a colon', () => {
    const blocks = parseDescription("What you'll do:\n- one\n- two")
    expect(blocks.map((b) => b.type)).toEqual(['p', 'ul'])
  })

  it('reads numbered lists and markdown headings', () => {
    const blocks = parseDescription('## Duties\n1. First\n2. Second')
    expect(blocks.map((b) => b.type)).toEqual(['h', 'ol'])
    expect(blocks[1].items).toHaveLength(2)
  })

  it('reads HTML, including escaped HTML as Greenhouse sends it', () => {
    const escaped = '&lt;p&gt;Intro&lt;/p&gt;&lt;ul&gt;&lt;li&gt;A&lt;/li&gt;&lt;li&gt;B &amp;amp; C&lt;/li&gt;&lt;/ul&gt;'
    const blocks = parseDescription(escaped)
    expect(blocks.map((b) => b.type)).toEqual(['p', 'ul'])
    expect(blocks[1].items.map(text)).toEqual(['A', 'B &amp; C'])
    expect(parseDescription('<p>One</p><p>Two<br>three</p>').map((b) => b.type)).toEqual(['p', 'p'])
  })

  it('never produces markup: a script tag in an ad is dropped, its text is plain text', () => {
    const out = JSON.stringify(parseDescription('Hi <script>alert(1)</script> there <img src=x onerror=alert(1)>'))
    expect(out).not.toContain('<script')
    expect(out).not.toContain('<img')
  })

  it('collapses to a word boundary and says whether it cut', () => {
    expect(truncateDescription('short', 100)).toEqual({ text: 'short', truncated: false })
    const long = truncateDescription(`${'word '.repeat(200)}`, 100)
    expect(long.truncated).toBe(true)
    expect(long.text.length).toBeLessThanOrEqual(101)
    expect(long.text.endsWith('…')).toBe(true)
    expect(toPlainLines('a\n\n\n\nb')).toBe('a\n\nb')
  })
})
