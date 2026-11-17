import { describe, it, expect } from 'vitest'
import { filterJobs } from '../../src/modules/jobs/jobFilters.js'
import { eligibilityBadges, isBlockedByVisa, isCapReason } from '../../src/modules/jobs/workAuthorization.js'
import { fitScoreOf, isInsufficientData, isNotRead } from '../../src/modules/jobs/matchScore.js'
import { notReadFirst } from '../../src/modules/jobs/jobTableModel.js'

const withState = (state) => ({ jobId: state, status: 'new', eligibility: { state, reason: 'why' } })

describe('eligibility on the job list (scoringVersion 1.5)', () => {
  it('shows each state as a text badge, and nothing when the check is dormant', () => {
    expect(eligibilityBadges(withState('authorized'))[0].label).toBe('Authorized')
    expect(eligibilityBadges(withState('sponsorship_offered'))[0].label).toBe('Sponsorship offered')
    expect(eligibilityBadges(withState('sponsorship_refused'))[0].label).toBe('Sponsorship refused')
    expect(eligibilityBadges(withState('unknown'))[0].label).toBe('Unconfirmed')
    expect(eligibilityBadges({ jobId: 'x', eligibility: null })).toEqual([])
    expect(eligibilityBadges({})).toEqual([])
  })

  it('shows the read status and the location state beside it', () => {
    const job = { readStatus: 'insufficient_evidence', confidence: { reasons: ['no requirements'] }, workAuthorization: { status: 'outside_allowed', reason: 'r' } }
    expect(eligibilityBadges(job).map((b) => b.label)).toEqual(['Insufficient evidence', 'Outside your places'])
    expect(eligibilityBadges({ readStatus: 'read' })).toEqual([])
    // the old visa statuses of a 1.4 row are not badged any more: only the eligibility state speaks for the visa
    expect(eligibilityBadges({ workAuthorization: { status: 'needs_visa_silent' } })).toEqual([])
  })

  it('hides only "Sponsorship refused" when asked, never Unconfirmed, and never an unscored job', () => {
    const jobs = ['sponsorship_refused', 'unknown', 'authorized', 'sponsorship_offered'].map(withState).concat({ jobId: 'raw' })
    expect(filterJobs(jobs, {})).toHaveLength(5)
    expect(isBlockedByVisa(withState('sponsorship_refused'))).toBe(true)
    expect(filterJobs(jobs, { hideNeedsVisa: true }).map((j) => j.jobId)).toEqual(['unknown', 'authorized', 'sponsorship_offered', 'raw'])
  })

  it('recognises cap reasons', () => {
    expect(isCapReason('Capped: the title matches no product target role')).toBe(true)
    expect(isCapReason('Work authorization: Unconfirmed: the ad does not mention sponsorship')).toBe(false)
  })
})

describe('Not read ads', () => {
  const notRead = { jobId: 'n', matchScore: null, matchLabel: 'Not read', dataStatus: 'not_read', readStatus: 'not_read' }
  const rated = (id, score) => ({ jobId: id, matchScore: score, matchLabel: 'Good', dataStatus: 'sufficient', readStatus: 'read' })

  it('have no Fit Score and are no band', () => {
    expect(isNotRead(notRead)).toBe(true)
    expect(isInsufficientData(notRead)).toBe(true)
    expect(fitScoreOf(notRead)).toBeNull()
    expect(isNotRead(rated('a', 60))).toBe(false)
  })

  it('form a group of their own in the default order instead of sorting to the bottom', () => {
    const rows = [rated('a', 80), rated('b', 60), notRead, { ...notRead, jobId: 'n2' }]
    expect(notReadFirst(rows).map((r) => r.jobId)).toEqual(['n', 'n2', 'a', 'b'])
  })
})
