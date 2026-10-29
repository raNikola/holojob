import http from 'node:http'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { handleApiRoutes } from '../../scripts/api-handler.js'
import { setAiSecret } from '../../scripts/secret-store.js'
import {
  AI_SETTINGS_KEY, clearLegacyAiKey, readLegacyAiKey,
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

describe('the legacy key after step 4', () => {
  it('"remove from this browser without moving" removes the whole entry once nothing else is in it', () => {
    data.set(AI_SETTINGS_KEY, JSON.stringify({ apiKey: CANARY }))
    expect(clearLegacyAiKey(storage)).toBe(true)
    expect(data.has(AI_SETTINGS_KEY)).toBe(false)
  })

  it('the store is untouched by reading the legacy key', () => {
    setAiSecret('openai', { key: CANARY })
    expect(readLegacyAiKey(storage)).toBeNull()
  })
})
