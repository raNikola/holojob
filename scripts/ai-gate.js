/**
 * Node side of the AI budget gate. The gate itself is python/llm/ai_gate.py, one
 * module for the whole app: this file runs its CLI, so the browser features
 * (scripts/run-ai.js) share the Python side's limits, lock and ledger.
 *
 * Fails closed: when the gate cannot be asked, the call is refused.
 */

import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const VENV_PYTHON = process.platform === 'win32' ? path.join(ROOT, '.venv/Scripts/python.exe') : path.join(ROOT, '.venv/bin/python')
const GATE = path.join(ROOT, 'python/llm/ai_gate.py')

/** Providers that are not a model call at all (canned answers); never gated, never recorded. */
export const UNGATED_PROVIDERS = new Set(['mock'])

function runGateCli(command, input) {
  return new Promise((resolve, reject) => {
    const child = spawn(VENV_PYTHON, [GATE, command], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    const out = []
    const err = []
    child.stdout.on('data', (d) => out.push(d))
    child.stderr.on('data', (d) => err.push(d))
    child.on('error', reject)
    child.on('close', (code) => {
      const stdout = Buffer.concat(out).toString('utf-8').trim()
      try {
        resolve(JSON.parse(stdout.split('\n').pop()))
      } catch {
        reject(new Error(`AI gate exited ${code}: ${Buffer.concat(err).toString('utf-8').slice(0, 300)}`))
      }
    })
    child.stdin.end(input ? JSON.stringify(input) : '')
  })
}

let runner = runGateCli

/** Tests replace the CLI runner; pass nothing to restore it. */
export function setGateRunner(fn) {
  runner = fn || runGateCli
}

/** Ask before a call. Resolves { allowed, id, reason }; never rejects. */
export async function reserveAiCall({ provider, model, promptChars, baseUrl, feature, jobId }) {
  try {
    const result = await runner('reserve', { provider, model: model || null, promptChars, baseUrl: baseUrl || null, feature, jobId: jobId || null })
    return { allowed: Boolean(result?.allowed), id: result?.id || null, reason: result?.reason || null }
  } catch (e) {
    return { allowed: false, id: null, reason: `AI gate unavailable, call refused: ${e.message}` }
  }
}

/** Record what an allowed call used. Never rejects: the answer is already in hand. */
export async function finishAiCall(id, { ok, inputTokens, outputTokens, error, baseUrl } = {}) {
  if (!id) return
  try {
    await runner('finish', {
      id,
      ok: Boolean(ok),
      inputTokens: Number.isInteger(inputTokens) ? inputTokens : null,
      outputTokens: Number.isInteger(outputTokens) ? outputTokens : null,
      error: error || null,
      baseUrl: baseUrl || null,
    })
  } catch (e) {
    console.error(`AI gate: could not record the result of call ${id}: ${e.message}`)
  }
}

/** Totals for GET /api/ai/usage. */
export function readAiUsage() {
  return runner('usage', null)
}

/** Validate and write the gate settings (data/ai/settings.json). Resolves ai_gate.save_settings' result. */
export function saveAiSettings(settings, confirm) {
  return runner('settings-put', { settings, confirm: confirm === true })
}

/** Validate and write the price-table overrides (data/ai/pricing-overrides.json). */
export function saveAiPricing(entries, confirm) {
  return runner('pricing-put', { entries, confirm: confirm === true })
}

/** Record a call the app refused before it reached the gate (e.g. redaction failed). Never rejects. */
export async function recordAiRefusal({ provider, model, feature, jobId, baseUrl, reason }) {
  try {
    await runner('refuse', { provider, model: model || null, feature, jobId: jobId || null, baseUrl: baseUrl || null, reason })
  } catch (e) {
    console.error(`AI gate: could not record a refusal (${reason}): ${e.message}`)
  }
}
