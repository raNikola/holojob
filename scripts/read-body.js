/**
 * The one reader of /api request bodies. Every body is counted in bytes as it arrives and refused past a limit,
 * so one oversized request cannot exhaust the server's memory.
 *
 * Past the limit the reader answers 413 itself and rejects with BodyTooLargeError. The route's own error handling
 * then runs, so each send function in the handlers does nothing once the response has ended.
 */

/** Default for JSON routes. */
export const MAX_JSON_BODY_BYTES = 1024 * 1024
/** Backup zips and the routes that post the browser's whole job list (about 4 MB for 425 jobs). */
export const MAX_LARGE_BODY_BYTES = 25 * 1024 * 1024

// A socket closed while the client is still sending can lose the answer, so the rest is read and dropped, for this long at most.
const DRAIN_MS = 2000

export class BodyTooLargeError extends Error {
  constructor() {
    super('Request body too large')
    this.name = 'BodyTooLargeError'
  }
}

function refuse(req, res, payload, drainMs) {
  res.statusCode = 413
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(payload))
  const timer = setTimeout(() => req.destroy(), drainMs)
  timer.unref()
  req.once('close', () => clearTimeout(timer))
  // Node would leave this connection open with no timer once the rest has arrived.
  req.once('end', () => req.socket.destroySoon())
  req.resume()
}

/**
 * The body as a Buffer.
 * @param {{ limit?: number, tooLarge?: object, drainMs?: number }} [options] `tooLarge` is the JSON answer for a 413.
 */
export function readRawBody(req, res, { limit = MAX_JSON_BODY_BYTES, tooLarge = { error: 'Request body too large' }, drainMs = DRAIN_MS } = {}) {
  return new Promise((resolve, reject) => {
    if (Number(req.headers?.['content-length'] ?? 0) > limit) {
      refuse(req, res, tooLarge, drainMs)
      reject(new BodyTooLargeError())
      return
    }
    let size = 0
    let settled = false
    const chunks = []
    const settle = (fn, value) => {
      if (settled) return
      settled = true
      if (fn === reject) chunks.length = 0
      fn(value)
    }
    req.on('data', (chunk) => {
      if (settled) return
      size += chunk.length
      if (size > limit) {
        refuse(req, res, tooLarge, drainMs)
        settle(reject, new BodyTooLargeError())
        return
      }
      chunks.push(chunk)
    })
    req.on('end', () => settle(resolve, Buffer.concat(chunks)))
    req.on('error', (e) => settle(reject, e))
    req.on('close', () => settle(reject, new Error('Request closed before the body ended')))
  })
}

/** Parsed JSON; an empty body is {}. Bad JSON rejects with the parser's own error, which the route maps. */
export async function readJsonBody(req, res, options) {
  const raw = (await readRawBody(req, res, options)).toString('utf-8')
  return raw ? JSON.parse(raw) : {}
}

/** A JSON object, for the settings and secrets routes. The error never quotes the input, as a parser message can. */
export async function readJsonObject(req, res, options) {
  const raw = await readRawBody(req, res, options)
  try {
    const body = JSON.parse(raw.toString('utf-8') || '{}')
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error('not an object')
    return body
  } catch {
    throw new Error('Body must be a JSON object')
  }
}
