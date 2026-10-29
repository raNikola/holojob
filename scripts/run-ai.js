/**
 * Dev-only AI feature runner — invoked from Vite middleware.
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildMessages, parseAiResponse } from '../src/modules/ai/aiPromptLibrary.js'
import { getProvider, PROVIDER_NAMES, KEYLESS_PROVIDERS, checkProviderHealth, listProviderModels } from '../src/modules/ai/aiProviderRegistry.js'
import { initSseResponse, sseWrite } from './stream-spawn.js'
import { UNGATED_PROVIDERS, finishAiCall, readAiSelection, recordAiRefusal, reserveAiCall } from './ai-gate.js'
import { assertClean, findLeaks, redactContext } from './ai-redact.js'
import { PROMPT_VERSIONS, appendFinding, buildCacheKey, jobEntityKey, lookupFinding, usesFindings } from './ai-findings-store.js'
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
export const NO_PROVIDER_MESSAGE = 'No AI provider selected (Settings > AI Provider). Nothing was sent.'

/**
 * The one effective settings object of a call: used for the gate, the provider, status and models.
 * For a call, `settings` is the stored selection (data/config/ai-settings.json, the file the Python pipeline reads too);
 * a request never supplies it. A keyed provider takes its key and
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

export async function runAiFeatureStream(res, { feature, context, refresh = false }) {
  initSseResponse(res)
  const selection = (await readAiSelection()).selection
  const providerName = selection?.provider || 'none'
  const model = selection?.model || ''
  const label = FEATURE_LABELS[feature] || feature
  sseWrite(res, { type: 'log', stream: 'stdout', line: `AI: ${label}` })
  sseWrite(res, { type: 'log', stream: 'stdout', line: `Provider: ${providerName}${model ? ` · ${model}` : ''}` })
  if (providerName === 'claude-code') {
    sseWrite(res, { type: 'log', stream: 'stdout', line: 'Claude Code is thinking — usually 30–90 seconds…' })
  } else if (providerName === 'mock') {
    sseWrite(res, { type: 'log', stream: 'stdout', line: 'Using mock provider (instant)' })
  } else if (selection) {
    sseWrite(res, { type: 'log', stream: 'stdout', line: 'Waiting for model response…' })
  }

  return runAiFeature({ feature, context, refresh })
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

/**
 * Would a call with these inputs be a findings hit? Read-only: no model call, no budget reservation, no key needed, no
 * ledger row, nothing written. Resolves { fresh, at, model }; { fresh: false, at: null, model: null } for anything that
 * is not a hit (no selection, a feature or provider without a store, a job without an id, redaction failing, a miss).
 */
export async function checkAiFinding({ feature, context }) {
  const none = { fresh: false, at: null, model: null }
  if (!usesFindings(feature)) return none
  const selection = (await readAiSelection()).selection
  if (!selection || !PROVIDER_NAMES.includes(selection.provider) || UNGATED_PROVIDERS.has(selection.provider)) return none
  const entityKey = jobEntityKey(context?.job?.jobId)
  if (!entityKey) return none
  try {
    const redacted = redactContext(context)
    assertClean(buildMessages(feature, redacted.context), redacted.ids)
    const { cacheKey } = buildCacheKey({ feature, model: selection.model, context: redacted.context })
    const found = lookupFinding({ feature, entityKey, cacheKey })
    return found.hit ? { fresh: true, at: found.finding.at, model: found.finding.model } : none
  } catch {
    return none
  }
}

/** Measured tokens, or nulls when the provider reported none (the gate then estimates). */
function measuredTokens(usage) {
  const input = usage?.inputTokens || usage?.prompt_tokens || 0
  const output = usage?.outputTokens || usage?.completion_tokens || 0
  return input || output ? { inputTokens: input, outputTokens: output } : { inputTokens: null, outputTokens: null }
}

/**
 * One feature call. The provider, model, temperature and token limit are the stored selection; a request cannot name
 * them (a `settings` field in the request is not read). With no usable selection, or one this server cannot run, the
 * call refuses and is logged: no other provider is tried.
 */
export async function runAiFeature({ feature, context, refresh = false }) {
  const chosen = await readAiSelection()
  const selection = chosen.selection
  if (!selection || !PROVIDER_NAMES.includes(selection.provider)) {
    const reason = !selection
      ? (chosen.error ? `${chosen.error}. Nothing was sent.` : NO_PROVIDER_MESSAGE)
      : `${selection.provider} is selected but the browser AI features cannot run it; select another provider in Settings. Nothing was sent.`
    await recordAiRefusal({ provider: selection?.provider || '', model: selection?.model, feature, jobId: context?.job?.jobId, reason: sanitizeKey(reason) })
    return { ok: false, refused: true, error: sanitizeKey(reason) }
  }
  const settings = resolveAiSettings({ ...selection, baseUrl: selection.baseUrl || undefined })
  const providerName = settings.provider
  const provider = getProvider(providerName)
  // Redaction comes first and fails closed: no identifier of the owner or a recruiter may reach the provider.
  let messages
  let redacted
  try {
    redacted = redactContext(context)
    messages = buildMessages(feature, redacted.context)
    assertClean(messages, redacted.ids)
  } catch (e) {
    const reason = `call not made: ${sanitizeKey(e.message)}`
    if (!UNGATED_PROVIDERS.has(providerName)) {
      await recordAiRefusal({ provider: providerName, model: settings?.model, feature, jobId: context?.job?.jobId, baseUrl: settings?.baseUrl, reason })
    }
    return { ok: false, refused: true, error: reason }
  }
  // A stored finding answers before anything is reserved: a hit is not a model call, so the gate is not asked, no ledger
  // row is written and no key is needed. A miss (new input, model or prompt version, stale, or `refresh`) goes on to the gate.
  const stored = usesFindings(feature) && !UNGATED_PROVIDERS.has(providerName) ? jobEntityKey(context?.job?.jobId) : null
  let lookupKey = null
  if (stored) {
    lookupKey = { entityKey: stored, ...buildCacheKey({ feature, model: settings?.model, context: redacted.context }) }
    if (!refresh) {
      const found = lookupFinding({ feature, entityKey: stored, cacheKey: lookupKey.cacheKey })
      if (found.hit) {
        console.info(`AI findings: hit ${feature} ${found.finding.id}, no call made`)
        return { ok: true, data: found.finding.finding, usage: null, diskPath: null, cached: true, findingId: found.finding.id, foundAt: found.finding.at }
      }
    }
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

    const response = { ok: true, data, usage: result.usage, diskPath }
    if (lookupKey) {
      // An identifier echoed by the model keeps the answer off disk; the caller still gets it this once.
      const leaks = findLeaks(JSON.stringify(data), redacted.ids)
      const saved = leaks.length
        ? { stored: false, reason: `identifier in the answer (${leaks.join(', ')})` }
        : appendFinding({
          feature, entityKey: lookupKey.entityKey, provider: providerName, model: settings?.model, promptVersion: PROMPT_VERSIONS[feature],
          inputHash: lookupKey.inputHash, cacheKey: lookupKey.cacheKey, result: data,
        })
      if (saved.stored) response.findingId = saved.finding.id
      else response.warning = `answer not stored: ${saved.reason}`
    }
    return response
  } catch (e) {
    return { ok: false, error: sanitizeKey(e.message) }
  }
}

export async function runAiChat({ context, message }) {
  return runAiFeature({
    feature: 'chat',
    context: { ...context, message },
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
