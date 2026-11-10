/**
 * The provider selection lives on the server (python/llm/ai_selection.py, read through the gate CLI). Tests answer
 * `selection-get` from here instead, so no test reads the real data/config/ai-settings.json.
 */

let current = null

/** A selection as the server would store it, from the old-style request settings the tests still write. */
export function selectionFrom(requested) {
  return {
    provider: requested.provider,
    model: requested.model ?? 'test-model',
    temperature: requested.temperature ?? 0.3,
    maxTokens: requested.maxTokens ?? 2000,
    ...(requested.serviceTier ? { serviceTier: requested.serviceTier } : {}),
    baseUrl: requested.provider === 'ollama' ? requested.baseUrl ?? '' : '',
    features: {},
  }
}

/** Select a provider for the next calls; pass nothing for "nothing selected". */
export function selectProvider(requested) {
  current = requested?.provider ? selectionFrom(requested) : null
}

/** Wraps a gate runner stub so it also answers selection-get. */
export function withSelection(runner) {
  return async (command, input) => (command === 'selection-get'
    ? { selection: current, providers: [] }
    : runner(command, input))
}
