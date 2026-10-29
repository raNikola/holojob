import http from 'node:http'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { handleApiRoutes } from '../../scripts/api-handler.js'
import { setAiSecret } from '../../scripts/secret-store.js'
import {
  AI_SETTINGS_KEY, clearLegacyAiKey, loadAiSettings, readLegacyAiKey, saveAiSettings, settingsForApi,
} from '../../src/modules/ai/aiSettings.js'
import { moveLegacyKeyToServer } from '../../src/modules/ai/secretsClient.js'
import { CANARY, useTempSecretStore } from './helpers/secretTestStore.js'

const realFetch = globalThis.fetch
useTempSecretStore()

let server
let base
let data
let storage

function fakeStorage() {
  data = new Map()
  storage = {
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
  }
  globalThis.localStorage = storage
}
const stored = () => JSON.parse(data.get(AI_SETTINGS_KEY))
const seedBrowser = (extra = {}) => data.set(AI_SETTINGS_KEY, JSON.stringify({ provider: 'openai', model: 'gpt-4o', apiKey: CANARY, baseUrl: '', ...extra }))

beforeEach(async () => {
  fakeStorage()
  server = http.createServer(async (req, res) => {
    if (!(await handleApiRoutes(req, res))) { res.statusCode = 404; res.end('{}') }
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  base = `http://127.0.0.1:${server.address().port}`
})

afterEach(async () => {
  delete globalThis.localStorage
  await new Promise((r) => server.close(r))
})

const viaServer = (path, init) => realFetch(base + path, init)

describe('moving the browser key to the server', () => {
  it('clears the browser copy only after the server confirmed "set" in its store with the same last 4', async () => {
    seedBrowser({ temperature: 0.5 })
    const order = []
    const spy = async (path, init) => {
      order.push(`${init?.method} ${path} browserKey=${stored().apiKey ? 'kept' : 'cleared'}`)
      return viaServer(path, init)
    }
    const result = await moveLegacyKeyToServer({ provider: 'openai', baseUrl: '' }, { storage, fetchImpl: spy })
    expect(result).toEqual({ ok: true })
    expect(order).toEqual(['PUT /api/secrets/ai/openai browserKey=kept', 'GET /api/secrets browserKey=kept'])
    expect(stored()).toEqual({ provider: 'openai', model: 'gpt-4o', baseUrl: '', temperature: 0.5 })
    expect(readLegacyAiKey(storage)).toBeNull()
    expect(((await (await viaServer('/api/secrets')).json()).ai.openai)).toMatchObject({ set: true, source: 'store', last4: CANARY.slice(-4) })
  })

  it('leaves the browser copy when the server refuses the key', async () => {
    seedBrowser({ apiKey: 'too-short' })
    const result = await moveLegacyKeyToServer({ provider: 'openai' }, { storage, fetchImpl: viaServer })
    expect(result.ok).toBe(false)
    expect(stored().apiKey).toBe('too-short')
  })

  it('leaves the browser copy when the server cannot be reached', async () => {
    seedBrowser()
    const down = async () => { throw new TypeError('fetch failed') }
    const result = await moveLegacyKeyToServer({ provider: 'openai' }, { storage, fetchImpl: down })
    expect(result).toEqual({ ok: false, error: 'The server could not be reached' })
    expect(stored().apiKey).toBe(CANARY)
  })

  it('leaves the browser copy when the status answer is not the stored key (.env key, other last 4, not set)', async () => {
    for (const answer of [
      { ai: { openai: { set: true, source: 'env', last4: CANARY.slice(-4) } } },
      { ai: { openai: { set: true, source: 'store', last4: 'zzzz' } } },
      { ai: { openai: { set: false } } },
      {},
    ]) {
      seedBrowser()
      const lying = async (path, init) => (init?.method === 'PUT'
        ? viaServer(path, init)
        : { ok: true, status: 200, json: async () => answer })
      const result = await moveLegacyKeyToServer({ provider: 'openai' }, { storage, fetchImpl: lying })
      expect(result.ok, JSON.stringify(answer)).toBe(false)
      expect(stored().apiKey, JSON.stringify(answer)).toBe(CANARY)
    }
  })

  it('leaves the browser copy when the status call itself fails', async () => {
    seedBrowser()
    const failing = async (path, init) => (init?.method === 'PUT' ? viaServer(path, init) : { ok: false, status: 500, json: async () => ({ error: 'Secret store error' }) })
    const result = await moveLegacyKeyToServer({ provider: 'openai' }, { storage, fetchImpl: failing })
    expect(result.ok).toBe(false)
    expect(stored().apiKey).toBe(CANARY)
  })

  it('reports it when the key is on the server but cannot be removed here', async () => {
    seedBrowser()
    storage.setItem = () => { throw new Error('quota') }
    const result = await moveLegacyKeyToServer({ provider: 'openai' }, { storage, fetchImpl: viaServer })
    expect(result).toMatchObject({ ok: false, onServer: true })
    expect(stored().apiKey).toBe(CANARY)
  })

  it('needs a keyed provider chosen and a key to move, and sends nothing otherwise', async () => {
    seedBrowser()
    const never = async () => { throw new Error('must not be called') }
    expect((await moveLegacyKeyToServer({ provider: '' }, { storage, fetchImpl: never })).ok).toBe(false)
    expect((await moveLegacyKeyToServer({ provider: 'ollama' }, { storage, fetchImpl: never })).ok).toBe(false)
    data.delete(AI_SETTINGS_KEY)
    expect((await moveLegacyKeyToServer({ provider: 'openai' }, { storage, fetchImpl: never })).error).toBe('There is no key in this browser')
  })

  it('moves the base URL together with the key', async () => {
    seedBrowser({ provider: 'openrouter' })
    await moveLegacyKeyToServer({ provider: 'openrouter', baseUrl: 'https://proxy.example/v1' }, { storage, fetchImpl: viaServer })
    expect((await (await viaServer('/api/secrets')).json()).ai.openrouter.baseUrl).toBe('https://proxy.example/v1')
  })

  it('"remove from this browser without moving" clears and reads back', () => {
    seedBrowser()
    expect(clearLegacyAiKey(storage)).toBe(true)
    expect(stored().apiKey).toBeUndefined()
    expect(stored().provider).toBe('openai')
  })
})

describe('browser settings after step 2', () => {
  it('a legacy key is not part of the loaded settings, and a save neither erases nor rewrites it', () => {
    seedBrowser()
    const loaded = loadAiSettings()
    expect(loaded).not.toHaveProperty('apiKey')
    const saved = saveAiSettings({ ...loaded, apiKey: 'attempt-to-write-a-new-key', temperature: 0.9 })
    expect(saved).not.toHaveProperty('apiKey')
    expect(stored()).toMatchObject({ apiKey: CANARY, temperature: 0.9 })
  })

  it('after the move a save does not bring a key back, and a fresh browser never gets one', () => {
    seedBrowser()
    clearLegacyAiKey(storage)
    saveAiSettings({ ...loadAiSettings(), apiKey: 'stale-state-from-the-form-1234' })
    expect(stored()).not.toHaveProperty('apiKey')
    data.clear()
    saveAiSettings({ ...loadAiSettings(), apiKey: 'typed-by-an-old-form-1234567' })
    expect(JSON.stringify(stored())).not.toContain('typed-by-an-old-form')
  })

  it('requests carry no key, and a base URL only for ollama', () => {
    const settings = { provider: 'openai', model: 'm', temperature: 0.3, maxTokens: 10, apiKey: CANARY, baseUrl: 'https://x.example' }
    expect(settingsForApi(settings)).toEqual({ provider: 'openai', model: 'm', temperature: 0.3, maxTokens: 10 })
    expect(settingsForApi({ ...settings, provider: 'ollama', baseUrl: 'http://localhost:11434' }).baseUrl).toBe('http://localhost:11434')
    expect(JSON.stringify(settingsForApi(settings))).not.toContain(CANARY)
  })

  it('the store is untouched by loading and saving settings', () => {
    setAiSecret('openai', { key: CANARY })
    saveAiSettings(loadAiSettings())
    expect(readLegacyAiKey(storage)).toBeNull()
  })
})
