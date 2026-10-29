/**
 * Dev-only AI feature runner — invoked from Vite middleware.
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildMessages, parseAiResponse } from '../src/modules/ai/aiPromptLibrary.js'
import { getProvider, PROVIDER_NAMES, KEYLESS_PROVIDERS, checkProviderHealth, listProviderModels } from '../src/modules/ai/aiProviderRegistry.js'
import { initSseResponse, sseWrite } from './stream-spawn.js'
import { UNGATED_PROVIDERS, finishAiCall, recordAiRefusal, reserveAiCall } from './ai-gate.js'
import { assertClean, redactContext } from './ai-redact.js'
import { maskSecrets } from './secret-mask.js'
import { getAiCredential } from './secret-store.js'
import { PROVIDER_DEFAULTS } from '../src/modules/ai/aiSettings.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const INTERVIEWS_ROOT = path.join(ROOT, 'data/interviews')
const RESUMES_ROOT = path.join(ROOT, 'data/resumes')
const ANALYTICS_ROOT = path.join(ROOT, 'data/analytics')

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
}

function sanitizeKey(key) {
  return maskSecrets(String(key || ''))
}

export function writeInterviewPrep(jobId, data) {
  const dir = path.join(INTERVIEWS_ROOT, path.basename(jobId))
  ensureDir(dir)
  const filePath = path.join(dir, 'interview_prep.json')
  fs.writeFileSync(filePath, JSON.stringify({ ...data, generatedAt: new Date().toISOString() }, null, 2))
  return filePath
}

export function writeCoverLetter(jobId, variants) {
  const dir = path.join(RESUMES_ROOT, path.basename(jobId))
  ensureDir(dir)
  const content = [
    '# AI Cover Letter Variants',
    '',
    '## Short',
    variants.short || '',
    '',
    '## Standard',
    variants.standard || '',
    '',
    '## Aggressive',
    variants.aggressive || '',
  ].join('\n')
  const filePath = path.join(dir, 'ai_cover_letter.md')
  fs.writeFileSync(filePath, content)
  return filePath
}

export function writeSkillGap(data) {
  ensureDir(ANALYTICS_ROOT)
  const filePath = path.join(ANALYTICS_ROOT, 'skill_gap.json')
  fs.writeFileSync(filePath, JSON.stringify({ ...data, generatedAt: new Date().toISOString() }, null, 2))
  return filePath
}

const FEATURE_LABELS = {
  jobAnalysis: 'job fit analysis',
  resumeEnhancement: 'resume enhancement',
  coverLetter: 'cover letter variants',
  interviewPrep: 'interview prep',
  outreach: 'outreach message',
  companyIntelligence: 'company intelligence',
  careerStrategy: 'career strategy',
  skillGap: 'skill gap analysis',
  applicationStrategy: 'application strategy',
  chat: 'chat response',
}

export const NO_KEY_MESSAGE = 'No API key configured'

/**
 * The one effective settings object of a call: used for the gate, the provider, status and models.
 * Only provider, model, temperature and maxTokens come from the request. A keyed provider takes its key and
 * base URL from the secret store (then .env); an apiKey or baseUrl in the request is ignored, so the key
 * cannot be redirected to another host nor the gate be told a different target. Ollama takes the request's
 * base URL because no credential is attached to it. Never log the result: it holds the key.
 */
export function resolveAiSettings(settings) {
  const provider = settings?.provider || 'mock'
  const effective = { provider, model: settings?.model, temperature: settings?.temperature, maxTokens: settings?.maxTokens }
  if (KEYLESS_PROVIDERS.has(provider)) {
    return { ...effective, baseUrl: provider === 'ollama' ? settings?.baseUrl : undefined, needsKey: false }
  }
  const credential = getAiCredential(provider)
  // The gate is told the host the key really goes to: the pinned URL, else the provider's own.
  return { ...effective, apiKey: credential?.apiKey, baseUrl: credential?.baseUrl || PROVIDER_DEFAULTS[provider]?.baseUrl, needsKey: true }
}

export function runAiFeatureStream(res, { feature, context, settings }) {
  initSseResponse(res)
  const providerName = settings?.provider || 'mock'
  const model = settings?.model || ''
  const label = FEATURE_LABELS[feature] || feature
  sseWrite(res, { type: 'log', stream: 'stdout', line: `AI: ${label}` })
  sseWrite(res, { type: 'log', stream: 'stdout', line: `Provider: ${providerName}${model ? ` · ${model}` : ''}` })
  if (providerName === 'claude-code') {
    sseWrite(res, { type: 'log', stream: 'stdout', line: 'Claude Code is thinking — usually 30–90 seconds…' })
  } else if (providerName === 'mock') {
    sseWrite(res, { type: 'log', stream: 'stdout', line: 'Using mock provider (instant)' })
  } else {
    sseWrite(res, { type: 'log', stream: 'stdout', line: 'Waiting for model response…' })
  }

  runAiFeature({ feature, context, settings })
    .then((result) => {
      if (!result.ok) {
        sseWrite(res, { type: 'error', message: result.error || 'AI request failed' })
        res.end()
        return
      }
      sseWrite(res, { type: 'log', stream: 'stdout', line: 'Response received — parsing output…' })
      if (result.usage) {
        const inTok = result.usage.inputTokens || result.usage.prompt_tokens || 0
        const outTok = result.usage.outputTokens || result.usage.completion_tokens || 0
        if (inTok || outTok) {
          sseWrite(res, { type: 'log', stream: 'stdout', line: `Tokens: ${inTok} in · ${outTok} out` })
        }
      }
      sseWrite(res, { type: 'done', ok: true, ...result })
      res.end()
    })
    .catch((e) => {
      sseWrite(res, { type: 'error', message: sanitizeKey(e.message) })
      res.end()
    })
}

