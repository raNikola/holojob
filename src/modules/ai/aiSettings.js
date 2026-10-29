export const AI_SETTINGS_KEY = 'job-dashboard-ai-settings'

export const DEFAULT_AI_SETTINGS = {
  provider: 'claude-code',
  model: 'sonnet',
  temperature: 0.3,
  maxTokens: 2000,
  baseUrl: '',
  features: {
    jobAnalysis: true,
    resumeEnhancement: true,
    coverLetter: true,
    interviewPrep: true,
    outreach: true,
    careerStrategy: true,
    skillGap: true,
    applicationStrategy: true,
    companyIntelligence: true,
  },
}

export const PROVIDER_DEFAULTS = {
  'claude-code': { model: 'sonnet', baseUrl: '' },
  mock: { model: 'mock', baseUrl: '' },
  ollama: { model: 'llama3.2', baseUrl: 'http://localhost:11434' },
  openai: { model: 'gpt-6-luna', baseUrl: 'https://api.openai.com/v1' },
  claude: { model: 'claude-sonnet-4-20250514', baseUrl: 'https://api.anthropic.com' },
  gemini: { model: 'gemini-2.0-flash', baseUrl: 'https://generativelanguage.googleapis.com/v1beta' },
  openrouter: { model: 'anthropic/claude-sonnet-4', baseUrl: 'https://openrouter.ai/api/v1' },
}

export function maskApiKey(key) {
  if (!key || key.length < 8) return key ? '****' : ''
  return `${key.slice(0, 3)}****${key.slice(-4)}`
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

/** The saved settings. A key left in the browser by an older build is never part of them (see the legacy helpers below). */
export function loadAiSettings() {
  const stored = readStored()
  if (!stored) return { ...DEFAULT_AI_SETTINGS }
  const { apiKey: _legacyKey, ...rest } = stored
  return { ...DEFAULT_AI_SETTINGS, ...rest, features: { ...DEFAULT_AI_SETTINGS.features, ...rest.features } }
}

export function saveAiSettings(settings) {
  const { apiKey: _ignored, ...clean } = settings
  const merged = {
    ...DEFAULT_AI_SETTINGS,
    ...clean,
    features: { ...DEFAULT_AI_SETTINGS.features, ...settings.features },
  }
  // Never written from here. A key an older build stored stays exactly as it is until the owner moves it
  // to the server (BROWSER_STORAGE_POLICY, section 4); saving other settings must not erase the only copy.
  const legacy = readStored()?.apiKey
  localStorage.setItem(AI_SETTINGS_KEY, JSON.stringify(legacy ? { ...merged, apiKey: legacy } : merged))
  return merged
}

/** What goes to the server. No key: the server holds it. A base URL only where no credential is attached. */
export function settingsForApi(settings) {
  return {
    provider: settings.provider,
    model: settings.model,
    temperature: settings.temperature,
    maxTokens: settings.maxTokens,
    ...(settings.provider === 'ollama' ? { baseUrl: settings.baseUrl } : {}),
  }
}

/** The key an older build stored in this browser, with the provider and base URL saved beside it; null when there is none. */
export function readLegacyAiKey(storage = globalThis.localStorage) {
  const stored = readStored(storage)
  const apiKey = typeof stored?.apiKey === 'string' ? stored.apiKey : ''
  return apiKey ? { apiKey, provider: stored.provider || '', baseUrl: stored.baseUrl || '' } : null
}

/** Remove the legacy key from the browser copy, then read it back. True only when it is really gone. */
export function clearLegacyAiKey(storage = globalThis.localStorage) {
  try {
    const stored = readStored(storage)
    if (stored && 'apiKey' in stored) {
      const { apiKey: _removed, ...rest } = stored
      storage.setItem(AI_SETTINGS_KEY, JSON.stringify(rest))
    }
  } catch {
    return false
  }
  return readLegacyAiKey(storage) === null
}
