import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { EventEmitter } from 'node:events'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// The real discovery fetches the ad page, starts the scraper and writes under data/outreach: never in a test.
const discover = vi.hoisted(() => vi.fn(async () => ({ ok: true, contacts: [], metadata: {} })))
vi.mock('../../scripts/run-outreach.js', () => ({
  runOutreachDiscover: discover,
  runOutreachGenerate: vi.fn(),
  getOutreachContactsFromDisk: vi.fn(() => []),
  getOutreachStats: vi.fn(() => ({})),
}))

const { handleApiRoutes } = await import('../../scripts/api-handler.js')
const { createBackupStream, importBackupZip } = await import('../../scripts/backup-handler.js')
const { scrapeLinkedInContacts, setBridgeRuntime } = await import('../../scripts/linkedin-scraper-bridge.js')
const { SecretStoreError, clearLinkedInSecret, describeSecrets, exactSecretValues, getLinkedInCookie, redactSecrets, setAiSecret, setLinkedInSecret, setSecretsRoot } = await import('../../scripts/secret-store.js')
const { maskSecrets } = await import('../../scripts/secret-mask.js')
const { moveLegacyLinkedInToServer, readLegacyLinkedInCookie } = await import('../../src/modules/outreach/linkedinCookie.js')
const { useTempSecretStore } = await import('./helpers/secretTestStore.js')

const require = createRequire(import.meta.url)
const AdmZip = require('adm-zip')
const realFetch = globalThis.fetch

// A LinkedIn canary of its own: under 32 characters and not written as li_at=..., so neither the AI canary's exact
// match nor a pattern rule can be what masks it.
const LI = 'LI-CANARY-5d2e8b9a41'
const OTHER = 'OTHER-COOKIE-77c0f3e2'

const store = useTempSecretStore()
const mode = (p) => fs.statSync(p).mode & 0o777

describe('the store entry', () => {
  it('creates data/secrets as 700 and linkedin.json as 600, atomically and without leftovers', () => {
    expect(setLinkedInSecret({ li_at: LI })).toMatchObject({ set: true, source: 'store', last4: LI.slice(-4) })
    expect(mode(store.dir)).toBe(0o700)
    expect(mode(path.join(store.dir, 'linkedin.json'))).toBe(0o600)
    expect(fs.readdirSync(store.dir)).toEqual(['linkedin.json'])
    expect(JSON.parse(fs.readFileSync(path.join(store.dir, 'linkedin.json'), 'utf-8'))).toMatchObject({ li_at: LI })
  })

  it('describes set / not set and the last 4 characters, never the value', () => {
    expect(describeSecrets().linkedin).toEqual({ set: false, source: null, last4: null, setAt: null })
    setLinkedInSecret({ li_at: LI })
    expect(JSON.stringify(describeSecrets())).not.toContain(LI)
    expect(describeSecrets().linkedin).toMatchObject({ set: true, source: 'store', last4: LI.slice(-4) })
  })

  it('keeps the AI file and the LinkedIn file apart', () => {
    setAiSecret('openai', { key: 'sk-test-0123456789abcdef' })
    setLinkedInSecret({ li_at: LI })
    clearLinkedInSecret()
    expect(describeSecrets().linkedin.set).toBe(false)
    expect(describeSecrets().ai.openai.set).toBe(true)
    expect(fs.existsSync(path.join(store.dir, 'linkedin.json'))).toBe(false)
  })

  it('falls back to LINKEDIN_LI_AT from .env, the store first', () => {
    vi.stubEnv('LINKEDIN_LI_AT', OTHER)
    expect(getLinkedInCookie()).toBe(OTHER)
    expect(describeSecrets().linkedin).toMatchObject({ set: true, source: 'env' })
    setLinkedInSecret({ li_at: LI })
    expect(getLinkedInCookie()).toBe(LI)
    vi.unstubAllEnvs()
  })

  it('refuses a bad value without quoting it, and never overwrites a file it cannot read', () => {
    for (const bad of ['short', `${LI} with space`, 123, '']) {
      let message = ''
      try { setLinkedInSecret({ li_at: bad }) } catch (e) { expect(e).toBeInstanceOf(SecretStoreError); message = e.message }
      expect(message).toMatch(/^Cookie must be/)
      expect(message).not.toContain(LI)
    }
    fs.mkdirSync(store.dir, { recursive: true, mode: 0o700 })
    fs.writeFileSync(path.join(store.dir, 'linkedin.json'), '{not json', { mode: 0o600 })
    expect(() => setLinkedInSecret({ li_at: LI })).toThrow(/cannot be read/)
    expect(() => clearLinkedInSecret()).toThrow(/cannot be read/)
    expect(fs.readFileSync(path.join(store.dir, 'linkedin.json'), 'utf-8')).toBe('{not json')
    expect(describeSecrets().unreadable).toBe(true)
  })

  it('does not carry a cached value from one store directory to the next', () => {
    setLinkedInSecret({ li_at: LI })
    const second = fs.mkdtempSync(path.join(os.tmpdir(), 'secrets2-'))
    setSecretsRoot(path.join(second, 'secrets'))
    expect(getLinkedInCookie()).toBeNull()
    fs.rmSync(second, { recursive: true, force: true })
  })
})

