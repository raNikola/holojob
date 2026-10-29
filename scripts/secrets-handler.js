/**
 * Routes of the secret store (BROWSER_STORAGE_POLICY, step 2). They sit behind the request guard
 * (JSON Content-Type, Origin / Host) like every /api route.
 *
 *   GET    /api/secrets                  -> { ai: { <provider>: { set, source, last4, baseUrl, setAt } }, linkedin: { set, source, last4, setAt } }
 *   PUT    /api/secrets/ai/<provider>    { key, baseUrl? }  store or replace; answers the same entry, never the key
 *   DELETE /api/secrets/ai/<provider>    remove the stored key
 *   PUT    /api/secrets/linkedin         { li_at }  store or replace the LinkedIn cookie; answers set / last 4, never the value
 *   DELETE /api/secrets/linkedin         remove the stored cookie
 *
 * No route returns a secret value, and no answer quotes the request body or the store's file path: errors are fixed
 * text. A replace without baseUrl drops a base URL pinned earlier (the key and its URL are one record).
 */

import { SecretStoreError, clearAiSecret, clearLinkedInSecret, describeSecrets, setAiSecret, setLinkedInSecret } from './secret-store.js'
import { maskErrorField } from './secret-mask.js'

const MAX_BODY = 8 * 1024
const AI_ROUTE = /^\/api\/secrets\/ai\/([a-z0-9-]{1,32})$/

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
        // Not the parser's own message: it can quote the start of the input.
        reject(new Error('Body must be a JSON object'))
      }
    })
    req.on('error', () => reject(new Error('Body could not be read')))
  })
}

function send(res, status, data) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.setHeader('Cache-Control', 'no-store')
  res.end(JSON.stringify(maskErrorField(data)))
}

function statusOfError(e) {
  if (!(e instanceof SecretStoreError)) return 500
  return e.code === 'provider' ? 404 : e.code === 'unreadable' ? 500 : 400
}

/** Returns true when it answered the request. */
export async function handleSecretsRequest(req, res) {
  const url = req.url?.split('?')[0] ?? ''
  if (url !== '/api/secrets' && !url.startsWith('/api/secrets/')) return false

  try {
    if (url === '/api/secrets') {
      if (req.method !== 'GET') {
        res.setHeader('Allow', 'GET')
        send(res, 405, { error: 'Use GET' })
        return true
      }
      send(res, 200, describeSecrets())
      return true
    }

    if (url === '/api/secrets/linkedin') {
      if (req.method === 'DELETE') {
        send(res, 200, { ok: true, secret: clearLinkedInSecret() })
        return true
      }
      if (req.method !== 'PUT') {
        res.setHeader('Allow', 'PUT, DELETE')
        send(res, 405, { error: 'Use PUT or DELETE' })
        return true
      }
      let body
      try {
        body = await readJson(req)
      } catch (e) {
        send(res, 400, { error: e.message })
        return true
      }
      send(res, 200, { ok: true, secret: setLinkedInSecret({ li_at: body.li_at }) })
      return true
    }

    const match = AI_ROUTE.exec(url)
    if (!match) {
      send(res, 404, { error: 'Not found' })
      return true
    }
    const provider = match[1]

    if (req.method === 'DELETE') {
      send(res, 200, { ok: true, provider, secret: clearAiSecret(provider) })
      return true
    }
    if (req.method !== 'PUT') {
      res.setHeader('Allow', 'PUT, DELETE')
      send(res, 405, { error: 'Use PUT or DELETE' })
      return true
    }

    let body
    try {
      body = await readJson(req)
    } catch (e) {
      send(res, 400, { error: e.message })
      return true
    }
    send(res, 200, { ok: true, provider, secret: setAiSecret(provider, { key: body.key, baseUrl: body.baseUrl }) })
  } catch (e) {
    const status = statusOfError(e)
    send(res, status, { error: status === 500 ? 'Secret store error' : e.message })
  }
  return true
}
