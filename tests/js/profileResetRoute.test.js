import http from 'node:http'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { handleApiRoutes } from '../../scripts/api-handler.js'
import { setProfileResetRunner } from '../../scripts/profile-reset.js'

const ROUTE = '/api/profile/reset'
let server
let base
let calls

function post(body, { type = 'application/json', headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const payload = typeof body === 'string' ? body : JSON.stringify(body)
    const req = http.request(base + ROUTE, { method: 'POST', headers: { 'Content-Type': type, 'Content-Length': Buffer.byteLength(payload), ...headers } }, (res) => {
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
    req.end(payload)
  })
}

beforeEach(async () => {
  calls = 0
  setProfileResetRunner(() => { calls += 1; return { ok: true, backup: 'profile.bak-20261101-090507', moved: 3 } })
  server = http.createServer(async (req, res) => {
    if (!(await handleApiRoutes(req, res))) { res.statusCode = 404; res.end('{}') }
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  base = `http://127.0.0.1:${server.address().port}`
})

afterEach(async () => {
  setProfileResetRunner()
  await new Promise((r) => server.close(r))
})

describe('POST /api/profile/reset', () => {
  it('resets when the body carries the word RESET and answers with a relative backup path', async () => {
    const res = await post({ confirm: 'RESET' })
    expect(res.status).toBe(200)
    expect(res.json).toEqual({ ok: true, backup: 'data/profile.bak-20261101-090507' })
    expect(calls).toBe(1)
  })

  it.each([{}, { confirm: 'reset' }, { confirm: true }, { confirm: 'RESET ' }])('refuses %j without running', async (body) => {
    const res = await post(body)
    expect(res.status).toBe(400)
    expect(res.json.code).toBe('not_confirmed')
    expect(calls).toBe(0)
  })

  it('refuses a body that is not JSON, naming nothing from it', async () => {
    const res = await post('canary-profile-text-7c1')
    expect(res.status).toBe(400)
    expect(res.text).not.toContain('canary-profile-text-7c1')
    expect(calls).toBe(0)
  })

  it('refuses text/plain with 415 before the runner is reached (request guard)', async () => {
    const res = await post(JSON.stringify({ confirm: 'RESET' }), { type: 'text/plain' })
    expect(res.status).toBe(415)
    expect(calls).toBe(0)
  })

  it('refuses a foreign Origin with 403', async () => {
    const res = await post({ confirm: 'RESET' }, { headers: { Origin: 'https://evil.example' } })
    expect(res.status).toBe(403)
    expect(calls).toBe(0)
  })

  it('answers a failed backup with a fixed message that holds no profile content', async () => {
    setProfileResetRunner(() => ({ ok: false, code: 'backup_failed' }))
    const res = await post({ confirm: 'RESET' })
    expect(res.status).toBe(500)
    expect(res.json).toEqual({ ok: false, code: 'backup_failed', error: 'The backup could not be made, so nothing was removed.' })
  })

  it('is idempotent: a second reset with nothing left still answers ok', async () => {
    setProfileResetRunner(() => ({ ok: true, backup: null, moved: 0 }))
    const res = await post({ confirm: 'RESET' })
    expect(res.json).toEqual({ ok: true, backup: null })
  })
})
