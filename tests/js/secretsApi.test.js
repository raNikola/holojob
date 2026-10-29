import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { handleApiRoutes } from '../../scripts/api-handler.js'
import { setGateRunner } from '../../scripts/ai-gate.js'
import { setIdentitySource } from '../../scripts/ai-redact.js'
import { getProvider } from '../../src/modules/ai/aiProviderRegistry.js'
import { setAiSecret } from '../../scripts/secret-store.js'
import { CANARY, useTempSecretStore } from './helpers/secretTestStore.js'

const realFetch = globalThis.fetch
const store = useTempSecretStore()
const LEVELS = ['log', 'info', 'warn', 'error', 'debug']

let server
let base
let logged
let gateCalls

beforeEach(async () => {
  logged = []
  for (const level of LEVELS) vi.spyOn(console, level).mockImplementation((...args) => { logged.push(args.map(String).join(' ')) })
  gateCalls = []
  setGateRunner(async (command, input) => {
    gateCalls.push({ command, input })
    if (command === 'reserve') return { allowed: true, id: 'c1' }
    if (command === 'usage') return { settings: {}, today: {}, month: {} }
    return { ok: true }
  })
  setIdentitySource(() => ({ names: [], emails: [], phones: [], links: [] }))
  // The providers must never reach a network, and the Claude Code health check must not start the CLI.
  vi.spyOn(getProvider('claude-code'), 'healthCheck').mockResolvedValue({ online: false, reason: 'stubbed' })
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
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  await new Promise((r) => server.close(r))
})

const call = (method, url, body, headers = {}) => realFetch(base + url, {
  method,
  headers: body === undefined ? headers : { 'Content-Type': 'application/json', ...headers },
  body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
})
const text = async (res) => `${await res.text()}\n${JSON.stringify([...res.headers])}`

function stubProviders(reply) {
  const fetchStub = vi.fn(async (url, init) => reply(String(url), init))
  vi.stubGlobal('fetch', fetchStub)
  return fetchStub
}
const ok = (data = {}) => ({ ok: true, status: 200, json: async () => data })

describe('the secret routes', () => {
  it('PUT stores a key and answers set / last 4 only; the key is never echoed', async () => {
    const res = await call('PUT', '/api/secrets/ai/openai', { key: CANARY, baseUrl: 'https://proxy.example/v1' })
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body).toMatchObject({ ok: true, provider: 'openai', secret: { set: true, source: 'store', last4: CANARY.slice(-4), baseUrl: 'https://proxy.example/v1' } })
    expect(JSON.stringify(body)).not.toContain(CANARY)
    expect(res.headers.get('cache-control')).toBe('no-store')
    expect(fs.readFileSync(path.join(store.dir, 'ai.json'), 'utf-8')).toContain(CANARY)
  })

  it('GET /api/secrets, replace and delete', async () => {
    await call('PUT', '/api/secrets/ai/gemini', { key: `${CANARY}-g` })
    let status = await (await call('GET', '/api/secrets')).json()
    expect(status.ai.gemini).toMatchObject({ set: true, last4: `${CANARY}-g`.slice(-4) })
    expect(status.ai.openai.set).toBe(false)
    await call('PUT', '/api/secrets/ai/gemini', { key: `${CANARY}-replaced` })
    status = await (await call('GET', '/api/secrets')).json()
    expect(status.ai.gemini.last4).toBe('aced')
    const del = await call('DELETE', '/api/secrets/ai/gemini')
    expect(del.status).toBe(200)
    expect((await (await call('GET', '/api/secrets')).json()).ai.gemini.set).toBe(false)
  })

  it('refuses unknown providers, other methods and other paths with fixed messages', async () => {
    expect((await call('PUT', '/api/secrets/ai/ollama', { key: CANARY })).status).toBe(404)
    expect((await call('PUT', '/api/secrets/ai/OPENAI', { key: CANARY })).status).toBe(404)
    expect((await call('DELETE', '/api/secrets/ai/mock')).status).toBe(404)
    expect((await call('POST', '/api/secrets/ai/openai', { key: CANARY })).status).toBe(405)
    expect((await call('GET', '/api/secrets/ai/openai')).status).toBe(405)
    expect((await call('PUT', '/api/secrets', { key: CANARY })).status).toBe(405)
    expect((await call('GET', '/api/secrets/linkedin')).status).toBe(405)
    expect(fs.existsSync(store.dir)).toBe(false)
  })

  it('does not echo a malformed or invalid body, and stores nothing for it', async () => {
    const attempts = [
      ['{"key":"' + CANARY, 400],
      [`[${JSON.stringify(CANARY)}]`, 400],
      [{ key: 'short' + CANARY.slice(0, 3) }, 400],
      [{ key: CANARY, baseUrl: `javascript:${CANARY}` }, 400],
      [{ key: `${CANARY} with spaces` }, 400],
    ]
    for (const [body, status] of attempts) {
      const res = await call('PUT', '/api/secrets/ai/openai', body)
      expect(res.status).toBe(status)
      expect(await text(res)).not.toContain(CANARY)
    }
    const huge = await call('PUT', '/api/secrets/ai/openai', { key: CANARY, pad: 'a'.repeat(20000) }).catch(() => ({ status: 0, text: async () => '' }))
    expect([0, 400]).toContain(huge.status)
    expect(fs.existsSync(path.join(store.dir, 'ai.json'))).toBe(false)
  })

  it('sits behind the request guard: Content-Type and Origin', async () => {
    const plain = await call('PUT', '/api/secrets/ai/openai', JSON.stringify({ key: CANARY }), { 'Content-Type': 'text/plain' })
    expect(plain.status).toBe(415)
    const foreign = await call('PUT', '/api/secrets/ai/openai', { key: CANARY }, { Origin: 'https://evil.example' })
    expect(foreign.status).toBe(403)
    const foreignDelete = await call('DELETE', '/api/secrets/ai/openai', undefined, { Origin: 'https://evil.example' })
    expect(foreignDelete.status).toBe(403)
    expect(fs.existsSync(store.dir)).toBe(false)
  })
})

