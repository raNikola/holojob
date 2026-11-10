/**
 * AI settings in the browser, after BROWSER_STORAGE_POLICY step 4.
 *
 * The provider, model, temperature, max tokens, base URL (ollama) and feature toggles live on the server
 * (data/config/ai-settings.json, aiSelectionClient.js), read by the browser path and by the Python pipeline alike.
 * Nothing is written to localStorage from here. The only use of the old key is to read what an older build left in
 * it, move the non-secret part to the server (migrateAiSettingsToServer) and remove it. A key an older build stored
 * stays until the owner moves it (secretsClient.js); it is the one thing the settings migration never removes.
 */

import { fetchAiSelection, putAiSelection } from './aiSelectionClient.js'

/** The legacy browser key. Read and removed, never written. */
export const AI_SETTINGS_KEY = 'job-dashboard-ai-settings'

export const FEATURE_KEYS = [
  'jobAnalysis', 'resumeEnhancement', 'coverLetter', 'interviewPrep', 'outreach',
  'careerStrategy', 'skillGap', 'applicationStrategy', 'companyIntelligence',
]

/** Form defaults while nothing is selected on the server. They are not a selection: calls refuse until one is saved. */
export const DEFAULT_AI_SETTINGS = {
  provider: 'claude-code',
  model: 'sonnet',
  temperature: 0.3,
  maxTokens: 2000,
  serviceTier: 'standard',
  baseUrl: '',
  features: Object.fromEntries(FEATURE_KEYS.map((k) => [k, true])),
}

export const PROVIDER_DEFAULTS = {
  'claude-code': { model: 'sonnet', baseUrl: '' },
  mock: { model: 'mock', baseUrl: '' },
  ollama: { model: 'llama3.2', baseUrl: 'http://localhost:11434' },
  openai: { model: 'gpt-6-luna', baseUrl: 'https://api.openai.com/v1' },
  claude: { model: 'claude-sonnet-4-20250514', baseUrl: 'https://api.anthropic.com' },
  gemini: { model: 'gemini-2.0-flash', baseUrl: 'https://generativelanguage.googleapis.com/v1beta' },
  openrouter: { model: 'anthropic/claude-sonnet-4', baseUrl: 'https://openrouter.ai/api/v1' },
  deepseek: { model: 'deepseek-flash', baseUrl: '' },
  groq: { model: 'openai/gpt-oss-120b', baseUrl: '' },
}

export function maskApiKey(key) {
  if (!key || key.length < 8) return key ? '****' : ''
  return `${key.slice(0, 3)}****${key.slice(-4)}`
}

/** The server's selection merged over the form defaults; the defaults alone when nothing is selected. */
export function formFromSelection(selection) {
  if (!selection) return { ...DEFAULT_AI_SETTINGS, features: { ...DEFAULT_AI_SETTINGS.features } }
  return { ...DEFAULT_AI_SETTINGS, ...selection, features: { ...DEFAULT_AI_SETTINGS.features, ...selection.features } }
}

/** What the form sends: only the fields the server stores. A base URL only for ollama, which has no credential. */
export function selectionFromForm(form) {
  return {
    provider: form.provider,
    model: form.model,
    temperature: form.temperature,
    maxTokens: form.maxTokens,
    serviceTier: form.serviceTier === 'flex' ? 'flex' : 'standard',
    baseUrl: form.provider === 'ollama' ? form.baseUrl || '' : '',
    features: Object.fromEntries(FEATURE_KEYS.map((k) => [k, form.features?.[k] !== false])),
  }
}

