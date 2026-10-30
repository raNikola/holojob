import { EventEmitter } from 'node:events'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AD_FIELDS, READ_FAILED, adFetchBody, applySuggestions, fetchAdFields, stillMissing } from '../../src/modules/jobs/adFill.js'
import { UNREADABLE_MESSAGE, cachedPage, clearCachedPages, fetchAd } from '../../scripts/run-ad-fill.js'

const json = (status, body) => ({ status, json: async () => body })
const FIELDS = { title: 'Senior PM', company: 'Acme', location: 'Niš, RS', salary: '3000 monthly EUR', description: 'Own the roadmap.' }

describe('applySuggestions (fills empty fields only)', () => {
  it('fills what is empty and reports it', () => {
    const { form, filled } = applySuggestions({ title: '', company: '  ', description: '', location: '', salary: '' }, FIELDS)
    expect(form).toMatchObject(FIELDS)
    expect(filled).toEqual(AD_FIELDS)
  })

  it('never overwrites a field the owner filled', () => {
    const typed = { title: 'My own title', company: '', location: 'Remote', salary: '', description: 'My text', jobUrl: 'https://a.example/1', notes: 'keep' }
    const { form, filled } = applySuggestions(typed, FIELDS)
    expect(form).toMatchObject({ title: 'My own title', location: 'Remote', description: 'My text', jobUrl: 'https://a.example/1', notes: 'keep' })
    expect(form).toMatchObject({ company: 'Acme', salary: '3000 monthly EUR' })
    expect(filled).toEqual(['company', 'salary'])
  })

  it('keeps a value an earlier step put there when a later step proposes another', () => {
    const first = applySuggestions({ title: '', company: '' }, { title: 'From the page', company: '' })
    const second = applySuggestions(first.form, { title: 'From somewhere else', company: 'Acme' })
    expect(second.form).toMatchObject({ title: 'From the page', company: 'Acme' })
    expect(second.filled).toEqual(['company'])
  })

  it('uses the form as it is when the answer arrives: text typed while the page loaded stays', () => {
    const atClick = { title: '', company: '' }
    const atArrival = { ...atClick, title: 'Typed meanwhile' }
    expect(applySuggestions(atArrival, FIELDS).form.title).toBe('Typed meanwhile')
  })

  it('ignores empty and unknown proposals and touches nothing else', () => {
    const base = { title: '', company: '', extraLinks: [{ url: 'x' }], sourceUrl: 'https://s.example' }
    const { form, filled } = applySuggestions(base, { title: '', company: '   ', bogus: 'x', sourceUrl: 'https://evil.example' })
    expect(filled).toEqual([])
    expect(form).toEqual(base)
  })

  it('lists what a later step could still be asked for', () => {
    expect(stillMissing({ title: 'x', company: '', location: '', salary: 'y', description: '' }, ['company', 'location', 'salary', 'bogus'])).toEqual(['company', 'location'])
  })
})

describe('the request to the server', () => {
  it('carries the address and nothing else', async () => {
    const fetchFn = vi.fn(async () => json(200, { ok: true, token: 't', fields: FIELDS, missing: [], finalUrl: 'https://a.example/1' }))
    const result = await fetchAdFields('  https://a.example/1 ', { fetchFn })
    expect(result).toMatchObject({ ok: true, token: 't', fields: FIELDS })
    const [url, init] = fetchFn.mock.calls[0]
    expect(url).toBe('/api/jobs/ad/fetch')
    expect(JSON.parse(init.body)).toEqual({ url: 'https://a.example/1' })
    expect(Object.keys(adFetchBody('https://a.example/1'))).toEqual(['url'])
  })

  it.each([
    ['the network is down', () => { throw new Error('offline') }],
    ['the server cannot read the page', () => json(502, { ok: false, error: 'login_wall', message: 'secret server text' })],
    ['an unreadable answer', () => ({ status: 200, json: async () => { throw new Error('bad json') } })],
    ['a 200 without a token', () => json(200, { ok: true })],
  ])('says the page could not be read when %s, and gives no fields', async (_name, reply) => {
    const result = await fetchAdFields('https://a.example/1', { fetchFn: async () => reply() })
    expect(result).toEqual({ ok: false, message: READ_FAILED, blocked: false })
  })

  it('shows the server\'s own message for a refused host', async () => {
    const result = await fetchAdFields('http://127.0.0.1:3073/', { fetchFn: async () => json(403, { ok: false, error: 'blocked_host', message: 'This address is not allowed: private, local and internal hosts are refused.' }) })
    expect(result).toMatchObject({ ok: false, blocked: true, message: expect.stringMatching(/not allowed/) })
  })
})

