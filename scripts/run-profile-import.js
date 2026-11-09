import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const VENV_PYTHON = process.platform === 'win32' ? path.join(ROOT, '.venv/Scripts/python.exe') : path.join(ROOT, '.venv/bin/python')
const SOURCES_FILE = path.join(ROOT, 'src/data/importSources.json')
const TEXT_RUNNER = path.join(ROOT, 'python/profile_import/run_text_import.py')

export const MAX_PASTE_BYTES = 200 * 1024
// JSON escaping can turn one character into six, so the body is allowed to be larger than the text it carries.
export const MAX_IMPORT_BODY_BYTES = MAX_PASTE_BYTES * 6 + 1024
const TIMEOUT_MS = 15000
const MAX_OUTPUT_BYTES = 4 * 1024 * 1024

export const IMPORT_ERRORS = {
  empty: { status: 400, error: 'There is no text to import.' },
  invalid_request: { status: 400, error: 'The import request is not valid.' },
  too_large: { status: 413, error: 'The text is too large. The limit is 200 KB.' },
  timeout: { status: 504, error: 'The import took too long and was stopped.' },
  runner_missing: { status: 503, error: 'Python venv not found. Run: npm run setup' },
  parse_failed: { status: 500, error: 'The text could not be read.' },
}

/** Spawn the Python parser with the request on stdin. Resolves { ok, draft } or { ok: false, code }; never the text. */
function runPythonParser(runner, request) {
  return new Promise((resolve) => {
    if (!fs.existsSync(VENV_PYTHON)) {
      resolve({ ok: false, code: 'runner_missing' })
      return
    }
    const child = spawn(VENV_PYTHON, [runner], {
      cwd: ROOT,
      env: { PATH: process.env.PATH, PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1' },
      stdio: ['pipe', 'pipe', 'ignore'],
    })
    const chunks = []
    let size = 0
    let settled = false
    const finish = (result) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve(result)
    }
    const timer = setTimeout(() => {
      child.kill('SIGKILL')
      finish({ ok: false, code: 'timeout' })
    }, TIMEOUT_MS)
    child.stdout.on('data', (chunk) => {
      size += chunk.length
      if (size > MAX_OUTPUT_BYTES) {
        child.kill('SIGKILL')
        finish({ ok: false, code: 'parse_failed' })
        return
      }
      chunks.push(chunk)
    })
    child.on('error', () => finish({ ok: false, code: 'parse_failed' }))
    child.stdin.on('error', () => {})
    child.on('close', () => {
      try {
        const answer = JSON.parse(Buffer.concat(chunks).toString('utf-8'))
        if (answer?.ok === true && answer.draft && typeof answer.draft === 'object') finish({ ok: true, draft: answer.draft })
        else finish({ ok: false, code: IMPORT_ERRORS[answer?.code] ? answer.code : 'parse_failed' })
      } catch {
        finish({ ok: false, code: 'parse_failed' })
      }
    })
    child.stdin.end(JSON.stringify(request))
  })
}

// The sources whose input is text come from src/data/importSources.json (shared with the parser and the browser).
export const IMPORT_SOURCES = Object.entries(JSON.parse(fs.readFileSync(SOURCES_FILE, 'utf-8')).sources)
  .filter(([, source]) => source.input === 'text')
  .map(([id]) => id)

const defaultRunners = Object.fromEntries(IMPORT_SOURCES.map((source) => [source, (request) => runPythonParser(TEXT_RUNNER, request)]))
let runners = defaultRunners

/** Tests inject a runner per source; call with nothing to restore the real ones. */
export function setImportRunners(next) {
  runners = next ? { ...defaultRunners, ...next } : defaultRunners
}

/**
 * Parse one import source into a draft. Writes nothing. The text is checked here
 * (type, size in bytes) and again by the parser. A PDF is read in the browser; only its text arrives.
 */
export async function parseImportSource(source, text) {
  if (!IMPORT_SOURCES.includes(source) || typeof text !== 'string') return { ok: false, code: 'invalid_request' }
  if (Buffer.byteLength(text, 'utf8') > MAX_PASTE_BYTES) return { ok: false, code: 'too_large' }
  if (!text.trim()) return { ok: false, code: 'empty' }
  return runners[source]({ text, source })
}
