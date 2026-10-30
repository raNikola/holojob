import http from 'node:http'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { handleSourcesRequest, setSourcesRunner } from '../../scripts/sources-handler.js'

let server
let base
let calls

beforeEach(async () => {
  calls = []
  server = http.createServer(async (req, res) => {
    if (!(await handleSourcesRequest(req, res))) {
      res.statusCode = 404
      res.end('{}')
    }
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  base = `http://127.0.0.1:${server.address().port}`
})

afterEach(async () => {
  setSourcesRunner()
  await new Promise((r) => server.close(r))
})

function cli(reply) {
  setSourcesRunner(async (command, input) => {
    calls.push({ command, input })
    return typeof reply === 'function' ? reply(command, input) : reply
  })
}

const send = (method, path, body) => fetch(base + path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

describe('/api/sources', () => {
  it('GET reads the settings through the CLI', async () => {
    cli({ boards: [{ name: 'joberty', optIn: true, active: false }] })
    const res = await fetch(`${base}/api/sources`)
    expect(res.status).toBe(200)
    expect((await res.json()).boards[0].active).toBe(false)
    expect(calls).toEqual([{ command: 'get', input: null }])
  })

  it('PUT passes only the boards on, so a consent time from the browser never reaches the store', async () => {
    cli({ ok: true, boards: [] })
    await send('PUT', '/api/sources', { boards: { joberty: { active: true, consentAccepted: true } }, consentAcceptedAt: '1999-01-01' })
    expect(calls).toEqual([{ command: 'put', input: { boards: { joberty: { active: true, consentAccepted: true } } } }])
  })

  it('maps the answers to 200, 409 (consent needed) and 400', async () => {
    cli((cmd, input) => {
      const change = input.boards?.joberty
      if (!change) return { ok: false, errors: ['boards must be an object naming at least one source'] }
      if (change.active && !change.consentAccepted) return { ok: false, needsConsent: ['joberty'] }
      return { ok: true, boards: [] }
    })
    expect((await send('PUT', '/api/sources', { boards: { joberty: { active: true, consentAccepted: true } } })).status).toBe(200)
    const refused = await send('PUT', '/api/sources', { boards: { joberty: { active: true } } })
    expect(refused.status).toBe(409)
    expect((await refused.json()).needsConsent).toEqual(['joberty'])
    expect((await send('PUT', '/api/sources', {})).status).toBe(400)
  })

  it('POST migrate-legacy passes the old value on', async () => {
    cli({ ok: true, migrated: true, boards: [] })
    const res = await send('POST', '/api/sources/migrate-legacy', { value: { includeJoberty: true } })
    expect(res.status).toBe(200)
    expect(calls).toEqual([{ command: 'migrate-legacy', input: { value: { includeJoberty: true } } }])
  })

  it('refuses other methods, a non-object body, and answers 500 when the CLI cannot run', async () => {
    cli({ ok: true })
    expect((await send('DELETE', '/api/sources', {})).status).toBe(405)
    expect((await fetch(`${base}/api/sources/migrate-legacy`)).status).toBe(405)
    expect((await fetch(`${base}/api/sources`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: '[1]' })).status).toBe(400)
    setSourcesRunner(async () => { throw new Error('python missing') })
    expect((await fetch(`${base}/api/sources`)).status).toBe(500)
  })

  it('leaves other routes alone', async () => {
    expect((await fetch(`${base}/api/sourcesx`)).status).toBe(404)
  })
})
