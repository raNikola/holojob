import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { handleApiRoutes } from '../../scripts/api-handler.js'
import { setGateRunner } from '../../scripts/ai-gate.js'
import { setIdentitySource } from '../../scripts/ai-redact.js'
import { runAiFeature } from '../../scripts/run-ai.js'
import { getProvider } from '../../src/modules/ai/aiProviderRegistry.js'
import { setAiSecret } from '../../scripts/secret-store.js'
import {
  AI_SETTINGS_KEY, migrateAiSettingsToServer, readLegacyAiKey, readLegacyAiSettings, selectionFromForm,
} from '../../src/modules/ai/aiSettings.js'
import { CANARY, useTempSecretStore } from './helpers/secretTestStore.js'

const realFetch = globalThis.fetch
const LEVELS = ['log', 'info', 'warn', 'error', 'debug']
const JOB = { jobId: 'j1', title: 'Product Manager', company: 'Acme', description: 'Own the roadmap.' }

useTempSecretStore()

// --- a fake of the server side of the selection: the gate CLI answers selection-get / selection-put -------------

let stored // the selection file: null = missing
let fileError
let calls
let providerCalls

const FREE = new Set(['mock', 'ollama'])
const PROVIDERS = [{ name: 'mock', class: 'free' }, { name: 'openai', class: 'paid' }, { name: 'deepseek', class: 'paid' }]

function gateRunner(command, input) {
  calls.push({ command, input })
  if (command === 'reserve') return { allowed: true, id: 'c1' }
  if (command === 'usage') return { settings: {}, today: {}, month: {} }
  if (command === 'selection-get') return { selection: stored, providers: PROVIDERS, ...(fileError ? { error: fileError } : {}) }
  if (command === 'selection-put') {
    const patch = input.settings
    const unknown = Object.keys(patch || {}).filter((k) => !['provider', 'model', 'temperature', 'maxTokens', 'baseUrl', 'features'].includes(k))
    if (unknown.length) return { ok: false, errors: unknown.map((k) => `unknown setting: ${k}`) }
    const merged = { temperature: 0.3, maxTokens: 2000, baseUrl: '', features: {}, ...stored, ...patch }
    const changed = !stored || stored.provider !== merged.provider || stored.model !== merged.model
    if (changed && !FREE.has(merged.provider) && input.confirm !== true) {
      return { ok: false, needsConfirm: true, increases: [`${merged.provider} / ${merged.model} is a paid provider (paid): its calls count against your AI budget`] }
    }
    stored = merged
    return { ok: true, selection: stored, class: 'paid', increases: [] }
  }
  return { ok: true }
}

let server
let base
let logged

