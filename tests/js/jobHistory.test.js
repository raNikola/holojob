import { describe, it, expect } from 'vitest'
import { formatSeen, historyBadges, isActionable } from '../../src/modules/jobs/jobHistory.js'
import { computeJobStats } from '../../src/modules/jobs/jobStats.js'

describe('history badges', () => {
  it('flag a job first seen recently as New', () => {
    expect(historyBadges({ isNew: true, firstSeen: '2026-10-23T12:00:00+00:00' })).toEqual([
      { label: 'New', variant: 'high', reason: 'First seen 2026-10-23' },
    ])
  })

  it('flag a job no longer listed as Closed, and never as New too', () => {
    const badges = historyBadges({ isNew: true, isClosed: true, closedAt: '2026-10-25T08:00:00+00:00' })
    expect(badges.map((b) => b.label)).toEqual(['Closed'])
    expect(badges[0].reason).toBe('No longer listed since 2026-10-25')
  })

  it('show nothing for a known open job, or a record from before the ledger', () => {
    expect(historyBadges({ isNew: false, isClosed: false })).toEqual([])
    expect(historyBadges({})).toEqual([])
    expect(historyBadges(undefined)).toEqual([])
  })

  it('format the dates it shows', () => {
    expect(formatSeen('2026-10-23T12:00:00+00:00')).toBe('2026-10-23')
    expect(formatSeen(undefined)).toBe('')
  })
})

describe('closed jobs are not candidates for action', () => {
  const job = (extra) => ({ status: 'new', matchScore: 80, applyRecommendation: 'Apply', priority: 'P1', ...extra })

  it('are told apart from open ones', () => {
    expect(isActionable(job({ isClosed: true }))).toBe(false)
    expect(isActionable(job({ isClosed: false }))).toBe(true)
    expect(isActionable(job({}))).toBe(true)
  })

  it('stay in the totals but leave the action buckets', () => {
    const stats = computeJobStats([job({}), job({ isClosed: true }), job({ priority: 'P2', applyRecommendation: 'Maybe', isClosed: true })])
    expect(stats.total).toBe(3)
    expect(stats.scored).toBe(3)
    expect([stats.p1, stats.p2, stats.apply, stats.maybe]).toEqual([1, 0, 1, 0])
  })
})

