import { describe, it, expect, vi, afterEach } from 'vitest'
import { EventEmitter } from 'node:events'

vi.mock('../../scripts/run-cv-analyze.js', () => ({
  previewCvAnalysis: vi.fn(async () => ({ ok: true, sentText: 'redacted' })),
  runCvAnalysis: vi.fn(async () => ({ ok: true, facts: {} })),
}))

const analyze = await import('../../scripts/run-cv-analyze.js')
const { handleApiRequest } = await import('../../scripts/api-handler.js')

function request(url, body) {
  const req = new EventEmitter()
  req.url = url
  req.method = 'POST'
  const res = { statusCode: 0, setHeader() {}, end(data) { this.body = JSON.parse(data) } }
  const done = handleApiRequest(req, res)
  req.emit('data', Buffer.from(JSON.stringify(body)))
  req.emit('end')
  return done.then(() => res)
}

afterEach(() => vi.clearAllMocks())

describe('the CV analysis boundary', () => {
  it('the preview never calls the provider', async () => {
    const res = await request('/api/ai/cv-analyze/preview', { rawText: 'cv', confirm: true })
    expect(res.statusCode).toBe(200)
    expect(analyze.previewCvAnalysis).toHaveBeenCalledOnce()
    expect(analyze.runCvAnalysis).not.toHaveBeenCalled()
  })
  it('a run without confirmation is refused', async () => {
    const res = await request('/api/ai/cv-analyze', { rawText: 'cv' })
    expect(res.statusCode).toBe(400)
    expect(analyze.runCvAnalysis).not.toHaveBeenCalled()
  })
  it('a confirmed run goes through', async () => {
    const res = await request('/api/ai/cv-analyze', { rawText: 'cv', confirm: true })
    expect(res.statusCode).toBe(200)
    expect(analyze.runCvAnalysis).toHaveBeenCalledOnce()
  })
})
