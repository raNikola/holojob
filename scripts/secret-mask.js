/**
 * Masks credentials in text that leaves the server: error bodies, SSE errors, ledger reasons, console output.
 * The secret store's exact values are masked first (setExactSecretSource); the patterns below are the second layer.
 */

const MASK = '[secret]'
const SECRET_NAME = '(?:api[_-]?key|x-api-key|x-goog-api-key|access[_-]?token|refresh[_-]?token|id[_-]?token|token|secret|password|passwd|cookie|li[_-]?at|session[_-]?id|sig|key)'

const RULES = [
  // Authorization headers, quoted or plain: Authorization: Bearer abc / "authorization":"Basic abc"
  [/(\bauthorization["']?\s*[:=]\s*["']?)(?:(?:bearer|basic|token|digest)\s+)?[^\s"',;]+/gi, `$1${MASK}`],
  // "Bearer abc" outside a header line
  [/\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}/gi, `$1 ${MASK}`],
  // Query strings and form bodies: ?key=..., &token=..., li_at=...
  [new RegExp(`([?&;]\\s*${SECRET_NAME}=)[^&\\s"'#<>]+`, 'gi'), `$1${MASK}`],
  // The LinkedIn cookie as a flag or a pair: --li-at abc, li_at=abc, "li_at": "abc"
  [/(--li-at[=\s]+|\bli_at["']?\s*[:=]\s*["']?)[^\s"',;&]+/gi, `$1${MASK}`],
  // JSON / header style pairs: "apiKey": "abc", x-api-key: abc, password=abc
  [new RegExp(`(["']?\\b${SECRET_NAME}["']?\\s*[:=]\\s*["']?)(?!\\[secret\\])[^\\s"',;&}\\]]{4,}`, 'gi'), `$1${MASK}`],
  // Well-known key shapes (OpenAI / Anthropic / OpenRouter sk-..., Google AIza..., GitHub ghp_...)
  [/\bsk-[A-Za-z0-9_-]{8,}/g, MASK],
  [/\bAIza[0-9A-Za-z_-]{20,}/g, MASK],
  [/\bgh[pousr]_[A-Za-z0-9]{20,}/g, MASK],
  // Any other long token: 32+ characters with at least one letter and one digit
  [/\b(?=[A-Za-z0-9_-]*[A-Za-z])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{32,}\b/g, MASK],
]

let exactSource = () => []

/** The secret store registers itself here, so the exact values it holds are masked (no import cycle). */
export function setExactSecretSource(fn) {
  exactSource = typeof fn === 'function' ? fn : () => []
}

/** Replace each listed value, literally (not as a pattern), longest first. */
export function maskExactValues(text, values) {
  if (text === null || text === undefined) return text
  let out = String(text)
  for (const value of [...values].sort((a, b) => b.length - a.length)) {
    if (value) out = out.split(value).join(MASK)
  }
  return out
}

export function maskSecrets(text) {
  if (text === null || text === undefined) return text
  // Exact values first: a pattern rule could otherwise mask only part of a stored key.
  let out = maskExactValues(text, exactSource())
  for (const [re, replacement] of RULES) out = out.replace(re, replacement)
  return out
}

/** A copy of an API payload whose `error` text is masked; everything else is passed through untouched. */
export function maskErrorField(data) {
  if (data && typeof data === 'object' && !Array.isArray(data) && typeof data.error === 'string') {
    return { ...data, error: maskSecrets(data.error) }
  }
  return data
}

const LEVELS = ['log', 'info', 'warn', 'error', 'debug']

/** Routes console output through maskSecrets. Safe to call more than once. */
export function installLogMasking(target = console) {
  if (target.__secretMasking) return
  for (const level of LEVELS) {
    const original = target[level]?.bind(target)
    if (!original) continue
    target[level] = (...args) => original(...args.map((a) => {
      if (typeof a === 'string') return maskSecrets(a)
      if (a instanceof Error) return maskSecrets(a.stack || a.message)
      return a
    }))
  }
  Object.defineProperty(target, '__secretMasking', { value: true })
}
