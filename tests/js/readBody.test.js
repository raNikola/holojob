import fs from 'node:fs'
import http from 'node:http'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { PassThrough } from 'node:stream'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { handleApiRoutes } from '../../scripts/api-handler.js'
import { handleApplicationsRequest } from '../../scripts/application-store.js'
import { MAX_CV_BYTES } from '../../scripts/cv-store.js'
import { MAX_JSON_BODY_BYTES, MAX_LARGE_BODY_BYTES, BodyTooLargeError, readJsonBody, readRawBody } from '../../scripts/read-body.js'

// No route under test may reach the real data folder.
const mocks = vi.hoisted(() => ({
  saveProfile: vi.fn(() => ({ path: 'stub' })),
  saveCv: vi.fn((buffer) => ({ id: 'stub', size: buffer.length })),
  importZip: vi.fn(async () => ({ ok: true })),
  exportZip: vi.fn(),
  manualJobs: vi.fn(async () => ({ status: 200, body: { ok: true } })),
}))
vi.mock('../../scripts/save-profile.js', async (original) => ({ ...(await original()), saveProfileToDisk: mocks.saveProfile }))
vi.mock('../../scripts/cv-store.js', async (original) => ({ ...(await original()), saveCvFile: mocks.saveCv }))
vi.mock('../../scripts/backup-handler.js', () => ({ importBackupZip: mocks.importZip, createBackupStream: mocks.exportZip }))
vi.mock('../../scripts/run-rescrape.js', async (original) => ({ ...(await original()), withRunLock: async (action) => ({ busy: false, value: await action() }) }))
vi.mock('../../scripts/view-guard.js', async (original) => ({ ...(await original()), ensureViewCurrent: async () => ({ regenerated: false }) }))
vi.mock('../../scripts/run-manual-job.js', async (original) => ({ ...(await original()), runManualJobs: mocks.manualJobs }))

const servers = []

async function listen(handler) {
  const server = http.createServer(handler)
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  servers.push(server)
  return server.address().port
}

/** Sends the chunks one write at a time, with no Content-Length (Transfer-Encoding: chunked). */
function sendChunks(port, route, chunks, { type = 'application/json', method = 'POST' } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ port, host: '127.0.0.1', path: route, method, headers: { 'Content-Type': type } }, (res) => {
      const parts = []
      res.on('data', (c) => parts.push(c))
      res.on('end', () => resolve({ status: res.statusCode, text: Buffer.concat(parts).toString('utf-8') }))
    })
    req.on('error', reject)
    for (const chunk of chunks) req.write(chunk)
    req.end()
  })
}

function post(port, route, body, type = 'application/json') {
  return fetch(`http://127.0.0.1:${port}${route}`, { method: 'POST', headers: { 'Content-Type': type }, body })
}

const paddedJson = (bytes) => {
  const empty = JSON.stringify({ pad: '' }).length
  return JSON.stringify({ pad: 'a'.repeat(bytes - empty) })
}

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockClear()
  mocks.exportZip.mockImplementation(() => {
    const stream = new PassThrough()
    stream.end('zip')
    return stream
  })
})

afterEach(async () => {
  for (const server of servers.splice(0)) {
    server.closeAllConnections()
    await new Promise((r) => server.close(r))
  }
})