describe('exact-value masking', () => {
  it('masks the stored cookie and the .env one in text, errors and console output', () => {
    setLinkedInSecret({ li_at: LI })
    vi.stubEnv('LINKEDIN_LI_AT', OTHER)
    expect(exactSecretValues()).toEqual(expect.arrayContaining([LI, OTHER]))
    expect(redactSecrets(`cookie ${LI} and ${OTHER}`)).toBe('cookie [secret] and [secret]')
    expect(maskSecrets(`Error: Playwright failed with value ${LI}`)).not.toContain(LI)
    vi.unstubAllEnvs()
  })
})

describe('the routes', () => {
  let server
  let base
  let logged

  beforeEach(async () => {
    logged = []
    for (const level of ['log', 'info', 'warn', 'error', 'debug']) vi.spyOn(console, level).mockImplementation((...a) => { logged.push(a.map(String).join(' ')) })
    discover.mockClear()
    server = http.createServer(async (req, res) => {
      if (!(await handleApiRoutes(req, res))) { res.statusCode = 404; res.end('{}') }
    })
    await new Promise((r) => server.listen(0, '127.0.0.1', r))
    base = `http://127.0.0.1:${server.address().port}`
  })
  afterEach(async () => {
    vi.restoreAllMocks()
    await new Promise((r) => server.close(r))
  })

  const call = (method, url, body, headers = {}) => realFetch(base + url, {
    method,
    headers: body === undefined ? headers : { 'Content-Type': 'application/json', ...headers },
    body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
  })

  it('PUT stores, GET reports set and last 4, DELETE removes; the value is never in an answer', async () => {
    const put = await call('PUT', '/api/secrets/linkedin', { li_at: LI })
    expect(put.status).toBe(200)
    const body = await put.json()
    expect(body).toMatchObject({ ok: true, secret: { set: true, source: 'store', last4: LI.slice(-4) } })
    expect(JSON.stringify(body)).not.toContain(LI)
    const status = await (await call('GET', '/api/secrets')).json()
    expect(status.linkedin).toMatchObject({ set: true, last4: LI.slice(-4) })
    expect(JSON.stringify(status)).not.toContain(LI)
    const del = await call('DELETE', '/api/secrets/linkedin')
    expect(del.status).toBe(200)
    expect((await (await call('GET', '/api/secrets')).json()).linkedin.set).toBe(false)
    expect(logged.join('\n')).not.toContain(LI)
  })

  it('answers a bad body and a wrong method with fixed text, and stores nothing', async () => {
    for (const body of [{ li_at: 'short' }, { li_at: `${LI} x` }, `{"li_at":"${LI}`, [LI]]) {
      const res = await call('PUT', '/api/secrets/linkedin', body)
      expect(res.status).toBe(400)
      expect(await res.text()).not.toContain(LI)
    }
    expect((await call('POST', '/api/secrets/linkedin', { li_at: LI })).status).toBe(405)
    expect((await call('GET', '/api/secrets/linkedin')).status).toBe(405)
    expect(fs.existsSync(path.join(store.dir, 'linkedin.json'))).toBe(false)
  })

  it('sits behind the request guard', async () => {
    expect((await call('PUT', '/api/secrets/linkedin', JSON.stringify({ li_at: LI }), { 'Content-Type': 'text/plain' })).status).toBe(415)
    expect((await call('PUT', '/api/secrets/linkedin', { li_at: LI }, { Origin: 'https://evil.example' })).status).toBe(403)
    expect((await call('DELETE', '/api/secrets/linkedin', undefined, { Origin: 'https://evil.example' })).status).toBe(403)
    expect(fs.existsSync(store.dir)).toBe(false)
  })

  it('POST /api/outreach/discover ignores liAt / li_at in the body: the run gets no cookie and nothing is logged', async () => {
    const res = await call('POST', '/api/outreach/discover', {
      job: { jobId: 'j1', company: 'Acme' }, deep: true, acceptTosRisk: true, liAt: LI, li_at: LI, cookie: LI,
    })
    expect(res.status).toBe(200)
    expect(discover).toHaveBeenCalledTimes(1)
    const arg = discover.mock.calls[0][0]
    expect(JSON.stringify(arg)).not.toContain(LI)
    expect(arg).not.toHaveProperty('liAt')
    expect(logged.join('\n')).not.toContain(LI)
  })
})

