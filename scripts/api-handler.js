/**
 * Shared /api route handler for Vite dev middleware and production local-server.
 */

import fs from 'node:fs'
import path from 'node:path'
import { pipeline } from 'node:stream/promises'
import { fileURLToPath } from 'node:url'
import { buildDiscoveryCommand, getDiscoveryStatus, runDiscovery } from './run-discovery.js'
import { runPipeline } from './run-pipeline.js'
import { runManualJobs } from './run-manual-job.js'
import { pruneKeptRescored, runKeptRescore } from './run-kept-rescore.js'
import { extractAdAi, fetchAd, previewAdAi } from './run-ad-fill.js'
import { buildScoringCommand, getScoringStatus, previewJudge, runJudgedScoring, runScoring } from './run-scoring.js'
import { buildTailorCommand, getTailorStatus, runTailor, runTailorStream } from './run-tailor.js'
import { getProjectScanStatus, runProjectScan } from './run-project-scan.js'
import { runJobImport } from './run-job-import.js'
import { checkClaudeAuth, ensureClaudeLogin } from './claude-auth.js'
import { saveProfileToDisk, PROFILE_PATH } from './save-profile.js'
import { runProfileReset, RESET_CONFIRM_WORD, RESET_ERRORS } from './profile-reset.js'
import { saveIntelligenceToDisk, INTELLIGENCE_PATH } from './save-intelligence.js'
import { checkAiFinding, runAiFeature, runAiFeatureStream, runAiChat, getAiStatus, getAiModels } from './run-ai.js'
import { readAiUsage } from './ai-gate.js'
import {
  runOutreachDiscover,
  runOutreachGenerate,
  getOutreachContactsFromDisk,
  getOutreachStats,
} from './run-outreach.js'
import {
  getQualityStatus,
  loadQualityReport,
  runQualityAudit,
} from './run-quality-audit.js'
import { IMPORT_ERRORS, MAX_IMPORT_BODY_BYTES, parseImportSource } from './run-profile-import.js'
import { handleAiSettingsRequest } from './ai-settings-handler.js'
import { handleSecretsRequest } from './secrets-handler.js'
import { handleSourcesRequest } from './sources-handler.js'
import { guardApiRequest } from './request-guard.js'
import { MAX_LARGE_BODY_BYTES, readJsonBody, readRawBody } from './read-body.js'
import { maskErrorField } from './secret-mask.js'
import { previewCvAnalysis, runCvAnalysis } from './run-cv-analyze.js'
import { MAX_CV_BYTES, cvFilePath, deleteCvFile, isCvId, saveCvFile } from './cv-store.js'
import { handleApplicationsRequest } from './application-store.js'
import { handleJobHistoryRequest, handleJobTextsRequest } from './job-history-read.js'
import { handleJobsAllRequest } from './job-all-read.js'
import { ViewUnrecoverable, ensureViewCurrent, viewUnrecoverableAnswer } from './view-guard.js'
import { getRun, listRuns } from './run-history.js'
import { RUN_ACTIVE, cancelRescrape, incompleteCommit, isRunBusy, rescrapeStatus, runHttpStatus, startRescrape, withRunLock } from './run-rescrape.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const JOBS_PATH = path.join(ROOT, 'data/jobs/discovered_jobs.json')
const SCORED_PATH = path.join(ROOT, 'data/jobs/scored_jobs.json')
const RESUMES_ROOT = path.join(ROOT, 'data/resumes')

const AI_ROUTES = {
  '/api/ai/job-analysis': 'jobAnalysis',
  '/api/ai/resume-enhance': 'resumeEnhancement',
  '/api/ai/cover-letter': 'coverLetter',
  '/api/ai/interview-prep': 'interviewPrep',
  '/api/ai/outreach': 'outreach',
  '/api/ai/company-intelligence': 'companyIntelligence',
  '/api/ai/career-strategy': 'careerStrategy',
  '/api/ai/skill-gap': 'skillGap',
  '/api/ai/application-strategy': 'applicationStrategy',
}