describe('no response, log or ledger text contains the key', () => {
  it('every GET route, with a key stored for every provider and in .env', async () => {
    for (const p of ['openai', 'openrouter', 'claude', 'gemini']) setAiSecret(p, { key: `${CANARY}-${p}` })
    vi.stubEnv('OPENAI_API_KEY', `${CANARY}-env`)
    const seen = stubProviders(() => ok({ data: [{ id: 'gpt-x' }] }))
    for (const url of ['/api/secrets', '/api/ai/usage', '/api/ai/status', '/api/ai/models', '/api/config']) {
      const res = await call('GET', url)
      expect(await text(res), url).not.toContain(CANARY)
    }
    const models = await call('POST', '/api/ai/models', { settings: { provider: 'openai', apiKey: 'from-the-browser-1234' } })
    expect(await text(models)).not.toContain(CANARY)
    expect(seen).toHaveBeenCalled()
    expect(logged.join('\n')).not.toContain(CANARY)
  })

  it('status uses the stored key (the health card works) and answers "No API key configured" without one', async () => {
    setAiSecret('openai', { key: CANARY })
    const seen = stubProviders(() => ok({}))
    const status = await (await call('GET', '/api/ai/status')).json()
    expect(status.providers.openai.online).toBe(true)
    expect(status.providers.claude).toEqual({ online: false, reason: 'No API key configured' })
    expect(status.providers.gemini.reason).toBe('No API key configured')
    expect(status.providers.mock.online).toBe(true)
    const [url, init] = seen.mock.calls.find(([u]) => String(u).includes('openai')) ?? []
    expect(url).toBe('https://api.openai.com/v1/models')
    expect(init.headers.Authorization).toBe(`Bearer ${CANARY}`)
    expect(seen.mock.calls.every(([u]) => !String(u).includes('anthropic') && !String(u).includes('generativelanguage'))).toBe(true)
  })

  it('a provider error that quotes the key is masked in the HTTP error, the gate record and the console', async () => {
    setAiSecret('openai', { key: CANARY })
    stubProviders(() => ({ ok: false, status: 401, json: async () => ({ error: { message: `Incorrect API key provided: ${CANARY}` } }) }))
    const res = await call('POST', '/api/ai/job-analysis', { context: { job: { jobId: 'j1', title: 'PM', description: 'Own it.' } }, settings: { provider: 'openai', model: 'gpt-4o' } })
    expect(res.status).toBe(500)
    expect(await text(res)).not.toContain(CANARY)
    const finish = gateCalls.find((c) => c.command === 'finish')
    expect(finish.input.ok).toBe(false)
    expect(JSON.stringify(gateCalls)).not.toContain(CANARY)
    expect(logged.join('\n')).not.toContain(CANARY)
  })

  it('a Gemini error is masked, and the key travels in a header, not in the URL', async () => {
    setAiSecret('gemini', { key: CANARY })
    const seen = stubProviders(() => ({ ok: false, status: 400, json: async () => ({ error: { message: `API key not valid: ${CANARY}` } }) }))
    const res = await call('POST', '/api/ai/skill-gap', { context: {}, settings: { provider: 'gemini' } })
    expect(await text(res)).not.toContain(CANARY)
    const [url, init] = seen.mock.calls[0]
    expect(url).not.toContain(CANARY)
    expect(url).not.toContain('key=')
    expect(init.headers['x-goog-api-key']).toBe(CANARY)
    expect(JSON.stringify(gateCalls)).not.toContain(CANARY)
  })

  it('a request that still carries an apiKey is ignored, not stored, not logged, not answered', async () => {
    const seen = stubProviders(() => ok())
    const res = await call('POST', '/api/ai/job-analysis', {
      context: { job: { jobId: 'j1', title: 'PM', description: 'Own it.' } },
      settings: { provider: 'openai', apiKey: 'sk-from-the-browser-0123456789', baseUrl: 'https://evil.example/v1' },
    })
    const out = await text(res)
    expect(JSON.parse(out.split('\n')[0]).error).toBe('No API key configured')
    expect(out).not.toContain('from-the-browser')
    expect(seen).not.toHaveBeenCalled()
    expect(gateCalls).toEqual([])
    expect(logged.join('\n')).not.toContain('from-the-browser')
    expect(fs.existsSync(store.dir)).toBe(false)
  })
})
