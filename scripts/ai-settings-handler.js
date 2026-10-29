/**
 * Routes that edit the AI budget gate's files. The rules live in python/llm/ai_gate.py
 * (validation, the confirm check, the atomic write); this file only carries JSON to it.
 *
 *   PUT /api/ai/settings  { settings: {...partial}, confirm? }   -> data/ai/settings.json
 *   PUT /api/ai/pricing   { entries: [...], confirm? }           -> data/ai/pricing-overrides.json
 *
 *   GET /api/ai/selection                                        -> the provider selection and the classes
 *   PUT /api/ai/selection { settings: {...partial}, confirm? }   -> data/config/ai-settings.json
 *
 * The selection (provider, model, temperature, max tokens, base URL for ollama, feature toggles) is the one both the
 * browser path and the Python pipeline read (python/llm/ai_selection.py). It never holds a secret. A paid or
 * unknown-class provider needs "confirm": true (409 with the reason). Reading usage is GET /api/ai/usage (api-handler.js). There is no route that writes or
 * deletes ledger rows. Answers: 200 saved, 400 invalid, 409 needs "confirm": true
 * (the body lists what the change raises), 500 the gate could not be run.
 */

import { readAiSelection, saveAiPricing, saveAiSelection, saveAiSettings } from './ai-gate.js'
import { PROVIDER_NAMES } from '../src/modules/ai/aiProviderRegistry.js'
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
  res.setHeader('Cache-Control', 'no-store')
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
  if (url === '/api/ai/selection' && req.method === 'GET') {
    const result = await readAiSelection()
    // nodeProviders: the ones this server can run; the Python pipeline refuses the rest of the list, and this path refuses its own gaps.
    send(res, 200, { ...result, nodeProviders: PROVIDER_NAMES })
    return true
  }
  if (url !== '/api/ai/settings' && url !== '/api/ai/pricing' && url !== '/api/ai/selection') return false
  if (req.method !== 'PUT') {
    res.setHeader('Allow', url === '/api/ai/selection' ? 'GET, PUT' : 'PUT')
    send(res, 405, { error: url === '/api/ai/selection' ? 'Use GET or PUT' : 'Use PUT' })
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
    const confirm = body.confirm === true
    const result = url === '/api/ai/settings'
      ? await saveAiSettings(body.settings, confirm)
      : url === '/api/ai/selection'
        ? await saveAiSelection(body.settings, confirm)
        : await saveAiPricing(body.entries, confirm)
    send(res, statusOf(result), result)
  } catch (e) {
    send(res, 500, { error: e.message })
  }
  return true
}
