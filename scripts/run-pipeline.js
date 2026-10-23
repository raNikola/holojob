#!/usr/bin/env node
/**
 * Run the whole pipeline (discovery, enrichment, scoring) through
 * python/run_pipeline.py, the same command cron and `npm run pipeline` use.
 * It never judges, and it stops at the first failed step.
 */

import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { saveIntelligenceToDisk } from './save-intelligence.js'
import { saveProfileToDisk } from './save-profile.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const INTELLIGENCE_PATH = path.join(ROOT, 'data/intelligence/candidate-intelligence.json')
const JOBS_PATH = path.join(ROOT, 'data/jobs/discovered_jobs.json')
const SCORED_PATH = path.join(ROOT, 'data/jobs/scored_jobs.json')
const VENV_PYTHON = process.platform === 'win32' ? path.join(ROOT, '.venv/Scripts/python.exe') : path.join(ROOT, '.venv/bin/python')
const RUN_PIPELINE = path.join(ROOT, 'python/run_pipeline.py')

export function buildPipelineCommand(opts = {}) {
  const providers = opts.providers || 'serbia'
  const country = opts.country ? ` --country ${opts.country}` : ''
  return `source .venv/bin/activate && python python/run_pipeline.py --providers ${providers}${country}`
}

function failure(stderr) {
  return { ok: false, exitCode: 1, stdout: '', stderr, payload: null, discoveredPayload: null, jobCount: 0, summary: null, failedStep: null }
}

/** Parse "PIPELINE STOPPED at <step>: <reason>" from the orchestrator's stderr. */
export function parseStoppedStep(stderr) {
  const m = /PIPELINE STOPPED at (\w+): ([^\n]*)/.exec(stderr || '')
  return m ? { failedStep: m[1], reason: m[2] } : { failedStep: null, reason: null }
}

export function runPipeline(opts = {}) {
  if (!fs.existsSync(VENV_PYTHON)) return Promise.resolve(failure('Python venv not found. Run: npm run setup:jobs'))
  if (opts.intelligence) saveIntelligenceToDisk(opts.intelligence)
  else if (!fs.existsSync(INTELLIGENCE_PATH)) {
    return Promise.resolve(failure(`Missing ${INTELLIGENCE_PATH}. Generate intelligence in Module 2 first.`))
  }
  if (opts.profile) saveProfileToDisk(opts.profile)

  const args = [RUN_PIPELINE, '--json', '--providers', opts.providers || 'serbia']
  if (opts.country) args.push('--country', opts.country)

  return new Promise((resolve) => {
    const chunks = { out: [], err: [] }
    const child = spawn(VENV_PYTHON, args, { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    child.stdout.on('data', (d) => chunks.out.push(d))
    child.stderr.on('data', (d) => chunks.err.push(d))
    child.on('error', (err) => resolve(failure(err.message)))
    child.on('close', (code) => {
      const stdout = Buffer.concat(chunks.out).toString('utf-8')
      const stderr = Buffer.concat(chunks.err).toString('utf-8')
      const read = (file) => {
        try { return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf-8')) : null } catch { return null }
      }
      let summary = null
      try { summary = JSON.parse(stdout.trim().split('\n').pop()) } catch { /* a failed run prints no summary */ }
      const payload = read(SCORED_PATH)
      resolve({
        ok: code === 0,
        exitCode: code ?? 1,
        stdout,
        stderr,
        summary,
        ...parseStoppedStep(stderr),
        payload,
        discoveredPayload: read(JOBS_PATH),
        jobCount: payload?.jobs?.length ?? 0,
      })
    })
  })
}
