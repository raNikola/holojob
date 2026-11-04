import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { handleJobTextsRequest, resetJobHistoryCache, MAX_TEXT_IDS } from '../../scripts/job-history-read.js'
import { readJsonBody } from '../../scripts/read-body.js'

const A = 'aaaaaaaaaaaaaaaa'
const B = 'bbbbbbbbbbbbbbbb'
let root, server, base
const ledger = { version: 1, jobs: {
  [A]: { firstSeen: 'x', job: { jobId: A, description: 'Ad text of A', title: 'TITLE-CANARY' }, llmFacts: 'FACTS-CANARY' },
  [B]: { firstSeen: 'x', job: { jobId: B, description: '  ' } },
} }
const post = async (body) => {
  const res = await fetch(`${base}/api/jobs/texts`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: typeof body === 'string' ? body : JSON.stringify(body) })
  return { status: res.status, body: await res.json() }
}

beforeEach(async () => {
  resetJobHistoryCache()
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'texts-'))
  fs.mkdirSync(path.join(root, 'data/jobs'), { recursive: true })
  fs.writeFileSync(path.join(root, 'data/jobs/job_history.json'), JSON.stringify(ledger))
  server = http.createServer(async (req, res) => {
    if (!(await handleJobTextsRequest(req, res, req.url, { root, readBody: readJsonBody }))) { res.statusCode = 418; res.end('{}') }
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  base = `http://127.0.0.1:${server.address().port}`
})
afterEach(async () => { await new Promise((r) => server.close(r)); fs.rmSync(root, { recursive: true, force: true }) })

describe('POST /api/jobs/texts', () => {
  it('returns the ad text of the ids it holds and names the rest as missing, and nothing else', async () => {
    const { status, body } = await post({ jobIds: [A, B, 'cccccccccccccccc'] })
    expect(status).toBe(200)
    expect(body).toEqual({ ok: true, texts: { [A]: 'Ad text of A' }, missing: [B, 'cccccccccccccccc'] })
    const text = JSON.stringify(body)
    expect(text).not.toContain('TITLE-CANARY')
    expect(text).not.toContain('FACTS-CANARY')
  })
  it('refuses a bad body', async () => {
    expect((await post({ jobIds: [] })).status).toBe(422)
    expect((await post({ jobIds: ['../x'] })).status).toBe(422)
    expect((await post({ jobIds: Array(MAX_TEXT_IDS + 1).fill(A) })).status).toBe(422)
    expect((await post('not json')).status).toBe(400)
  })
  it('answers 503 when the ledger cannot be read', async () => {
    fs.writeFileSync(path.join(root, 'data/jobs/job_history.json'), '{broken')
    resetJobHistoryCache()
    expect((await post({ jobIds: [A] })).status).toBe(503)
  })
  it('is POST only', async () => {
    expect((await fetch(`${base}/api/jobs/texts`)).status).toBe(405)
  })
})
