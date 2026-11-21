// Coarse tiers of the Jobs list (owner decision 2026-11-21, option A): assignment from existing scoring 1.6 output, and the group headings.
import { describe, expect, it } from 'vitest'
import { TIER_POSSIBLE, TIER_STRONG, TIER_WEAK, groupHeading, listGroupOf, tierOf } from '../../src/modules/jobs/fitTier.js'
import { defaultOrder } from '../../src/modules/jobs/jobTableModel.js'

const row = (jobId, matchScore, extra = {}) => ({ jobId, matchScore, matchLabel: 'x', ...extra })

describe('tier assignment', () => {
  it('uses the existing boundaries: Apply line 70 and Good floor 55', () => {
    expect([100, 85, 70].map((s) => tierOf(row('a', s)))).toEqual([TIER_STRONG, TIER_STRONG, TIER_STRONG])
    expect([69, 55].map((s) => tierOf(row('a', s)))).toEqual([TIER_POSSIBLE, TIER_POSSIBLE])
    expect([54, 40, 5].map((s) => tierOf(row('a', s)))).toEqual([TIER_WEAK, TIER_WEAK, TIER_WEAK])
  })

  it('an Avoid-role or avoided-industry Skip verdict is Weak fit at any score', () => {
    expect(tierOf(row('a', 90, { applyRecommendation: 'Skip' }))).toBe(TIER_WEAK)
  })

  it('a blocked ad is in no tier, whatever its score', () => {
    expect(tierOf(row('a', 95, { blockedBy: [{ kind: 'language', text: 'x' }] }))).toBeNull()
    expect(tierOf(row('a', 95, { applyRecommendation: 'Blocked' }))).toBeNull()
  })

  it('an ad with no Fit Score is in no tier', () => {
    expect(tierOf(row('a', undefined))).toBeNull()
    expect(tierOf(row('a', 3, { matchLabel: 'Not read', readStatus: 'not_read' }))).toBeNull()
  })

  it('a role-class-other ad (capped at 54 by scoring 1.6) cannot reach a top tier', () => {
    expect(tierOf(row('a', 54, { roleClass: 'other' }))).toBe(TIER_WEAK)
  })
})

describe('groups and headings in the default order', () => {
  it('a blocked ad sits in its own group after every tier, never under a tier heading', () => {
    const rows = [row('blocked', 99, { blockedBy: [{ kind: 'location', text: 'x' }] }), row('weak', 10), row('strong', 80)]
    const ordered = defaultOrder(rows).map((r) => listGroupOf(r))
    expect(ordered).toEqual([TIER_STRONG, TIER_WEAK, 'blocked'])
  })

  it('shows a heading only where a group starts, and says the group is not ranked', () => {
    const rows = [row('s1', 90), row('s2', 80), row('p', 60)]
    expect(groupHeading(rows, 0)).toContain('Strong fit')
    expect(groupHeading(rows, 0)).toContain('Not ranked by fit')
    expect(groupHeading(rows, 1)).toBeNull()
    expect(groupHeading(rows, 2)).toContain('Possible fit')
  })
})
