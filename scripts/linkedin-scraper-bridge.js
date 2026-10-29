/**
 * Bridge to the Playwright-based LinkedIn contact scraper.
 *
 * Spawns python/outreach_scraper/scrape_linkedin_contacts.py, which has two
 * modes:
 *   - "search" (default): public DuckDuckGo snippets, no LinkedIn login.
 *   - "deep": authenticated people-search using the user's li_at cookie.
 *
 * The li_at cookie comes from the secret store (data/secrets/linkedin.json), then the
 * LINKEDIN_LI_AT variable of .env (scripts/secret-store.js). It is handed to the scraper
 * only in the child's own environment (LINKEDIN_LI_AT), never as an argument: argv is
 * readable by every local process. It is never written to discovery output, and
 * the scraper's text is masked before it leaves this module.
 */

import fs from 'node:fs'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { getLinkedInCookie } from './secret-store.js'
import { maskSecrets } from './secret-mask.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const VENV_PYTHON = process.platform === 'win32' ? path.join(ROOT, '.venv/Scripts/python.exe') : path.join(ROOT, '.venv/bin/python')
const SCRAPER = path.join(ROOT, 'python/outreach_scraper/scrape_linkedin_contacts.py')
const COOKIE_ENV = 'LINKEDIN_LI_AT'

// Test seam: the real spawn and the interpreter check can be replaced, so a test never starts the scraper.
let runtime = { spawn, pythonExists: () => fs.existsSync(VENV_PYTHON) }
export function setBridgeRuntime(overrides) {
  runtime = overrides ? { ...runtime, ...overrides } : { spawn, pythonExists: () => fs.existsSync(VENV_PYTHON) }
}

/** The stored (else .env) cookie, or ''. A cookie in a request is never accepted. */
export function resolveLiAt() {
  return getLinkedInCookie() || ''
}

/** The child's environment: never the cookie, except `liAt` in deep mode. */
function childEnv(liAt) {
  const env = { ...process.env, PYTHONIOENCODING: 'utf-8' }
  delete env[COOKIE_ENV]
  if (liAt) env[COOKIE_ENV] = liAt
  return env
}

function runPython(args, { timeoutMs, liAt = '' }) {
  return new Promise((resolve) => {
    if (!runtime.pythonExists()) {
      resolve({ contacts: [], queriesRun: 0, error: 'Python venv not found (run npm run setup:jobs)' })
      return
    }
    const child = runtime.spawn(VENV_PYTHON, [SCRAPER, ...args], { cwd: ROOT, env: childEnv(liAt) })
    let stdout = ''
    let stderr = ''
    const timer = setTimeout(() => child.kill('SIGKILL'), timeoutMs)
    child.stdout.on('data', (d) => { stdout += d })
    child.stderr.on('data', (d) => { stderr += d })
    child.on('close', () => {
      clearTimeout(timer)
      const line = stdout.trim().split('\n').filter(Boolean).pop()
      try {
        const result = JSON.parse(line)
        for (const field of ['error', 'status']) if (typeof result[field] === 'string') result[field] = maskSecrets(result[field])
        resolve(result)
      } catch {
        resolve({ contacts: [], queriesRun: 0, error: maskSecrets(stderr.trim()) || 'scraper produced no JSON' })
      }
    })
  })
}

/**
 * @param {object} job - must have `company`
 * @param {object} opts - { mode: 'search'|'deep', acceptTosRisk, maxContacts }
 */
export async function scrapeLinkedInContacts(job, opts = {}) {
  const company = (job?.company || '').trim()
  if (!company) return { contacts: [], queriesRun: 0, mode: opts.mode || 'search' }

  const mode = opts.mode === 'deep' ? 'deep' : 'search'
  const maxContacts = opts.maxContacts || 10
  let liAt = ''
  const args = ['--company', company, '--mode', mode, '--max', String(maxContacts)]

  if (mode === 'deep') {
    if (!opts.acceptTosRisk) {
      return {
        contacts: [],
        queriesRun: 0,
        mode,
        error: 'deep mode requires acceptTosRisk: true (LinkedIn ToS violation and account ban risk)',
      }
    }
    liAt = resolveLiAt()
    if (!liAt) {
      return { contacts: [], queriesRun: 0, mode, error: 'deep mode requires a LinkedIn li_at cookie (set it in Settings > Privacy)' }
    }
    args.push('--i-accept-tos-risk')
  }

  // deep mode is slower (human-like delays + multiple pages)
  const timeoutMs = mode === 'deep' ? 180000 : 90000
  return runPython(args, { timeoutMs, liAt })
}
