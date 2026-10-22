import { describe, it, expect, vi, afterEach } from 'vitest'
import { OpenAIProvider, isReasoningModel } from '../../src/modules/ai/providers/openaiProvider.js'
import { PROVIDER_DEFAULTS } from '../../src/modules/ai/aiSettings.js'

function stubFetch(reply = { choices: [{ message: { content: 'ok' } }], usage: {} }) {
  const fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => reply }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

afterEach(() => vi.unstubAllGlobals())

describe('OpenAI chat requests', () => {
  it('send max_completion_tokens and never max_tokens', async () => {
    const fetch = stubFetch()
    await new OpenAIProvider().complete({ messages: [], model: 'gpt-4o', maxTokens: 900, apiKey: 'k' })
    const body = JSON.parse(fetch.mock.calls[0][1].body)
    expect(body.max_completion_tokens).toBe(900)
    expect(body).not.toHaveProperty('max_tokens')
  })

  it('default to a model that is not being retired', async () => {
    const fetch = stubFetch()
    await new OpenAIProvider().complete({ messages: [], apiKey: 'k' })
    expect(JSON.parse(fetch.mock.calls[0][1].body).model).toBe('gpt-6-luna')
    expect(PROVIDER_DEFAULTS.openai.model).toBe('gpt-6-luna')
    expect(await new OpenAIProvider().listModels({})).not.toContain('gpt-4o-mini')
  })

  it('give reasoning models low effort and room for their hidden reasoning', async () => {
    const fetch = stubFetch()
    await new OpenAIProvider().complete({ messages: [], model: 'gpt-5-mini', maxTokens: 2000, apiKey: 'k' })
    const body = JSON.parse(fetch.mock.calls[0][1].body)
    expect(body.reasoning_effort).toBe('low')
    expect(body.max_completion_tokens).toBe(8000)
  })

  it('leave temperature out for reasoning models, keep it for the rest', async () => {
    const fetch = stubFetch()
    await new OpenAIProvider().complete({ messages: [], model: 'gpt-5-mini', temperature: 0.3, apiKey: 'k' })
    expect(JSON.parse(fetch.mock.calls[0][1].body)).not.toHaveProperty('temperature')
    await new OpenAIProvider().complete({ messages: [], model: 'gpt-4o', temperature: 0.3, apiKey: 'k' })
    expect(JSON.parse(fetch.mock.calls[1][1].body).temperature).toBe(0.3)
    expect(isReasoningModel('o3-mini')).toBe(true)
    expect(isReasoningModel('gpt-4.1')).toBe(false)
  })
})
