import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import {
  KEYED_AI_PROVIDERS,
  SecretStoreError,
  clearAiSecret,
  describeSecrets,
  exactSecretValues,
  getAiCredential,
  redactSecrets,
  setAiSecret,
} from '../../scripts/secret-store.js'
import { maskSecrets } from '../../scripts/secret-mask.js'
import { CANARY, useTempSecretStore } from './helpers/secretTestStore.js'

const store = useTempSecretStore()
const file = () => path.join(store.dir, 'ai.json')
const mode = (p) => fs.statSync(p).mode & 0o777

describe('files', () => {
  it('creates the directory with mode 700 and the file with mode 600', () => {
    setAiSecret('openai', { key: CANARY })
    expect(mode(store.dir)).toBe(0o700)
    expect(mode(file())).toBe(0o600)
  })

  it('keeps mode 600 whatever the process umask is, and tightens a loose directory', () => {
    fs.mkdirSync(store.dir, { recursive: true, mode: 0o755 })
    fs.chmodSync(store.dir, 0o755)
    const old = process.umask(0o000)
    try {
      setAiSecret('openai', { key: CANARY })
      setAiSecret('openai', { key: `${CANARY}-2` })
    } finally {
      process.umask(old)
    }
    expect(mode(store.dir)).toBe(0o700)
    expect(mode(file())).toBe(0o600)
  })

  it('leaves no temp file behind and replaces the file in one rename', () => {
    setAiSecret('openai', { key: CANARY })
    setAiSecret('gemini', { key: `${CANARY}-g` })
    expect(fs.readdirSync(store.dir)).toEqual(['ai.json'])
    expect(JSON.parse(fs.readFileSync(file(), 'utf-8'))).toMatchObject({ openai: { key: CANARY }, gemini: { key: `${CANARY}-g` } })
  })

  it('removes a failed temp file and keeps the old content when the write fails', () => {
    setAiSecret('openai', { key: CANARY })
    const before = fs.readFileSync(file(), 'utf-8')
    const rename = vi.spyOn(fs, 'renameSync').mockImplementation(() => { throw new Error('disk full') })
    expect(() => setAiSecret('gemini', { key: `${CANARY}-g` })).toThrow('disk full')
    rename.mockRestore()
    expect(fs.readFileSync(file(), 'utf-8')).toBe(before)
    expect(fs.readdirSync(store.dir)).toEqual(['ai.json'])
  })

  it('removes the file when the last key is cleared, and keeps the others until then', () => {
    setAiSecret('openai', { key: CANARY })
    setAiSecret('gemini', { key: `${CANARY}-g` })
    clearAiSecret('openai')
    expect(Object.keys(JSON.parse(fs.readFileSync(file(), 'utf-8')))).toEqual(['gemini'])
    clearAiSecret('gemini')
    expect(fs.existsSync(file())).toBe(false)
    expect(describeSecrets().ai.openai.set).toBe(false)
  })

  it('never overwrites a store file it cannot read', () => {
    fs.mkdirSync(store.dir, { recursive: true, mode: 0o700 })
    fs.writeFileSync(file(), '{ not json')
    expect(describeSecrets().unreadable).toBe(true)
    expect(() => setAiSecret('openai', { key: CANARY })).toThrow(SecretStoreError)
    expect(() => clearAiSecret('openai')).toThrow(SecretStoreError)
    expect(fs.readFileSync(file(), 'utf-8')).toBe('{ not json')
  })
})

describe('what is reported', () => {
  it('describes a key by "set" and its last 4 characters only', () => {
    const entry = setAiSecret('openai', { key: CANARY })
    expect(entry).toMatchObject({ set: true, source: 'store', last4: CANARY.slice(-4), baseUrl: null })
    expect(JSON.stringify(describeSecrets())).not.toContain(CANARY)
    expect(describeSecrets().ai.claude).toMatchObject({ set: false, source: null, last4: null })
  })

  it('lists every keyed provider and no keyless one', () => {
    expect(Object.keys(describeSecrets().ai)).toEqual(KEYED_AI_PROVIDERS)
  })

  it('shows a short .env key as ****', () => {
    vi.stubEnv('OPENAI_API_KEY', 'short-key')
    expect(describeSecrets().ai.openai).toMatchObject({ set: true, source: 'env', last4: '****' })
    vi.unstubAllEnvs()
  })
})

