import { describe, expect, it, vi } from 'vitest'
import { installLogMasking, maskErrorField, maskSecrets } from '../../scripts/secret-mask.js'

const SECRETS = {
  openai: 'sk-proj-AbCdEf1234567890xyz',
  anthropic: 'sk-ant-api03-AbCdEf1234567890',
  google: 'AIzaCcF-1pTlom01IerLPuWP-d4rKIK6nmJHMLR',
  hex: 'a3f9c1d27b8e4f60a3f9c1d27b8e4f60',
  mixed: 'Zx81QwErTy92UiOpAs03DfGh45JkLz67',
  cookie: 'AQEDAReallyLongLiAtCookieValue123',
}

describe('maskSecrets', () => {
  it('masks sk- keys, Google keys and long tokens', () => {
    for (const value of Object.values(SECRETS)) {
      expect(maskSecrets(`provider said: bad credential ${value} for this call`)).not.toContain(value)
    }
  })

  it('masks key=, token= and similar query-string values and keeps the rest of the URL', () => {
    const out = maskSecrets(`fetch failed https://generativelanguage.googleapis.com/v1beta/models/m:generateContent?alt=sse&key=${SECRETS.google}&x=1`)
    expect(out).not.toContain(SECRETS.google)
    expect(out).toContain('generativelanguage.googleapis.com/v1beta/models/m:generateContent?alt=sse&key=[secret]')
    expect(maskSecrets('GET /x?access_token=abc12345&li_at=hunter2hunter2')).toBe('GET /x?access_token=[secret]&li_at=[secret]')
  })

  it('masks Authorization headers in plain and JSON form', () => {
    expect(maskSecrets('Authorization: Bearer abc.def-ghi12345')).toBe('Authorization: [secret]')
    expect(maskSecrets('{"Authorization":"Basic dXNlcjpwYXNz"}')).not.toContain('dXNlcjpwYXNz')
    expect(maskSecrets('headers { authorization: \'Bearer tok_12345678\' }')).not.toContain('tok_12345678')
    expect(maskSecrets('retry with Bearer abcdefghijklmnop please')).not.toContain('abcdefghijklmnop')
  })

  it('masks the li_at cookie as a flag, a pair or a JSON field', () => {
    expect(maskSecrets(`spawn python scrape.py --li-at ${SECRETS.cookie} --max 5`)).toBe('spawn python scrape.py --li-at [secret] --max 5')
    expect(maskSecrets(`li_at=${SECRETS.cookie}; JSESSIONID=x`)).not.toContain(SECRETS.cookie)
    expect(maskSecrets(`{"li_at": "${SECRETS.cookie}"}`)).not.toContain(SECRETS.cookie)
  })

  it('masks key-like JSON fields and headers', () => {
    expect(maskSecrets('{"apiKey":"abcd1234efgh","model":"m"}')).toBe('{"apiKey":"[secret]","model":"m"}')
    expect(maskSecrets('x-api-key: abcd1234efgh')).toBe('x-api-key: [secret]')
    expect(maskSecrets('password=correcthorse')).toBe('password=[secret]')
  })

  it('leaves ordinary error text alone', () => {
    for (const text of [
      'Unexpected token } in JSON at position 12',
      'ENOENT: no such file or directory, open data/jobs/scored_jobs.json',
      'File is too large. Maximum size is 10 MB.',
      'Application 8f3c not found',
      'Provider claude-code is offline',
    ]) expect(maskSecrets(text)).toBe(text)
  })

  it('passes null and undefined through', () => {
    expect(maskSecrets(null)).toBeNull()
    expect(maskSecrets(undefined)).toBeUndefined()
  })
})

describe('maskErrorField', () => {
  it('masks only the error string', () => {
    const data = { error: `bad key ${SECRETS.openai}`, id: SECRETS.mixed }
    const out = maskErrorField(data)
    expect(out.error).not.toContain(SECRETS.openai)
    expect(out.id).toBe(SECRETS.mixed)
    expect(maskErrorField([1])).toEqual([1])
    expect(maskErrorField({ ok: true })).toEqual({ ok: true })
  })
})

describe('installLogMasking', () => {
  it('masks strings and errors written to the console, once', () => {
    const seen = []
    const target = { log: (...a) => seen.push(a), info: () => {}, warn: () => {}, error: (...a) => seen.push(a), debug: () => {} }
    installLogMasking(target)
    installLogMasking(target)
    target.error(`call failed ?key=${SECRETS.google}`, new Error(`boom Bearer ${SECRETS.mixed}`), { n: 1 })
    const flat = JSON.stringify(seen)
    expect(flat).not.toContain(SECRETS.google)
    expect(flat).not.toContain(SECRETS.mixed)
    expect(seen[0][2]).toEqual({ n: 1 })
    vi.restoreAllMocks()
  })
})