function readStored(storage = globalThis.localStorage) {
  try {
    const raw = storage?.getItem(AI_SETTINGS_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
  } catch {
    return null
  }
}

/** The non-secret settings an older build left in this browser, or null. Never includes the key. */
export function readLegacyAiSettings(storage = globalThis.localStorage) {
  const stored = readStored(storage)
  if (!stored) return null
  const { apiKey: _key, ...rest } = stored
  return Object.keys(rest).length ? rest : null
}

/** The key an older build stored in this browser, with the provider and base URL saved beside it; null when there is none. */
export function readLegacyAiKey(storage = globalThis.localStorage) {
  const stored = readStored(storage)
  const apiKey = typeof stored?.apiKey === 'string' ? stored.apiKey : ''
  return apiKey ? { apiKey, provider: stored.provider || '', baseUrl: stored.baseUrl || '' } : null
}

function writeBack(storage, rest) {
  if (Object.keys(rest).length) storage.setItem(AI_SETTINGS_KEY, JSON.stringify(rest))
  else storage.removeItem(AI_SETTINGS_KEY)
}

/** Remove the legacy key from the browser copy, then read it back. True only when it is really gone. */
export function clearLegacyAiKey(storage = globalThis.localStorage) {
  try {
    const stored = readStored(storage)
    if (stored && 'apiKey' in stored) {
      const { apiKey: _removed, ...rest } = stored
      writeBack(storage, rest)
    }
  } catch {
    return false
  }
  return readLegacyAiKey(storage) === null
}

/** Remove the non-secret settings, keeping an unmoved key. True only when they are really gone. */
export function clearLegacyAiSettings(storage = globalThis.localStorage) {
  try {
    const stored = readStored(storage)
    if (stored) writeBack(storage, 'apiKey' in stored ? { apiKey: stored.apiKey } : {})
  } catch {
    return false
  }
  return readLegacyAiSettings(storage) === null
}

/** The legacy values as a selection the server will validate; fields it does not store are dropped. */
function payloadFromLegacy(legacy) {
  const out = {}
  for (const key of ['provider', 'model', 'temperature', 'maxTokens']) if (legacy[key] !== undefined) out[key] = legacy[key]
  if (legacy.provider === 'ollama' && typeof legacy.baseUrl === 'string') out.baseUrl = legacy.baseUrl
  if (legacy.features && typeof legacy.features === 'object') {
    out.features = Object.fromEntries(FEATURE_KEYS.filter((k) => typeof legacy.features[k] === 'boolean').map((k) => [k, legacy.features[k]]))
  }
  return out
}

function sameAsPayload(selection, payload) {
  if (!selection) return false
  const { features = {}, ...flat } = payload
  return Object.entries(flat).every(([k, v]) => selection[k] === v)
    && Object.entries(features).every(([k, v]) => selection.features?.[k] === v)
}

/**
 * The one-time move of the non-secret settings an older build left in this browser (BROWSER_STORAGE_POLICY, step 4).
 * Owner-triggered. The browser copy is removed only after the server accepted the settings AND a second read shows
 * them stored; any failure leaves it untouched. A key waiting for its own move (secretsClient.js) is never removed here.
 *
 *   confirm    the owner agreed to a paid or unknown-class provider (otherwise { needsConfirm, increases })
 *   overwrite  the owner agreed to replace a different selection the server already holds (otherwise { conflict })
 */
export async function migrateAiSettingsToServer({ storage = globalThis.localStorage, fetchImpl = globalThis.fetch, confirm = false, overwrite = false } = {}) {
  const legacy = readLegacyAiSettings(storage)
  if (!legacy) return { ok: false, error: 'There are no AI settings in this browser' }
  const payload = payloadFromLegacy(legacy)

  const current = await fetchAiSelection(fetchImpl)
  if (!current.ok) return { ok: false, error: current.error }
  const onServer = current.data.selection
  if (onServer && !sameAsPayload(onServer, payload) && !overwrite) {
    return { ok: false, conflict: true, server: { provider: onServer.provider, model: onServer.model }, browser: { provider: payload.provider, model: payload.model } }
  }

  if (!sameAsPayload(onServer, payload)) {
    const saved = await putAiSelection(payload, { confirm }, fetchImpl)
    if (saved.needsConfirm) return { ok: false, needsConfirm: true, increases: saved.increases }
    if (!saved.ok) return { ok: false, error: saved.error || (saved.errors || []).join('; ') }
    const again = await fetchAiSelection(fetchImpl)
    if (!again.ok || !sameAsPayload(again.data.selection, payload)) {
      return { ok: false, error: 'The server did not confirm the settings. They were left in this browser.' }
    }
  }

  if (!clearLegacyAiSettings(storage)) {
    return { ok: false, error: 'The settings are on the server, but could not be removed from this browser. Remove them by hand.', onServer: true }
  }
  return { ok: true, keyRemains: readLegacyAiKey(storage) !== null }
}
