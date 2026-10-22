import { BaseProvider } from './baseProvider.js'

const DEFAULT_MODEL = 'gpt-6-luna'

// Reasoning models reject max_tokens and any temperature but the default, and
// they spend the completion budget on hidden reasoning before any visible text,
// so a small budget comes back empty.
export function isReasoningModel(model) {
  return /^(gpt-5|gpt-6|o\d)/i.test(model || DEFAULT_MODEL)
}
const REASONING_MIN_COMPLETION_TOKENS = 8000

export class OpenAIProvider extends BaseProvider {
  constructor() {
    super('openai')
  }

  async complete({ messages, model, temperature, maxTokens, apiKey, baseUrl }) {
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
        ...(isReasoningModel(model)
          ? { reasoning_effort: 'low', max_completion_tokens: Math.max(maxTokens ?? 2000, REASONING_MIN_COMPLETION_TOKENS) }
          : { temperature: temperature ?? 0.3, max_completion_tokens: maxTokens ?? 2000 }),
      }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error?.message || `OpenAI error: ${res.status}`)
    return {
      text: data.choices?.[0]?.message?.content || '',
      usage: {
        inputTokens: data.usage?.prompt_tokens || 0,
        outputTokens: data.usage?.completion_tokens || 0,
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
