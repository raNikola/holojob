// "Many unknown musts" label, the quote-check note and the details wording (owner decisions 2026-11-23): display only.
import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import FitTier from '../../src/components/jobs/FitTier.jsx'
import EngineShadowSection from '../../src/components/jobs/EngineShadowSection.jsx'
import { manyUnknownMustsLabel, tierCounts, tierOf, unknownMustCounts } from '../../src/modules/jobs/fitTier.js'
import { QUOTE_NOT_VERIFIED_NOTE, quoteLoweredIds } from '../../src/modules/jobs/engineShadow.js'

const must = (status, i = 0) => ({ id: `m${i}`, text: `t${i}`, importance: 'must', status, strength: 0, postingQuote: 'q' })
const withMusts = (statuses, extra = {}) => ({
  jobId: 'j', matchScore: 80, matchLabel: 'x',
  engineShadow: { requirements: statuses.map((s, i) => must(s, i)), ...extra },
})
const unknowns = (n, total) => [...Array(n).fill('UNKNOWN'), ...Array(total - n).fill('MET')]

describe('many unknown musts label', () => {
  it('threshold: 29% shows nothing, 30% shows the label', () => {
    // 29 of 100 musts
    expect(manyUnknownMustsLabel(withMusts(unknowns(29, 100)))).toBeNull()
    expect(manyUnknownMustsLabel(withMusts(unknowns(30, 100)))).toBe('30 of 100 musts unknown')
    // 2 of 7 = 28.6% no, 3 of 10 = 30% yes
    expect(manyUnknownMustsLabel(withMusts(unknowns(2, 7)))).toBeNull()
    expect(manyUnknownMustsLabel(withMusts(unknowns(3, 10)))).toBe('3 of 10 musts unknown')
  })

  it('counts UNKNOWN and NOT_EVIDENCED, and only musts', () => {
    const row = withMusts(['UNKNOWN', 'NOT_EVIDENCED', 'MET', 'MET', 'MISSING'])
    row.engineShadow.requirements.push({ ...must('UNKNOWN', 9), importance: 'preferred' }, { ...must('UNKNOWN', 8), importance: 'nice' })
    expect(unknownMustCounts(row)).toEqual({ unknown: 2, total: 5 })
    expect(manyUnknownMustsLabel(row)).toBe('2 of 5 musts unknown')
  })

  it('no label without an engine answer, with a failed call, or without musts', () => {
    expect(manyUnknownMustsLabel({ jobId: 'j', matchScore: 80 })).toBeNull()
    expect(manyUnknownMustsLabel({ matchScore: 80, engineShadow: { enabled: false } })).toBeNull()
    expect(manyUnknownMustsLabel({ matchScore: 80, engineShadow: { error: 'x', requirements: [must('UNKNOWN')] } })).toBeNull()
    expect(manyUnknownMustsLabel({ matchScore: 80, engineShadow: { requirements: [{ ...must('UNKNOWN'), importance: 'preferred' }] } })).toBeNull()
  })

  it('never changes the tier or the tier counts', () => {
    const plain = [60, 70, 80, 40].map((s) => ({ jobId: `j${s}`, matchScore: s, matchLabel: 'x' }))
    const labelled = plain.map((r) => ({ ...r, engineShadow: { requirements: [must('UNKNOWN')] } }))
    expect(labelled.map(tierOf)).toEqual(plain.map(tierOf))
    expect(tierCounts(labelled)).toEqual(tierCounts(plain))
  })

  it('shows on a Strong list row only when over the threshold', () => {
    expect(renderToStaticMarkup(createElement(FitTier, { job: withMusts(unknowns(4, 9)) }))).toContain('4 of 9 musts unknown')
    expect(renderToStaticMarkup(createElement(FitTier, { job: withMusts(unknowns(1, 9)) }))).not.toContain('musts unknown')
  })
})

describe('quote-check note', () => {
  const warning = "requirement 'm1': PARTIAL lowered to UNKNOWN, evidence quote 'x' not found in 'ev1'"
  const shadow = {
    fit: 50, label: 'Partial', confidence: 0.8, bucket: 'apply', counts: {}, gates: [], warnings: [warning],
    requirements: [must('UNKNOWN', 1), must('UNKNOWN', 2)].map((r, i) => ({ ...r, id: `m${i + 1}`, importance: 'must' })),
  }

  it('reads the lowered requirement ids from the stored warnings', () => {
    expect([...quoteLoweredIds(shadow)]).toEqual(['m1'])
    expect([...quoteLoweredIds({ warnings: ["requirement 'a': MET lowered to PARTIAL, evidence quote 'x' not found in 'e'", 'dropped requirement x'] })]).toEqual(['a'])
    expect(quoteLoweredIds(null).size).toBe(0)
  })

  it('shows the note on that requirement only', () => {
    const html = renderToStaticMarkup(createElement(EngineShadowSection, { shadow }))
    expect(html.split(QUOTE_NOT_VERIFIED_NOTE).length - 1).toBe(1)
  })
})
