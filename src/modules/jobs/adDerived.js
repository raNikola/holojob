// What the server works out on every read and never stores (list-cleanup, owner brief 2026-11-27): the package 4 text labels of an ad and the
// package 7 repost count. The rules are python/job_scoring/job_derived.py; this file only words them and asks for them.
// Display only: nothing here changes a score, a tier, a filter, the order or the number of rows.
import { useEffect, useState } from 'react'

export const DERIVED_URL = '/api/jobs/derived'

const EMPLOYMENT = { internship: 'Internship', part_time: 'Part-time', contract: 'Contract or fixed term', full_time: 'Full-time' }

/** The words of one label ("years:7" -> "7+ years asked"), or the label as it came for one this build does not know. */
export function labelText(label) {
  const [rule, value = ''] = String(label).split(':')
  if (rule === 'language') return `Language: ${value.charAt(0).toUpperCase()}${value.slice(1)}`
  if (rule === 'years') return `${value}+ years asked`
  if (rule === 'onsite') return 'On-site only'
  if (rule === 'visa') return value === 'no_sponsorship' ? 'No visa sponsorship' : 'Visa sponsorship offered'
  if (rule === 'employment') return EMPLOYMENT[value] ?? value
  return String(label)
}

/** The labels to show, in words, as `{ label, text }`. `years` shows in Job Details only; no list shows any label. */
export const labelChips = (labels) => (Array.isArray(labels) ? labels : [])
  .filter((l) => l && typeof l.label === 'string')
  .map((l) => ({ label: l.label, text: labelText(l.label) }))

export const LABELS_NOTE = 'Read from the ad text. Informational: they change no score, filter or order.'

/** The repost badge of a row, or null: `repostCount` is the number of other postings of the same role (the counter's six rules). */
export function repostBadge(row) {
  const count = row?.repostCount
  if (!Number.isInteger(count) || count < 1) return null
  const others = count === 1 ? '1 other posting' : `${count} other postings`
  return {
    label: `Reposted ×${count}`,
    variant: 'derived',
    reason: `${others} of this role: same company, same title words, same board, different link, within the repost window (Settings > Sources). Rows are not merged.`,
  }
}

/** `{ ok: true, labels, labelsFrom, repostCount }` or `{ ok: false }`. Never throws. */
export async function fetchDerived(jobId, fetchFn = globalThis.fetch) {
  try {
    const res = await fetchFn(`${DERIVED_URL}?jobId=${encodeURIComponent(jobId)}`)
    const body = await res.json().catch(() => null)
    return res.ok && body?.ok === true ? body : { ok: false }
  } catch {
    return { ok: false }
  }
}

/** The derived facts of one ad, asked again when the ad or its text changes (a pasted text changes the labels). `null` until the answer is there. */
export function useAdDerived(jobId, textKey = '') {
  const [state, setState] = useState({ jobId: null, value: null })
  useEffect(() => {
    if (!jobId || typeof fetch !== 'function') return undefined
    let live = true
    fetchDerived(jobId).then((answer) => { if (live && answer.ok) setState({ jobId, value: answer }) })
    return () => { live = false }
  }, [jobId, textKey])
  return state.jobId === jobId ? state.value : null
}