function fileMtime(filePath) {
  try {
    return fs.statSync(filePath).mtimeMs
  } catch {
    return null
  }
}

export function getAppConfig() {
  const demoFlag = (process.env.DEMO_MODE ?? '').toLowerCase()
  return {
    demoMode: demoFlag === '1' || demoFlag === 'true',
    version: '1.0.0',
  }
}

function readJsonFile(...paths) {
  for (const filePath of paths) {
    try {
      if (fs.existsSync(filePath)) {
        return JSON.parse(fs.readFileSync(filePath, 'utf-8'))
      }
    } catch {
      // try next path
    }
  }
  return null
}

export function getDemoBootstrap() {
  const { demoMode } = getAppConfig()
  const exampleProfile = path.join(ROOT, 'data/examples/candidate-profile.example.json')
  const exampleIntelligence = path.join(ROOT, 'data/examples/candidate-intelligence.example.json')
  const exampleJobs = path.join(ROOT, 'data/examples/scored_jobs.example.json')

  if (demoMode) {
    const profile = readJsonFile(exampleProfile)
    const intelligence = readJsonFile(exampleIntelligence)
    const jobs = readJsonFile(exampleJobs)
    if (!profile || !intelligence || !jobs) return null
    return { profile, intelligence, jobs }
  }

  // Outside demo mode these are the user's own files and nothing else: a missing
  // one is an empty state, never filled in from the bundled example.
  const profile = readJsonFile(PROFILE_PATH)
  const intelligence = readJsonFile(INTELLIGENCE_PATH)
  const jobs = readJsonFile(SCORED_PATH)
  if (!profile || !intelligence || !jobs) {
    return null
  }
  return { profile, intelligence, jobs }
}

export function getPipelineHealth() {
  const discovery = getDiscoveryStatus()
  const scoring = getScoringStatus()
  const tailor = getTailorStatus()
  let scoredMeta = null
  if (fs.existsSync(SCORED_PATH)) {
    try {
      scoredMeta = JSON.parse(fs.readFileSync(SCORED_PATH, 'utf-8')).meta
    } catch {
      // ignore
    }
  }
  let discoveredMeta = null
  if (fs.existsSync(JOBS_PATH)) {
    try {
      discoveredMeta = JSON.parse(fs.readFileSync(JOBS_PATH, 'utf-8')).meta
    } catch {
      // ignore
    }
  }
  return {
    available: true,
    profile: { exists: fs.existsSync(PROFILE_PATH), path: PROFILE_PATH },
    intelligence: { exists: fs.existsSync(INTELLIGENCE_PATH), path: INTELLIGENCE_PATH },
    discovery: {
      ...discovery,
      generatedAt: discoveredMeta?.generatedAt ?? discovery.lastRunAt,
      mtime: fileMtime(JOBS_PATH),
    },
    scoring: {
      ...scoring,
      generatedAt: scoredMeta?.generatedAt ?? scoring.lastRunAt,
      mtime: fileMtime(SCORED_PATH),
    },
    tailoring: tailor,
  }
}

function sendJson(res, status, data) {
  if (res.writableEnded) return // read-body.js has already answered 413
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(maskErrorField(data)))
}

function commitIncompleteAnswer(commit) {
  const files = commit.unreadable ? '' : ` Written: ${commit.written.join(', ') || 'none'}. Not written: ${commit.pending.join(', ') || 'none'}.`
  return {
    ok: false,
    error: 'commit_incomplete',
    message: `No backup was made: a save of the job files did not finish, so they may not match each other.${files} Run a Re-scrape to the end, then back up.`,
  }
}

function contentTypeFor(filePath) {
  if (filePath.endsWith('.pdf')) return 'application/pdf'
  if (filePath.endsWith('.html')) return 'text/html; charset=utf-8'
  if (filePath.endsWith('.md')) return 'text/markdown; charset=utf-8'
  return 'application/octet-stream'
}

