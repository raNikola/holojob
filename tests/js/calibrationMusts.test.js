import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { getMusts, handleMustRequest, mustPaths, saveMust } from '../../scripts/calibration-musts.js'
import { getReview, handleCalibrationRequest, reviewPaths, saveLabel } from '../../scripts/calibration-review.js'

let root
const files = () => mustPaths(root)
const sha = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const sample = (n, extra = {}) => ({
  itemId: `i${String(n).padStart(2, '0')}`, jobId: `job${n % 2 + 1}`, reqId: `r${n}`, kind: 'skill', importance: 'must', text: `Requirement ${n}`,
  postingQuote: `Quote ${n}`, mode: 'production_like', class: 'disagree', probe: false,
  verdict: { status: 'MISSING', strength: 0, evidenceQuote: `Engine evidence ${n}` }, title: 'T', company: 'C', ...extra,
})
const ad = (n) => ({ jobId: `job${n}`, title: `Title ${n}`, company: `Acme ${n}`, location: 'Remote', site: 'x', jobUrl: `https://example.test/${n}`, description: `Ad text ${n}` })
const body = (n, extra = {}) => ({ itemId: `i${String(n).padStart(2, '0')}`, isMust: 'yes', meets: 'partial', ...extra })

function seed() {
  fs.mkdirSync(files().dir, { recursive: true, mode: 0o700 })
  fs.writeFileSync(files().sample, JSON.stringify({ version: 1, items: [sample(1), sample(2, { probe: true, importance: 'nice' }), sample(3)] }))
  fs.writeFileSync(files().ads, JSON.stringify({ version: 1, items: [ad(1), ad(2), ad(3)] }))
}

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'musts-'))
})
afterEach(() => fs.rmSync(root, { recursive: true, force: true }))

describe('blind first', () => {
  it('says there is no sample when the file is missing', () => {
    expect(() => getMusts(root)).toThrow(/no must-have sample/)
  })

  it('never returns the verdict, the importance, the class, the mode or the probe flag before an answer', () => {
    seed()
    const review = getMusts(root)
    expect(Object.keys(review.items[0]).sort()).toEqual(['itemId', 'jobId', 'kind', 'label', 'postingQuote', 'reveal', 'text'])
    const text = JSON.stringify(review)
    for (const word of ['MISSING', 'Engine evidence', 'verdict', 'importance', 'probe', 'production_like', 'disagree', 'strength', 'class']) {
      expect(text).not.toContain(word)
    }
    expect(review.items.every((i) => i.reveal === null && i.label === null)).toBe(true)
    expect(review.progress).toEqual({ total: 3, answered: 0 })
    expect(Object.keys(review.ads).sort()).toEqual(['job1', 'job2'])
  })

  it('returns the verdict with the save, and with a later read of that item only', async () => {
    seed()
    const saved = await saveMust(root, body(1))
    expect(saved.reveal).toEqual({ status: 'MISSING', strength: 0, evidenceQuote: 'Engine evidence 1' })
    const again = getMusts(root)
    expect(again.items[0].reveal.status).toBe('MISSING')
    expect(again.items[2].reveal).toBeNull() // the next item is still blind
    expect(JSON.stringify(again.items[2])).not.toContain('Engine evidence')
  })
})

