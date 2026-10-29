/**
 * The secret store (BROWSER_STORAGE_POLICY, step 2): the only code that WRITES data/secrets/ and the only Node reader.
 * Python reads ai.json, read-only, through python/llm/secret_store.py (policy section 11c); it never writes.
 *
 *   data/secrets/            mode 700
 *   data/secrets/ai.json     mode 600   { "<provider>": { "key": "...", "baseUrl": "https://...", "setAt": "ISO" } }
 *   data/secrets/linkedin.json mode 600 { "li_at": "...", "setAt": "ISO" }
 *
 * Files are written atomically (a temp file in the same directory, fsync, rename) and are created with mode 600,
 * so the value is never readable by another user, not even for a moment. Nothing here logs: no console, no thrown
 * message that contains a key, a base URL or a path. A secret value leaves this module only through getAiCredential,
 * which is for the server's own provider calls (getLinkedInCookie likewise, for the scraper's environment); describeSecrets gives "set" and the last 4 characters.
 *
 * Resolution order for an AI key: the store first, then .env (OPENAI_API_KEY, ANTHROPIC_API_KEY) where one is defined.
 * The LinkedIn cookie: the store first, then .env (LINKEDIN_LI_AT).
 */

import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { maskExactValues, setExactSecretSource } from './secret-mask.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DEFAULT_ROOT = path.resolve(__dirname, '../data/secrets')

/** Providers that take a key. The others (claude-code, mock, ollama) have no credential to store. */
export const KEYED_AI_PROVIDERS = ['openai', 'openrouter', 'claude', 'gemini']
const ENV_KEYS = { openai: 'OPENAI_API_KEY', claude: 'ANTHROPIC_API_KEY' }

export const MIN_KEY_LENGTH = 12
const MAX_KEY_LENGTH = 512
const MAX_URL_LENGTH = 300
/** Values shorter than this are never used for masking: they would mangle ordinary text. */
const MIN_MASK_LENGTH = 8

const AI_FILE = 'ai.json'
const LINKEDIN_FILE = 'linkedin.json'
const LINKEDIN_ENV = 'LINKEDIN_LI_AT'

/** Thrown for a request the store refuses. The message is fixed text and never contains the input. */
export class SecretStoreError extends Error {
  constructor(message, code = 'invalid') {
    super(message)
    this.name = 'SecretStoreError'
    this.code = code
  }
}

let rootOverride = null
const caches = new Map() // file path -> { stamp, data }

function root() {
  return rootOverride || process.env.CAREER_OS_SECRETS_DIR || DEFAULT_ROOT
}

/** Tests point the store at a temp directory; pass nothing to restore the default. */
export function setSecretsRoot(dir) {
  rootOverride = dir || null
  caches.clear()
}

function aiFile() {
  return path.join(root(), AI_FILE)
}

function linkedinFile() {
  return path.join(root(), LINKEDIN_FILE)
}

function ensureDir() {
  const dir = root()
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 })
  if ((fs.statSync(dir).mode & 0o777) !== 0o700) fs.chmodSync(dir, 0o700)
  return dir
}

function writeAtomic(file, text) {
  const dir = path.dirname(file)
  const tmp = path.join(dir, `.${path.basename(file)}.${process.pid}.${crypto.randomBytes(6).toString('hex')}.tmp`)
  let fd
  try {
    fd = fs.openSync(tmp, 'wx', 0o600)
    fs.fchmodSync(fd, 0o600) // a restrictive umask must not leave the file at a different mode
    fs.writeSync(fd, text)
    fs.fsyncSync(fd)
    fs.closeSync(fd)
    fd = undefined
    fs.renameSync(tmp, file)
  } catch (e) {
    if (fd !== undefined) {
      try { fs.closeSync(fd) } catch { /* already closed */ }
    }
    try { fs.unlinkSync(tmp) } catch { /* never created */ }
    throw e
  }
  try {
    const dirFd = fs.openSync(dir, 'r')
    try { fs.fsyncSync(dirFd) } finally { fs.closeSync(dirFd) }
  } catch { /* directory fsync is best effort */ }
}

