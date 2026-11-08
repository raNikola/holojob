import { describe, it, expect } from 'vitest'
import { closedAdIds, formatSeen, historyBadges, isActionable } from '../../src/modules/jobs/jobHistory.js'
import { computeJobStats } from '../../src/modules/jobs/jobStats.js'

describe('history badges', () => {
  it('flag a job first seen recently as Just found', () => {
    expect(historyBadges({ isNew: true, firstSeen: '2026-10-23T12:00:00+00:00' })).toEqual([
      { label: 'Just found', variant: 'high', reason: 'First seen 2026-10-23' },
    ])
  })

  it('flag a job no longer listed as Closed, and never as Just found too', () => {
    const badges = historyBadges({ isNew: true, isClosed: true, closedAt: '2026-10-25T08:00:00+00:00' })
    expect(badges.map((b) => b.label)).toEqual(['Closed'])
    expect(badges[0].reason).toBe('No longer listed since 2026-10-25')
  })

  it('an ad closed by the two-check rule says so; one closed before it keeps the old wording', () => {
    const [badge] = historyBadges({ isClosed: true, closedAt: '2026-11-05T08:00:00+00:00', closedAfterChecks: 2 })
    expect(badge.label).toBe('Closed')
    expect(badge.reason).toBe("Not on the company's board in 2 complete checks since 2026-11-05")
  })

  it('an absent ad gets its own badge with the date, and is still actionable', () => {
    const job = { isAbsent: true, absentSince: '2026-11-04T08:00:00+00:00', lastSeen: '2026-11-03T08:00:00+00:00' }
    const [badge] = historyBadges(job)
    expect(badge.label).toBe('Not in latest search')
    expect(badge.reason).toContain('2026-11-04')
    expect(badge.reason).toContain('Last seen 2026-11-03')
    expect(isActionable(job)).toBe(true)
  })

  it('closed wins over absent', () => {
    expect(historyBadges({ isClosed: true, isAbsent: true, closedAt: '2026-11-05' })[0].label).toBe('Closed')
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


describe('closed ads on applications', () => {
  it('reads the class first, then the stored mark', () => {
    expect([...closedAdIds([{ jobId: 'a', class: 'closed' }, { jobId: 'b', class: 'found', isClosed: true }, { jobId: 'c', isClosed: true }, { jobId: 'd' }])]).toEqual(['a', 'c'])
  })

  it('no rows, no ids', () => {
    expect(closedAdIds(null).size).toBe(0)
  })
})
