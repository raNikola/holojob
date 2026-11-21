import { describe, it, expect } from 'vitest'
import { eligibilityBadges } from '../../src/modules/jobs/workAuthorization.js'
import { blockedLast, closedLast, defaultOrder } from '../../src/modules/jobs/jobTableModel.js'
import { scoreRowChips } from '../../src/modules/jobs/fitScore.js'

const blocked = { jobId: 'b', matchScore: 90, priority: 'Blocked', applyRecommendation: 'Blocked', blockedBy: [{ kind: 'language', text: 'needs German' }, { kind: 'location', text: 'Berlin is outside' }] }
const free = (jobId, matchScore) => ({ jobId, matchScore, priority: 'P2', applyRecommendation: 'Apply', blockedBy: [] })

describe('Blocked (Step 2b)', () => {
  it('shows a Blocked badge first, with every reason in its tooltip', () => {
    const [badge] = eligibilityBadges(blocked)
    expect(badge.label).toBe('Blocked')
    expect(badge.reason).toBe('needs German. Berlin is outside')
    expect(eligibilityBadges(free('a', 80))).toEqual([])
    expect(eligibilityBadges({ jobId: 'old' })).toEqual([]) // a row stored before 1.5 / 2b has no blockedBy
  })

  it('does not repeat Blocked as a priority or apply chip', () => {
    expect(scoreRowChips(blocked)).toEqual([])
    expect(scoreRowChips(free('a', 80)).map((c) => c.text)).toEqual(['P2', 'Apply'])
  })

  it('puts blocked ads after the others in the default order, each group in the neutral order, and hides nothing', () => {
    const rows = [blocked, free('a', 70), free('c', 80)]
    const ordered = blockedLast(defaultOrder(rows))
    expect(ordered.map((r) => r.jobId)).toEqual(['a', 'c', 'b'])
    expect(ordered).toHaveLength(3)
    expect(closedLast(ordered).map((r) => r.jobId)).toEqual(['a', 'c', 'b'])
  })

  it('shows an unconfirmed language as a flag, not as Blocked (Step 2c)', () => {
    const row = { ...free('u', 80), languageState: { blocking: [], unconfirmed: [{ language: 'German', why: 'quote_not_in_ad' }] } }
    expect(eligibilityBadges(row).map((b) => b.label)).toEqual(['Language unconfirmed'])
    expect(eligibilityBadges({ ...free('u', 80), languageState: { blocking: [], unconfirmed: [] } })).toEqual([])
  })
})
