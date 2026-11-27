// Labels and repost count shown beside an ad (list-cleanup 2a, 2b). They are display only: stripped before a row is stored, no row is added or removed.
import { EventEmitter } from 'node:events'
import { describe, expect, it } from 'vitest'
import { fetchDerived, labelChips, labelText, repostBadge } from '../../src/modules/jobs/adDerived.js'
import { handleJobDerivedRequest } from '../../scripts/job-derived-read.js'
import { composeJobList, stripDisplayFields } from '../../src/modules/jobs/allAds.js'

describe('labels', () => {
  it('words every rule and keeps an unknown label as it came', () => {
    expect(labelChips([{ label: 'years:7' }, { label: 'visa:no_sponsorship' }, { label: 'language:german' }, { label: 'employment:part_time' }, { label: 'onsite:only' }, { label: 'other:x' }]).map((c) => c.text))
      .toEqual(['7+ years asked', 'No visa sponsorship', 'Language: German', 'Part-time', 'On-site only', 'other:x'])
    expect(labelText('visa:sponsorship')).toBe('Visa sponsorship offered')
    expect(labelChips(null)).toEqual([])
  })

  it('a failed answer is "no labels", never an error', async () => {
    expect(await fetchDerived('a1', async () => { throw new Error('down') })).toEqual({ ok: false })
    expect(await fetchDerived('a1', async () => ({ ok: false, json: async () => ({ ok: false }) }))).toEqual({ ok: false })
  })
})

describe('repost badge', () => {
  it('shows only a real count', () => {
    expect(repostBadge({ repostCount: 2 }).label).toBe('Reposted ×2')
    for (const bad of [undefined, null, 0, -1, 1.5, '2']) expect(repostBadge({ repostCount: bad })).toBeNull()
  })

  it('is display only: stripped before storing, and it adds or removes no row', () => {
    expect('repostCount' in stripDisplayFields({ jobId: 'a', repostCount: 2 })).toBe(false)
    const server = [{ jobId: 'a', class: 'found', repostCount: 1, title: 'A', lastSeen: '2026-11-26T00:00:00Z' }, { jobId: 'b', class: 'found', title: 'A', lastSeen: '2026-11-26T00:00:00Z' }]
    const composed = composeJobList({ stored: [], server, applications: null, reference: '2026-11-27T00:00:00Z', activeWindowDays: 14, jobStateDoc: null })
    expect(composed.all).toHaveLength(2)
    expect(composed.all.find((r) => r.jobId === 'a').repostCount).toBe(1)
  })
})

describe('GET /api/jobs/derived', () => {
  const call = (req, url, options) => new Promise((resolve, reject) => {
    const res = { statusCode: 200, headers: {}, setHeader(k, v) { this.headers[k] = v }, end(text) { resolve({ status: this.statusCode, text }) } }
    handleJobDerivedRequest(req, res, url, options).then((done) => { if (!done) resolve({ handled: false }) }, reject)
  })

  it('ignores other routes, refuses a bad id and a wrong method, runs the script for a good one', async () => {
    expect((await call({ method: 'GET', url: '/api/other' }, '/api/other', {})).handled).toBe(false)
    expect((await call({ method: 'POST', url: '/api/jobs/derived?jobId=a1' }, '/api/jobs/derived', {})).status).toBe(405)
    expect((await call({ method: 'GET', url: '/api/jobs/derived?jobId=../x' }, '/api/jobs/derived', {})).status).toBe(400)
    let args = null
    const spawnFn = (python, argv) => {
      args = argv
      const child = new EventEmitter()
      child.stdout = new EventEmitter()
      setTimeout(() => { child.stdout.emit('data', Buffer.from('{"ok":true,"labels":[],"repostCount":1}')); child.emit('close', 0) }, 0)
      return child
    }
    const ok = await call({ method: 'GET', url: '/api/jobs/derived?jobId=a1' }, '/api/jobs/derived', { root: '/r', python: 'py', spawnFn })
    expect(ok.status).toBe(200)
    expect(JSON.parse(ok.text).repostCount).toBe(1)
    expect(args).toContain('a1')
  })
})