function serveResumeFile(res, jobId, filename) {
  const safeJobId = path.basename(jobId)
  const safeName = path.basename(filename)
  const filePath = path.join(RESUMES_ROOT, safeJobId, safeName)
  if (!filePath.startsWith(RESUMES_ROOT) || !fs.existsSync(filePath)) {
    sendJson(res, 404, { error: 'File not found' })
    return
  }
  res.statusCode = 200
  res.setHeader('Content-Type', contentTypeFor(filePath))
  res.setHeader('Content-Disposition', `attachment; filename="${safeName}"`)
  fs.createReadStream(filePath).pipe(res)
}

/**
 * Every /api request enters here: the request checks, then the AI budget routes, then the rest.
 * The production server and the Vite dev middleware both call this and nothing else.
 */
export async function handleApiRoutes(req, res) {
  if (guardApiRequest(req, res)) return true
  return (await handleAiSettingsRequest(req, res)) || (await handleSecretsRequest(req, res)) || (await handleSourcesRequest(req, res)) || (await handleApiRequest(req, res))
}

/**
 * Handle an /api/* request. Returns true if handled, false if not an API route.
 */
export async function handleApiRequest(req, res) {
  const url = req.url?.split('?')[0] ?? ''

  if (!url.startsWith('/api/')) {
    return false
  }

  if (url === '/api/config' && req.method === 'GET') {
    sendJson(res, 200, getAppConfig())
    return true
  }

  if (url === '/api/demo/bootstrap' && req.method === 'GET') {
    const bundle = getDemoBootstrap()
    if (!bundle) {
      sendJson(res, 404, { error: 'Demo bootstrap data not available' })
      return true
    }
    sendJson(res, 200, bundle)
    return true
  }

  if (url === '/api/discovery/status' && req.method === 'GET') {
    try {
      await ensureViewCurrent()
    } catch (e) {
      if (e instanceof ViewUnrecoverable) {
        sendJson(res, 503, viewUnrecoverableAnswer(e))
        return true
      }
      throw e
    }
    sendJson(res, 200, {
      available: true,
      ...getDiscoveryStatus(),
      command: buildDiscoveryCommand({ providers: 'serbia' }),
    })
    return true
  }

  if (url === '/api/discovery/jobs' && req.method === 'GET') {
    try {
      await ensureViewCurrent() // the job list is a view of the ledger: never serve one that is behind it
      if (!fs.existsSync(JOBS_PATH)) {
        sendJson(res, 404, { error: 'No discovered_jobs.json yet' })
        return true
      }
      const payload = JSON.parse(fs.readFileSync(JOBS_PATH, 'utf-8'))
      sendJson(res, 200, payload)
    } catch (e) {
      if (e instanceof ViewUnrecoverable) sendJson(res, 503, viewUnrecoverableAnswer(e))
      else sendJson(res, 500, { error: e.message })
    }
    return true
  }

  // Re-scrape as one background run (python/run_rescrape.py): the browser starts it and reads its status.
  if (url === '/api/rescrape' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const { status, body: answer } = await startRescrape(body)
      sendJson(res, status, answer)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  // Run history (S7a): read-only, slim, bounded. No lock, no process, no recovery, no ledger or staging.
  if (url === '/api/runs' && req.method === 'GET') {
    try {
      const { status, body: answer } = listRuns(new URL(req.url, 'http://localhost').searchParams)
      sendJson(res, status, answer)
    } catch {
      sendJson(res, 500, { error: 'The run history could not be read.' })
    }
    return true
  }

  // One run, live (S7c): the record and its events from a cursor. Node only: no lock, no process, no recovery, no write.
  const oneRun = /^\/api\/runs\/([^/]+)$/.exec(url)
  if (oneRun && req.method === 'GET') {
    try {
      const { status, body: answer } = getRun(oneRun[1], new URL(req.url, 'http://localhost').searchParams)
      sendJson(res, status, answer)
    } catch {
      sendJson(res, 500, { error: 'The run could not be read.' })
    }
    return true
  }

  // Cancel a running Re-scrape: writes a request file, never signals (S6). Idempotent; an unknown, finished or cancelled run changes nothing.
  if (url === '/api/rescrape/cancel' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const { status, body: answer } = await cancelRescrape(body)
      sendJson(res, status, answer)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/rescrape/status' && req.method === 'GET') {
    try {
      const after = new URL(req.url, 'http://localhost').searchParams.get('after')
      const { status, body: answer } = await rescrapeStatus(after)
      sendJson(res, status, answer)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/discovery/run' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      // Before the mirrors: a refused request must not change an active run's input.
      if (await isRunBusy()) {
        sendJson(res, 409, RUN_ACTIVE)
        return true
      }
      const result = await runDiscovery({
        providers: body.providers || 'serbia',
        country: body.country,
        locations: body.locations,
        intelligence: body.intelligence,
        profile: body.profile,
      })
      sendJson(res, runHttpStatus(result), result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  // Discovery, enrichment and scoring as one fail-fast run (python/run_pipeline.py).
  // Never judges; the judged run keeps its own confirmed route.
  if (url === '/api/pipeline/run' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      if (await isRunBusy()) {
        sendJson(res, 409, RUN_ACTIVE)
        return true
      }
      const result = await runPipeline({
        providers: body.providers || 'serbia',
        country: body.country,
        intelligence: body.intelligence,
        profile: body.profile,
      })
      sendJson(res, runHttpStatus(result), result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/scoring/status' && req.method === 'GET') {
    sendJson(res, 200, {
      available: true,
      ...getScoringStatus(),
      command: buildScoringCommand(),
    })
    return true
  }

  if (url === '/api/scoring/jobs' && req.method === 'GET') {
    try {
      if (getAppConfig().demoMode) {
        const bundle = getDemoBootstrap()
        if (bundle?.jobs) {
          sendJson(res, 200, bundle.jobs)
          return true
        }
      }
      if (!fs.existsSync(SCORED_PATH)) {
        sendJson(res, 404, { error: 'No scored_jobs.json yet' })
        return true
      }
      const payload = JSON.parse(fs.readFileSync(SCORED_PATH, 'utf-8'))
      sendJson(res, 200, payload)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  // Local scoring only. A judge field in the body is ignored on purpose: the
  // judged run has its own route below.
  if (url === '/api/scoring/run' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const result = await runScoring({ minScore: body.minScore })
      sendJson(res, runHttpStatus(result), result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/scoring/judge/preview' && req.method === 'GET') {
    const result = await previewJudge()
    sendJson(res, result.ok ? 200 : 500, result)
    return true
  }

  // Sends a candidate digest to the configured LLM provider. Requires an
  // explicit confirmation in the body, which only the confirm dialog sends.
  if (url === '/api/scoring/judge' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      if (body.confirm !== true) {
        sendJson(res, 400, { error: 'A judged run needs { "confirm": true }.' })
        return true
      }
      const result = await runJudgedScoring()
      sendJson(res, runHttpStatus(result), result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/tailor/status' && req.method === 'GET') {
    sendJson(res, 200, {
      available: true,
      ...getTailorStatus(),
      command: buildTailorCommand({ limit: 5 }),
    })
    return true
  }

  if (url === '/api/tailor/stream' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      await runTailorStream(res, {
        jobId: body.jobId,
        jobIds: body.jobIds,
        priority: body.priority,
        applyRecommendation: body.applyOnly ? 'Apply' : body.applyRecommendation,
        applyOnly: Boolean(body.applyOnly),
        limit: body.limit,
        profile: body.profile,
      })
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/tailor/run' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const result = await runTailor({
        jobId: body.jobId,
        jobIds: body.jobIds,
        priority: body.priority,
        applyRecommendation: body.applyOnly ? 'Apply' : body.applyRecommendation,
        applyOnly: Boolean(body.applyOnly),
        limit: body.limit,
        profile: body.profile,
      })
      sendJson(res, result.ok ? 200 : 500, result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  // Fill from ad (Add job): the server reads one job page. No model, no candidate data; the body is the address only.
  if (url === '/api/jobs/ad/fetch' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const result = await fetchAd(body.url)
      sendJson(res, result.status, result.body)
    } catch {
      sendJson(res, 400, { ok: false, error: 'bad_url', message: 'Could not read this page, paste the text manually.' })
    }
    return true
  }

  // Fill from ad, step 2 (AI): `preview` returns exactly what would be sent and calls no model; `extract` is the only path that
  // sends the (redacted) page text to Claude Code and needs `"confirm": true`. Both take a token and field names, nothing else.
  if ((url === '/api/jobs/ad/ai-preview' || url === '/api/jobs/ad/ai-extract') && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const result = url.endsWith('/ai-preview') ? await previewAdAi(body) : await extractAdAi(body)
      sendJson(res, result.status, result.body)
    } catch {
      sendJson(res, 400, { ok: false, error: 'invalid', message: 'The request was not understood.' })
    }
    return true
  }

  // Hand-entered jobs (Add job): `score` stores and scores one, `check` only looks for a clash (a job without text), `sync` only stores the browser's manual jobs so the
  // next scoring run has them. Local scoring; no model, no network.
  if ((url === '/api/jobs/manual/score' || url === '/api/jobs/manual/check' || url === '/api/jobs/manual/sync') && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res, url.endsWith('/sync') ? { limit: MAX_LARGE_BODY_BYTES } : undefined)
      const single = !url.endsWith('/sync')
      const mode = url.endsWith('/score') ? 'score' : url.endsWith('/check') ? 'check' : 'store'
      const result = await runManualJobs(single ? (body.job ? [body.job] : []) : body.jobs, { mode })
      sendJson(res, result.status, result.body)
    } catch {
      sendJson(res, 400, { ok: false, error: 'invalid', field: 'json' })
    }
    return true
  }

  // Kept ads: `rescore` scores one by hand (local, no model); `sync` sends the ids the browser keeps so the set of re-scored ids forgets the rest.
  if ((url === '/api/jobs/kept/rescore' || url === '/api/jobs/kept/sync') && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res, url.endsWith('/sync') ? { limit: MAX_LARGE_BODY_BYTES } : undefined)
      const result = url.endsWith('/sync') ? await pruneKeptRescored(body.keptIds) : await runKeptRescore(body.jobId)
      sendJson(res, result.status, result.body)
    } catch {
      sendJson(res, 400, { ok: false, error: 'invalid', field: 'json' })
    }
    return true
  }

  if (url === '/api/jobs/import-url' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      if (await isRunBusy()) {
        sendJson(res, 409, RUN_ACTIVE)
        return true
      }
      const result = await runJobImport({
        urls: body.urls || (body.url ? [body.url] : []),
        tailor: Boolean(body.tailor),
        profile: body.profile,
      })
      sendJson(res, result.ok ? 200 : 500, result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/projects/scan' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const result = await runProjectScan({ noLlm: body.noLlm, repos: body.repos })
      sendJson(res, result.ok ? 200 : 500, result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/projects/status' && req.method === 'GET') {
    sendJson(res, 200, getProjectScanStatus())
    return true
  }

  if (url === '/api/projects/intelligence' && req.method === 'GET') {
    const intelPath = path.join(ROOT, 'data/intelligence/project-intelligence.json')
    if (!fs.existsSync(intelPath)) {
      sendJson(res, 200, null)
      return true
    }
    try {
      sendJson(res, 200, JSON.parse(fs.readFileSync(intelPath, 'utf-8')))
    } catch {
      sendJson(res, 200, null)
    }
    return true
  }

  if (url === '/api/intelligence/candidate' && req.method === 'GET') {
    if (getAppConfig().demoMode) {
      const bundle = getDemoBootstrap()
      sendJson(res, 200, bundle?.intelligence ?? null)
      return true
    }
    const intelPath = path.join(ROOT, 'data/intelligence/candidate-intelligence.json')
    if (!fs.existsSync(intelPath)) {
      sendJson(res, 200, null)
      return true
    }
    try {
      sendJson(res, 200, JSON.parse(fs.readFileSync(intelPath, 'utf-8')))
    } catch {
      sendJson(res, 200, null)
    }
    return true
  }

  if (url === '/api/claude/status' && req.method === 'GET') {
    sendJson(res, 200, checkClaudeAuth())
    return true
  }

  if (url === '/api/claude/login' && req.method === 'POST') {
    const status = await ensureClaudeLogin()
    sendJson(res, 200, status)
    return true
  }

  // CV analysis. The preview returns the redacted text a run would send and calls
  // nothing; the run sends it to the LLM provider and, like the judge, needs an
  // explicit confirmation in the body, which only the confirm dialog sends.
  if (url === '/api/ai/cv-analyze/preview' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const result = await previewCvAnalysis(body)
      sendJson(res, result.ok ? 200 : 400, result)
    } catch (e) {
      sendJson(res, 400, { error: e.message })
    }
    return true
  }

  if (url === '/api/ai/cv-analyze' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      if (body.confirm !== true) {
        sendJson(res, 400, { error: 'A CV analysis needs { "confirm": true }.' })
        return true
      }
      const result = await runCvAnalysis(body, { force: body.force === true })
      sendJson(res, result.ok ? 200 : 502, result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  // Application tracker: the store module owns every route under /api/applications.
  if (await handleApplicationsRequest(req, res, url, { root: ROOT })) {
    return true
  }

  if (await handleJobHistoryRequest(req, res, url, { root: ROOT })) {
    return true
  }

  if (await handleJobTextsRequest(req, res, url, { root: ROOT, readBody: readJsonBody })) {
    return true
  }

  if (await handleJobsAllRequest(req, res, url, { root: ROOT })) {
    return true
  }

  // Uploaded CVs (data/profile/cvs). The client names a CV only by its id.
  if (url === '/api/cvs' && req.method === 'POST') {
    try {
      const saved = saveCvFile(await readRawBody(req, res, { limit: MAX_CV_BYTES, tooLarge: { error: 'File is too large. Maximum size is 10 MB.' } }))
      sendJson(res, 200, { ok: true, id: saved.id, size: saved.size })
    } catch (e) {
      sendJson(res, 400, { error: e.message })
    }
    return true
  }

  const cvMatch = /^\/api\/cvs\/([^/]+)(\/file)?$/.exec(url)
  if (cvMatch) {
    const [, id, isFile] = cvMatch
    if (!isCvId(id)) {
      sendJson(res, 400, { error: 'Invalid CV id' })
      return true
    }
    if (req.method === 'GET' && isFile) {
      const file = cvFilePath(id)
      if (!fs.existsSync(file)) {
        sendJson(res, 404, { error: 'File not found' })
        return true
      }
      const name = new URL(req.url, 'http://localhost').searchParams.get('name') || 'cv.pdf'
      const safeName = name.replace(/[^\w .()[\]-]/g, '_').slice(0, 120) || 'cv.pdf'
      res.statusCode = 200
      res.setHeader('Content-Type', 'application/pdf')
      res.setHeader('Content-Disposition', `attachment; filename="${safeName}"`)
      fs.createReadStream(file).pipe(res)
      return true
    }
    if (req.method === 'DELETE' && !isFile) {
      sendJson(res, 200, { ok: true, deleted: deleteCvFile(id) })
      return true
    }
  }

  if (url.startsWith('/api/resumes/') && req.method === 'GET') {
    const parts = url.replace('/api/resumes/', '').split('/')
    if (parts.length === 2) {
      serveResumeFile(res, parts[0], parts[1])
      return true
    }
  }

  // Stateless: parses pasted text into an import draft and writes nothing. Every answer is fixed text; the text is never echoed.
  if (url === '/api/profile/import/parse' && req.method === 'POST') {
    const fail = (code) => {
      const { status, error } = IMPORT_ERRORS[code] ?? IMPORT_ERRORS.parse_failed
      sendJson(res, status, { ok: false, code, error })
    }
    let body
    try {
      const raw = await readRawBody(req, res, {
        limit: MAX_IMPORT_BODY_BYTES,
        tooLarge: { ok: false, code: 'too_large', error: IMPORT_ERRORS.too_large.error },
      })
      body = JSON.parse(raw.toString('utf-8') || '{}')
    } catch {
      fail('invalid_request')
      return true
    }
    const result = await parseImportSource(body?.source, body?.text)
    if (result.ok) sendJson(res, 200, { ok: true, draft: result.draft })
    else fail(result.code)
    return true
  }

  if (url === '/api/profile/save' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const result = saveProfileToDisk(body.profile)
      sendJson(res, 200, { ok: true, ...result })
    } catch (e) {
      sendJson(res, 400, { error: e.message })
    }
    return true
  }

  // Moves the profile mirror, the stored CVs and the candidate intelligence into data/profile.bak-<time>.
  // Fixed answers only; nothing from the body or the disk is echoed.
  if (url === '/api/profile/reset' && req.method === 'POST') {
    const fail = (code) => {
      const { status, error } = RESET_ERRORS[code]
      sendJson(res, status, { ok: false, code, error })
    }
    let body
    try {
      body = await readJsonBody(req, res)
    } catch {
      body = null
    }
    if (body?.confirm !== RESET_CONFIRM_WORD) {
      fail('not_confirmed')
      return true
    }
    const result = runProfileReset()
    if (!result.ok) fail(result.code)
    else sendJson(res, 200, { ok: true, backup: result.backup ? `data/${result.backup}` : null })
    return true
  }

  if (url === '/api/intelligence/save' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const result = saveIntelligenceToDisk(body.intelligence)
      sendJson(res, 200, { ok: true, ...result })
    } catch (e) {
      sendJson(res, 400, { error: e.message })
    }
    return true
  }

  if (url === '/api/backup/export' && req.method === 'POST') {
    try {
      const { createBackupStream } = await import('./backup-handler.js')
      const body = await readJsonBody(req, res, { limit: MAX_LARGE_BODY_BYTES })
      // The lock is held until the last byte, so every file in the archive comes from one state: no run writes during it.
      let held
      try {
        held = await withRunLock(async () => {
          const unfinished = incompleteCommit()
          if (unfinished) return { refused: commitIncompleteAnswer(unfinished) }
          // The job files must agree in the archive. The pipeline lock is held, so no commit can happen during the export;
          // the rebuild takes only the view lock, so it can run under it.
          try {
            await ensureViewCurrent()
          } catch (e) {
            if (e instanceof ViewUnrecoverable) return { refused: viewUnrecoverableAnswer(e), status: 503 }
            throw e
          }
          res.statusCode = 200
          res.setHeader('Content-Type', 'application/zip')
          res.setHeader('Content-Disposition', 'attachment; filename="holojob-backup.zip"')
          await pipeline(createBackupStream(ROOT, {
            profile: body.profile,
            intelligence: body.intelligence,
            jobs: body.jobs,
          }), res)
          return {}
        })
      } catch (e) {
        if (res.headersSent) {
          res.destroy() // the download broke off: there is no status left to send
          return true
        }
        if (e.lockUnknown) {
          sendJson(res, 503, { ok: false, error: 'lock_unknown', message: 'Could not check for a running job run, so no backup was made.' })
          return true
        }
        throw e
      }
      if (held.busy) sendJson(res, 409, RUN_ACTIVE)
      else if (held.value.refused) sendJson(res, held.value.status ?? 409, held.value.refused)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/backup/import' && req.method === 'POST') {
    try {
      const { importBackupZip } = await import('./backup-handler.js')
      const zipBuffer = await readRawBody(req, res, { limit: MAX_LARGE_BODY_BYTES })
      if (!zipBuffer.length) {
        sendJson(res, 400, { error: 'Empty backup file' })
        return true
      }
      // A restore overwrites the job files, so it holds the run lock: no run under it, and none starts during it.
      let held
      try {
        held = await withRunLock(() => importBackupZip(ROOT, zipBuffer))
      } catch (e) {
        if (e.lockUnknown) {
          sendJson(res, 503, { ok: false, error: 'lock_unknown', message: 'Could not check for a running job run, so nothing was restored.' })
          return true
        }
        throw e
      }
      if (held.busy) {
        sendJson(res, 409, RUN_ACTIVE)
        return true
      }
      sendJson(res, 200, held.value)
    } catch (e) {
      sendJson(res, 400, { error: e.message })
    }
    return true
  }

  if (url === '/api/pipeline/health' && req.method === 'GET') {
    sendJson(res, 200, getPipelineHealth())
    return true
  }

  // AI budget gate: effective settings and today's / this month's usage (python/llm/ai_gate.py).
  if (url === '/api/ai/usage' && req.method === 'GET') {
    try {
      sendJson(res, 200, await readAiUsage())
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/ai/status' && req.method === 'GET') {
    try {
      const status = await getAiStatus()
      sendJson(res, 200, { available: true, ...status })
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/ai/models' && (req.method === 'GET' || req.method === 'POST')) {
    try {
      const body = req.method === 'POST' ? await readJsonBody(req, res) : {}
      const result = await getAiModels(body.settings || {})
      sendJson(res, 200, result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  // Read-only: is there a stored finding for these inputs? Makes no call and reserves no budget.
  if (url === '/api/ai/findings/check' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      sendJson(res, 200, await checkAiFinding({ feature: body.feature, context: body.context }))
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/ai/chat' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const result = await runAiChat({
        context: body.context,
        message: body.message || body.context?.message,
      })
      sendJson(res, result.ok ? 200 : 500, result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (AI_ROUTES[url] && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const feature = body.feature || AI_ROUTES[url]
      if (body.stream) {
        await runAiFeatureStream(res, {
          feature,
          context: body.context,
          refresh: body.refresh === true,
        })
        return true
      }
      const result = await runAiFeature({
        feature,
        context: body.context,
        refresh: body.refresh === true,
      })
      sendJson(res, result.ok ? 200 : 500, result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/outreach/discover' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      if (body.deep === true && body.acceptTosRisk !== true) {
        sendJson(res, 400, {
          error: 'Deep LinkedIn mode requires acceptTosRisk: true. See README — LinkedIn deep mode risks.',
        })
        return true
      }
      const result = await runOutreachDiscover({
        job: body.job,
        fetchPages: body.fetchPages !== false,
        deep: body.deep === true,
        // The cookie is never read from the request: runOutreachDiscover takes it from the secret store.
        acceptTosRisk: body.acceptTosRisk === true,
      })
      sendJson(res, result.ok ? 200 : 500, result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/outreach/generate' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const result = await runOutreachGenerate({
        job: body.job,
        contact: body.contact,
        messageType: body.messageType,
      })
      sendJson(res, result.ok ? 200 : 500, result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/outreach/contacts' && req.method === 'GET') {
    try {
      const contacts = getOutreachContactsFromDisk()
      sendJson(res, 200, { contacts })
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/outreach/stats' && req.method === 'GET') {
    try {
      const stats = getOutreachStats()
      sendJson(res, 200, stats)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/quality/status' && req.method === 'GET') {
    try {
      sendJson(res, 200, getQualityStatus())
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/quality/report' && req.method === 'GET') {
    try {
      const result = loadQualityReport()
      sendJson(res, result.ok ? 200 : 404, result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url === '/api/quality/run' && req.method === 'POST') {
    try {
      const body = await readJsonBody(req, res)
      const result = await runQualityAudit({
        sampleMe: Boolean(body.sampleMe),
        limit: body.limit || 0,
      })
      sendJson(res, result.ok ? 200 : 500, result)
    } catch (e) {
      sendJson(res, 500, { error: e.message })
    }
    return true
  }

  if (url.startsWith('/api/interviews/') && req.method === 'GET') {
    const parts = url.replace('/api/interviews/', '').split('/')
    if (parts.length === 2 && parts[1] === 'interview_prep.json') {
      const filePath = path.join(ROOT, 'data/interviews', path.basename(parts[0]), 'interview_prep.json')
      if (fs.existsSync(filePath)) {
        sendJson(res, 200, JSON.parse(fs.readFileSync(filePath, 'utf-8')))
        return true
      }
      sendJson(res, 404, { error: 'Not found' })
      return true
    }
  }

  sendJson(res, 404, { error: 'API route not found' })
  return true
}
