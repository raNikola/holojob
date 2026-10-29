import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { runAiFeature } from '../../scripts/run-ai.js'
import { setGateRunner } from '../../scripts/ai-gate.js'
import { setIdentitySource } from '../../scripts/ai-redact.js'
import { getProvider } from '../../src/modules/ai/aiProviderRegistry.js'
import { setAiSecret } from '../../scripts/secret-store.js'
import { CANARY, useTempSecretStore } from './helpers/secretTestStore.js'
import { selectProvider, withSelection } from './helpers/selectionStub.js'

const JOB = {
  jobId: 'j1', title: 'Product Manager', company: 'Acme',
  description: 'Own the roadmap. Contact hr@acme-test.example or Jane Roe (+49 170 5550123).',
}
const OWNER_EMAIL = 'zlatan.qwerty@owner-test.example'

useTempSecretStore()

let gateCalls
let gateDecision

beforeEach(() => {
  gateCalls = []
  gateDecision = { allowed: true, id: 'c1' }
  setGateRunner(withSelection(async (command, input) => {
    gateCalls.push({ command, input })
    return command === 'reserve' ? gateDecision : { ok: true }
  }))
  setIdentitySource(() => ({ names: ['Zlatan Qwerty'], emails: [OWNER_EMAIL], phones: [], links: [] }))
})