describe('the scraper process', () => {
  function fakeSpawn(lines = ['{"contacts":[],"queriesRun":0,"mode":"search"}'], stderr = '') {
    const calls = []
    const spawn = vi.fn((cmd, argv, options) => {
      calls.push({ cmd, argv, env: options.env })
      const child = new EventEmitter()
      child.stdout = new EventEmitter()
      child.stderr = new EventEmitter()
      child.kill = vi.fn()
      setImmediate(() => {
        for (const l of lines) child.stdout.emit('data', `${l}\n`)
        if (stderr) child.stderr.emit('data', stderr)
        child.emit('close', 0)
      })
      return child
    })
    return { spawn, calls }
  }
  beforeEach(() => { vi.stubEnv('LINKEDIN_LI_AT', ''); })
  afterEach(() => { setBridgeRuntime(); vi.unstubAllEnvs() })

  const job = { company: 'Acme' }

  it('deep mode: argv holds no cookie and no --li-at flag; the child environment holds the stored one', async () => {
    setLinkedInSecret({ li_at: LI })
    const { spawn, calls } = fakeSpawn()
    setBridgeRuntime({ spawn, pythonExists: () => true })
    await scrapeLinkedInContacts(job, { mode: 'deep', acceptTosRisk: true, liAt: OTHER })
    expect(calls).toHaveLength(1)
    const argv = [calls[0].cmd, ...calls[0].argv]
    expect(argv.join('\n')).not.toContain(LI)
    expect(argv.join('\n')).not.toContain(OTHER)
    expect(argv.some((a) => /li-at/i.test(a))).toBe(false)
    expect(argv).toContain('--i-accept-tos-risk')
    expect(calls[0].env.LINKEDIN_LI_AT).toBe(LI) // the store's value, not an option passed in
  })

  it('search mode: the child gets no cookie, not even the one from .env', async () => {
    setLinkedInSecret({ li_at: LI })
    vi.stubEnv('LINKEDIN_LI_AT', OTHER)
    const { spawn, calls } = fakeSpawn()
    setBridgeRuntime({ spawn, pythonExists: () => true })
    await scrapeLinkedInContacts(job, { mode: 'search' })
    expect(calls[0].env).not.toHaveProperty('LINKEDIN_LI_AT')
    expect([calls[0].cmd, ...calls[0].argv].join('\n')).not.toContain(LI)
  })

  it('deep mode without a stored cookie does not start the scraper', async () => {
    const { spawn } = fakeSpawn()
    setBridgeRuntime({ spawn, pythonExists: () => true })
    const result = await scrapeLinkedInContacts(job, { mode: 'deep', acceptTosRisk: true, liAt: OTHER })
    expect(result.error).toMatch(/Settings/)
    expect(spawn).not.toHaveBeenCalled()
  })

  it('masks the cookie in the scraper\'s stderr and error text before they leave the bridge', async () => {
    setLinkedInSecret({ li_at: LI })
    const crash = fakeSpawn([], `Traceback ... cookie ${LI} rejected`)
    setBridgeRuntime({ spawn: crash.spawn, pythonExists: () => true })
    const a = await scrapeLinkedInContacts(job, { mode: 'deep', acceptTosRisk: true })
    expect(JSON.stringify(a)).not.toContain(LI)
    expect(a.error).toContain('[secret]')
    const reported = fakeSpawn([`{"contacts":[],"queriesRun":0,"error":"bad cookie ${LI}"}`])
    setBridgeRuntime({ spawn: reported.spawn, pythonExists: () => true })
    const b = await scrapeLinkedInContacts(job, { mode: 'deep', acceptTosRisk: true })
    expect(JSON.stringify(b)).not.toContain(LI)
  })
})

