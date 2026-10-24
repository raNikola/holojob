/**
 * CV analysis: reads one CV with the configured LLM provider (python/cv_analysis).
 * The Python side redacts the text first; the preview returns exactly what a run
 * would send, and only runCvAnalysis() calls the provider.
 */

import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const VENV_PYTHON = process.platform === 'win32' ? path.join(ROOT, '.venv/Scripts/python.exe') : path.join(ROOT, '.venv/bin/python')
const RUNNER = path.join(ROOT, 'python/cv_analysis/run_cv_analyze.py')

function spawnAnalysis(args, input) {
  return new Promise((resolve) => {
    if (!fs.existsSync(VENV_PYTHON)) {
      resolve({ ok: false, error: 'Python venv not found. Run: npm run setup:jobs' })
      return
    }
    const child = spawn(VENV_PYTHON, [RUNNER, ...args], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    let stdout = ''
    let stderr = ''
    child.stdin.write(JSON.stringify({
      rawText: String(input.rawText || ''),
      fullName: String(input.fullName || ''),
      links: Array.isArray(input.links) ? input.links.map(String) : [],
    }))
    child.stdin.end()
    child.stdout.on('data', (d) => { stdout += d })
    child.stderr.on('data', (d) => { stderr += d })
    child.on('error', (err) => resolve({ ok: false, error: err.message }))
    child.on('close', (code) => {
      try {
        const payload = JSON.parse(stdout.trim().split('\n').pop() || '{}')
        resolve({ ...payload, ok: code === 0 && payload.ok !== false })
      } catch {
        resolve({ ok: false, error: stderr.trim().split('\n').pop() || 'CV analysis produced no result' })
      }
    })
  })
}

/** What a run would send and to whom. Calls no model. */
export function previewCvAnalysis(input) {
  return spawnAnalysis(['--preview'], input)
}

/** The one path that sends CV text to an LLM provider. */
export function runCvAnalysis(input, { force = false } = {}) {
  return spawnAnalysis(force ? ['--force'] : [], input)
}