describe('saving', () => {
  it('keeps the first answer for good and flags a change after the reveal', async () => {
    seed()
    const first = await saveMust(root, body(1))
    expect(first.label).toMatchObject({ changedAfterReveal: false, first: { isMust: 'yes', meets: 'partial' } })
    const same = await saveMust(root, body(1))
    expect(same.label.changedAfterReveal).toBe(false)
    const changed = await saveMust(root, body(1, { isMust: 'nice', meets: 'no' }))
    expect(changed.label.first).toMatchObject({ isMust: 'yes', meets: 'partial' })
    expect(changed.label.final).toMatchObject({ isMust: 'nice', meets: 'no' })
    expect(changed.label.changedAfterReveal).toBe(true)
    const back = await saveMust(root, body(1)) // changing it back is not a change from the first answer
    expect(back.label.changedAfterReveal).toBe(false)
    expect(fs.statSync(files().labels).mode & 0o777).toBe(0o600)
    expect(JSON.parse(fs.readFileSync(files().labels, 'utf-8'))).toMatchObject({ version: 1, revision: 4 })
  })

  it('keeps both labels when two saves arrive together, and does not write over an unreadable file', async () => {
    seed()
    await Promise.all([saveMust(root, body(1)), saveMust(root, body(3, { isMust: 'no' }))])
    expect(Object.keys(JSON.parse(fs.readFileSync(files().labels, 'utf-8')).labels).sort()).toEqual(['i01', 'i03'])
    fs.writeFileSync(files().labels, '{ not json')
    await expect(saveMust(root, body(1))).rejects.toMatchObject({ status: 500 })
    expect(fs.readFileSync(files().labels, 'utf-8')).toBe('{ not json')
  })

  it('refuses a bad body and writes nothing', async () => {
    seed()
    const bad = [null, [], 'x', body(1, { isMust: 'maybe' }), body(1, { meets: 'n/a' }), { ...body(1), note: 'x' }, { ...body(1), verdict: 'MET' },
      body(1, { itemId: '../x' }), body(1, { itemId: 5 }), { isMust: 'yes', meets: 'yes' }]
    for (const b of bad) await expect(saveMust(root, b)).rejects.toMatchObject({ status: 400 })
    await expect(saveMust(root, body(9))).rejects.toMatchObject({ status: 404 })
    expect(fs.existsSync(files().labels)).toBe(false)
  })
})

describe('the existing review and its labels file stay untouched', () => {
  it('leaves ran-labels.json byte-identical through a full must-labelling session, and the review still works', async () => {
    seed()
    fs.writeFileSync(reviewPaths(root).items, JSON.stringify({ version: 1, items: [ad(1), ad(2), ad(3)] }))
    fs.writeFileSync(reviewPaths(root).proposals, JSON.stringify({ version: 1, proposals: {} }))
    await saveLabel(root, { jobId: 'job1', functionFit: 'yes', hardRequirements: 'partial', overall: 2 })
    const before = sha(reviewPaths(root).labels)
    const mtime = fs.statSync(reviewPaths(root).labels).mtimeMs
    for (const n of [1, 2, 3]) await saveMust(root, body(n))
    await saveMust(root, body(1, { isMust: 'no' }))
    getMusts(root)
    expect(sha(reviewPaths(root).labels)).toBe(before)
    expect(fs.statSync(reviewPaths(root).labels).mtimeMs).toBe(mtime)
    expect(getReview(root).progress).toEqual({ total: 3, reviewed: 1 })
    expect(path.basename(files().labels)).toBe('ran-must-labels.json')
  })
})

describe('the routes', () => {
  let server
  let base
  beforeEach(async () => {
    seed()
    server = http.createServer(async (req, res) => {
      const url = req.url.split('?')[0]
      // the same order as api-handler.js: the must handler first, the review handler second
      if (!(await handleMustRequest(req, res, url, { root })) && !(await handleCalibrationRequest(req, res, url, { root }))) {
        res.statusCode = 404
        res.end('{}')
      }
    })
    await new Promise((r) => server.listen(0, '127.0.0.1', r))
    base = `http://127.0.0.1:${server.address().port}`
  })
  afterEach(() => new Promise((r) => server.close(r)))

  const put = (data) => fetch(`${base}/api/calibration/musts/labels`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: typeof data === 'string' ? data : JSON.stringify(data) })

  it('answers GET and PUT, and refuses other methods, other paths, bad JSON and big bodies', async () => {
    const got = await fetch(`${base}/api/calibration/musts`)
    expect(got.status).toBe(200)
    expect(await got.text()).not.toContain('MISSING') // the blind payload, as sent over the wire
    const saved = await put(body(1))
    expect(saved.status).toBe(200)
    expect((await saved.json()).reveal.status).toBe('MISSING')
    expect((await put('{bad')).status).toBe(400)
    expect((await put(body(1, { isMust: 'x' }))).status).toBe(400)
    expect((await put(JSON.stringify({ ...body(1), pad: 'x'.repeat(5000) }))).status).toBe(413)
    expect((await fetch(`${base}/api/calibration/musts/labels`)).status).toBe(404)
    expect((await fetch(`${base}/api/calibration/musts/other`)).status).toBe(404)
    expect((await fetch(`${base}/api/calibration/musts-x`)).status).toBe(404) // falls through to the review handler's 404
  })

  it('does not take over the review routes', async () => {
    fs.writeFileSync(reviewPaths(root).items, JSON.stringify({ version: 1, items: [ad(1)] }))
    expect((await fetch(`${base}/api/calibration/review`)).status).toBe(200)
  })
})
