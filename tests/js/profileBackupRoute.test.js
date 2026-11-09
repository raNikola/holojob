import http from 'node:http'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { handleApiRoutes } from '../../scripts/api-handler.js'

let server
let base
const post = (payload) => new Promise((resolve, reject) => {
  const body = typeof payload === 'string' ? payload : JSON.stringify(payload)
  const req = http.request(`${base}/api/profile/backup`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } }, (res) => {
    const chunks = []
    res.on('data', (c) => chunks.push(c))
    res.on('end', () => resolve({ status: res.statusCode, text: Buffer.concat(chunks).toString('utf-8') }))
  })
  req.on('error', reject)
  req.end(body)
})

beforeEach(async () => {
  server = http.createServer(async (req, res) => { if (!(await handleApiRoutes(req, res))) { res.statusCode = 404; res.end('{}') } })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  base = `http://127.0.0.1:${server.address().port}`
})
afterEach(() => new Promise((r) => server.close(r)))

// Only the refusals are exercised here: a success would write under the real data/backups.
describe('POST /api/profile/backup refusals', () => {
  it.each([[{}], [{ profile: null }], [{ profile: 'x' }], [{ profile: [] }], ['not json CANARY-77']])('answers 400 with a fixed code and echoes nothing (%j)', async (body) => {
    const res = await post(body)
    expect(res.status).toBe(400)
    expect(JSON.parse(res.text)).toEqual({ ok: false, code: 'invalid_profile', error: 'The profile to back up was not valid.' })
    expect(res.text).not.toContain('CANARY')
  })
})
