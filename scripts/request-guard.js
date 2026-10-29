/**
 * Request checks in front of every /api route (BROWSER_STORAGE_POLICY, step 1).
 *
 *   1. Content-Type: POST / PUT / PATCH must be application/json, except the routes in BODY_TYPES that take a
 *      binary body (a CV PDF, a backup zip). A DELETE needs it only when it carries a body.
 *   2. Origin: when the browser sends one it must be an allowed origin.
 *   3. Host: when allowed origins are configured, the request's Host (or the proxy's X-Forwarded-Host) must be one of them.
 *
 * Allowed origins come from CAREER_OS_ALLOWED_ORIGINS, a comma separated list such as
 * "https://holojob.example.com,http://localhost:3073". With no list the app accepts its own origin only:
 * the Origin's host must equal the request's Host. These checks stop cross-site writes from a page in the
 * owner's browser and DNS rebinding; they are not authentication.
 */

const STATE_CHANGING = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

/** Routes whose body is not JSON, with the one type each accepts. */
export const BODY_TYPES = {
  'POST /api/cvs': 'application/pdf',
  'POST /api/backup/import': 'application/zip',
}

function hostOf(value) {
  return String(value ?? '').trim().toLowerCase().replace(/^[a-z][a-z0-9+.-]*:\/\//, '').replace(/\/.*$/, '')
}

/** Parse the env value into host:port strings (scheme is not compared: a TLS proxy changes it). */
export function parseAllowedOrigins(value) {
  return String(value ?? '').split(',').map(hostOf).filter(Boolean)
}

function mediaType(header) {
  return String(header ?? '').split(';')[0].trim().toLowerCase()
}

function hasBody(req) {
  const length = Number(req.headers['content-length'] ?? 0)
  return length > 0 || req.headers['transfer-encoding'] !== undefined
}

/** { ok: true } or { ok: false, status, error }. */
export function checkApiRequest(req, { allowedOrigins = parseAllowedOrigins(process.env.CAREER_OS_ALLOWED_ORIGINS) } = {}) {
  const headers = req.headers ?? {}
  const method = String(req.method ?? 'GET').toUpperCase()
  const path = String(req.url ?? '').split('?')[0]
  const host = hostOf(headers.host)
  const forwarded = hostOf(String(headers['x-forwarded-host'] ?? '').split(',')[0])

  if (allowedOrigins.length) {
    const seen = forwarded || host
    if (!allowedOrigins.includes(seen) && !allowedOrigins.includes(host)) {
      return { ok: false, status: 403, error: 'Host not allowed' }
    }
  }

  if (headers.origin !== undefined) {
    const origin = String(headers.origin).trim().toLowerCase()
    const originHost = origin === 'null' ? '' : hostOf(origin)
    const allowed = allowedOrigins.length
      ? allowedOrigins.includes(originHost)
      : originHost !== '' && originHost === (forwarded || host)
    if (!allowed) return { ok: false, status: 403, error: 'Origin not allowed' }
  }

  if (STATE_CHANGING.has(method)) {
    if (method === 'DELETE' && !hasBody(req)) return { ok: true }
    const type = mediaType(headers['content-type'])
    const expected = BODY_TYPES[`${method} ${path}`] ?? 'application/json'
    if (type !== expected) return { ok: false, status: 415, error: `Content-Type must be ${expected}` }
  }
  return { ok: true }
}

/** Answers the request itself when it fails the checks. Returns true when it did. */
export function guardApiRequest(req, res, options) {
  const result = checkApiRequest(req, options)
  if (result.ok) return false
  res.statusCode = result.status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify({ error: result.error }))
  return true
}
