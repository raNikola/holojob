import http from 'node:http'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { setGateRunner } from '../../scripts/ai-gate.js'
import { handleAiSettingsRequest } from '../../scripts/ai-settings-handler.js'
import { gateRefusalReason } from '../../src/modules/ai/runQuality.js'
import { formFromSettings, settingsFromForm } from '../../src/modules/ai/gateClient.js'

let server
let base
let calls

beforeEach(async () => {
  calls = []
  server = http.createServer(async (req, res) => {
    if (!(await handleAiSettingsRequest(req, res))) {
      res.statusCode = 404
      res.end('{}')
    }
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  base = `http://127.0.0.1:${server.address().port}`
})

afterEach(async () => {
  setGateRunner()
  await new Promise((r) => server.close(r))
})

function gate(reply) {
  setGateRunner(async (command, input) => {
    calls.push({ command, input })
    return typeof reply === 'function' ? reply(command, input) : reply
  })
}

const put = (path, body) => fetch(base + path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

describe('PUT /api/ai/settings', () => {
  it('maps the gate answers to 200, 400 and 409 and sends confirm only when it is exactly true', async () => {
    gate((cmd, input) => {
      if (input.settings.dailyLimit < 0) return { ok: false, errors: ['dailyLimit must be a number from 0 to 1000000'] }
      if (!input.confirm) return { ok: false, needsConfirm: true, increases: ['daily limit up: 0 -> 5 USD'] }
      return { ok: true, settings: { dailyLimit: 5 }, warnings: [] }
    })
    let res = await put('/api/ai/settings', { settings: { dailyLimit: -1 } })
    expect(res.status).toBe(400)
    expect((await res.json()).errors[0]).toContain('dailyLimit')

    res = await put('/api/ai/settings', { settings: { dailyLimit: 5 } })
    expect(res.status).toBe(409)
    expect((await res.json()).increases).toEqual(['daily limit up: 0 -> 5 USD'])

    res = await put('/api/ai/settings', { settings: { dailyLimit: 5 }, confirm: 'true' })
    expect(res.status).toBe(409)
    expect(calls.at(-1).input.confirm).toBe(false)

    res = await put('/api/ai/settings', { settings: { dailyLimit: 5 }, confirm: true })
    expect(res.status).toBe(200)
    expect(calls.at(-1)).toMatchObject({ command: 'settings-put', input: { confirm: true } })
  })

  it('refuses everything but PUT, bad JSON and an oversized body, and never asks the gate', async () => {
    gate({ ok: true })
    expect((await fetch(`${base}/api/ai/settings`, { method: 'DELETE' })).status).toBe(405)
    expect((await fetch(`${base}/api/ai/settings`)).status).toBe(405)
    const bad = await fetch(`${base}/api/ai/settings`, { method: 'PUT', body: '[1]' })
    expect(bad.status).toBe(400)
    const huge = await fetch(`${base}/api/ai/settings`, { method: 'PUT', body: JSON.stringify({ x: 'a'.repeat(70000) }) }).catch(() => ({ status: 0 }))
    expect([0, 400]).toContain(huge.status)
    expect(calls).toEqual([])
  })

  it('reports a gate that cannot run as 500 without leaking more than the message', async () => {
    gate(() => { throw new Error('gate down') })
    const res = await put('/api/ai/settings', { settings: { dailyLimit: 1 } })
    expect(res.status).toBe(500)
    expect(await res.json()).toEqual({ error: 'gate down' })
  })

  it('has no route that writes or deletes ledger rows', async () => {
    gate({ ok: true })
    for (const method of ['PUT', 'POST', 'DELETE', 'PATCH']) {
      for (const path of ['/api/ai/ledger', '/api/ai/usage', '/api/ai/usage/rows']) {
        const res = await fetch(base + path, { method, body: method === 'DELETE' ? undefined : '{}' })
        expect(res.status).toBe(404)
      }
    }
    expect(calls).toEqual([])
  })
})

describe('PUT /api/ai/pricing', () => {
  it('passes the entries and confirm to the gate and relays its validation errors', async () => {
    gate((cmd, input) => (input.entries[0].source ? { ok: true, pricing: { entries: [] } } : { ok: false, errors: ['a source note is required'] }))
    let res = await put('/api/ai/pricing', { entries: [{ provider: 'openai', model: 'x', class: 'free' }] })
    expect(res.status).toBe(400)
    res = await put('/api/ai/pricing', { entries: [{ provider: 'openai', model: 'x', class: 'free', source: 'page' }], confirm: true })
    expect(res.status).toBe(200)
    expect(calls.at(-1).command).toBe('pricing-put')
  })

  it('no response body carries a secret-looking key', async () => {
    gate({ ok: true, settings: { dailyLimit: 1 }, warnings: [] })
    const text = await (await put('/api/ai/settings', { settings: { dailyLimit: 1 }, confirm: true })).text()
    expect(text).not.toMatch(/apiKey|api_key|secret|token"/i)
  })
})

describe('form conversion', () => {
  it('turns an empty call limit into null and an empty amount into a value the server rejects', () => {
    const form = formFromSettings({
      currency: 'USD', dailyLimit: 0, monthlyLimit: 0, maxCallsDaily: null, maxCallsMonthly: 5,
      estimatedOutputTokens: 1000, timezone: 'UTC', automation: { enabled: false },
    })
    expect(settingsFromForm(form)).toMatchObject({ maxCallsDaily: null, maxCallsMonthly: 5, dailyLimit: 0, automation: { enabled: false } })
    const empty = settingsFromForm({ ...form, dailyLimit: '' })
    expect(JSON.parse(JSON.stringify(empty)).dailyLimit).toBeNull()
  })
})

describe('badge source', () => {
  it('shows only for a gate refusal, not for --skip-enrich or a normal run', () => {
    expect(gateRefusalReason({ quality: { reduced: true, reason: 'AI enrichment refused: paid call refused: AI budget is 0' } })).toContain('budget is 0')
    expect(gateRefusalReason({ quality: { reduced: true, reason: 'enrichment skipped (--skip-enrich)' } })).toBeNull()
    expect(gateRefusalReason({ quality: { reduced: false } })).toBeNull()
    expect(gateRefusalReason(null)).toBeNull()
  })
})
