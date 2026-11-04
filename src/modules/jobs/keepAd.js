// "Keep this ad": the one way a row only the server holds becomes a stored row (slice S5e3d). The ad comes from the ledger through
// `resolveJob`, the path Job Details already reads a ledger-only ad by. A ledger that cannot answer stores nothing: the owner sees why,
// and can try again. A ledger that answers with no ad text is stored and marked, so an incomplete ad never passes as complete.
import { resolveJob } from './jobResolve.js'
import { promoteRow } from './jobsStore.js'
import { loadJobHistory } from './pipelineRunner.js'

export const KEEP_FAILED = 'The ad could not be read from the job history, so nothing was kept. Try again.'

/** @returns {Promise<{ ok: true, job: object } | { ok: false, message: string }>} */
export async function keepAd(row, { loadHistory = loadJobHistory } = {}) {
  const ledger = await loadHistory(row.jobId)
  const ad = ledger ? resolveJob({ ledger }).job : null
  if (!ad) return { ok: false, message: KEEP_FAILED }
  return { ok: true, job: promoteRow(row, ad) }
}