/** The parsed file, or null when it exists but cannot be read (it is then never overwritten). */
function readJsonFile(file) {
  let stat
  try {
    stat = fs.statSync(file)
  } catch {
    caches.set(file, { stamp: 'none', data: {} })
    return {}
  }
  const stamp = `${stat.mtimeMs}:${stat.size}:${stat.ino}`
  const cached = caches.get(file)
  if (cached?.stamp === stamp) return cached.data
  let data = null
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf-8'))
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) data = parsed
  } catch { /* unreadable: handled below */ }
  caches.set(file, { stamp, data })
  return data
}

const readAi = () => readJsonFile(aiFile())
const readLinkedIn = () => readJsonFile(linkedinFile())

function entryOf(data, provider) {
  const entry = data && Object.hasOwn(data, provider) ? data[provider] : null
  return entry && typeof entry.key === 'string' && entry.key ? entry : null
}

function last4(value) {
  return value.length >= MIN_KEY_LENGTH ? value.slice(-4) : '****'
}

function validateProvider(provider) {
  if (!KEYED_AI_PROVIDERS.includes(provider)) throw new SecretStoreError('Unknown provider', 'provider')
}

function validateKey(key, label = 'Key') {
  const value = typeof key === 'string' ? key.trim() : ''
  if (value.length < MIN_KEY_LENGTH || value.length > MAX_KEY_LENGTH || /[\s\p{Cc}]/u.test(value)) {
    throw new SecretStoreError(`${label} must be ${MIN_KEY_LENGTH} to ${MAX_KEY_LENGTH} characters, with no spaces or control characters`)
  }
  return value
}

function validateBaseUrl(baseUrl) {
  if (baseUrl === undefined || baseUrl === null || baseUrl === '') return null
  const text = typeof baseUrl === 'string' ? baseUrl.trim() : ''
  let url
  try {
    url = new URL(text)
  } catch {
    throw new SecretStoreError('Base URL must be a full http or https URL')
  }
  if (!text || text.length > MAX_URL_LENGTH || !['http:', 'https:'].includes(url.protocol)
    || url.username || url.password || url.search || url.hash) {
    throw new SecretStoreError('Base URL must be a plain http or https URL without credentials, query or fragment')
  }
  return text.replace(/\/+$/, '')
}

function describeEntry(provider, data) {
  const entry = entryOf(data, provider)
  if (entry) {
    return { set: true, source: 'store', last4: last4(entry.key), baseUrl: entry.baseUrl || null, setAt: entry.setAt || null }
  }
  const envValue = ENV_KEYS[provider] ? String(process.env[ENV_KEYS[provider]] ?? '').trim() : ''
  if (envValue) return { set: true, source: 'env', last4: last4(envValue), baseUrl: null, setAt: null }
  return { set: false, source: null, last4: null, baseUrl: null, setAt: null }
}

/** { ai: { <provider>: { set, source, last4, baseUrl, setAt } }, unreadable? }. Never a value. */
export function describeSecrets() {
  const data = readAi()
  const ai = {}
  for (const provider of KEYED_AI_PROVIDERS) ai[provider] = describeEntry(provider, data)
  const linkedinData = readLinkedIn()
  const linkedin = describeLinkedIn(linkedinData)
  return data === null || linkedinData === null ? { ai, linkedin, unreadable: true } : { ai, linkedin }
}

/** The key and pinned base URL for a provider call, or null. Server internal: never put the result in a response. */
export function getAiCredential(provider) {
  if (!KEYED_AI_PROVIDERS.includes(provider)) return null
  const entry = entryOf(readAi(), provider)
  if (entry) return { apiKey: entry.key, baseUrl: entry.baseUrl || undefined, source: 'store' }
  const envValue = ENV_KEYS[provider] ? String(process.env[ENV_KEYS[provider]] ?? '').trim() : ''
  return envValue ? { apiKey: envValue, baseUrl: undefined, source: 'env' } : null
}

