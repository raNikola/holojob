import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { runAiFeature } from '../../scripts/run-ai.js'
import { setGateRunner } from '../../scripts/ai-gate.js'
import { setIdentitySource } from '../../scripts/ai-redact.js'
import { setAiSecret } from '../../scripts/secret-store.js'
import { OpenAIProvider } from '../../src/modules/ai/providers/openaiProvider.js'
import { CANARY, useTempSecretStore } from './helpers/secretTestStore.js'
import { selectProvider, withSelection } from './helpers/selectionStub.js'

// Mocked fetch only: no test reaches OpenAI.
useTempSecretStore()

const JOB = { jobId: 'j1', title: 'Product Manager', company: 'Acme', description: 'Own the roadmap.' }
let gateCalls

beforeEach(() => {
  gateCalls = []
  setGateRunner(withSelection(async (command, input) => {
    gateCalls.push({ command, input })
    return command === 'reserve' ? { allowed: true, id: 'c1' } : { ok: true }
  }))
  setIdentitySource(() => ({ names: [], emails: [], phones: [], links: [] }))
  setAiSecret('openai', { key: CANARY })
})

afterEach(() => {
  setGateRunner()
  setIdentitySource()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const reply = (extra = {}) => ({
  choices: [{ message: { content: '{"answer":"ok"}' } }],
  usage: { prompt_tokens: 200, completion_tokens: 50, prompt_tokens_details: { cached_tokens: 80 } },
  ...extra,
})
function stubFetch(status = 200, body = reply()) {
  const fetch = vi.fn(async () => ({ ok: status < 300, status, json: async () => body }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}
const run = (settings) => {
  selectProvider(settings)
  return runAiFeature({ feature: 'jobAnalysis', context: { job: JOB }, settings, refresh: true })
}
const bodyOf = (fetch) => JSON.parse(fetch.mock.calls[0][1].body)
const gate = (command) => gateCalls.find((c) => c.command === command)?.input

describe('the OpenAI request carries the selected service tier', () => {
  it('sends service_tier "default" for standard, which is also the default when none is stored', async () => {
    const fetch = stubFetch()
    await run({ provider: 'openai', model: 'gpt-6-luna' })
    expect(bodyOf(fetch).service_tier).toBe('default')
    expect(gate('reserve').serviceTier).toBe('standard')
  })

  it('sends service_tier "flex" when flex is selected, and tells the gate', async () => {
    const fetch = stubFetch(200, reply({ service_tier: 'flex' }))
    await run({ provider: 'openai', model: 'gpt-6-luna', serviceTier: 'flex' })
    expect(bodyOf(fetch).service_tier).toBe('flex')
    expect(gate('reserve').serviceTier).toBe('flex')
  })

  it('refuses a tier it does not know before any request', async () => {
    const fetch = stubFetch()
    await expect(new OpenAIProvider().complete({ messages: [], apiKey: 'k', serviceTier: 'fast' })).rejects.toThrow(/unknown service tier/)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('sends no tier when none is passed (other callers are unchanged)', async () => {
    const fetch = stubFetch()
    await new OpenAIProvider().complete({ messages: [], apiKey: 'k' })
    expect(bodyOf(fetch)).not.toHaveProperty('service_tier')
  })
})

describe('the actual tier and the cached tokens reach the ledger', () => {
  it('records the tier that served the call (not the one asked for), with cached tokens', async () => {
    stubFetch(200, reply({ service_tier: 'default' }))
    const result = await run({ provider: 'openai', model: 'gpt-6-luna', serviceTier: 'flex' })
    expect(result.ok).toBe(true)
    const finish = gate('finish')
    expect(finish).toMatchObject({ ok: true, inputTokens: 200, outputTokens: 50, cachedInputTokens: 80, serviceTierActual: 'default', flexUnavailable: false })
    expect(gate('reserve').serviceTier).toBe('flex')
  })

  it('passes null when the response names no tier', async () => {
    stubFetch(200, reply())
    await run({ provider: 'openai', model: 'gpt-6-luna' })
    expect(gate('finish').serviceTierActual).toBeNull()
  })
})

describe('flex unavailable', () => {
  for (const status of [429, 503]) {
    it(`HTTP ${status} is a clear error, one request, no standard fallback`, async () => {
      const fetch = stubFetch(status, { error: { message: 'Resource Unavailable' } })
      const result = await run({ provider: 'openai', model: 'gpt-6-luna', serviceTier: 'flex' })
      expect(result.ok).toBe(false)
      expect(result.error).toMatch(/flex processing is unavailable/)
      expect(result.error).toMatch(/not switched to standard/)
      expect(fetch).toHaveBeenCalledTimes(1)
      expect(bodyOf(fetch).service_tier).toBe('flex')
      expect(gate('finish')).toMatchObject({ ok: false, flexUnavailable: true })
    })
  }

  it('a 429 on standard is an ordinary error, not a flex one', async () => {
    stubFetch(429, { error: { message: 'Rate limit' } })
    const result = await run({ provider: 'openai', model: 'gpt-6-luna', serviceTier: 'standard' })
    expect(result.ok).toBe(false)
    expect(gate('finish').flexUnavailable).toBe(false)
  })
})

describe('tier mapping', () => {
  it('standard is sent as "default" and flex as "flex"', async () => {
    const { API_SERVICE_TIER } = await import('../../src/modules/ai/providers/openaiProvider.js')
    expect(API_SERVICE_TIER).toEqual({ standard: 'default', flex: 'flex' })
  })
})