/** Measured tokens, or nulls when the provider reported none (the gate then estimates). */
function measuredTokens(usage) {
  const input = usage?.inputTokens || usage?.prompt_tokens || 0
  const output = usage?.outputTokens || usage?.completion_tokens || 0
  return input || output ? { inputTokens: input, outputTokens: output } : { inputTokens: null, outputTokens: null }
}

export async function runAiFeature({ feature, context, settings: requested }) {
  const settings = resolveAiSettings(requested)
  const providerName = settings.provider
  const provider = getProvider(providerName)
  // Redaction comes first and fails closed: no identifier of the owner or a recruiter may reach the provider.
  let messages
  try {
    const redacted = redactContext(context)
    messages = buildMessages(feature, redacted.context)
    assertClean(messages, redacted.ids)
  } catch (e) {
    const reason = `call not made: ${sanitizeKey(e.message)}`
    if (!UNGATED_PROVIDERS.has(providerName)) {
      await recordAiRefusal({ provider: providerName, model: settings?.model, feature, jobId: context?.job?.jobId, baseUrl: settings?.baseUrl, reason })
    }
    return { ok: false, refused: true, error: reason }
  }
  // No key, no call: nothing to reserve in the budget either.
  if (settings.needsKey && !settings.apiKey) return { ok: false, error: NO_KEY_MESSAGE }
  // The AI budget gate (python/llm/ai_gate.py) decides before every real call.
  let ticket = null
  if (!UNGATED_PROVIDERS.has(providerName)) {
    ticket = await reserveAiCall({
      provider: providerName,
      model: settings?.model,
      promptChars: messages.reduce((n, m) => n + String(m.content || '').length, 0),
      baseUrl: settings?.baseUrl,
      feature,
      jobId: context?.job?.jobId,
    })
    if (!ticket.allowed) {
      return { ok: false, refused: true, error: ticket.reason || 'AI call refused by the budget gate' }
    }
  }
  try {
    const result = await provider.complete({
      messages,
      model: settings?.model,
      temperature: settings?.temperature,
      maxTokens: settings?.maxTokens,
      apiKey: settings.apiKey,
      baseUrl: settings.baseUrl,
      featureId: feature,
    }).catch(async (e) => {
      if (ticket) await finishAiCall(ticket.id, { ok: false, error: sanitizeKey(e.message), baseUrl: settings?.baseUrl })
      ticket = null
      throw e
    })
    if (ticket) await finishAiCall(ticket.id, { ok: true, ...measuredTokens(result.usage), baseUrl: settings?.baseUrl })
    const data = parseAiResponse(result.text, feature)
    let diskPath = null

    if (feature === 'interviewPrep' && context?.job?.jobId) {
      diskPath = writeInterviewPrep(context.job.jobId, data)
    }
    if (feature === 'coverLetter' && context?.job?.jobId) {
      diskPath = writeCoverLetter(context.job.jobId, data)
    }
    if (feature === 'skillGap') {
      diskPath = writeSkillGap(data)
    }

    return {
      ok: true,
      data,
      usage: result.usage,
      diskPath,
    }
  } catch (e) {
    return { ok: false, error: sanitizeKey(e.message) }
  }
}

export async function runAiChat({ context, settings, message }) {
  return runAiFeature({
    feature: 'chat',
    context: { ...context, message },
    settings,
  })
}

/** Provider health. Keyed providers use the stored key; a request cannot supply one. */
export async function getAiStatus() {
  const results = {}
  for (const name of PROVIDER_NAMES) {
    const effective = resolveAiSettings({ provider: name })
    if (effective.needsKey && !effective.apiKey) {
      results[name] = { online: false, reason: NO_KEY_MESSAGE }
      continue
    }
    try {
      results[name] = await checkProviderHealth(effective)
    } catch (e) {
      results[name] = { online: false, reason: sanitizeKey(e.message) }
    }
  }
  return { available: true, providers: results }
}

export async function getAiModels(settings) {
  const models = await listProviderModels(resolveAiSettings(settings))
  return { models }
}
