import { describe, expect, it } from 'vitest'
import { paidSummary, statusLabel, statusSentence } from '../../src/modules/activity/runView.js'
import { AD_NOT_READ_LABEL, adNotReadLabel } from '../../src/modules/jobs/fitTier.js'
import { formFromSettings, settingsFromForm } from '../../src/modules/ai/gateClient.js'

const run = (extra = {}) => ({
  status: 'waiting', steps: [], counts: {}, classification: null, cancel: null,
  paid: {
    limits: { usd: 1, ads: 50 }, spentUsd: 0.4321, ads: 20, waiting: 14,
    steps: {
      classification: { candidates: 30, done: 18, failed: 1, waiting: 12, stopped: 'run_usd', spentUsd: 0.2, ads: 18 },
      reading: { candidates: 4, done: 2, failed: 0, waiting: 2, stopped: 'run_ads', spentUsd: 0.2321, ads: 2 },
      engine: { candidates: 0, done: 0, failed: 0, waiting: null, stopped: 'engine_not_allowed', spentUsd: 0, ads: 0 },
    },
  },
  ...extra,
})

describe('a run that stopped on a limit with ads left', () => {
  it('is not shown as plainly completed: the badge says how many ads wait', () => {
    expect(statusLabel('waiting', run())).toBe('Completed, 14 ads waiting')
    expect(statusLabel('waiting', run({ paid: { ...run().paid, waiting: 1 } }))).toBe('Completed, 1 ad waiting')
    expect(statusLabel('partial', run())).toBe('Partial')
    expect(statusSentence(run())).toMatch(/limit stopped some work/)
  })

  it('says which limit stopped each step and how many ads wait', () => {
    const summary = paidSummary(run())
    expect(summary.headline).toBe('Run limit: $1.00 and 50 ads. Spent $0.4321 on 20 ads.')
    expect(summary.lines).toEqual([
      'Classification: 18 classified, 1 failed (tried again next run), $0.2000 spent. Stopped: the run spend limit in Settings was reached, 12 ads waiting.',
      'Reading: 2 read, $0.2321 spent. Stopped: the ads-per-run limit in Settings was reached, 2 ads waiting.',
      'Engine fill: 0 filled. Stopped: engine fill not allowed in Settings.',
    ])
  })

  it('says "run limit not set in Settings" when there is no limit, and nothing for a run without paid steps', () => {
    expect(paidSummary(run({ paid: { limits: null, spentUsd: 0, ads: 0, waiting: 0, steps: { classification: null, reading: null, engine: null } } })).headline)
      .toMatch(/^Run limit not set in Settings: the paid steps spent nothing\./)
    expect(paidSummary({ status: 'ok' })).toBeNull()
  })
})

describe('the unread label', () => {
  it('shows on a row scored without the ad facts, and only there', () => {
    expect(adNotReadLabel({ aiEnrichment: 'missing' })).toBe(AD_NOT_READ_LABEL)
    expect(AD_NOT_READ_LABEL).toBe('Ad not read: sponsorship and language not checked')
    expect(adNotReadLabel({ matchScore: 80 })).toBeNull()
    expect(adNotReadLabel(null)).toBeNull()
  })
})

describe('the run limit fields of Settings', () => {
  const settings = { currency: 'USD', dailyLimit: 1, monthlyLimit: 5, maxCallsDaily: null, maxCallsMonthly: null, estimatedOutputTokens: 1000, timezone: 'UTC', automation: { enabled: false },
    claudeCodeSubscription: { enabled: false, maxCallsDaily: 5, features: ['jobAnalysis'] } }

  it('are empty (not set) by default and never get a number from the code', () => {
    const form = formFromSettings(settings)
    expect([form.runLimitUsd, form.runLimitAds, form.allowEngineFill]).toEqual(['', '', false])
    const sent = settingsFromForm(form)
    expect([sent.runLimitUsd, sent.runLimitAds, sent.allowEngineFill]).toEqual([null, null, false])
  })

  it('round-trip a value the owner typed', () => {
    const form = { ...formFromSettings({ ...settings, runLimitUsd: 0.5, runLimitAds: 40, allowEngineFill: true }) }
    const sent = settingsFromForm(form)
    expect([sent.runLimitUsd, sent.runLimitAds, sent.allowEngineFill]).toEqual([0.5, 40, true])
  })
})
