import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { runAiFeature } from '../../scripts/run-ai.js'
import { setGateRunner } from '../../scripts/ai-gate.js'
import { setIdentitySource } from '../../scripts/ai-redact.js'
import { getProvider } from '../../src/modules/ai/aiProviderRegistry.js'
import { formFromSettings, settingsFromForm } from '../../src/modules/ai/gateClient.js'
import { selectProvider, withSelection } from './helpers/selectionStub.js'

// The decision itself is python/llm/ai_gate.py (tests/python/test_ai_gate_subscription.py). Here: what the Node side
// asks the gate, and that a stored finding never reaches it, so it cannot count toward the daily call cap.
const ANSWER = '{"fitSummary":"Good fit"}'
const context = { profile: { currentRole: 'PM' }, job: { jobId: 'wk-9', title: 'PM', company: 'Acme', description: 'Own the roadmap.' } }

let gateCalls
let decision
let complete

beforeEach(() => {
  gateCalls = []
  decision = { allowed: true, id: 'c1' }
  setGateRunner(withSelection(async (command, input) => {
    gateCalls.push({ command, input })
    return command === 'reserve' ? decision : { ok: true }
  }))
  setIdentitySource(() => ({ names: [], emails: [], phones: [], links: [] }))
  selectProvider({ provider: 'claude-code', model: 'sonnet' })
  complete = vi.spyOn(getProvider('claude-code'), 'complete').mockResolvedValue({ text: ANSWER, usage: { inputTokens: 5, outputTokens: 5 } })
  vi.spyOn(console, 'info').mockImplementation(() => {})
})

afterEach(() => {
  setGateRunner()
  setIdentitySource()
  vi.restoreAllMocks()
})

const reserves = () => gateCalls.filter((c) => c.command === 'reserve')

describe('claude-code through the gate', () => {
  it('a miss asks the gate with the provider, model and feature, then records the result', async () => {
    const result = await runAiFeature({ feature: 'jobAnalysis', context })
    expect(result.ok).toBe(true)
    expect(reserves()).toHaveLength(1)
    expect(reserves()[0].input).toMatchObject({ provider: 'claude-code', model: 'sonnet', feature: 'jobAnalysis' })
    expect(gateCalls.some((c) => c.command === 'finish')).toBe(true)
  })

  it('a stored finding reserves nothing, so it does not count toward the daily cap', async () => {
    await runAiFeature({ feature: 'jobAnalysis', context })
    gateCalls.length = 0
    const again = await runAiFeature({ feature: 'jobAnalysis', context })
    expect(again).toMatchObject({ ok: true, cached: true })
    expect(gateCalls.filter((c) => c.command !== 'selection-get')).toEqual([])
    expect(complete).toHaveBeenCalledTimes(1)
  })

  it('a refusal (budget 0 or the daily cap) stops the call and stores nothing', async () => {
    decision = { allowed: false, reason: 'daily Claude subscription call limit reached (5)' }
    const result = await runAiFeature({ feature: 'jobAnalysis', context })
    expect(result).toMatchObject({ ok: false, refused: true })
    expect(result.error).toContain('daily Claude subscription call limit reached')
    expect(complete).not.toHaveBeenCalled()
  })

  it('another feature is asked under its own name, so the gate can keep it paid', async () => {
    await runAiFeature({ feature: 'coverLetter', context })
    expect(reserves()[0].input.feature).toBe('coverLetter')
  })
})

describe('the settings form', () => {
  const settings = { currency: 'USD', dailyLimit: 0, monthlyLimit: 0, maxCallsDaily: null, maxCallsMonthly: null, estimatedOutputTokens: 1000,
    timezone: 'UTC', automation: { enabled: false }, claudeCodeSubscription: { enabled: false, maxCallsDaily: 5, features: ['jobAnalysis'] } }

  it('round-trips the subscription setting, off by default', () => {
    const form = formFromSettings(settings)
    expect(form).toMatchObject({ subscriptionEnabled: false, subscriptionMaxCallsDaily: '5', subscriptionFeatures: ['jobAnalysis'] })
    expect(settingsFromForm(form).claudeCodeSubscription).toEqual({ enabled: false, maxCallsDaily: 5, features: ['jobAnalysis'] })
    expect(settingsFromForm({ ...form, subscriptionEnabled: true }).claudeCodeSubscription.enabled).toBe(true)
  })
})
