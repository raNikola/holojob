// Fill from ad: ask the server to read the page behind the Job URL and propose values for the Add job form.
// The request carries the address and nothing else (no Notes, links, Source URL or profile); the page text stays on the
// server behind `token`. Proposed values only ever go into fields that are still empty, and are shown as "suggested".

export const AD_FIELDS = ['title', 'company', 'location', 'salary', 'description']
export const READ_FAILED = 'Could not read this page, paste the text manually.'

/** The body of the fetch request: the address only. */
export function adFetchBody(url) {
  return { url: String(url ?? '').trim() }
}

/**
 * @returns {Promise<{ ok: true, token: string, fields: object, missing: string[], finalUrl: string } | { ok: false, message: string, blocked: boolean }>}
 */
export async function fetchAdFields(url, { fetchFn = globalThis.fetch } = {}) {
  let response
  try {
    response = await fetchFn('/api/jobs/ad/fetch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(adFetchBody(url)) })
  } catch {
    return { ok: false, message: READ_FAILED, blocked: false }
  }
  const data = await response.json().catch(() => ({}))
  if (response.status === 200 && data.ok && data.token) {
    return { ok: true, token: data.token, fields: data.fields ?? {}, missing: Array.isArray(data.missing) ? data.missing : [], finalUrl: data.finalUrl ?? '' }
  }
  // The server picks the wording from the failure code and status; anything missing falls back to the generic message.
  return { ok: false, message: typeof data.message === 'string' && data.message ? data.message : READ_FAILED, blocked: data.error === 'blocked_host' }
}

const isEmpty = (value) => !String(value ?? '').trim()

/**
 * `fields` laid into the empty fields of `form`; a field the owner has filled, or an earlier step filled, is never touched.
 * @returns {{ form: object, filled: string[] }}
 */
export function applySuggestions(form, fields) {
  const next = { ...form }
  const filled = []
  for (const name of AD_FIELDS) {
    const value = String(fields?.[name] ?? '').trim()
    if (value && isEmpty(form[name])) {
      next[name] = value
      filled.push(name)
    }
  }
  return { form: next, filled }
}

export const LABELS = { title: 'Title', company: 'Company', location: 'Location', salary: 'Salary', description: 'Job description' }

const names = (list) => list.map((name) => LABELS[name].toLowerCase()).join(', ')

/**
 * One state transition for a fill, so the form, the "suggested" marks and the note can never disagree. `draft` is
 * `{ form, suggested, note }`; the result fills only the form's empty fields, marks exactly those as suggested (earlier marks
 * stay) and words the note from what was filled. `source` is 'page' or 'ai'; `wanted` are the fields an AI step was asked for.
 */
export function applyFill(draft, fields, { source = 'page', wanted = [] } = {}) {
  const { form, filled } = applySuggestions(draft.form, fields)
  const suggested = { ...draft.suggested, ...Object.fromEntries(filled.map((name) => [name, true])) }
  const notFound = wanted.filter((name) => !filled.includes(name))
  let text
  if (source === 'ai') {
    text = `${filled.length ? `The AI found: ${names(filled)} (suggested, edit or keep). ` : 'The AI found nothing the page states. '}${notFound.length ? `Not stated in the text, left empty: ${names(notFound)}.` : ''}`.trim()
  } else {
    text = filled.length
      ? `Filled from the page: ${names(filled)}. These are suggestions: edit them or leave them, nothing is saved until you click Save.`
      : 'The page had nothing new for the empty fields.'
  }
  return { ...draft, form, suggested, note: { kind: 'info', text }, lastFilled: filled }
}

/** The mark of a field goes when the owner edits it. */
export function clearSuggested(draft, field) {
  return draft.suggested[field] ? { ...draft, suggested: { ...draft.suggested, [field]: false } } : draft
}

/** The fields the page did not state that are still empty in the form: what an AI step could be asked for. */
export function stillMissing(form, missing) {
  return (missing || []).filter((name) => AD_FIELDS.includes(name) && isEmpty(form[name]))
}

async function postAi(path, body, fetchFn) {
  let response
  try {
    response = await fetchFn(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  } catch {
    return { status: 0, data: {} }
  }
  return { status: response.status, data: await response.json().catch(() => ({})) }
}

const AI_UNAVAILABLE = 'The AI step is not available right now. Fill the fields in by hand.'

/**
 * What the AI step would send: the redacted page text, the fields, and whether the gate allows it. Calls no model.
 * The body is the token and the field names only.
 * @returns {Promise<{ ok: true, text: string, want: string[], removed: object, provider: string, gate: { allowed: boolean, reason: string|null, class: string } } | { ok: false, message: string }>}
 */
export async function previewAdAi({ token, want }, { fetchFn = globalThis.fetch } = {}) {
  const { status, data } = await postAi('/api/jobs/ad/ai-preview', { token, want }, fetchFn)
  if (status === 200 && data.ok) return data
  return { ok: false, message: data.message || AI_UNAVAILABLE }
}

/**
 * The one call that sends the page text to a model; send it only from the confirm button.
 * @returns {Promise<{ ok: true, fields: object, rejected: string[] } | { ok: false, message: string }>}
 */
export async function runAdAi({ token, want }, { fetchFn = globalThis.fetch } = {}) {
  const { status, data } = await postAi('/api/jobs/ad/ai-extract', { token, want, confirm: true }, fetchFn)
  if (status === 200 && data.ok) return { ok: true, fields: data.fields ?? {}, rejected: data.rejected ?? [] }
  return { ok: false, message: data.message || AI_UNAVAILABLE }
}
