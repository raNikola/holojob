/**
 * Routes that edit the AI budget gate's files. The rules live in python/llm/ai_gate.py
 * (validation, the confirm check, the atomic write); this file only carries JSON to it.
 *
 *   PUT /api/ai/settings  { settings: {...partial}, confirm? }   -> data/ai/settings.json
 *   PUT /api/ai/pricing   { entries: [...], confirm? }           -> data/ai/pricing-overrides.json
 *
 * Reading is GET /api/ai/usage (api-handler.js). There is no route that writes or
 * deletes ledger rows. Answers: 200 saved, 400 invalid, 409 needs "confirm": true
 * (the body lists what the change raises), 500 the gate could not be run.
 */

import { saveAiPricing, saveAiSettings } from './ai-gate.js'
import { maskErrorField } from './secret-mask.js'

const MAX_BODY = 64 * 1024

function readJson(req) {
  return new Promise((resolve, reject) => {
    let size = 0
    const chunks = []
    req.on('data', (c) => {
      size += c.length
      if (size > MAX_BODY) {
        reject(new Error('Body too large'))
        req.destroy()
      } else chunks.push(c)
    })
    req.on('end', () => {
      try {
        const body = JSON.parse(Buffer.concat(chunks).toString('utf-8') || '{}')
        if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error('not an object')
        resolve(body)
      } catch {
        reject(new Error('Body must be a JSON object'))
      }
    })
    req.on('error', reject)
  })
}

function send(res, status, data) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(maskErrorField(data)))
}

function statusOf(result) {
  if (result?.ok) return 200
  if (result?.needsConfirm) return 409
  return 400
}

/** Returns true when it answered the request. */
export async function handleAiSettingsRequest(req, res) {
  const url = req.url?.split('?')[0] ?? ''
  if (url !== '/api/ai/settings' && url !== '/api/ai/pricing') return false
  if (req.method !== 'PUT') {
    res.setHeader('Allow', 'PUT')
    send(res, 405, { error: 'Use PUT' })
    return true
  }
  let body
  try {
    body = await readJson(req)
  } catch (e) {
    send(res, 400, { error: e.message })
    return true
  }
  try {
    const result = url === '/api/ai/settings'
      ? await saveAiSettings(body.settings, body.confirm === true)
      : await saveAiPricing(body.entries, body.confirm === true)
    send(res, statusOf(result), result)
  } catch (e) {
    send(res, 500, { error: e.message })
  }
  return true
}
