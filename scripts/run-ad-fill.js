#!/usr/bin/env node
/**
 * Fill from ad (Add job): the server reads one job page for the form. The Python side (`python/job_import/ad_fill.py`)
 * does the fetch with its own SSRF limits and reads schema.org JSON-LD; no model is involved here.
 *
 * Only the URL goes to Python, on stdin. No candidate data, Notes, links or Source URL is ever part of the request.
 * The page text stays in this process behind a short-lived token, so a later, confirmed AI step is given the text the
 * server fetched and nothing the browser sends.
 */

import { spawn } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const VENV_PYTHON = process.platform === 'win32' ? path.join(ROOT, '.venv/Scripts/python.exe') : path.join(ROOT, '.venv/bin/python')
const SCRIPT = path.join(ROOT, 'python/job_import/ad_fill.py')
const TTL_MS = 15 * 60 * 1000
const MAX_ENTRIES = 20

export const UNREADABLE_MESSAGE = 'Could not read this page, paste the text manually.'

const pages = new Map()

function remember(entry, now) {
  for (const [token, value] of pages) if (now - value.at > TTL_MS) pages.delete(token)
  while (pages.size >= MAX_ENTRIES) pages.delete(pages.keys().next().value)
  const token = crypto.randomUUID()
  pages.set(token, { ...entry, at: now })
  return token
}

/** The cached page for a token, or null (expired, unknown). It is not removed: the owner may extract twice. */
export function cachedPage(token, now = Date.now()) {
  const entry = pages.get(String(token ?? ''))
  if (!entry || now - entry.at > TTL_MS) {
    pages.delete(String(token ?? ''))
    return null
  }
  return entry
}

export function clearCachedPages() {
  pages.clear()
}

/** Runs one ad_fill.py command with `payload` on stdin; resolves with the parsed answer or null. */
export function runAdFill(command, payload, { spawnFn = spawn, python = VENV_PYTHON, script = SCRIPT } = {}) {
  return new Promise((resolve) => {
    if (spawnFn === spawn && !fs.existsSync(python)) {
      resolve(null)
      return
    }
    const out = []
    const child = spawnFn(python, [script, command], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    child.stdout.on('data', (d) => out.push(d))
    child.stderr?.on('data', () => {})
    child.on('error', () => resolve(null))
    child.on('close', () => {
      try {
        resolve(JSON.parse(Buffer.concat(out).toString('utf-8').trim().split('\n').pop()))
      } catch {
        resolve(null)
      }
    })
    child.stdin.end(JSON.stringify(payload))
  })
}

/**
 * @returns {Promise<{ status: number, body: object }>}
 * ok: `{ ok, token, fields, missing, finalUrl }`; the page text is not in the answer.
 */
export async function fetchAd(url, options = {}) {
  const text = String(url ?? '').trim()
  if (!/^https?:\/\//i.test(text) || text.length > 2000) {
    return { status: 422, body: { ok: false, error: 'bad_url', message: UNREADABLE_MESSAGE } }
  }
  const result = await runAdFill('fetch', { url: text }, options)
  if (!result || result.ok !== true) {
    const error = typeof result?.error === 'string' ? result.error : 'failed'
    const blocked = error === 'blocked_host'
    return {
      status: blocked ? 403 : 502,
      body: { ok: false, error, message: blocked ? String(result.message) : UNREADABLE_MESSAGE, detail: typeof result?.message === 'string' ? result.message : '' },
    }
  }
  const token = remember({ pageText: String(result.pageText ?? ''), fields: result.fields ?? {}, missing: result.missing ?? [] }, options.now ?? Date.now())
  return { status: 200, body: { ok: true, token, fields: result.fields ?? {}, missing: result.missing ?? [], finalUrl: result.finalUrl ?? text, source: result.source ?? 'none' } }
}

export const EXPIRED_MESSAGE = 'The page was read a while ago. Click Fill from ad again.'
export const AI_FAILED_MESSAGE = 'The AI could not read the fields from this page. Fill them in by hand.'

/** The fields to ask for: those the owner wants that the page did not state. A token that is gone or a list with nothing left is refused. */
function wanted(entry, want) {
  const asked = Array.isArray(want) ? want.map(String) : []
  return asked.filter((name) => (entry.missing || []).includes(name))
}

/**
 * What an AI step would send, without sending it: the redacted page text, the fields, the provider and whether the gate allows it.
 * The text comes from the cached page; nothing from the browser but the token and the field names.
 */
export async function previewAdAi({ token, want }, options = {}) {
  const entry = cachedPage(token, options.now)
  if (!entry) return { status: 410, body: { ok: false, error: 'expired', message: EXPIRED_MESSAGE } }
  const fields = wanted(entry, want)
  if (!fields.length) return { status: 422, body: { ok: false, error: 'nothing_to_ask', message: 'Every field is already filled.' } }
  const result = await runAdFill('ai-preview', { pageText: entry.pageText, want: fields }, options)
  if (!result || result.ok !== true) return { status: 502, body: { ok: false, error: result?.error || 'failed', message: result?.message || AI_FAILED_MESSAGE } }
  return { status: 200, body: result }
}

/** The one path that sends the page text to a model. Refused without `confirm: true`, like the CV analysis. */
export async function extractAdAi({ token, want, confirm }, options = {}) {
  if (confirm !== true) return { status: 409, body: { ok: false, error: 'confirm_required', message: 'Confirm what is sent first.' } }
  const entry = cachedPage(token, options.now)
  if (!entry) return { status: 410, body: { ok: false, error: 'expired', message: EXPIRED_MESSAGE } }
  const fields = wanted(entry, want)
  if (!fields.length) return { status: 422, body: { ok: false, error: 'nothing_to_ask', message: 'Every field is already filled.' } }
  const result = await runAdFill('ai-extract', { pageText: entry.pageText, want: fields }, options)
  if (result?.ok === true) return { status: 200, body: { ok: true, fields: result.fields ?? {}, rejected: result.rejected ?? [] } }
  const refused = result?.error === 'refused'
  return {
    status: refused ? 403 : 502,
    body: { ok: false, error: result?.error || 'failed', message: refused || result?.error === 'redaction' ? String(result.message) : AI_FAILED_MESSAGE },
  }
}
