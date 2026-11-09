#!/usr/bin/env node
/**
 * Writes the job ids that have an application, one per line, to a file: the list Python needs and may not read for itself
 * (TRACKER_PLAN 6a). Read-only on the store. Only ids are written: no title, company, note or contact.
 *
 *   podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm \
 *     node scripts/export-application-job-ids.js data/backups/application-job-ids.txt
 *
 * Read-only coverage check (counts only, writes nothing): how many applications have no job id, and how many ledger rows they match
 * by posting key (normalised URL, else title|company|location):
 *
 *   podman run --rm --security-opt label=disable -v /srv/holojob:/work -w /work docker.io/library/node:20-bookworm \
 *     node scripts/export-application-job-ids.js --check
 *
 * The export also lists those URL-matched ledger ids, and records `# jobid-less-applications N` and `# ledger-sha256` in its header.
 * The output file is private (mode 600) and lives under data/, which git ignores. Feed it to scripts/older-key-report.py and
 * scripts/prune-older-key.py with --application-job-ids.
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadStore, postingKeyFor, storePaths } from './application-store.js'

const LEDGER_FILE = ['data', 'jobs', 'job_history.json']
const ID_OK = /^[^\s#]{1,200}$/

/** The distinct job ids of the applications in `store`, sorted. Applications entered by hand have none. */
export function applicationJobIds(store) {
  const ids = new Set()
  for (const app of Object.values(store?.applications ?? {})) {
    const id = app?.posting?.jobId
    if (typeof id === 'string' && ID_OK.test(id)) ids.add(id)
  }
  return [...ids].sort()
}

/**
 * Applications without a usable job id (entered by hand, history-only, voided, ad-less) can match a ledger row only by posting key
 * (the store's own `postingKeyFor`: normalised URL, else title|company|location). Counts, and the ledger ids those keys match.
 * `ledger` is the parsed job_history.json (or null). Nothing here carries ad text.
 */
export function urlKeyCoverage(store, ledger) {
  const keys = new Map()
  let total = 0
  let jobIdless = 0
  for (const app of Object.values(store?.applications ?? {})) {
    total += 1
    const posting = app?.posting ?? {}
    if (typeof posting.jobId === 'string' && ID_OK.test(posting.jobId)) continue
    jobIdless += 1
    const key = postingKeyFor({ ...posting, jobId: '' })
    keys.set(key, (keys.get(key) ?? 0) + 1)
  }
  const matchedIds = []
  const matchedKeys = new Set()
  for (const [id, entry] of Object.entries(ledger?.jobs ?? {})) {
    const job = entry?.job ?? {}
    const key = postingKeyFor({ jobId: '', url: job.jobUrl || job.url, company: job.company, title: job.title, location: job.location })
    if (keys.has(key) && ID_OK.test(id)) {
      matchedIds.push(id)
      matchedKeys.add(key)
    }
  }
  const matchedApplications = [...matchedKeys].reduce((sum, key) => sum + keys.get(key), 0)
  return { applications: total, jobIdless, matchedApplications, matchedLedgerRows: matchedIds.length, matchedIds: matchedIds.sort() }
}

function readLedger(root) {
  const file = path.join(root, ...LEDGER_FILE)
  if (!fs.existsSync(file)) return { ledger: null, sha: 'none' }
  const bytes = fs.readFileSync(file)
  return { ledger: JSON.parse(bytes.toString('utf-8')), sha: crypto.createHash('sha256').update(bytes).digest('hex') }
}

/** The read-only check: counts only, no file written, no id printed. */
export function applicationIdCoverage(root) {
  const { applications, jobIdless, matchedApplications, matchedLedgerRows } = urlKeyCoverage(loadStore(root), readLedger(root).ledger)
  return { applications, jobIdless, matchedApplications, matchedLedgerRows }
}

/** Hash of the store file's bytes, `none` when there is no file: the header Python compares with the live file before any prune. */
export function storeSha256(root) {
  const file = storePaths(root).store
  return fs.existsSync(file) ? crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex') : 'none'
}

export function exportApplicationJobIds(root, outFile) {
  const sha = storeSha256(root)
  const store = loadStore(root)
  const { ledger, sha: ledgerSha } = readLedger(root)
  const coverage = urlKeyCoverage(store, ledger)
  // Ledger rows that match a job-id-less application only by posting key are protected by their own ledger id.
  const ids = [...new Set([...applicationJobIds(store), ...coverage.matchedIds])].sort()
  if (storeSha256(root) !== sha) throw new Error('applications.json changed during the export; run it again')
  if (readLedger(root).sha !== ledgerSha) throw new Error('job_history.json changed during the export; run it again')
  fs.mkdirSync(path.dirname(outFile), { recursive: true, mode: 0o700 })
  fs.writeFileSync(outFile, `# store-sha256 ${sha}\n# jobid-less-applications ${coverage.jobIdless}\n# ledger-sha256 ${ledgerSha}\n${ids.length ? `${ids.join('\n')}\n` : ''}`, { mode: 0o600 })
  fs.chmodSync(outFile, 0o600)
  return ids.length
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const out = process.argv[2]
  if (out === '--check') {
    console.log(JSON.stringify(applicationIdCoverage(root), null, 2))
    process.exit(0)
  }
  if (!out) {
    console.error('usage: node scripts/export-application-job-ids.js OUT_FILE | --check')
    process.exit(2)
  }
  console.log(`wrote ${exportApplicationJobIds(root, path.resolve(out))} job ids to ${out}`)
}