describe('what is refused', () => {
  it('refuses an unknown or keyless provider', () => {
    for (const provider of ['ollama', 'claude-code', 'mock', '__proto__', 'constructor', '']) {
      expect(() => setAiSecret(provider, { key: CANARY }), provider).toThrow(/Unknown provider/)
      expect(() => clearAiSecret(provider), provider).toThrow(/Unknown provider/)
    }
    expect(getAiCredential('__proto__')).toBeNull()
  })

  it('refuses a bad key without quoting it', () => {
    for (const key of [undefined, null, 5, '', 'short', 'has a space in it 123', `${CANARY}\n${CANARY}`, 'x'.repeat(513)]) {
      let error
      try { setAiSecret('openai', { key }) } catch (e) { error = e }
      expect(error, String(key)).toBeInstanceOf(SecretStoreError)
      expect(error.message).not.toContain(CANARY)
    }
    expect(fs.existsSync(file())).toBe(false)
  })

  it('refuses a base URL that is not plain http(s), without quoting it', () => {
    for (const baseUrl of ['ftp://x.example', 'javascript:alert(1)', 'not a url', 'https://user:pw@x.example/v1', 'https://x.example/v1?key=1', 'https://x.example/#a', 5]) {
      let error
      try { setAiSecret('openai', { key: CANARY, baseUrl }) } catch (e) { error = e }
      expect(error, String(baseUrl)).toBeInstanceOf(SecretStoreError)
      expect(error.message).not.toContain('x.example')
    }
  })

  it('trims a pasted key', () => {
    setAiSecret('openai', { key: `  ${CANARY}\n` })
    expect(getAiCredential('openai').apiKey).toBe(CANARY)
  })
})

describe('what the server reads', () => {
  it('pins the base URL to the stored key, and a replace without one drops it', () => {
    setAiSecret('openrouter', { key: CANARY, baseUrl: 'https://proxy.example/v1/' })
    expect(getAiCredential('openrouter')).toEqual({ apiKey: CANARY, baseUrl: 'https://proxy.example/v1', source: 'store' })
    setAiSecret('openrouter', { key: `${CANARY}-2` })
    expect(getAiCredential('openrouter')).toEqual({ apiKey: `${CANARY}-2`, baseUrl: undefined, source: 'store' })
  })

  it('prefers the store over .env, falls back to .env for openai and claude only, and returns null otherwise', () => {
    vi.stubEnv('OPENAI_API_KEY', 'env-openai-key-value')
    vi.stubEnv('ANTHROPIC_API_KEY', 'env-claude-key-value')
    expect(getAiCredential('openai')).toMatchObject({ apiKey: 'env-openai-key-value', source: 'env' })
    expect(getAiCredential('claude')).toMatchObject({ apiKey: 'env-claude-key-value', source: 'env' })
    expect(getAiCredential('gemini')).toBeNull()
    expect(getAiCredential('openrouter')).toBeNull()
    setAiSecret('openai', { key: CANARY })
    expect(getAiCredential('openai')).toMatchObject({ apiKey: CANARY, source: 'store' })
    clearAiSecret('openai')
    expect(getAiCredential('openai').source).toBe('env')
    vi.unstubAllEnvs()
  })

  it('sees a replaced key at once, and a file changed by another process', () => {
    setAiSecret('openai', { key: CANARY })
    setAiSecret('openai', { key: `${CANARY}-new` })
    expect(getAiCredential('openai').apiKey).toBe(`${CANARY}-new`)
    fs.writeFileSync(file(), JSON.stringify({ openai: { key: `${CANARY}-edited-by-hand` } }), { mode: 0o600 })
    expect(getAiCredential('openai').apiKey).toBe(`${CANARY}-edited-by-hand`)
  })
})

describe('exact-value masking', () => {
  it('masks the stored key, its URL-encoded form and .env keys wherever they appear', () => {
    const key = 'abc/def+ghi=jkl-0123456789'
    setAiSecret('openai', { key })
    vi.stubEnv('ANTHROPIC_API_KEY', 'env-claude-key-value')
    const text = `boom ${key} then ${encodeURIComponent(key)} and ${'env-claude-key-value'} (${key.slice(0, 6)})`
    for (const out of [maskSecrets(text), redactSecrets(text)]) {
      expect(out).not.toContain(key)
      expect(out).not.toContain(encodeURIComponent(key))
      expect(out).not.toContain('env-claude-key-value')
    }
    expect(exactSecretValues()).toContain(key)
    vi.unstubAllEnvs()
  })

  it('masks a key the patterns do not know, in the first place and not as a leftover', () => {
    setAiSecret('openrouter', { key: 'plain-key-without-known-shape' })
    expect(maskSecrets('upstream said: plain-key-without-known-shape rejected')).toBe('upstream said: [secret] rejected')
  })

  it('stops masking a key once it is cleared, and ignores very short values', () => {
    setAiSecret('openai', { key: CANARY })
    clearAiSecret('openai')
    expect(maskSecrets(`x ${CANARY} y`)).toBe(`x ${CANARY} y`)
    vi.stubEnv('OPENAI_API_KEY', 'tiny')
    expect(maskSecrets('a tiny thing')).toBe('a tiny thing')
    vi.unstubAllEnvs()
  })
})
