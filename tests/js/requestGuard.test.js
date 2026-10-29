import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setGateRunner } from '../../scripts/ai-gate.js'
import { handleApiRoutes } from '../../scripts/api-handler.js'
import { handleApplicationsRequest } from '../../scripts/application-store.js'
import { checkApiRequest, guardApiRequest, parseAllowedOrigins } from '../../scripts/request-guard.js'

const JSON_TYPE = { 'Content-Type': 'application/json' }

function send(base, method, url, { headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(base + url, { method, headers }, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf-8')
        let json = null
        try { json = JSON.parse(text) } catch { /* not json */ }
        resolve({ status: res.statusCode, json, text })
      })
    })
    req.on('error', reject)
    req.end(body)
  })
}

async function listen(handler) {
  const server = http.createServer(handler)
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  return { server, base: `http://127.0.0.1:${server.address().port}`, host: `127.0.0.1:${server.address().port}` }
}

describe('checkApiRequest', () => {
  const req = (method, url, headers = {}) => ({ method, url, headers })

  it('parses the allowed origins as host[:port], ignoring scheme and path', () => {
    expect(parseAllowedOrigins(' https://Holojob.Example.com/ , http://localhost:3073,,')).toEqual(['holojob.example.com', 'localhost:3073'])
    expect(parseAllowedOrigins(undefined)).toEqual([])
  })

  it('needs application/json on POST / PUT / PATCH, with parameters allowed', () => {
    for (const method of ['POST', 'PUT', 'PATCH']) {
      expect(checkApiRequest(req(method, '/api/x', { host: 'h' }), { allowedOrigins: [] })).toMatchObject({ ok: false, status: 415 })
      expect(checkApiRequest(req(method, '/api/x', { host: 'h', 'content-type': 'text/plain' }), { allowedOrigins: [] })).toMatchObject({ status: 415 })
      expect(checkApiRequest(req(method, '/api/x', { host: 'h', 'content-type': 'Application/JSON; charset=utf-8' }), { allowedOrigins: [] }).ok).toBe(true)
    }
  })

  it('lets a bodyless DELETE through but needs JSON when a DELETE carries a body', () => {
    expect(checkApiRequest(req('DELETE', '/api/cvs/x', { host: 'h' }), { allowedOrigins: [] }).ok).toBe(true)
    expect(checkApiRequest(req('DELETE', '/api/x', { host: 'h', 'content-length': '5', 'content-type': 'text/plain' }), { allowedOrigins: [] }).status).toBe(415)
  })

  it('accepts a binary type only on the two upload routes', () => {
    const opts = { allowedOrigins: [] }
    expect(checkApiRequest(req('POST', '/api/cvs', { host: 'h', 'content-type': 'application/pdf' }), opts).ok).toBe(true)
    expect(checkApiRequest(req('POST', '/api/backup/import', { host: 'h', 'content-type': 'application/zip' }), opts).ok).toBe(true)
    expect(checkApiRequest(req('POST', '/api/cvs', { host: 'h', 'content-type': 'application/json' }), opts).status).toBe(415)
    expect(checkApiRequest(req('POST', '/api/profile/save', { host: 'h', 'content-type': 'application/pdf' }), opts).status).toBe(415)
  })

  it('does not require a content type on GET', () => {
    expect(checkApiRequest(req('GET', '/api/config', { host: 'h' }), { allowedOrigins: [] }).ok).toBe(true)
  })

  it('with no list, accepts an Origin only when it is the request Host', () => {
    const opts = { allowedOrigins: [] }
    const h = { host: 'ds9:3073', 'content-type': 'application/json' }
    expect(checkApiRequest(req('POST', '/api/x', { ...h, origin: 'http://ds9:3073' }), opts).ok).toBe(true)
    expect(checkApiRequest(req('POST', '/api/x', { ...h, origin: 'https://evil.example' }), opts)).toMatchObject({ ok: false, status: 403 })
    expect(checkApiRequest(req('POST', '/api/x', { ...h, origin: 'null' }), opts).status).toBe(403)
    expect(checkApiRequest(req('GET', '/api/x', { host: 'ds9:3073', origin: 'http://evil.example' }), opts).status).toBe(403)
    expect(checkApiRequest(req('POST', '/api/x', h), opts).ok).toBe(true)
  })

  it('with a list, needs Origin and Host (or X-Forwarded-Host) on it', () => {
    const opts = { allowedOrigins: ['holojob.example.com', 'localhost:3073'] }
    const post = (headers) => checkApiRequest(req('POST', '/api/x', { 'content-type': 'application/json', ...headers }), opts)
    expect(post({ host: 'holojob.example.com', origin: 'https://holojob.example.com' }).ok).toBe(true)
    expect(post({ host: 'localhost:3073', origin: 'http://localhost:3073' }).ok).toBe(true)
    // Caddy rewrote Host to the upstream; the public name arrives in X-Forwarded-Host.
    expect(post({ host: 'ds9:5173', 'x-forwarded-host': 'holojob.example.com', origin: 'https://holojob.example.com' }).ok).toBe(true)
    expect(post({ host: 'holojob.example.com', origin: 'https://evil.example' })).toMatchObject({ status: 403, error: 'Origin not allowed' })
    // DNS rebinding: the attacker's name reaches the server, with or without an Origin.
    expect(post({ host: 'evil.example' })).toMatchObject({ status: 403, error: 'Host not allowed' })
    expect(post({ host: 'evil.example', origin: 'http://evil.example' }).status).toBe(403)
    expect(post({ host: '192.168.1.5:3073' }).status).toBe(403)
    // Same-origin by Host does not substitute for the list.
    expect(post({ host: 'ds9:3073', origin: 'http://ds9:3073' }).status).toBe(403)
  })

  it('answers with a short message that carries no request data', () => {
    const res = { headers: {}, setHeader(k, v) { this.headers[k] = v }, end(b) { this.body = b } }
    const refused = guardApiRequest(req('POST', '/api/x', { host: 'h', origin: 'http://evil.example?key=abc123abc123' }), res, { allowedOrigins: [] })
    expect(refused).toBe(true)
    expect(res.statusCode).toBe(403)
    expect(JSON.parse(res.body)).toEqual({ error: 'Origin not allowed' })
  })
})

