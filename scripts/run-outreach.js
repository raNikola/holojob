/**
 * Dev-only outreach discovery and generation runner.
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { PRIVATE_DIR_MODE, PRIVATE_FILE_MODE } from './atomic-file.js'
import { discoverContactsForJob } from '../src/modules/outreach/recruiterDiscovery.js'
import { scrapeLinkedInContacts, resolveLiAt } from './linkedin-scraper-bridge.js'
import { maskSecrets } from './secret-mask.js'
import { computeOutreachMetrics, aggregateAllContacts } from '../src/modules/outreach/outreachMetrics.js'
import { runAiFeature } from './run-ai.js'
import { buildAiContext } from '../src/modules/ai/aiContextBuilder.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const OUTREACH_ROOT = path.join(ROOT, 'data/outreach')
const JOBS_PATH = path.join(ROOT, 'data/jobs/scored_jobs.json')

/** Save a job's contacts (names, recruiter links). The modes apply only when the file or folder is created. */
export function writeContactsFile(jobId, data, root = OUTREACH_ROOT) {
  const dir = path.join(root, path.basename(jobId || 'unknown'))
  fs.mkdirSync(dir, { recursive: true, mode: PRIVATE_DIR_MODE })
  const contactsPath = path.join(dir, 'contacts.json')
  fs.writeFileSync(contactsPath, JSON.stringify(data, null, 2), { mode: PRIVATE_FILE_MODE })
  return contactsPath
}

async function fetchPublicPage(url) {
  if (!url) return null
  try {
    const res = await fetch(url, {
      headers: { 'User-Agent': 'JobDashboard-Outreach/1.0 (public page fetch)' },
      signal: AbortSignal.timeout(10000),
    })
    if (!res.ok) return null
    return await res.text()
  } catch {
    return null
  }
}

function loadJobsFromDisk() {
  if (!fs.existsSync(JOBS_PATH)) return []
  try {
    const data = JSON.parse(fs.readFileSync(JOBS_PATH, 'utf-8'))
    return data.jobs || []
  } catch {
    return []
  }
}

export async function runOutreachDiscover({ job, fetchPages = true, deep = false, acceptTosRisk = false }) {
  if (!job) throw new Error('job is required')

  let fetchedHtml = null
  if (fetchPages && job.jobUrl) {
    fetchedHtml = await fetchPublicPage(job.jobUrl)
  }

  const discovery = await discoverContactsForJob(job, { fetchedHtml })

  // Auto-discover LinkedIn contacts. Default = public search snippets (no
  // LinkedIn login). Deep mode = authenticated people-search via li_at cookie.
  const wantDeep = deep && acceptTosRisk && Boolean(resolveLiAt())
  try {
    let scraped = await scrapeLinkedInContacts(job, {
      mode: wantDeep ? 'deep' : 'search',
      acceptTosRisk: wantDeep ? acceptTosRisk : false,
    })
    // If deep mode hit a login wall / rate limit, fall back to safe search mode.
    if (wantDeep && (scraped.error || scraped.status === 'login_wall' || scraped.status === 'rate_limited')) {
      const deepIssue = scraped.error || scraped.status
      scraped = await scrapeLinkedInContacts(job, { mode: 'search' })
      scraped.deepFallback = deepIssue
    }
    const seen = new Set(discovery.contacts.map((c) => (c.linkedinUrl || c.name || '').toLowerCase()))
    for (const contact of scraped.contacts || []) {
      const key = (contact.linkedinUrl || contact.name).toLowerCase()
      if (!seen.has(key)) {
        discovery.contacts.push(contact)
        seen.add(key)
      }
    }
    discovery.metadata.linkedinScrape = {
      mode: scraped.mode,
      queriesRun: scraped.queriesRun,
      contactsFound: (scraped.contacts || []).length,
      ...(scraped.status ? { status: scraped.status } : {}),
      ...(scraped.deepFallback ? { deepFallback: maskSecrets(scraped.deepFallback) } : {}),
      ...(scraped.error ? { error: maskSecrets(scraped.error) } : {}),
    }
  } catch (e) {
    discovery.metadata.linkedinScrape = { error: maskSecrets(e.message) }
  }

  const contactsPath = writeContactsFile(job.jobId, {
    jobId: job.jobId,
    discoveredAt: new Date().toISOString(),
    ...discovery,
  })

  return { ok: true, ...discovery, diskPath: contactsPath }
}

export async function runOutreachGenerate({ job, contact, messageType }) {
  if (!job) throw new Error('job is required')

  const context = buildAiContext({
    featureId: 'outreach',
    job,
    extra: { contact, messageType, outreach: job.outreach },
  })

  const result = await runAiFeature({ feature: 'outreach', context })
  if (!result.ok) return result

  const drafts = result.data || {}
  const body = drafts[messageType] || drafts.inMail || drafts.connectionRequest || ''

  return {
    ok: true,
    data: { body, drafts, messageType },
    meta: result.meta,
  }
}

export function getOutreachContactsFromDisk(jobs) {
  const source = jobs?.length ? jobs : loadJobsFromDisk()
  return aggregateAllContacts(source)
}

export function getOutreachStats(jobs) {
  const source = jobs?.length ? jobs : loadJobsFromDisk()
  return computeOutreachMetrics(source)
}
