import { consumeSsePost } from '../operations/streamClient.js'
import { ensureApiAvailable, isApiAvailable } from '../../utils/apiAvailability.js'
import { fetchAiSelection } from './aiSelectionClient.js'
import { getFeature, isFeatureEnabled } from './aiFeatureRegistry.js'
import { buildMessages, parseAiResponse } from './aiPromptLibrary.js'
import { buildAiContext, buildAiRedactionHints } from './aiContextBuilder.js'
import { buildCacheKey, getCachedResponse, setCachedResponse } from './aiResponseCache.js'
import { trackAiUsage } from './aiUsageTracker.js'
import { mergeFeatureIntoMemory } from './aiMemory.js'

/** The selection on the server. The browser keeps no copy; with none selected, nothing is sent. */
export async function loadAiSelection() {
  const result = await fetchAiSelection()
  if (!result.ok) throw new Error(result.error)
  if (!result.data.selection) throw new Error(result.data.error || 'No AI provider selected (Settings > AI Provider)')
  return result.data.selection
}

export async function runAiFeature(featureId, { job, message, extra, skipCache = false, onLog } = {}) {
  const settings = await loadAiSelection()
  const feature = getFeature(featureId)
  if (!feature) throw new Error(`Unknown AI feature: ${featureId}`)
  if (!isFeatureEnabled(settings, featureId)) {
    throw new Error(`AI feature "${feature.label}" is disabled in Settings`)
  }

  const context = buildAiContext({ featureId, job, message, extra })
  const messages = buildMessages(featureId, context)
  const cacheKey = buildCacheKey({
    provider: settings.provider,
    model: settings.model,
    feature: featureId,
    jobId: job?.jobId,
    prompt: messages,
  })

  if (!skipCache) {
    const cached = getCachedResponse(cacheKey)
    if (cached) {
      trackAiUsage({
        provider: settings.provider,
        model: settings.model,
        feature: featureId,
        prompt: JSON.stringify(messages),
        response: cached,
        cached: true,
      })
      return { data: cached, cached: true, meta: { provider: settings.provider, model: settings.model } }
    }
  }

  const available = await ensureApiAvailable()
  if (!available) {
    throw new Error('AI features require the local API server (npm run dev or npm run start)')
  }

  const apiBody = {
    feature: featureId,
    // The hints name what the server must strip; it removes them before the prompt is built.
    context: { ...context, redactionHints: buildAiRedactionHints({ job, extra }) },
    stream: Boolean(onLog),
    // "Regenerate" asks the server for a fresh answer instead of a stored finding.
    refresh: skipCache,
  }

  let payload
  if (onLog && isApiAvailable()) {
    payload = await consumeSsePost(feature.apiPath, apiBody, {
      onEvent: (e) => {
        if (e.type === 'log' && e.line) onLog(e.line)
      },
    })
  } else {
    const res = await fetch(feature.apiPath, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(apiBody),
    })
    payload = await res.json()
    if (!res.ok) throw new Error(payload.error || 'AI request failed')
  }

  const data = payload.data || parseAiResponse(payload.text, featureId)
  setCachedResponse(cacheKey, data)
  trackAiUsage({
    provider: settings.provider,
    model: settings.model,
    feature: featureId,
    prompt: JSON.stringify(messages),
    response: data,
    cached: false,
  })
  mergeFeatureIntoMemory(featureId, data)

  return {
    data,
    cached: false,
    meta: {
      provider: settings.provider,
      model: settings.model,
      generatedAt: new Date().toISOString(),
      diskPath: payload.diskPath,
    },
  }
}

export async function fetchAiStatus() {
  if (!(await ensureApiAvailable())) return { available: false }
  try {
    const res = await fetch('/api/ai/status')
    return res.json()
  } catch {
    return { available: false }
  }
}

export async function fetchAiModels(settings) {
  if (!(await ensureApiAvailable())) return []
  const res = await fetch(`/api/ai/models?provider=${settings.provider}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings: { provider: settings.provider, ...(settings.provider === 'ollama' ? { baseUrl: settings.baseUrl } : {}) } }),
  })
  const data = await res.json()
  return data.models || []
}
