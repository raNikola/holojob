import { describe, expect, it } from 'vitest'
import { formFromSettings, settingsFromForm, withSubscriptionFeature } from '../../src/modules/ai/gateClient.js'

describe('the job-import entry of the Claude subscription allowlist (Settings > AI budget)', () => {
  it('adds and removes a feature without touching the others', () => {
    expect(withSubscriptionFeature(['jobAnalysis'], 'job-import', true)).toEqual(['jobAnalysis', 'job-import'])
    expect(withSubscriptionFeature(['jobAnalysis', 'job-import'], 'job-import', true)).toEqual(['jobAnalysis', 'job-import'])
    expect(withSubscriptionFeature(['jobAnalysis', 'job-import'], 'job-import', false)).toEqual(['jobAnalysis'])
  })

  it('never empties the list: the server needs at least one feature', () => {
    expect(withSubscriptionFeature(['job-import'], 'job-import', false)).toEqual(['job-import'])
  })

  it('reaches the saved settings through the form', () => {
    const form = formFromSettings({ currency: 'USD', timezone: 'UTC', claudeCodeSubscription: { enabled: true, maxCallsDaily: 5, features: ['jobAnalysis'] } })
    const next = { ...form, subscriptionFeatures: withSubscriptionFeature(form.subscriptionFeatures, 'job-import', true) }
    expect(settingsFromForm(next).claudeCodeSubscription.features).toEqual(['jobAnalysis', 'job-import'])
  })
})