describe('readRawBody', () => {
  const LIMIT = 1000

  /** A server around the reader that records what it read and how it ended. */
  async function readerServer(options = {}) {
    const seen = { bodies: [], errors: [] }
    const port = await listen(async (req, res) => {
      try {
        const body = await readRawBody(req, res, { limit: LIMIT, ...options })
        seen.bodies.push(body)
        res.end('ok')
      } catch (e) {
        seen.errors.push(e)
      }
    })
    return { port, seen }
  }

  it('accepts a body of exactly the limit and refuses one byte more', async () => {
    const { port, seen } = await readerServer()
    expect((await post(port, '/', 'a'.repeat(LIMIT))).status).toBe(200)
    expect(seen.bodies[0].length).toBe(LIMIT)
    const over = await post(port, '/', 'a'.repeat(LIMIT + 1))
    expect(over.status).toBe(413)
    expect(await over.json()).toEqual({ error: 'Request body too large' })
    expect(seen.errors[0]).toBeInstanceOf(BodyTooLargeError)
  })

  it('adds up a body that arrives in many chunks', async () => {
    const { port, seen } = await readerServer()
    const under = await sendChunks(port, '/', Array.from({ length: 100 }, () => 'a'.repeat(10)))
    expect(under.status).toBe(200)
    expect(seen.bodies[0].length).toBe(LIMIT)
    const over = await sendChunks(port, '/', Array.from({ length: 101 }, () => 'a'.repeat(10)))
    expect(over.status).toBe(413)
    expect(seen.bodies).toHaveLength(1)
  })

  it('counts bytes, not characters', async () => {
    const { port } = await readerServer()
    expect((await sendChunks(port, '/', ['é'.repeat(LIMIT / 2)])).status).toBe(200)
    expect((await sendChunks(port, '/', ['é'.repeat(LIMIT / 2 + 1)])).status).toBe(413)
  })

  it('refuses from Content-Length without waiting for the body', async () => {
    const { port } = await readerServer()
    const socket = net.connect(port, '127.0.0.1')
    socket.write(`POST / HTTP/1.1\r\nHost: x\r\nContent-Length: ${LIMIT + 1}\r\n\r\n`)
    const answer = await new Promise((resolve) => socket.once('data', (d) => resolve(d.toString('utf-8'))))
    expect(answer).toMatch(/^HTTP\/1\.1 413/)
    socket.destroy()
  })

  it('destroys the request of a client that keeps sending after the 413', async () => {
    const { port } = await readerServer({ drainMs: 50 })
    const socket = net.connect(port, '127.0.0.1')
    socket.on('error', () => {})
    const closed = new Promise((resolve) => socket.once('close', resolve))
    socket.write('POST / HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n')
    const chunk = `${(LIMIT + 1).toString(16)}\r\n${'a'.repeat(LIMIT + 1)}\r\n`
    const answer = new Promise((resolve) => socket.once('data', (d) => resolve(d.toString('utf-8'))))
    socket.write(chunk)
    expect(await answer).toMatch(/^HTTP\/1\.1 413/)
    const timer = setInterval(() => { if (socket.writable) socket.write(chunk) }, 5)
    await closed
    clearInterval(timer)
  })

  it('closes the connection once a refused body has been read to the end', async () => {
    const { port } = await readerServer()
    const socket = net.connect(port, '127.0.0.1')
    socket.on('error', () => {})
    const closed = new Promise((resolve) => socket.once('close', resolve))
    socket.resume()
    socket.write(`POST / HTTP/1.1\r\nHost: x\r\nContent-Length: ${LIMIT + 1}\r\n\r\n${'a'.repeat(LIMIT + 1)}`)
    await closed
  })

  it('rejects when the client goes away before the body ends', async () => {
    const { port, seen } = await readerServer()
    const socket = net.connect(port, '127.0.0.1')
    await new Promise((r) => socket.write(`POST / HTTP/1.1\r\nHost: x\r\nContent-Length: ${LIMIT}\r\n\r\nabc`, r))
    socket.destroy()
    await vi.waitFor(() => expect(seen.errors).toHaveLength(1))
    expect(seen.bodies).toEqual([])
  })

  it('readJsonBody gives {} for an empty body and the parser error for bad JSON', async () => {
    const results = []
    const port = await listen(async (req, res) => {
      try {
        results.push(await readJsonBody(req, res))
      } catch (e) {
        results.push(e)
      }
      res.end()
    })
    await post(port, '/', '')
    await post(port, '/', '{bad')
    expect(results[0]).toEqual({})
    expect(results[1]).toBeInstanceOf(SyntaxError)
  })
})

