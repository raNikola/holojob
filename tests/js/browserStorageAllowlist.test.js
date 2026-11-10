import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  BROWSER_STORAGE_ALLOWLIST, STORAGE_API_USERS, TOLERATED_UNTIL_MIGRATED,
} from '../../src/modules/browserStorage/allowlist.js'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const STORAGE_API = /\b(localStorage|sessionStorage|indexedDB)\b|document\.cookie/
// Keys the sources name: a *_KEY constant, a literal given to getItem / setItem / removeItem, or any job-dashboard-* / holojob-demo-* literal.
const KEY_PATTERNS = [
  /\b[A-Z0-9_]*(?:STORAGE_)?KEY\s*=\s*['"`]([^'"`$]+)['"`]/g,
  /\.(?:getItem|setItem|removeItem)\(\s*['"`]([^'"`$]+)['"`]/g,
  /['"`]((?:job-dashboard|holojob-demo)-[a-z0-9-]+)['"`]/g,
]

/** { storageFile: boolean, keys: Set } for one source text. */
export function scanStorageUse(source) {
  const keys = new Set()
  for (const pattern of KEY_PATTERNS) for (const m of source.matchAll(pattern)) keys.add(m[1])
  return { usesStorage: STORAGE_API.test(source), keys }
}

function sourceFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name)
    if (e.isDirectory()) return sourceFiles(full)
    return /\.(js|jsx)$/.test(e.name) ? [full] : []
  })
}

const known = new Set([...BROWSER_STORAGE_ALLOWLIST, ...TOLERATED_UNTIL_MIGRATED].map((e) => e.key))
// src/modules/browserStorage/ holds this list (and, in step 5, the wrapper); everything else is scanned.
const files = sourceFiles(path.join(ROOT, 'src')).filter((f) => !f.includes(`${path.sep}browserStorage${path.sep}`)).map((f) => ({ rel: path.relative(ROOT, f).split(path.sep).join('/'), text: fs.readFileSync(f, 'utf-8') }))

describe('browser storage allowlist', () => {
  it('every key a source names is on the allowlist or the tolerated list', () => {
    const unknown = []
    for (const { rel, text } of files) {
      for (const key of scanStorageUse(text).keys) if (!known.has(key)) unknown.push(`${rel}: ${key}`)
    }
    expect(unknown, 'new browser storage key: argue for it in src/modules/browserStorage/allowlist.js').toEqual([])
  })

  it('only the listed files use a storage API', () => {
    const users = files.filter(({ text }) => scanStorageUse(text).usesStorage).map(({ rel }) => rel).sort()
    expect(users).toEqual([...STORAGE_API_USERS].sort())
  })

  it('fails on a new key and on a new file that uses storage (self-test of the scanner)', () => {
    const newKey = scanStorageUse("const STORAGE_KEY = 'job-dashboard-new-thing'\nlocalStorage.setItem(STORAGE_KEY, 'x')")
    expect(newKey.usesStorage).toBe(true)
    expect([...newKey.keys].filter((k) => !known.has(k))).toEqual(['job-dashboard-new-thing'])
    const direct = scanStorageUse("localStorage.setItem('some_other_key', value)")
    expect([...direct.keys].filter((k) => !known.has(k))).toEqual(['some_other_key'])
    const session = scanStorageUse("sessionStorage.getItem(`dyn-${x}`)")
    expect(session.usesStorage).toBe(true)
    expect(STORAGE_API_USERS).not.toContain('src/components/NewPanel.jsx')
  })

  it('has a reason, a store and a size for each allowed key, and a step for each tolerated one', () => {
    for (const e of BROWSER_STORAGE_ALLOWLIST) {
      expect(e.reason, e.key).toBeTruthy()
      expect(['local', 'session']).toContain(e.store)
      expect(e.maxBytes, e.key).toBeGreaterThan(0)
    }
    for (const e of TOLERATED_UNTIL_MIGRATED) {
      expect(e.until, e.key).toMatch(/^step [2-6]$/)
      expect(e.reason, e.key).toBeTruthy()
    }
  })

  it('never lists an API key, and no key is on both lists', () => {
    const all = [...BROWSER_STORAGE_ALLOWLIST, ...TOLERATED_UNTIL_MIGRATED].map((e) => e.key)
    expect(new Set(all).size).toBe(all.length)
    expect(all.filter((k) => /api-?key|secret|token/i.test(k))).toEqual([])
  })

  it('the AI key is no longer stored by any source except as the legacy value waiting for the move', () => {
    const writers = files.filter(({ text }) => /apiKey/.test(text) && STORAGE_API.test(text)).map(({ rel }) => rel)
    expect(writers).toEqual(['src/modules/ai/aiSettings.js'])
  })
})

describe('the LinkedIn cookie in the browser', () => {
  it('no source writes linkedin_li_at; only the move code reads and removes it', () => {
    const writers = files.filter(({ text }) => /setItem\(\s*['"`]linkedin_li_at['"`]/.test(text)).map(({ rel }) => rel)
    expect(writers).toEqual([])
    const namers = files.filter(({ text }) => text.includes('linkedin_li_at')).map(({ rel }) => rel)
    expect(namers).toEqual(['src/modules/outreach/linkedinCookie.js'])
  })
})
