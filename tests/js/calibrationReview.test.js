import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { getReview, handleCalibrationRequest, reviewPaths, saveLabel } from '../../scripts/calibration-review.js'

let root
const files = () => reviewPaths(root)
const item = (n, extra = {}) => ({
  jobId: `job${n}`, title: `Title ${n}`, company: `Acme ${n}`, location: 'Remote', site: 'greenhouse',
  jobUrl: `https://example.test/${n}`, description: `Description ${n}`, ...extra,
})
const proposal = (extra = {}) => ({
  status: 'ok', functionFit: 'yes', hardRequirements: 'unknown', overall: 2, reason: 'A reason.', confidence: 'medium',
  missingInformation: [], promptVersion: 'v', blockHash: 'b', adHash: 'a', provider: 'openai', model: 'm', ...extra,
})
const body = (n, extra = {}) => ({ jobId: `job${n}`, functionFit: 'yes', hardRequirements: 'unknown', overall: 2, ...extra })

function seed({ proposals = {} } = {}) {
  fs.mkdirSync(files().dir, { recursive: true, mode: 0o700 })
  fs.writeFileSync(files().items, JSON.stringify({ version: 1, items: [item(1), item(2), item(3)] }))
  fs.writeFileSync(files().proposals, JSON.stringify({ version: 1, proposals }))
}

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'calibration-'))
})
afterEach(() => fs.rmSync(root, { recursive: true, force: true }))

describe('reading the review', () => {
  it('says there is no sample when the file is missing', () => {
    expect(() => getReview(root)).toThrow(/no calibration sample/)
  })

  it('returns the ads, the proposals and progress, and nothing else', () => {
    seed({ proposals: { job1: proposal(), job2: { status: 'invalid', error: 'x' } } })
    // A row that carries score fields must not leak them: only the whitelisted fields are copied.
    fs.writeFileSync(files().items, JSON.stringify({ version: 1, items: [item(1, { matchScore: 77, matchLabel: 'Strong', reasons: ['Capped: x'], engineShadow: { fit: 1 } }), item(2), item(3)] }))
    const review = getReview(root)
    expect(review.progress).toEqual({ total: 3, reviewed: 0 })
    expect(Object.keys(review.items[0]).sort()).toEqual(['company', 'description', 'jobId', 'jobUrl', 'label', 'location', 'proposal', 'site', 'title'])
    expect(Object.keys(review.items[0].proposal).sort()).toEqual(['confidence', 'functionFit', 'hardRequirements', 'missingInformation', 'overall', 'reason'])
    expect(review.items[1].proposal).toBeNull() // an invalid proposal is not shown
    const text = JSON.stringify(review)
    for (const word of ['matchScore', 'matchLabel', 'Capped', 'engineShadow', 'blockHash', 'promptVersion']) expect(text).not.toContain(word)
  })
})

describe('saving and resuming', () => {
  it('saves at once, resumes from the file, and works out the source on the server', async () => {
    seed({ proposals: { job1: proposal() } })
    const confirmed = await saveLabel(root, body(1))
    expect(confirmed.label.source).toBe('confirmed')
    const changed = await saveLabel(root, body(1, { overall: 3 }))
    expect(changed.label.source).toBe('changed')
    const manual = await saveLabel(root, body(2))
    expect(manual.label.source).toBe('manual') // no proposal for job2
    expect(manual.progress).toEqual({ total: 3, reviewed: 2 })
    expect(fs.statSync(files().labels).mode & 0o777).toBe(0o600)
    // a new "session" reads the same state back
    const again = getReview(root)
    expect(again.progress.reviewed).toBe(2)
    expect(again.items[0].label).toMatchObject({ overall: 3, source: 'changed' })
    expect(again.items[2].label).toBeNull()
    expect(JSON.parse(fs.readFileSync(files().labels, 'utf-8'))).toMatchObject({ version: 1, revision: 3 })
  })

  it('keeps both labels when two saves arrive together', async () => {
    seed()
    await Promise.all([saveLabel(root, body(1)), saveLabel(root, body(2, { overall: 0 }))])
    const labels = JSON.parse(fs.readFileSync(files().labels, 'utf-8')).labels
    expect(Object.keys(labels).sort()).toEqual(['job1', 'job2'])
  })

  it('does not write over a labels file it cannot read', async () => {
    seed()
    fs.writeFileSync(files().labels, '{ not json')
    await expect(saveLabel(root, body(1))).rejects.toMatchObject({ status: 500 })
    expect(fs.readFileSync(files().labels, 'utf-8')).toBe('{ not json')
  })
})

describe('input validation', () => {
  it('refuses a bad body and writes nothing', async () => {
    seed()
    const bad = [
      null, [], 'x',
      body(1, { functionFit: 'maybe' }), body(1, { hardRequirements: 'n/a' }), body(1, { overall: 4 }), body(1, { overall: '2' }),
      body(1, { overall: true }), { ...body(1), note: 'x' }, { ...body(1), source: 'confirmed' }, body(1, { jobId: '../x' }),
      body(1, { jobId: 7 }), { functionFit: 'yes', hardRequirements: 'yes', overall: 1 },
    ]
    for (const b of bad) await expect(saveLabel(root, b)).rejects.toMatchObject({ status: 400 })
    await expect(saveLabel(root, body(9))).rejects.toMatchObject({ status: 404 }) // valid shape, not in the sample
    expect(fs.existsSync(files().labels)).toBe(false)
  })
})

describe('the routes', () => {
  let server
  let base
  beforeEach(async () => {
    seed({ proposals: { job1: proposal() } })
    server = http.createServer(async (req, res) => {
      if (!(await handleCalibrationRequest(req, res, req.url.split('?')[0], { root }))) {
        res.statusCode = 404
        res.end('{}')
      }
    })
    await new Promise((r) => server.listen(0, '127.0.0.1', r))
    base = `http://127.0.0.1:${server.address().port}`
  })
  afterEach(() => new Promise((r) => server.close(r)))

  const put = (data) => fetch(`${base}/api/calibration/labels`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: typeof data === 'string' ? data : JSON.stringify(data) })

  it('answers GET review, PUT labels, and refuses other methods, other paths, bad JSON and big bodies', async () => {
    expect((await (await fetch(`${base}/api/calibration/review`)).json()).progress.total).toBe(3)
    const saved = await put(body(1))
    expect(saved.status).toBe(200)
    expect((await saved.json()).progress.reviewed).toBe(1)
    expect((await put('{bad')).status).toBe(400)
    expect((await put(body(1, { overall: 9 }))).status).toBe(400)
    expect((await put(JSON.stringify({ ...body(1), pad: 'x'.repeat(10_000) }))).status).toBe(413)
    expect((await fetch(`${base}/api/calibration/labels`)).status).toBe(404)
    expect((await fetch(`${base}/api/calibration/other`)).status).toBe(404)
    expect((await fetch(`${base}/api/jobs/state`)).status).toBe(404) // not this handler's URL
  })
})