beforeEach(async () => {
  stored = null
  fileError = null
  calls = []
  providerCalls = []
  logged = []
  for (const level of LEVELS) vi.spyOn(console, level).mockImplementation((...args) => { logged.push(args.map(String).join(' ')) })
  setGateRunner(async (command, input) => gateRunner(command, input))
  setIdentitySource(() => ({ names: [], emails: [], phones: [], links: [] }))
  for (const name of ['openai', 'mock', 'claude-code', 'ollama', 'openrouter']) {
    vi.spyOn(getProvider(name), 'complete').mockImplementation(async (args) => {
      providerCalls.push({ provider: name, ...args })
      return { text: '{"answer":"ok"}', usage: {} }
    })
  }
  server = http.createServer(async (req, res) => {
    if (!(await handleApiRoutes(req, res))) { res.statusCode = 404; res.end('{}') }
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  base = `http://127.0.0.1:${server.address().port}`
})

afterEach(async () => {
  setGateRunner()
  setIdentitySource()
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
  await new Promise((r) => server.close(r))
})

const call = (method, url, body, headers = {}) => realFetch(base + url, {
  method,
  headers: body === undefined ? headers : { 'Content-Type': 'application/json', ...headers },
  body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
})
const viaServer = (p, init) => realFetch(base + p, init)
const run = (requested = {}) => runAiFeature({ feature: 'jobAnalysis', context: { job: JOB }, settings: requested })

describe('GET and PUT /api/ai/selection', () => {
  it('GET answers the selection, the classes and the providers this server can run', async () => {
    stored = { provider: 'mock', model: 'mock', temperature: 0.3, maxTokens: 2000, baseUrl: '', features: {} }
    const body = await (await call('GET', '/api/ai/selection')).json()
    expect(body.selection.provider).toBe('mock')
    expect(body.providers.map((p) => p.name)).toEqual(['mock', 'openai', 'deepseek'])
    expect(body.nodeProviders).toEqual(expect.arrayContaining(['claude-code', 'mock', 'ollama', 'openai', 'openrouter', 'claude', 'gemini']))
    expect(body.nodeProviders).not.toContain('deepseek')
  })

  it('maps the gate answers to 200, 400 and 409 and sends confirm only when it is exactly true', async () => {
    let res = await call('PUT', '/api/ai/selection', { settings: { provider: 'openai', model: 'gpt-x' } })
    expect(res.status).toBe(409)
    expect((await res.json()).increases[0]).toMatch(/paid provider/)
    expect(stored).toBeNull()

    for (const confirm of ['true', 1, 'yes']) {
      res = await call('PUT', '/api/ai/selection', { settings: { provider: 'openai', model: 'gpt-x' }, confirm })
      expect(res.status).toBe(409)
    }
    res = await call('PUT', '/api/ai/selection', { settings: { provider: 'openai', model: 'gpt-x' }, confirm: true })
    expect(res.status).toBe(200)
    expect(stored.provider).toBe('openai')

    res = await call('PUT', '/api/ai/selection', { settings: { provider: 'openai', temperature: 0.7 } })
    expect(res.status).toBe(200) // no change of target: no confirm
    res = await call('PUT', '/api/ai/selection', { settings: { apiKey: CANARY } })
    expect(res.status).toBe(400)
    expect(await res.text()).not.toContain(CANARY)
  })

  it('has no secret in any answer, log or the file it is handed', async () => {
    setAiSecret('openai', { key: CANARY })
    await call('PUT', '/api/ai/selection', { settings: { provider: 'mock', model: 'mock', apiKey: CANARY } })
    const texts = [await (await call('GET', '/api/ai/selection')).text(), logged.join('\n'), JSON.stringify(stored)]
    for (const t of texts) expect(t).not.toContain(CANARY)
  })

  it('sits behind the request guard and refuses other methods', async () => {
    expect((await call('PUT', '/api/ai/selection', JSON.stringify({ settings: { provider: 'mock', model: 'm' } }), { 'Content-Type': 'text/plain' })).status).toBe(415)
    expect((await call('PUT', '/api/ai/selection', { settings: { provider: 'mock', model: 'm' } }, { Origin: 'https://evil.example' })).status).toBe(403)
    expect((await call('POST', '/api/ai/selection', {})).status).toBe(405)
    expect((await call('DELETE', '/api/ai/selection')).status).toBe(405)
    expect(stored).toBeNull()
  })
})

describe('a call uses the stored selection and nothing else', () => {
  it('ignores the provider, model and limits in the request', async () => {
    stored = { provider: 'openai', model: 'gpt-stored', temperature: 0.2, maxTokens: 321, baseUrl: '', features: {} }
    setAiSecret('openai', { key: CANARY })
    const result = await run({ provider: 'mock', model: 'from-the-request', temperature: 1.9, maxTokens: 99999, apiKey: 'x' })
    expect(result.ok).toBe(true)
    expect(providerCalls).toHaveLength(1)
    expect(providerCalls[0]).toMatchObject({ provider: 'openai', model: 'gpt-stored', temperature: 0.2, maxTokens: 321 })
    expect(calls.find((c) => c.command === 'reserve').input).toMatchObject({ provider: 'openai', model: 'gpt-stored' })
  })

  it('with nothing selected it refuses, logs the refusal and calls no provider, whatever keys exist', async () => {
    setAiSecret('openai', { key: CANARY })
    vi.stubEnv('OPENAI_API_KEY', 'sk-env-0123456789abcdef')
    const result = await run({ provider: 'openai' })
    expect(result).toMatchObject({ ok: false, refused: true })
    expect(result.error).toMatch(/^No AI provider selected/)
    expect(providerCalls).toEqual([])
    expect(calls.map((c) => c.command)).not.toContain('reserve')
    expect(calls.find((c) => c.command === 'refuse').input.reason).toMatch(/^No AI provider selected/)
  })

  it('an unusable selection file refuses with its reason and does not fall back', async () => {
    fileError = 'ai-settings.json unreadable: Expecting value'
    const result = await run({ provider: 'mock' })
    expect(result.refused).toBe(true)
    expect(result.error).toContain('unreadable')
    expect(providerCalls).toEqual([])
  })

  it('a provider this server cannot run is refused, not swapped for one that works', async () => {
    stored = { provider: 'deepseek', model: 'deepseek-flash', temperature: 0.3, maxTokens: 2000, baseUrl: '', features: {} }
    setAiSecret('openai', { key: CANARY })
    const result = await run({ provider: 'openai' })
    expect(result).toMatchObject({ ok: false, refused: true })
    expect(result.error).toMatch(/deepseek is selected but the browser AI features cannot run it/)
    expect(providerCalls).toEqual([])
    expect(calls.map((c) => c.command)).not.toContain('reserve')
    expect(calls.find((c) => c.command === 'refuse').input.provider).toBe('deepseek')
  })

  it('a selected keyed provider with no key answers "No API key configured" and tries no other', async () => {
    stored = { provider: 'openai', model: 'm', temperature: 0.3, maxTokens: 2000, baseUrl: '', features: {} }
    vi.stubEnv('ANTHROPIC_API_KEY', 'sk-ant-0123456789abcdef') // a key for another provider must not matter
    setAiSecret('openrouter', { key: CANARY })
    const result = await run({})
    expect(result.error).toBe('No API key configured')
    expect(providerCalls).toEqual([])
  })

  it('takes the ollama base URL from the selection, not from the request', async () => {
    stored = { provider: 'ollama', model: 'llama3.2', temperature: 0.3, maxTokens: 2000, baseUrl: 'http://localhost:11434', features: {} }
    await run({ provider: 'ollama', baseUrl: 'http://evil.example:11434' })
    expect(providerCalls[0].baseUrl).toBe('http://localhost:11434')
  })
})

describe('the browser keeps no AI settings', () => {
  const read = (rel) => fs.readFileSync(path.resolve(rel), 'utf-8')

  it('only aiSettings.js names the legacy key, and it never writes anything but the remaining key', () => {
    const files = []
    const walk = (dir) => fs.readdirSync(dir, { withFileTypes: true }).forEach((e) => {
      const full = path.join(dir, e.name)
      if (e.isDirectory()) walk(full)
      else if (/\.(js|jsx)$/.test(e.name)) files.push(full)
    })
    walk('src')
    // src/modules/browserStorage/ is the allowlist, data that names the keys.
    const namers = files.filter((f) => !f.includes(`${path.sep}browserStorage${path.sep}`) && /job-dashboard-ai-settings|AI_SETTINGS_KEY/.test(read(f))).map((f) => f.split(path.sep).join('/'))
    expect(namers).toEqual(['src/modules/ai/aiSettings.js'])
    const source = read('src/modules/ai/aiSettings.js')
    expect(source).not.toMatch(/export function (loadAiSettings|saveAiSettings|settingsForApi)/)
    expect([...source.matchAll(/setItem\(/g)]).toHaveLength(1) // writeBack, which can only keep what is already there
  })

  it('a request carries no provider settings and no key', () => {
    const client = read('src/modules/ai/aiClient.js')
    const body = client.slice(client.indexOf('const apiBody'), client.indexOf('let payload'))
    expect(body).not.toMatch(/settings|apiKey|provider/)
  })

  it('the form sends only the fields the server stores, a base URL only for ollama', () => {
    const form = { provider: 'openai', model: 'm', temperature: 0.5, maxTokens: 10, baseUrl: 'https://x.example', apiKey: CANARY, features: { outreach: false, bogus: true } }
    const sent = selectionFromForm(form)
    expect(Object.keys(sent).sort()).toEqual(['baseUrl', 'features', 'maxTokens', 'model', 'provider', 'serviceTier', 'temperature'])
    expect(sent.baseUrl).toBe('')
    expect(sent.features.outreach).toBe(false)
    expect(sent.features).not.toHaveProperty('bogus')
    expect(JSON.stringify(sent)).not.toContain(CANARY)
    expect(selectionFromForm({ ...form, provider: 'ollama' }).baseUrl).toBe('https://x.example')
  })
})

describe('moving the browser settings to the server', () => {
  let data
  let storage

  beforeEach(() => {
    data = new Map()
    storage = { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k) }
  })
  const seed = (extra = {}) => data.set(AI_SETTINGS_KEY, JSON.stringify({
    provider: 'mock', model: 'mock', temperature: 0.5, maxTokens: 700, baseUrl: '',
    features: { outreach: false, jobAnalysis: true, bogus: 1 }, ...extra,
  }))
  const browser = () => (data.has(AI_SETTINGS_KEY) ? JSON.parse(data.get(AI_SETTINGS_KEY)) : null)

  it('removes the browser copy only after the server accepted the settings and a second read shows them stored', async () => {
    seed()
    const order = []
    const spy = async (p, init) => {
      order.push(`${init?.method || 'GET'} ${p} browser=${data.has(AI_SETTINGS_KEY) ? 'kept' : 'cleared'}`)
      return viaServer(p, init)
    }
    const result = await migrateAiSettingsToServer({ storage, fetchImpl: spy })
    expect(result).toEqual({ ok: true, keyRemains: false })
    expect(order).toEqual([
      'GET /api/ai/selection browser=kept',
      'PUT /api/ai/selection browser=kept',
      'GET /api/ai/selection browser=kept',
    ])
    expect(browser()).toBeNull()
    expect(stored).toMatchObject({ provider: 'mock', model: 'mock', temperature: 0.5, maxTokens: 700 })
    expect(stored.features).toEqual({ outreach: false, jobAnalysis: true }) // an unknown toggle is dropped, not sent
  })

  it('leaves an unmoved API key in the browser, and sends it nowhere', async () => {
    seed({ apiKey: CANARY })
    const sent = []
    const spy = async (p, init) => { sent.push(init?.body || ''); return viaServer(p, init) }
    const result = await migrateAiSettingsToServer({ storage, fetchImpl: spy })
    expect(result).toEqual({ ok: true, keyRemains: true })
    expect(browser()).toEqual({ apiKey: CANARY })
    expect(readLegacyAiKey(storage).apiKey).toBe(CANARY)
    expect(readLegacyAiSettings(storage)).toBeNull()
    expect(sent.join('\n')).not.toContain(CANARY)
    expect(JSON.stringify(stored)).not.toContain(CANARY)
  })

  it('a paid provider asks first: nothing is written or cleared without confirm', async () => {
    seed({ provider: 'openai', model: 'gpt-x' })
    const first = await migrateAiSettingsToServer({ storage, fetchImpl: viaServer })
    expect(first).toMatchObject({ ok: false, needsConfirm: true })
    expect(first.increases[0]).toMatch(/paid provider/)
    expect(stored).toBeNull()
    expect(browser().provider).toBe('openai')
    const second = await migrateAiSettingsToServer({ storage, fetchImpl: viaServer, confirm: true })
    expect(second.ok).toBe(true)
    expect(stored.provider).toBe('openai')
    expect(browser()).toBeNull()
  })

  it('asks before replacing a different selection the server already holds, and does nothing for an equal one', async () => {
    seed()
    stored = { provider: 'ollama', model: 'llama3.2', temperature: 0.3, maxTokens: 2000, baseUrl: '', features: {} }
    const conflict = await migrateAiSettingsToServer({ storage, fetchImpl: viaServer })
    expect(conflict).toMatchObject({ ok: false, conflict: true, server: { provider: 'ollama' }, browser: { provider: 'mock' } })
    expect(stored.provider).toBe('ollama')
    expect(browser()).not.toBeNull()
    expect(calls.filter((c) => c.command === 'selection-put')).toEqual([])
    expect((await migrateAiSettingsToServer({ storage, fetchImpl: viaServer, overwrite: true })).ok).toBe(true)
    expect(stored.provider).toBe('mock')

    seed()
    const before = calls.filter((c) => c.command === 'selection-put').length
    expect((await migrateAiSettingsToServer({ storage, fetchImpl: viaServer })).ok).toBe(true)
    expect(calls.filter((c) => c.command === 'selection-put')).toHaveLength(before) // already equal: no write
    expect(browser()).toBeNull()
  })

  it('leaves the browser copy when the server refuses, cannot be reached, or does not confirm', async () => {
    seed({ temperature: 9 })
    stored = null
    const refuse = async (p, init) => (init?.method === 'PUT'
      ? { ok: false, status: 400, json: async () => ({ ok: false, errors: ['temperature must be a number from 0 to 2'] }) }
      : viaServer(p, init))
    const refused = await migrateAiSettingsToServer({ storage, fetchImpl: refuse })
    expect(refused).toMatchObject({ ok: false, error: 'temperature must be a number from 0 to 2' })
    expect(browser().temperature).toBe(9)

    const down = async () => { throw new TypeError('fetch failed') }
    expect(await migrateAiSettingsToServer({ storage, fetchImpl: down })).toEqual({ ok: false, error: 'The server could not be reached' })

    seed()
    stored = null
    const lying = async (p, init) => {
      const res = await viaServer(p, init)
      if (init?.method === 'PUT') stored = null // the write did not stick
      return res
    }
    const unconfirmed = await migrateAiSettingsToServer({ storage, fetchImpl: lying })
    expect(unconfirmed.ok).toBe(false)
    expect(unconfirmed.error).toMatch(/did not confirm/)
    expect(browser()).not.toBeNull()
  })

  it('reports a copy it could not remove, and does nothing when there is none', async () => {
    expect((await migrateAiSettingsToServer({ storage, fetchImpl: viaServer })).ok).toBe(false)
    seed()
    const stuck = { getItem: storage.getItem, setItem: storage.setItem, removeItem: () => { /* does not remove */ } }
    const result = await migrateAiSettingsToServer({ storage: stuck, fetchImpl: viaServer })
    expect(result).toMatchObject({ ok: false, onServer: true })
  })
})