describe('the /api routes', () => {
  let port

  beforeEach(async () => {
    port = await listen(async (req, res) => {
      if (!(await handleApiRoutes(req, res))) { res.statusCode = 404; res.end('{}') }
    })
  })

  it('answers 413 to an oversized JSON body and never reaches the handler', async () => {
    const res = await post(port, '/api/profile/save', paddedJson(MAX_JSON_BODY_BYTES + 1))
    expect(res.status).toBe(413)
    expect(await res.json()).toEqual({ error: 'Request body too large' })
    expect(mocks.saveProfile).not.toHaveBeenCalled()
  })

  it('counts an oversized JSON body sent in many chunks, without reaching the handler', async () => {
    const chunk = 'a'.repeat(64 * 1024)
    const chunks = ['{"pad":"', ...Array.from({ length: 17 }, () => chunk), '"}']
    const res = await sendChunks(port, '/api/profile/save', chunks)
    expect(res.status).toBe(413)
    expect(mocks.saveProfile).not.toHaveBeenCalled()
  })

  it('still works after refusing a body', async () => {
    expect((await post(port, '/api/profile/save', paddedJson(MAX_JSON_BODY_BYTES + 1))).status).toBe(413)
    const res = await post(port, '/api/profile/save', JSON.stringify({ profile: { name: 'x' } }))
    expect(res.status).toBe(200)
    expect(mocks.saveProfile).toHaveBeenCalledWith({ name: 'x' })
  })

  it('parses a normal body sent in many chunks, with a character split across two', async () => {
    const whole = Buffer.from(JSON.stringify({ profile: { name: 'Šiška €' } }))
    const res = await sendChunks(port, '/api/profile/save', Array.from(whole, (byte) => Buffer.from([byte])))
    expect(res.status).toBe(200)
    expect(mocks.saveProfile).toHaveBeenCalledWith({ name: 'Šiška €' })
  })

  it('takes a JSON body of exactly the default limit', async () => {
    const res = await post(port, '/api/profile/save', paddedJson(MAX_JSON_BODY_BYTES))
    expect(res.status).not.toBe(413)
    expect(mocks.saveProfile).toHaveBeenCalled()
  })

  it('keeps the answer to bad JSON on each kind of route', async () => {
    const parser = await post(port, '/api/profile/save', '{bad')
    expect(parser.status).toBe(400)
    expect((await parser.json()).error).toMatch(/JSON/)
    const reset = await post(port, '/api/profile/reset', '{bad')
    expect(reset.status).toBe(400)
    expect((await reset.json()).code).toBe('not_confirmed')
    const object = await fetch(`http://127.0.0.1:${port}/api/ai/settings`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: '{bad' })
    expect(object.status).toBe(400)
    expect(await object.json()).toEqual({ error: 'Body must be a JSON object' })
  })

  it('does not reset the profile on an oversized body', async () => {
    const res = await post(port, '/api/profile/reset', paddedJson(MAX_JSON_BODY_BYTES + 1))
    expect(res.status).toBe(413)
    expect(await res.json()).toEqual({ error: 'Request body too large' })
  })

  it('leaves the request guard in front: a wrong type is 415 at any size', async () => {
    const res = await post(port, '/api/profile/save', paddedJson(MAX_JSON_BODY_BYTES + 1), 'text/plain')
    expect(res.status).toBe(415)
  })

  describe('the larger limit is separate', () => {
    it('lets a backup zip past the JSON limit, up to its own', async () => {
      const zip = Buffer.alloc(MAX_JSON_BODY_BYTES + 1, 1)
      expect((await post(port, '/api/backup/import', zip, 'application/zip')).status).toBe(200)
      expect(mocks.importZip.mock.calls[0][1].length).toBe(zip.length)
    })

    it('refuses a backup zip over its own limit', async () => {
      const res = await post(port, '/api/backup/import', Buffer.alloc(MAX_LARGE_BODY_BYTES + 1, 1), 'application/zip')
      expect(res.status).toBe(413)
      expect(mocks.importZip).not.toHaveBeenCalled()
    })

    it('lets a whole job list past the JSON limit on the backup export and the manual sync', async () => {
      const list = JSON.stringify({ jobs: [{ jobId: 'a', description: 'a'.repeat(4 * 1024 * 1024) }] })
      const backup = await post(port, '/api/backup/export', list)
      expect(backup.status).toBe(200)
      await backup.arrayBuffer()
      expect(mocks.exportZip).toHaveBeenCalled()
      expect((await post(port, '/api/jobs/manual/sync', list)).status).toBe(200)
      expect(mocks.manualJobs).toHaveBeenCalled()
    })

    it('holds the single-job manual routes to the JSON limit', async () => {
      expect((await post(port, '/api/jobs/manual/score', paddedJson(MAX_JSON_BODY_BYTES + 1))).status).toBe(413)
      expect(mocks.manualJobs).not.toHaveBeenCalled()
    })

    it('lets a job list past the JSON limit on the migration routes, and only those', async () => {
      const root = fs.mkdtempSync(path.join(os.tmpdir(), 'holojob-read-body-'))
      try {
        const storePort = await listen(async (req, res) => {
          await handleApplicationsRequest(req, res, req.url, { root })
        })
        const list = JSON.stringify({ jobs: [], pad: 'a'.repeat(MAX_JSON_BODY_BYTES + 1) })
        expect((await post(storePort, '/api/applications/migrate/preview', list)).status).not.toBe(413)
        expect((await post(storePort, '/api/applications/migrate', list)).status).not.toBe(413)
        expect((await post(storePort, '/api/applications', list)).status).toBe(413)
        const bad = await post(storePort, '/api/applications', '{bad')
        expect(bad.status).toBe(400)
        expect((await bad.json()).error).toBe('Body is not valid JSON')
      } finally {
        fs.rmSync(root, { recursive: true, force: true })
      }
    })
  })

  describe('the limits a route had already', () => {
    it('CV upload: 10 MB and the same message, now as a 413', async () => {
      const ok = await post(port, '/api/cvs', Buffer.alloc(MAX_CV_BYTES, 1), 'application/pdf')
      expect(ok.status).toBe(200)
      const over = await post(port, '/api/cvs', Buffer.alloc(MAX_CV_BYTES + 1, 1), 'application/pdf')
      expect(over.status).toBe(413)
      expect(await over.json()).toEqual({ error: 'File is too large. Maximum size is 10 MB.' })
      expect(mocks.saveCv).toHaveBeenCalledTimes(1)
    })

    it('secrets stay at 8 KB and sources at 16 KB', async () => {
      const put = (route, bytes) => fetch(`http://127.0.0.1:${port}${route}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: paddedJson(bytes) })
      expect((await put('/api/secrets/linkedin', 8 * 1024 + 1)).status).toBe(413)
      expect((await put('/api/sources', 16 * 1024 + 1)).status).toBe(413)
    })

    it('profile import keeps its own code in the 413, for a chunked body too', async () => {
      const res = await sendChunks(port, '/api/profile/import/parse', Array.from({ length: 30 }, () => 'a'.repeat(64 * 1024)))
      expect(res.status).toBe(413)
      expect(JSON.parse(res.text)).toMatchObject({ ok: false, code: 'too_large' })
    })
  })
})