afterEach(() => {
  setGateRunner()
  setIdentitySource()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

function stubFetch(reply = { choices: [{ message: { content: '{"answer":"ok"}' } }], usage: {} }) {
  const fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => reply }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}
// `settings` is what a request body might carry; the server ignores it. The selection is what the server stores.
const run = (settings, context = { job: JOB, message: `from ${OWNER_EMAIL}` }, feature = 'jobAnalysis') => {
  selectProvider(settings)
  // These tests are about the key and the gate, so every call must reach the provider: `refresh` skips the findings store.
  return runAiFeature({ feature, context, settings, refresh: true })
}
const reserve = () => gateCalls.find((c) => c.command === 'reserve')?.input

describe('the key and base URL come from the store', () => {
  it('uses the stored key and its pinned base URL, and ignores the request\'s apiKey and baseUrl', async () => {
    setAiSecret('openai', { key: CANARY, baseUrl: 'https://proxy.example/v1' })
    const fetch = stubFetch()
    const result = await run({ provider: 'openai', model: 'gpt-4o', apiKey: 'sk-browser-key-0123456789', baseUrl: 'https://evil.example/v1' })
    expect(result.ok).toBe(true)
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('https://proxy.example/v1/chat/completions')
    expect(init.headers.Authorization).toBe(`Bearer ${CANARY}`)
    expect(JSON.stringify(fetch.mock.calls)).not.toContain('evil.example')
    expect(JSON.stringify(fetch.mock.calls)).not.toContain('browser-key')
    expect(JSON.stringify(gateCalls)).not.toContain('evil.example')
  })

  it('uses the provider\'s own URL when none is pinned, whatever the request says', async () => {
    setAiSecret('openai', { key: CANARY })
    const fetch = stubFetch()
    await run({ provider: 'openai', baseUrl: 'http://localhost:11434' })
    expect(fetch.mock.calls[0][0]).toBe('https://api.openai.com/v1/chat/completions')
  })

  it('tells the gate the host the key really goes to, not the one the request names', async () => {
    setAiSecret('openai', { key: CANARY })
    stubFetch()
    await run({ provider: 'openai', baseUrl: 'http://localhost:11434' })
    expect(reserve().baseUrl).toBe('https://api.openai.com/v1')
    gateCalls.length = 0
    setAiSecret('openai', { key: CANARY, baseUrl: 'https://proxy.example/v1' })
    await run({ provider: 'openai', baseUrl: 'http://localhost:11434' })
    expect(reserve().baseUrl).toBe('https://proxy.example/v1')
    expect(gateCalls.find((c) => c.command === 'finish').input.baseUrl).toBe('https://proxy.example/v1')
  })

  it('falls back to OPENAI_API_KEY in .env, the store winning when both exist', async () => {
    vi.stubEnv('OPENAI_API_KEY', 'env-openai-key-value')
    const fetch = stubFetch()
    await run({ provider: 'openai' })
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer env-openai-key-value')
    setAiSecret('openai', { key: CANARY })
    await run({ provider: 'openai' })
    expect(fetch.mock.calls[1][1].headers.Authorization).toBe(`Bearer ${CANARY}`)
  })
})

describe('without a stored key', () => {
  it('answers "No API key configured" for every keyed provider, and makes no call and no reservation', async () => {
    const fetch = stubFetch()
    for (const provider of ['openai', 'openrouter', 'claude', 'gemini']) {
      const result = await run({ provider, apiKey: 'sk-browser-key-0123456789' })
      expect(result).toEqual({ ok: false, error: 'No API key configured' })
    }
    expect(fetch).not.toHaveBeenCalled()
    expect(gateCalls).toEqual([])
  })

  it('a key stored for one provider does not serve another', async () => {
    setAiSecret('gemini', { key: CANARY })
    const fetch = stubFetch()
    expect((await run({ provider: 'openai' })).error).toBe('No API key configured')
    expect(fetch).not.toHaveBeenCalled()
  })
})

describe('the budget gate and redaction still come first', () => {
  it('makes no call when the gate refuses, even with a stored key', async () => {
    setAiSecret('openai', { key: CANARY })
    gateDecision = { allowed: false, id: 'c9', reason: 'paid call openai refused: AI budget is 0' }
    const fetch = stubFetch()
    const result = await run({ provider: 'openai' })
    expect(result).toMatchObject({ ok: false, refused: true })
    expect(fetch).not.toHaveBeenCalled()
    expect(gateCalls.map((c) => c.command)).toEqual(['reserve'])
  })

  it('asks the gate once before the call, and the prompt that leaves is redacted', async () => {
    setAiSecret('openai', { key: CANARY })
    const fetch = stubFetch()
    await run({ provider: 'openai' })
    expect(gateCalls.map((c) => c.command)).toEqual(['reserve', 'finish'])
    const body = String(fetch.mock.calls[0][1].body)
    for (const leaked of [OWNER_EMAIL, 'hr@acme-test.example', 'Zlatan', '5550123']) expect(body).not.toContain(leaked)
    expect(reserve().promptChars).toBeGreaterThan(0)
  })

  it('refuses without calling when redaction cannot run, key or not', async () => {
    setAiSecret('openai', { key: CANARY })
    setIdentitySource(() => { throw new Error('mirror unreadable') })
    const fetch = stubFetch()
    const result = await run({ provider: 'openai' })
    expect(result).toMatchObject({ ok: false, refused: true })
    expect(fetch).not.toHaveBeenCalled()
    expect(gateCalls.map((c) => c.command)).toEqual(['refuse'])
  })
})

describe('providers without a key are unaffected', () => {
  it('claude-code: gated, called without a key, no secret lookup needed', async () => {
    const complete = vi.spyOn(getProvider('claude-code'), 'complete').mockResolvedValue({ text: '{}', usage: {} })
    const result = await run({ provider: 'claude-code', model: 'sonnet', apiKey: 'x', baseUrl: 'https://evil.example' })
    expect(result.ok).toBe(true)
    expect(complete.mock.calls[0][0]).toMatchObject({ apiKey: undefined, baseUrl: undefined, model: 'sonnet' })
    expect(gateCalls.map((c) => c.command)).toEqual(['reserve', 'finish'])
  })

  it('ollama: gated, and it keeps the request\'s base URL (no credential is attached)', async () => {
    const complete = vi.spyOn(getProvider('ollama'), 'complete').mockResolvedValue({ text: '{}', usage: {} })
    const result = await run({ provider: 'ollama', baseUrl: 'http://192.168.1.5:11434', apiKey: 'x' })
    expect(result.ok).toBe(true)
    expect(complete.mock.calls[0][0]).toMatchObject({ baseUrl: 'http://192.168.1.5:11434', apiKey: undefined })
    expect(reserve().baseUrl).toBe('http://192.168.1.5:11434')
  })

  it('mock: neither gated nor keyed', async () => {
    const result = await run({ provider: 'mock' })
    expect(result.ok).toBe(true)
    expect(gateCalls).toEqual([])
  })
})
