// Which record Job Details shows for a job id, in this order: the stored browser row, the scored or discovered file,
// the ledger (`GET /api/jobs/history/<jobId>`), the frozen posting of the job's application.
//
// A fallback is display only. It is never written to the browser's job list: a saved row would count as an active
// job in stats, exports and AI contexts, and Step 5 would migrate it as one. Applications need no row at all.
import { applicationsForJob, jobFromPosting, latestActiveApplication } from '../applications/trackingView.js'

const blank = (text) => !String(text ?? '').trim()

const jobFromLedger = (ledger) => ({
  ...ledger.job,
  jobId: ledger.jobId,
  firstSeen: ledger.firstSeen,
  lastSeen: ledger.lastSeen,
  closedAt: ledger.closedAt,
  isClosed: Boolean(ledger.closedAt),
  ...(ledger.closedAt
    ? (ledger.absentRuns >= 2 ? { closedAfterChecks: ledger.absentRuns } : {})
    : (ledger.absentSince ? { isAbsent: true, absentSince: ledger.absentSince } : {})),
})

/** The base record and which source gave it. */
function pickSource({ stored, fileFields, fileJob, ledger, application }) {
  if (stored) return { source: 'stored', job: { ...fileFields, ...stored } }
  if (fileJob) return { source: 'file', job: fileJob }
  if (ledger) return { source: 'ledger', job: jobFromLedger(ledger) }
  if (application?.posting) return { source: 'application', job: jobFromPosting(application.posting) }
  return null
}

/**
 * Pure. `applications` are the job's attempts, oldest first. `fileChecked` says the file was read, `inFile` that it holds
 * the job. `notInLatest` needs an answer: with no file read, only a row's own `offList` mark can say so.
 */
export function resolveJob({ stored = null, fileFields = null, fileJob = null, ledger = null, applications = [], fileChecked = false, inFile = false }) {
  const active = latestActiveApplication(applications)
  const application = active ?? applications[applications.length - 1] ?? null
  const picked = pickSource({ stored, fileFields, fileJob, ledger, application })
  if (!picked) return { status: 'missing', job: null, source: null, readOnly: true, notInLatest: false, lastSeen: null, capturedAt: null }

  const { source } = picked
  const job = { ...picked.job }
  // A row saved without its ad text (`slimJob`) gets it back here. A hand-entered job with no text stays that way: the form asks for it.
  if (!job.manualEntry && blank(job.description)) {
    const text = [ledger?.job?.description, application?.posting?.description].find((value) => !blank(value))
    if (text) job.description = text
  }
  if ((source === 'ledger' || source === 'application') && active) job.status = 'applied_manually'

  return {
    status: 'found',
    job,
    source,
    // Only a stored row has anywhere to write job fields; a tracker edit goes to the application store and needs none.
    readOnly: source !== 'stored',
    notInLatest: !job.manualEntry && (stored?.offList === true || (fileChecked && !inFile)),
    lastSeen: ledger?.lastSeen ?? job.lastSeen ?? null,
    capturedAt: application?.posting?.capturedAt ?? null,
  }
}

/** True when Job Details has something to show for a job with no stored row. */
export function hasFallback(jobId, store, ledger) {
  return applicationsForJob(store, jobId).length > 0 || Boolean(ledger?.found)
}

/**
 * Reads what `resolveJob` needs and stores nothing. `addable` is the only row a caller may add to the browser's list:
 * one the imported file really holds, as the page has always done.
 */
export async function loadJobSources(jobId, state, { autoLoad, loadDiscovered, loadHistory }) {
  const { state: next, source } = await autoLoad(state)
  let fileChecked = source !== 'local'
  const row = fileChecked ? next.jobs.find((job) => job.jobId === jobId) ?? null : null
  // The merged list also holds kept rows, and those are exactly the ones the file lacks.
  let inFile = Boolean(row && !row.offList)
  const addable = inFile ? row : null
  let fileJob = addable
  // The scored file can be missing a job discovery found (--min-score), and that job is still in the latest run.
  if (fileChecked && !inFile && source === 'scored') {
    try {
      const discovered = await loadDiscovered()
      fileJob = discovered?.jobs?.find((job) => job.jobId === jobId) ?? null
      inFile = Boolean(fileJob)
    } catch {
      fileChecked = false
    }
  }
  const text = (fileJob ?? row)?.description
  const ledger = !inFile || blank(text) ? await loadHistory(jobId) : null
  return { fileChecked, inFile, row, fileJob, addable, ledger }
}
