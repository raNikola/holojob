import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const VENV_PYTHON = process.platform === 'win32' ? path.join(ROOT, '.venv/Scripts/python.exe') : path.join(ROOT, '.venv/bin/python')
const SOURCES_FILE = path.join(ROOT, 'src/data/importSources.json')
const IMPACT_RUNNER = path.join(ROOT, 'python/profile_import/run_impact.py')
const FILE_RUNNER = path.join(ROOT, 'python/profile_import/run_file_import.py')
const TEXT_RUNNER = path.join(ROOT, 'python/profile_import/run_text_import.py')

export const MAX_PASTE_BYTES = 200 * 1024
// JSON escaping can turn one character into six, so the body is allowed to be larger than the text it carries.
export const MAX_IMPORT_BODY_BYTES = MAX_PASTE_BYTES * 6 + 1024
const TIMEOUT_MS = 15000
const MAX_OUTPUT_BYTES = 4 * 1024 * 1024

export const IMPORT_ERRORS = {
  empty: { status: 400, error: 'There is no text to import.' },
  invalid_request: { status: 400, error: 'The import request is not valid.' },
  too_large: { status: 413, error: 'The text or file is too large. The limits are 200 KB for text and 10 MB for a Word or PDF file.' },
  timeout: { status: 504, error: 'The import took too long and was stopped.' },
  runner_missing: { status: 503, error: 'Python venv not found. Run: npm run setup' },
  corrupt_file: { status: 422, error: 'The file could not be opened. It may be damaged or not the type its name says.' },
  encrypted: { status: 422, error: 'The file is password protected or an old Word (.doc) file. Save it as an unprotected .docx, or paste the text.' },
  unsupported_type: { status: 415, error: 'This file type is not supported (macro-enabled and non-Word files are refused).' },
  no_text: { status: 422, error: 'No text could be read from the file. Scanned or image-only documents are not supported (there is no OCR); paste the text instead.' },
  json_invalid: { status: 422, error: 'This file is not valid JSON.' },
  json_not_resume: { status: 422, error: 'This JSON file is not a JSON Resume: it has none of the sections basics, work, education, skills, languages, projects or certificates.' },
  parse_failed: { status: 500, error: 'The text could not be read.' },
  impact_failed: { status: 500, error: 'The effect on your scoring caches could not be worked out.' },
}

/** Spawn the Python parser with the request on stdin. Resolves { ok, draft } or { ok: false, code }; never the text. */
function runPythonParser(runner, request, answerKey = 'draft') {
  return runPython(runner, [], JSON.stringify(request), answerKey)
}

/** The same for a file: its source id is the one argument, its bytes go on stdin (never in argv). */
function runPythonFile(source, bytes) {
  return runPython(FILE_RUNNER, [source], bytes, 'draft')
}

function runPython(runner, args, stdinData, answerKey) {
  return new Promise((resolve) => {
    if (!fs.existsSync(VENV_PYTHON)) {
      resolve({ ok: false, code: 'runner_missing' })
      return
    }
    const child = spawn(VENV_PYTHON, [runner, ...args], {
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
        if (answer?.ok === true && answer[answerKey] && typeof answer[answerKey] === 'object') finish({ ok: true, [answerKey]: answer[answerKey] })
        else finish({ ok: false, code: IMPORT_ERRORS[answer?.code] ? answer.code : 'parse_failed' })
      } catch {
        finish({ ok: false, code: 'parse_failed' })
      }
    })
    child.stdin.end(stdinData)
  })
}

// The sources whose input is text come from src/data/importSources.json (shared with the parser and the browser).
const SOURCES = JSON.parse(fs.readFileSync(SOURCES_FILE, 'utf-8')).sources
export const IMPORT_SOURCES = Object.entries(SOURCES).filter(([, source]) => source.input === 'text').map(([id]) => id)
/** The sources whose file the server reads itself (their bytes arrive on a route of their own). */
export const FILE_SOURCES = Object.entries(SOURCES).filter(([, source]) => source.input === 'bytes').map(([id]) => id)
/** Size limit per file source, in bytes (a text source is limited to 200 KB). */
export const FILE_LIMITS = { resume_docx: 10 * 1024 * 1024 }

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

let impactRunner = (request) => runPythonParser(IMPACT_RUNNER, request, 'impact')

/** Tests inject the impact runner; call with nothing to restore the real one. */
export function setImpactRunner(next) {
  impactRunner = next ?? ((request) => runPythonParser(IMPACT_RUNNER, request, 'impact'))
}

/**
 * What applying an import would do to the caches that depend on the profile: counts and profile versions only, read-only, local.
 * `before` and `after` are the two profiles as the mirror would hold them (the browser sends them through buildExportProfile).
 */
export async function importImpact(before, after) {
  const isProfile = (p) => p && typeof p === 'object' && !Array.isArray(p)
  if (!isProfile(before) || !isProfile(after)) return { ok: false, code: 'invalid_request' }
  return impactRunner({ before, after })
}

const defaultFileRunners = Object.fromEntries(FILE_SOURCES.map((source) => [source, (bytes) => runPythonFile(source, bytes)]))
let fileRunners = defaultFileRunners

/** Tests inject a runner per file source; call with nothing to restore the real ones. */
export function setFileRunners(next) {
  fileRunners = next ? { ...defaultFileRunners, ...next } : defaultFileRunners
}

/**
 * Parse an uploaded file (bytes) into a draft. Writes nothing: the file is handed to the parser on stdin and never stored.
 * The size is checked here and again by the parser; every answer is a draft or a fixed code.
 */
export async function parseImportFile(source, bytes) {
  if (!FILE_SOURCES.includes(source) || !Buffer.isBuffer(bytes)) return { ok: false, code: 'invalid_request' }
  if (bytes.length === 0) return { ok: false, code: 'empty' }
  if (bytes.length > FILE_LIMITS[source]) return { ok: false, code: 'too_large' }
  return fileRunners[source](bytes)
}
