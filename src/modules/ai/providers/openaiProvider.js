import { BaseProvider } from './baseProvider.js'

const DEFAULT_MODEL = 'gpt-6-luna'

// Reasoning models reject max_tokens and any temperature but the default, and
// they spend the completion budget on hidden reasoning before any visible text,
// so a small budget comes back empty.
export function isReasoningModel(model) {
  return /^(gpt-5|gpt-6|o\d)/i.test(model || DEFAULT_MODEL)
}
// Same numbers as REASONING_MIN_COMPLETION_TOKENS and DEFAULTS["reasoningEffort"] in python/llm/ai_selection.py.
export const REASONING_MIN_COMPLETION_TOKENS = 8000
export const DEFAULT_REASONING_EFFORT = 'low'

// Our tier names to the API's service_tier values (standard processing is "default"), and back.
export const API_SERVICE_TIER = { standard: 'default', flex: 'flex' }

/** Flex had no capacity. Never retried here and never moved to standard: changing the tier is the owner's choice. */
export class FlexUnavailableError extends Error {
  constructor(status) {
    super(`openai flex processing is unavailable right now (HTTP ${status}, no charge). Not retried and not switched to standard; choose the standard tier in Settings to continue.`)
    this.name = 'FlexUnavailableError'
    this.flexUnavailable = true
    this.status = status
  }
}

export class OpenAIProvider extends BaseProvider {
  constructor() {
    super('openai')
  }

  async complete({ messages, model, temperature, maxTokens, apiKey, baseUrl, serviceTier, reasoningEffort }) {
    if (serviceTier && !API_SERVICE_TIER[serviceTier]) throw new Error(`unknown service tier: ${serviceTier}`)
    const url = `${(baseUrl || 'https://api.openai.com/v1').replace(/\/$/, '')}/chat/completions`
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: model || DEFAULT_MODEL,
        messages,
        ...(serviceTier ? { service_tier: API_SERVICE_TIER[serviceTier] } : {}),
        ...(isReasoningModel(model)
          ? { reasoning_effort: reasoningEffort || DEFAULT_REASONING_EFFORT, max_completion_tokens: Math.max(maxTokens ?? 2000, REASONING_MIN_COMPLETION_TOKENS) }
          : { temperature: temperature ?? 0.3, max_completion_tokens: maxTokens ?? 2000 }),
      }),
    })
    if (serviceTier === 'flex' && (res.status === 429 || res.status === 503)) throw new FlexUnavailableError(res.status)
    const data = await res.json()
    if (!res.ok) {
      const error = new Error(data.error?.message || `OpenAI error: ${res.status}`)
      error.status = res.status
      throw error
    }
    return {
      text: data.choices?.[0]?.message?.content || '',
      usage: {
        inputTokens: data.usage?.prompt_tokens || 0,
        outputTokens: data.usage?.completion_tokens || 0,
        // prompt_tokens counts the cached tokens too; the gate bills those at the cached rate.
        cachedInputTokens: Number.isInteger(data.usage?.prompt_tokens_details?.cached_tokens) ? data.usage.prompt_tokens_details.cached_tokens : null,
        // The tier that actually served the call, as the API reports it (it can differ from the one asked for).
        serviceTier: serviceTier ? (data.service_tier ?? null) : null,
      },
    }
  }

  async healthCheck({ apiKey, baseUrl }) {
    if (!apiKey) return { online: false, reason: 'API key required' }
    try {
      const url = `${(baseUrl || 'https://api.openai.com/v1').replace(/\/$/, '')}/models`
      const res = await fetch(url, { headers: { Authorization: `Bearer ${apiKey}` } })
      return { online: res.ok, reason: res.ok ? undefined : `HTTP ${res.status}` }
    } catch (e) {
      return { online: false, reason: e.message }
    }
  }

  async listModels({ apiKey, baseUrl }) {
    if (!apiKey) return [DEFAULT_MODEL, 'gpt-6.1-sol']
    try {
      const url = `${(baseUrl || 'https://api.openai.com/v1').replace(/\/$/, '')}/models`
      const res = await fetch(url, { headers: { Authorization: `Bearer ${apiKey}` } })
      if (!res.ok) return [DEFAULT_MODEL, 'gpt-6.1-sol']
      const data = await res.json()
      return (data.data || []).map((m) => m.id).filter((id) => id.includes('gpt')).slice(0, 20)
    } catch {
      return [DEFAULT_MODEL, 'gpt-6.1-sol']
    }
  }
}