/** Store or replace the key (and the base URL pinned to it) for a provider. Resolves the new describe entry. */
export function setAiSecret(provider, { key, baseUrl } = {}) {
  validateProvider(provider)
  const value = validateKey(key)
  const pinned = validateBaseUrl(baseUrl)
  const data = readAi()
  if (data === null) throw new SecretStoreError('The secret store file cannot be read; it was left as it is', 'unreadable')
  ensureDir()
  const entry = { key: value, setAt: new Date().toISOString() }
  if (pinned) entry.baseUrl = pinned
  writeAtomic(aiFile(), `${JSON.stringify({ ...data, [provider]: entry }, null, 2)}\n`)
  caches.clear()
  return describeEntry(provider, readAi())
}

/** Remove the stored key for a provider. Resolves the describe entry after removal (a .env key may remain). */
export function clearAiSecret(provider) {
  validateProvider(provider)
  const data = readAi()
  if (data === null) throw new SecretStoreError('The secret store file cannot be read; it was left as it is', 'unreadable')
  if (Object.hasOwn(data, provider)) {
    const rest = { ...data }
    delete rest[provider]
    if (Object.keys(rest).length) {
      ensureDir()
      writeAtomic(aiFile(), `${JSON.stringify(rest, null, 2)}\n`)
    } else {
      fs.rmSync(aiFile(), { force: true })
    }
    caches.clear()
  }
  return describeEntry(provider, readAi())
}

function liAtEntry(data) {
  return data && typeof data.li_at === 'string' && data.li_at ? data : null
}

function envLiAt() {
  return String(process.env[LINKEDIN_ENV] ?? '').trim()
}

function describeLinkedIn(data) {
  const entry = liAtEntry(data)
  if (entry) return { set: true, source: 'store', last4: last4(entry.li_at), setAt: entry.setAt || null }
  const envValue = envLiAt()
  if (envValue) return { set: true, source: 'env', last4: last4(envValue), setAt: null }
  return { set: false, source: null, last4: null, setAt: null }
}

/** The li_at cookie for the scraper's environment, or null. Server internal: never put it in a response or in argv. */
export function getLinkedInCookie() {
  const entry = liAtEntry(readLinkedIn())
  if (entry) return entry.li_at
  return envLiAt() || null
}

/** Store or replace the LinkedIn li_at cookie. Resolves the new describe entry. */
export function setLinkedInSecret({ li_at } = {}) {
  const value = validateKey(li_at, 'Cookie')
  const data = readLinkedIn()
  if (data === null) throw new SecretStoreError('The secret store file cannot be read; it was left as it is', 'unreadable')
  ensureDir()
  writeAtomic(linkedinFile(), `${JSON.stringify({ li_at: value, setAt: new Date().toISOString() }, null, 2)}\n`)
  caches.clear()
  return describeLinkedIn(readLinkedIn())
}

/** Remove the stored cookie. Resolves the describe entry after removal (a .env value may remain). */
export function clearLinkedInSecret() {
  const data = readLinkedIn()
  if (data === null) throw new SecretStoreError('The secret store file cannot be read; it was left as it is', 'unreadable')
  fs.rmSync(linkedinFile(), { force: true })
  caches.clear()
  return describeLinkedIn(readLinkedIn())
}

/** Every secret value this process holds (the store and .env), plus the URL-encoded form of each. */
export function exactSecretValues() {
  const found = new Set()
  const add = (value) => {
    const text = typeof value === 'string' ? value : ''
    if (text.length < MIN_MASK_LENGTH) return
    found.add(text)
    const encoded = encodeURIComponent(text)
    if (encoded !== text) found.add(encoded)
  }
  const data = readAi()
  for (const provider of KEYED_AI_PROVIDERS) {
    add(entryOf(data, provider)?.key)
    if (ENV_KEYS[provider]) add(String(process.env[ENV_KEYS[provider]] ?? '').trim())
  }
  add(liAtEntry(readLinkedIn())?.li_at)
  add(envLiAt())
  return [...found]
}

/** Replace every stored (and .env) secret value in the text with [secret]. */
export function redactSecrets(text) {
  return maskExactValues(text, exactSecretValues())
}

setExactSecretSource(exactSecretValues)