describe('the one-time move from the browser', () => {
  let server
  let base
  let data
  let storage

  beforeEach(async () => {
    data = new Map()
    storage = { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k) }
    server = http.createServer(async (req, res) => {
      if (!(await handleApiRoutes(req, res))) { res.statusCode = 404; res.end('{}') }
    })
    await new Promise((r) => server.listen(0, '127.0.0.1', r))
    base = `http://127.0.0.1:${server.address().port}`
  })
  afterEach(async () => { await new Promise((r) => server.close(r)) })

  const viaServer = (p, init) => realFetch(base + p, init)

  it('removes the browser copy only after the server confirmed "set" in its store with the same last 4', async () => {
    data.set('linkedin_li_at', LI)
    const order = []
    const spy = async (p, init) => {
      order.push(`${init?.method} ${p} browser=${data.has('linkedin_li_at') ? 'kept' : 'cleared'}`)
      return viaServer(p, init)
    }
    expect(await moveLegacyLinkedInToServer({ storage, fetchImpl: spy })).toEqual({ ok: true })
    expect(order).toEqual(['PUT /api/secrets/linkedin browser=kept', 'GET /api/secrets browser=kept'])
    expect(data.has('linkedin_li_at')).toBe(false)
    expect(readLegacyLinkedInCookie(storage)).toBeNull()
    expect(getLinkedInCookie()).toBe(LI)
  })

  it('leaves the browser copy when the server refuses, cannot be reached, or does not confirm', async () => {
    data.set('linkedin_li_at', 'short')
    expect((await moveLegacyLinkedInToServer({ storage, fetchImpl: viaServer })).ok).toBe(false)
    expect(data.get('linkedin_li_at')).toBe('short')

    data.set('linkedin_li_at', LI)
    const down = async () => { throw new TypeError('fetch failed') }
    expect(await moveLegacyLinkedInToServer({ storage, fetchImpl: down })).toEqual({ ok: false, error: 'The server could not be reached' })
    expect(data.get('linkedin_li_at')).toBe(LI)

    for (const answer of [
      { linkedin: { set: true, source: 'env', last4: LI.slice(-4) } },
      { linkedin: { set: true, source: 'store', last4: 'zzzz' } },
      { linkedin: { set: false } },
      {},
    ]) {
      const fake = async (p, init) => (init?.method === 'PUT'
        ? viaServer(p, init)
        : { ok: true, status: 200, json: async () => answer })
      const result = await moveLegacyLinkedInToServer({ storage, fetchImpl: fake })
      expect(result.ok, JSON.stringify(answer)).toBe(false)
      expect(data.get('linkedin_li_at')).toBe(LI)
    }
  })

  it('does nothing when there is no browser copy, and reports a copy it could not remove', async () => {
    expect((await moveLegacyLinkedInToServer({ storage, fetchImpl: viaServer })).ok).toBe(false)
    data.set('linkedin_li_at', LI)
    const stuck = { getItem: storage.getItem, setItem: storage.setItem, removeItem: () => { /* does not remove */ } }
    const result = await moveLegacyLinkedInToServer({ storage: stuck, fetchImpl: viaServer })
    expect(result).toMatchObject({ ok: false, onServer: true })
  })
})

describe('backup export and restore with a real store file', () => {
  let root
  beforeEach(() => { root = fs.mkdtempSync(path.join(os.tmpdir(), 'backup-li-')) })
  afterEach(() => { fs.rmSync(root, { recursive: true, force: true }) })

  it('exports no entry and no byte of it; a restore refuses the file and leaves its bytes and mode alone', async () => {
    const dir = path.join(root, 'data/secrets')
    setSecretsRoot(dir)
    setLinkedInSecret({ li_at: LI })
    fs.mkdirSync(path.join(root, 'data/profile'), { recursive: true })
    fs.writeFileSync(path.join(root, 'data/profile/candidate-profile.json'), '{"name":"x"}')

    const chunks = []
    for await (const c of createBackupStream(root, { profile: { name: 'x' } })) chunks.push(c)
    const zip = new AdmZip(Buffer.concat(chunks))
    const names = zip.getEntries().map((e) => e.entryName)
    expect(names).toContain('data/profile/candidate-profile.json')
    expect(names.filter((n) => n.includes('secrets') || n.includes('linkedin'))).toEqual([])
    for (const entry of zip.getEntries()) expect(entry.getData().toString('utf-8')).not.toContain(LI)

    const file = path.join(dir, 'linkedin.json')
    const before = fs.readFileSync(file, 'utf-8')
    const attack = new AdmZip()
    attack.addFile('data/secrets/linkedin.json', Buffer.from('{"li_at":"attacker-cookie-0123456789"}'))
    attack.addFile('data/outreach/linkedin_session.json', Buffer.from('{"li_at":"attacker-cookie-0123456789"}'))
    const result = await importBackupZip(root, attack.toBuffer())
    expect(result.refused.sort()).toEqual(['data/outreach/linkedin_session.json', 'data/secrets/linkedin.json'])
    expect(result.restored).toEqual([])
    expect(fs.readFileSync(file, 'utf-8')).toBe(before)
    expect(mode(file)).toBe(0o600)
    expect(fs.existsSync(path.join(root, 'data/outreach'))).toBe(false)
  })
})
