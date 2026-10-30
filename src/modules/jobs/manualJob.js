// A job the owner types in by hand. Pure helpers: validation, URL normalising, the record to store.
// Nothing here talks to the server, and Notes / extra links are owner-only (they stay in the browser's job record).

export const MANUAL_SOURCES = ['LinkedIn', 'Company site', 'Referral', 'Other']

/**
 * The only fields of a manual job that go to the server's scoring (python/job_scoring/manual_jobs.py SCORING_FIELDS, kept
 * in step by a test). Notes and extra links are not among them.
 */
export const SCORING_FIELDS = [
  'jobId', 'title', 'company', 'description', 'jobUrl', 'location', 'salary', 'site', 'provider',
  'sourceChoice', 'status', 'createdAt', 'firstSeen', 'lastSeen', 'scrapedAt',
]

/** The scoring payload of a stored manual job: the string fields above, nothing else. */
export function scoringPayload(job) {
  return Object.fromEntries(SCORING_FIELDS.filter((field) => typeof job?.[field] === 'string').map((field) => [field, job[field]]))
}

/** Fields a re-import of the scored-jobs file must carry over from the stored record. */
export const MANUAL_FIELDS = ['manualEntry', 'sourceChoice', 'notes', 'extraLinks', 'createdAt']

/** `new` is shown as "Unreviewed"; any other status keeps its stored wording. */
export function jobStatusLabel(status) {
  if (!status || status === 'new') return 'Unreviewed'
  return String(status).replace(/_/g, ' ')
}

/**
 * The URL as compared for duplicates: http(s) only, lowercase host, no query, hash or trailing slash.
 * @returns {string|null} null when the text is not an http(s) URL
 */
export function normalizeJobUrl(raw) {
  const text = String(raw ?? '').trim()
  if (!text) return null
  let url
  try {
    url = new URL(text)
  } catch {
    return null
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null
  const path = url.pathname.replace(/\/+$/, '')
  return `${url.protocol}//${url.host.toLowerCase()}${path}`
}

/** The stored job whose main link matches `url`, or null. */
export function findDuplicateByUrl(jobs, url) {
  const key = normalizeJobUrl(url)
  if (!key) return null
  return (jobs || []).find((job) => normalizeJobUrl(job.jobUrl) === key) ?? null
}

/** The extra link rows that carry something; a row with only a label is an error, an empty row is dropped. */
export function cleanExtraLinks(rows) {
  return (rows || [])
    .map((row) => ({ url: String(row?.url ?? '').trim(), label: String(row?.label ?? '').trim() }))
    .filter((row) => row.url || row.label)
}

/**
 * Inline errors by field; an empty object means the form can be saved.
 * `extraLinks` errors are keyed by the row's index in the cleaned list.
 */
export function validateManualJob(input) {
  const errors = {}
  if (!String(input?.title ?? '').trim()) errors.title = 'Enter the job title.'
  if (!String(input?.company ?? '').trim()) errors.company = 'Enter the company.'
  if (!String(input?.description ?? '').trim()) errors.description = 'Paste the job description.'
  if (String(input?.jobUrl ?? '').trim() && !normalizeJobUrl(input.jobUrl)) {
    errors.jobUrl = 'Enter a full link starting with http:// or https://.'
  }
  const linkErrors = {}
  cleanExtraLinks(input?.extraLinks).forEach((row, index) => {
    if (!normalizeJobUrl(row.url)) linkErrors[index] = 'Enter a full link starting with http:// or https://.'
  })
  if (Object.keys(linkErrors).length) errors.extraLinks = linkErrors
  return errors
}

const hostOf = (url) => {
  try {
    return new URL(url).host.toLowerCase().replace(/^www\./, '')
  } catch {
    return ''
  }
}

/**
 * The record to store. It has no score, no salaryMonthlyEur and no isRemote: those are set by scoring or stay
 * unknown. `salary` is the text as typed, the same field the other jobs carry the ad's pay in.
 */
export function buildManualJob(input, { now = new Date(), id = `manual-${globalThis.crypto.randomUUID()}` } = {}) {
  const stamp = now.toISOString()
  const jobUrl = String(input.jobUrl ?? '').trim()
  const job = {
    jobId: id,
    title: input.title.trim(),
    company: input.company.trim(),
    description: input.description.trim(),
    location: String(input.location ?? '').trim(),
    jobUrl,
    site: hostOf(jobUrl),
    provider: 'manual',
    manualEntry: true,
    sourceChoice: MANUAL_SOURCES.includes(input.sourceChoice) ? input.sourceChoice : 'Other',
    status: 'new',
    createdAt: stamp,
    firstSeen: stamp,
    lastSeen: stamp,
    scrapedAt: stamp,
  }
  const salary = String(input.salary ?? '').trim()
  if (salary) job.salary = salary
  const notes = String(input.notes ?? '').trim()
  if (notes) job.notes = notes
  const extraLinks = cleanExtraLinks(input.extraLinks)
  if (extraLinks.length) job.extraLinks = extraLinks
  return job
}