describe('the real routes behind the guard', () => {
  let app
  let calls

  beforeEach(async () => {
    calls = []
    setGateRunner(async (command, input) => {
      calls.push({ command, input })
      return { ok: true }
    })
    app = await listen((rq, rs) => handleApiRoutes(rq, rs))
  })

  afterEach(async () => {
    setGateRunner()
    await new Promise((r) => app.server.close(r))
  })

  it('refuses a cross-origin or text/plain write before any handler runs', async () => {
    const body = JSON.stringify({ settings: { dailyLimit: 1000 }, confirm: true })
    const cross = await send(app.base, 'PUT', '/api/ai/settings', { headers: { ...JSON_TYPE, Origin: 'https://evil.example' }, body })
    expect(cross.status).toBe(403)
    const plain = await send(app.base, 'PUT', '/api/ai/settings', { headers: { 'Content-Type': 'text/plain' }, body })
    expect(plain.status).toBe(415)
    const noType = await send(app.base, 'POST', '/api/profile/save', { body })
    expect(noType.status).toBe(415)
    const crossProfile = await send(app.base, 'POST', '/api/profile/save', { headers: { ...JSON_TYPE, Origin: 'https://evil.example' }, body })
    expect(crossProfile.status).toBe(403)
    expect(calls).toEqual([])
  })

  it('still serves a same-origin JSON write to the AI settings route', async () => {
    const res = await send(app.base, 'PUT', '/api/ai/settings', {
      headers: { ...JSON_TYPE, Origin: `http://${app.host}` },
      body: JSON.stringify({ settings: { dailyLimit: 1 } }),
    })
    expect(res.status).toBe(200)
    expect(calls[0].command).toBe('settings-put')
  })

  it('still serves a same-origin read', async () => {
    const res = await send(app.base, 'GET', '/api/config', { headers: { Origin: `http://${app.host}` } })
    expect(res.status).toBe(200)
  })

  it('refuses a cross-origin read as well', async () => {
    expect((await send(app.base, 'GET', '/api/config', { headers: { Origin: 'https://evil.example' } })).status).toBe(403)
  })

  it('masks a credential in an error body', async () => {
    const res = await send(app.base, 'PUT', '/api/ai/pricing', { headers: JSON_TYPE, body: '{not json key=sk-abcdefghijklmnop' })
    expect(res.status).toBe(400)
    expect(res.text).not.toContain('sk-abcdefghijklmnop')
  })
})

describe('the tracker and migration routes behind the guard', () => {
  let root
  let app

  beforeEach(async () => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'guard-'))
    fs.mkdirSync(path.join(root, 'data/jobs'), { recursive: true })
    app = await listen(async (rq, rs) => {
      if (guardApiRequest(rq, rs)) return
      const handled = await handleApplicationsRequest(rq, rs, rq.url.split('?')[0], { root })
      if (!handled) { rs.statusCode = 418; rs.end() }
    })
  })

  afterEach(async () => {
    await new Promise((r) => app.server.close(r))
    fs.rmSync(root, { recursive: true, force: true })
  })

  it('reads and writes with a same-origin JSON request; refuses the same request from another origin', async () => {
    const same = { ...JSON_TYPE, Origin: `http://${app.host}` }
    expect((await send(app.base, 'GET', '/api/applications', { headers: { Origin: `http://${app.host}` } })).status).toBe(200)
    // The migration preview reaches the store (400 for a malformed body), not the guard.
    const preview = await send(app.base, 'POST', '/api/applications/migrate/preview', { headers: same, body: JSON.stringify({ jobs: 'x' }) })
    expect(preview.status).toBe(400)
    const settings = await send(app.base, 'POST', '/api/applications/settings', { headers: same, body: '{}' })
    expect([200, 400, 409]).toContain(settings.status)
    const before = fs.readdirSync(path.join(root, 'data'))
    const cross = await send(app.base, 'POST', '/api/applications', { headers: { ...JSON_TYPE, Origin: 'https://evil.example' }, body: '{}' })
    expect(cross.status).toBe(403)
    expect(await send(app.base, 'POST', '/api/applications', { headers: { 'Content-Type': 'text/plain' }, body: '{}' })).toMatchObject({ status: 415 })
    expect(fs.readdirSync(path.join(root, 'data'))).toEqual(before)
  })
})

describe('allowed origins from the environment', () => {
  it('uses CAREER_OS_ALLOWED_ORIGINS when no list is passed', () => {
    const saved = process.env.CAREER_OS_ALLOWED_ORIGINS
    process.env.CAREER_OS_ALLOWED_ORIGINS = 'https://holojob.example.com,http://localhost:3073'
    try {
      const headers = { host: 'holojob.example.com', origin: 'https://holojob.example.com', 'content-type': 'application/json' }
      expect(checkApiRequest({ method: 'POST', url: '/api/x', headers }).ok).toBe(true)
      expect(checkApiRequest({ method: 'POST', url: '/api/x', headers: { ...headers, origin: 'https://other.example' } }).status).toBe(403)
    } finally {
      if (saved === undefined) delete process.env.CAREER_OS_ALLOWED_ORIGINS
      else process.env.CAREER_OS_ALLOWED_ORIGINS = saved
    }
  })
})

