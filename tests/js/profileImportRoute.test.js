import fs from 'node:fs'
import http from 'node:http'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { handleApiRoutes } from '../../scripts/api-handler.js'
import { IMPORT_ERRORS, MAX_PASTE_BYTES, parseImportSource, setFileRunners, setImpactRunner, setImportRunners } from '../../scripts/run-profile-import.js'
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
  const runner = async (request) => {
    seen.push(request)
    return { ok: true, draft: { source: request.source, rawText: request.text } }
  }
  setImportRunners({ paste: runner, resume_pdf: runner, linkedin_pdf: runner })
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
  it('returns the draft the runner made, and gives the runner only the text and the source', async () => {
    const res = await post({ source: 'paste', text: 'Jane Sample\nSKILLS\nPython' })
    expect(res.status).toBe(200)
    expect(res.json).toEqual({ ok: true, draft: { source: 'paste', rawText: 'Jane Sample\nSKILLS\nPython' } })
    expect(seen).toEqual([{ text: 'Jane Sample\nSKILLS\nPython', source: 'paste' }])
  })

  it.each(['resume_pdf', 'linkedin_pdf'])('reads the text of a PDF as %s with the same parser and nothing else', async (source) => {
    const res = await post({ source, text: 'JANE\nSAMPLE', fileName: 'secret-name.pdf', file: 'AAAA' })
    expect(res.status).toBe(200)
    expect(res.json.draft.source).toBe(source)
    expect(seen).toEqual([{ text: 'JANE\nSAMPLE', source }])
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

describe('POST /api/profile/import/impact', () => {
  const impactPost = (body) => new Promise((resolve, reject) => {
    const payload = typeof body === 'string' ? body : JSON.stringify(body)
    const req = http.request(`${base}/api/profile/import/impact`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) } }, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => resolve({ status: res.statusCode, text: Buffer.concat(chunks).toString('utf-8') }))
    })
    req.on('error', reject)
    req.end(payload)
  })

  it('hands the two profiles to the impact runner and answers its counts', async () => {
    let seenRequest
    setImpactRunner(async (request) => { seenRequest = request; return { ok: true, impact: { profileVersion: { changed: false } } } })
    const res = await impactPost({ before: { a: 1 }, after: { a: 2 } })
    expect(res.status).toBe(200)
    expect(JSON.parse(res.text)).toEqual({ ok: true, impact: { profileVersion: { changed: false } } })
    expect(seenRequest).toEqual({ before: { a: 1 }, after: { a: 2 } })
    setImpactRunner()
  })

  it.each([[{}], [{ before: [], after: {} }], [{ before: {}, after: 'x' }], ['not json CANARY-3']])('refuses a bad request with a fixed code and echoes nothing (%j)', async (body) => {
    setImpactRunner(async () => { throw new Error('must not run') })
    const res = await impactPost(body)
    expect(res.status).toBe(400)
    expect(JSON.parse(res.text)).toMatchObject({ ok: false, code: 'invalid_request' })
    expect(res.text).not.toContain('CANARY')
    setImpactRunner()
  })

  it('a failing runner is a fixed 500', async () => {
    setImpactRunner(async () => ({ ok: false, code: 'impact_failed' }))
    const res = await impactPost({ before: {}, after: {} })
    expect(res.status).toBe(500)
    expect(JSON.parse(res.text).code).toBe('impact_failed')
    setImpactRunner()
  })
})

describe('JSON Resume refusals reach the browser as fixed messages', () => {
  it('knows the two JSON codes and answers 422 with a message that holds no input', () => {
    for (const code of ['json_invalid', 'json_not_resume']) {
      expect(IMPORT_ERRORS[code].status).toBe(422)
      expect(IMPORT_ERRORS[code].error).toMatch(/JSON/)
    }
  })
})

describe('POST /api/profile/import/parse-docx', () => {
  const DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  const upload = (bytes, { type = DOCX } = {}) => new Promise((resolve, reject) => {
    const req = http.request(`${base}/api/profile/import/parse-docx`, { method: 'POST', headers: { 'Content-Type': type, 'Content-Length': bytes.length } }, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => resolve({ status: res.statusCode, text: Buffer.concat(chunks).toString('utf-8') }))
    })
    req.on('error', reject)
    req.end(bytes)
  })
  let files
  beforeEach(() => {
    files = []
    setFileRunners({ resume_docx: async (bytes) => { files.push(bytes); return { ok: true, draft: { source: 'resume_docx' } } } })
  })
  afterEach(() => setFileRunners())

  it('hands the bytes to the file runner and answers its draft; nothing else is passed', async () => {
    const res = await upload(Buffer.from('PK-bytes'))
    expect(res.status).toBe(200)
    expect(JSON.parse(res.text)).toEqual({ ok: true, draft: { source: 'resume_docx' } })
    expect(files).toHaveLength(1)
    expect(files[0].toString()).toBe('PK-bytes')
  })

  it('refuses an empty body, an oversized body (413, runner never called) and a wrong content type (415)', async () => {
    expect(JSON.parse((await upload(Buffer.alloc(0))).text)).toMatchObject({ ok: false, code: 'empty' })
    const big = await upload(Buffer.alloc(10 * 1024 * 1024 + 1))
    expect(big.status).toBe(413)
    expect(files).toHaveLength(0)
    expect((await upload(Buffer.from('x'), { type: 'application/json' })).status).toBe(415)
    expect((await upload(Buffer.from('x'), { type: 'application/pdf' })).status).toBe(415)
    expect(files).toHaveLength(0)
  })

  it('a parser refusal is a fixed message and nothing of the file is echoed', async () => {
    setFileRunners({ resume_docx: async () => ({ ok: false, code: 'corrupt_file' }) })
    const res = await upload(Buffer.from('CANARY-DOCX-BYTES'))
    expect(res.status).toBe(422)
    expect(JSON.parse(res.text)).toMatchObject({ ok: false, code: 'corrupt_file' })
    expect(res.text).not.toContain('CANARY')
  })

  it('the file entry point refuses what is not a Buffer, not a file source, empty or too large before any runner', async () => {
    const { parseImportFile } = await import('../../scripts/run-profile-import.js')
    expect(await parseImportFile('resume_docx', 'not a buffer')).toEqual({ ok: false, code: 'invalid_request' })
    expect(await parseImportFile('paste', Buffer.from('x'))).toEqual({ ok: false, code: 'invalid_request' })
    expect(await parseImportFile('resume_docx', Buffer.alloc(0))).toEqual({ ok: false, code: 'empty' })
    expect(await parseImportFile('resume_docx', Buffer.alloc(10 * 1024 * 1024 + 1))).toEqual({ ok: false, code: 'too_large' })
  })

  it('writes nothing to disk', async () => {
    const spies = ['writeFileSync', 'appendFileSync', 'mkdirSync', 'renameSync', 'createWriteStream', 'copyFileSync'].map((name) => vi.spyOn(fs, name))
    expect((await upload(Buffer.from('x'))).status).toBe(200)
    for (const spy of spies) expect(spy).not.toHaveBeenCalled()
    vi.restoreAllMocks()
  })
})
