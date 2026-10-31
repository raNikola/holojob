import fs from 'node:fs'
import http from 'node:http'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { handleApiRoutes } from '../../scripts/api-handler.js'
import { MAX_PASTE_BYTES, parseImportSource, setImportRunners } from '../../scripts/run-profile-import.js'
import { checkApiRequest } from '../../scripts/request-guard.js'

const ROUTE = '/api/profile/import/parse'
const CANARY = 'canary-cv-text-9f3'

let server
let base
let seen

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
  seen = []
  setImportRunners({
    paste: async (request) => {
      seen.push(request)
      return { ok: true, draft: { source: 'paste', rawText: request.text } }
    },
  })
  server = http.createServer(async (req, res) => {
    if (!(await handleApiRoutes(req, res))) { res.statusCode = 404; res.end('{}') }
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  base = `http://127.0.0.1:${server.address().port}`
})

afterEach(async () => {
  setImportRunners()
  vi.restoreAllMocks()
  await new Promise((r) => server.close(r))
})

describe('POST /api/profile/import/parse', () => {
  it('returns the draft the runner made, and gives the runner only the text', async () => {
    const res = await post({ source: 'paste', text: 'Jane Sample\nSKILLS\nPython' })
    expect(res.status).toBe(200)
    expect(res.json).toEqual({ ok: true, draft: { source: 'paste', rawText: 'Jane Sample\nSKILLS\nPython' } })
    expect(seen).toEqual([{ text: 'Jane Sample\nSKILLS\nPython' }])
  })

  it('writes nothing to disk', async () => {
    const spies = ['writeFileSync', 'appendFileSync', 'mkdirSync', 'renameSync', 'createWriteStream', 'copyFileSync'].map((name) => vi.spyOn(fs, name))
    expect((await post({ source: 'paste', text: 'x' })).status).toBe(200)
    for (const spy of spies) expect(spy).not.toHaveBeenCalled()
  })

  it('accepts JSON and refuses any other content type with 415', () => {
    const request = (type) => ({ method: 'POST', url: ROUTE, headers: { host: 'localhost:3073', 'content-type': type } })
    expect(checkApiRequest(request('application/json'), { allowedOrigins: [] })).toEqual({ ok: true })
    expect(checkApiRequest(request('application/json; charset=utf-8'), { allowedOrigins: [] })).toEqual({ ok: true })
    expect(checkApiRequest(request('text/plain'), { allowedOrigins: [] })).toMatchObject({ ok: false, status: 415 })
    expect(checkApiRequest(request('multipart/form-data'), { allowedOrigins: [] })).toMatchObject({ ok: false, status: 415 })
  })

  it('answers 415 over HTTP for text/plain without calling the runner', async () => {
    const res = await post(JSON.stringify({ source: 'paste', text: CANARY }), { type: 'text/plain' })
    expect(res.status).toBe(415)
    expect(seen).toEqual([])
    expect(res.text).not.toContain(CANARY)
  })

  it('refuses a cross-site origin', async () => {
    const res = await post({ source: 'paste', text: 'x' }, { headers: { Origin: 'https://evil.example' } })
    expect(res.status).toBe(403)
    expect(seen).toEqual([])
  })

  it('answers 400 with a fixed message for a broken body, never quoting it', async () => {
    const res = await post(`{"source": "paste", "text": "${CANARY} unterminated`)
    expect(res.status).toBe(400)
    expect(res.json).toMatchObject({ ok: false, code: 'invalid_request' })
    expect(res.text).not.toContain(CANARY)
    expect(seen).toEqual([])
  })

  it.each([
    ['unknown source', { source: 'docx', text: 'x' }],
    ['no text', { source: 'paste' }],
    ['text that is not a string', { source: 'paste', text: 5 }],
  ])('answers 400 for %s', async (_name, body) => {
    const res = await post(body)
    expect(res.status).toBe(400)
    expect(res.json.code).toBe('invalid_request')
  })

  it('answers 400 for blank text', async () => {
    const res = await post({ source: 'paste', text: ' \n\t ' })
    expect(res.status).toBe(400)
    expect(res.json.code).toBe('empty')
  })

  it('answers 413 when the text is over 200 KB, counted in bytes', async () => {
    const res = await post({ source: 'paste', text: 'é'.repeat(MAX_PASTE_BYTES / 2 + 1) })
    expect(res.status).toBe(413)
    expect(res.json.code).toBe('too_large')
    expect(seen).toEqual([])
  })

  it('answers 413 from Content-Length alone for a far larger body', async () => {
    const res = await post({ source: 'paste', text: 'a'.repeat(2 * 1024 * 1024) })
    expect(res.status).toBe(413)
    expect(seen).toEqual([])
  })

  it('accepts text at the limit even when JSON escaping inflates the body', async () => {
    const text = '"'.repeat(MAX_PASTE_BYTES)
    expect(JSON.stringify({ source: 'paste', text }).length).toBeGreaterThan(MAX_PASTE_BYTES)
    expect((await post({ source: 'paste', text })).status).toBe(200)
  })

  it('maps a runner failure to a fixed message without the text', async () => {
    setImportRunners({ paste: async () => ({ ok: false, code: 'parse_failed' }) })
    const res = await post({ source: 'paste', text: CANARY })
    expect(res.status).toBe(500)
    expect(res.json).toEqual({ ok: false, code: 'parse_failed', error: 'The text could not be read.' })
    expect(res.text).not.toContain(CANARY)
  })
})

const hasVenv = fs.existsSync('.venv/bin/python') || fs.existsSync('.venv/Scripts/python.exe')

describe.runIf(hasVenv)('the real parser behind parseImportSource', () => {
  beforeEach(() => setImportRunners())

  it('parses a CV through the Python runner', async () => {
    const result = await parseImportSource('paste', 'Jane Sample\nSenior Product Manager\njane@example.com\n\nSKILLS\nPython, SQL')
    expect(result.ok).toBe(true)
    expect(result.draft.basicProfile).toMatchObject({ fullName: 'Jane Sample', email: 'jane@example.com' })
    expect(result.draft.parsedData.skills).toEqual(['Python', 'SQL'])
  })

  it('reports a parser refusal as a code only', async () => {
    expect(await parseImportSource('paste', '\u0000\u0001')).toEqual({ ok: false, code: 'empty' })
  })
})