// --- the Node side ------------------------------------------------------------------------------------------------

function fakeSpawn(answer) {
  const calls = []
  const fn = (cmd, args) => {
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.stdin = {
      end: (data) => {
        calls.push({ cmd, args, stdin: data })
        setImmediate(() => {
          if (answer !== undefined) child.stdout.emit('data', Buffer.from(typeof answer === 'string' ? answer : `${JSON.stringify(answer)}\n`))
          child.emit('close', 0)
        })
      },
    }
    return child
  }
  fn.calls = calls
  return fn
}

describe('fetchAd (Node)', () => {
  beforeEach(() => clearCachedPages())
  afterEach(() => clearCachedPages())

  const OK = { ok: true, finalUrl: 'https://a.example/1', source: 'json-ld', fields: FIELDS, missing: [], pageText: 'PAGE TEXT THAT STAYS ON THE SERVER' }

  it('sends the address on stdin, keeps the page text behind a token and does not return it', async () => {
    const spawnFn = fakeSpawn(OK)
    const { status, body } = await fetchAd('https://a.example/1', { spawnFn })
    expect(status).toBe(200)
    expect(body).toMatchObject({ ok: true, fields: FIELDS, missing: [], finalUrl: 'https://a.example/1' })
    expect(JSON.stringify(body)).not.toContain('PAGE TEXT')
    expect(JSON.parse(spawnFn.calls[0].stdin)).toEqual({ url: 'https://a.example/1' })
    expect(spawnFn.calls[0].args.join(' ')).not.toContain('a.example')
    expect(cachedPage(body.token)).toMatchObject({ pageText: 'PAGE TEXT THAT STAYS ON THE SERVER' })
  })

  it('forgets a page after its time and does not know a token it never issued', async () => {
    const { body } = await fetchAd('https://a.example/1', { spawnFn: fakeSpawn(OK), now: 1_000 })
    expect(cachedPage(body.token, 1_000 + 14 * 60 * 1000)).not.toBeNull()
    expect(cachedPage(body.token, 1_000 + 16 * 60 * 1000)).toBeNull()
    expect(cachedPage('not-a-token')).toBeNull()
    expect(cachedPage(undefined)).toBeNull()
  })

  it('refuses a non-http address without starting Python', async () => {
    const spawnFn = fakeSpawn(OK)
    for (const url of ['ftp://a.example', 'file:///etc/passwd', '', undefined, 'a.example/x', `https://a.example/${'x'.repeat(3000)}`]) {
      expect((await fetchAd(url, { spawnFn })).status).toBe(422)
    }
    expect(spawnFn.calls).toHaveLength(0)
  })

  it.each([
    ['a login wall', { ok: false, error: 'login_wall', message: 'The page needs a login.' }],
    ['a failed fetch', { ok: false, error: 'http_error', message: 'The site refused or did not have the page.' }],
    ['an unreadable page', { ok: false, error: 'unreadable', message: 'No job posting could be read from this page.' }],
    ['garbage', 'not json'],
    ['no answer', undefined],
  ])('answers the same plain message for %s and caches nothing', async (_name, answer) => {
    const { status, body } = await fetchAd('https://a.example/1', { spawnFn: fakeSpawn(answer) })
    expect(status).toBe(502)
    expect(body).toMatchObject({ ok: false, message: UNREADABLE_MESSAGE })
    expect(body.token).toBeUndefined()
  })

  it('says why when the host is refused', async () => {
    const { status, body } = await fetchAd('http://127.0.0.1:3073/', { spawnFn: fakeSpawn({ ok: false, error: 'blocked_host', message: 'This address is not allowed: private, local and internal hosts are refused.' }) })
    expect(status).toBe(403)
    expect(body.message).toMatch(/not allowed/)
  })
})
