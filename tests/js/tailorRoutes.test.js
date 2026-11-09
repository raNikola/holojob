// The tailoring routes: nothing is sent to a provider without an explicit confirm, and the preview calls no model.
import http from 'node:http'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const runTailor = vi.fn(async () => ({ ok: true, payload: null }))
const runTailorStream = vi.fn((res) => { res.statusCode = 200; res.end('{}') })
const previewTailor = vi.fn(async () => ({ status: 200, body: { ok: true, jobs: [] } }))

vi.mock('../../scripts/run-tailor.js', async (importOriginal) => ({
  ...(await importOriginal()),
  runTailor: (...a) => runTailor(...a),
  runTailorStream: (...a) => runTailorStream(...a),
  previewTailor: (...a) => previewTailor(...a),
}))

const { handleApiRoutes } = await import('../../scripts/api-handler.js')
const { buildTailorCommand, isConfirmed } = await import('../../scripts/run-tailor.js')

let server
let base
beforeEach(async () => {
  runTailor.mockClear(); runTailorStream.mockClear(); previewTailor.mockClear()
  server = http.createServer(async (req, res) => {
    if (!(await handleApiRoutes(req, res))) { res.statusCode = 404; res.end('{}') }
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  base = `http://127.0.0.1:${server.address().port}`
})
afterEach(async () => { await new Promise((r) => server.close(r)) })

const post = (url, body) => fetch(base + url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

describe('confirm is required to tailor', () => {
  it.each(['/api/tailor/run', '/api/tailor/stream'])('%s refuses a body without confirm: true and starts nothing', async (url) => {
    for (const body of [{ jobId: 'j1' }, { jobId: 'j1', confirm: 'true' }, { jobId: 'j1', confirm: 1 }, { jobId: 'j1', confirm: false }]) {
      const res = await post(url, body)
      expect(res.status).toBe(409)
      expect((await res.json()).error).toBe('confirm_required')
    }
    expect(runTailor).not.toHaveBeenCalled()
    expect(runTailorStream).not.toHaveBeenCalled()
  })

  it('/api/tailor/run with confirm: true passes the confirmation on', async () => {
    const res = await post('/api/tailor/run', { jobId: 'j1', confirm: true })
    expect(res.status).toBe(200)
    expect(runTailor.mock.calls[0][0]).toMatchObject({ jobId: 'j1', confirm: true })
  })

  it('/api/tailor/stream with confirm: true passes the confirmation on', async () => {
    await post('/api/tailor/stream', { jobId: 'j1', confirm: true })
    expect(runTailorStream.mock.calls[0][1]).toMatchObject({ jobId: 'j1', confirm: true })
  })

  it('rule-based documents (noLlm) need no confirm and are passed on without one', async () => {
    const res = await post('/api/tailor/run', { jobId: 'j1', noLlm: true })
    expect(res.status).toBe(200)
    expect(runTailor.mock.calls[0][0]).toMatchObject({ jobId: 'j1', noLlm: true, confirm: false })
  })

  it('only the boolean true asks for rule-based documents', async () => {
    const res = await post('/api/tailor/run', { jobId: 'j1', noLlm: 'true' })
    expect(res.status).toBe(409)
  })

  it('the preview needs no confirm, never passes one, and starts no run', async () => {
    const res = await post('/api/tailor/preview', { jobId: 'j1', confirm: true })
    expect(res.status).toBe(200)
    expect(previewTailor).toHaveBeenCalledTimes(1)
    expect(previewTailor.mock.calls[0][0].confirm).toBeUndefined()
    expect(runTailor).not.toHaveBeenCalled()
    expect(runTailorStream).not.toHaveBeenCalled()
  })

  it('only the boolean true confirms', () => {
    expect(isConfirmed({ confirm: true })).toBe(true)
    for (const v of [undefined, null, 'true', 1, 'yes', {}, []]) expect(isConfirmed({ confirm: v })).toBe(false)
    expect(isConfirmed(undefined)).toBe(false)
  })

  it('the command shown to the person running it carries the flag they type themselves', () => {
    expect(buildTailorCommand({ jobId: 'j1' })).toContain('run_tailor.py --confirm --job-id j1')
  })
})
