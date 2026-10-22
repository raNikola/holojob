import { describe, it, expect, vi, afterEach } from 'vitest'
import { EventEmitter } from 'node:events'

vi.mock('../../scripts/run-scoring.js', async (orig) => ({
  ...(await orig()),
  runScoring: vi.fn(async () => ({ ok: true })),
  runJudgedScoring: vi.fn(async () => ({ ok: true })),
}))

const scoring = await import('../../scripts/run-scoring.js')
const { handleApiRequest } = await import('../../scripts/api-handler.js')
const client = await import('../../src/modules/jobs/pipelineRunner.js')

function request(url, body) {
  const req = new EventEmitter()
  req.url = url
  req.method = 'POST'
  const res = { statusCode: 0, headers: {}, setHeader() {}, end(data) { this.body = JSON.parse(data) } }
  const done = handleApiRequest(req, res)
  req.emit('data', Buffer.from(JSON.stringify(body)))
  req.emit('end')
  return done.then(() => res)
}

afterEach(() => vi.clearAllMocks())

describe('the judge boundary on the server', () => {
  it('local scoring never judges, whatever the body says', async () => {
    await request('/api/scoring/run', { judge: true, confirm: true })
    expect(scoring.runScoring).toHaveBeenCalledWith({ minScore: undefined })
    expect(scoring.runJudgedScoring).not.toHaveBeenCalled()
  })

  it('a judged run without confirmation is refused', async () => {
    const res = await request('/api/scoring/judge', {})
    expect(res.statusCode).toBe(400)
    expect(scoring.runJudgedScoring).not.toHaveBeenCalled()
  })

  it('a confirmed judged run goes through', async () => {
    const res = await request('/api/scoring/judge', { confirm: true })
    expect(res.statusCode).toBe(200)
    expect(scoring.runJudgedScoring).toHaveBeenCalledOnce()
  })
})

describe('the judge boundary in the client', () => {
  it('runScoring posts to the local route with no judge field', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => ({}) }))
    vi.stubGlobal('fetch', fetch)
    await client.runScoring()
    expect(fetch).toHaveBeenCalledWith('/api/scoring/run', expect.objectContaining({ body: '{}' }))
    vi.unstubAllGlobals()
  })
})
