import { describe, it, expect } from 'vitest'
import { formatSeen, historyBadges } from '../../src/modules/jobs/jobHistory.js'

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
