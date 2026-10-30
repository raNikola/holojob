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
  const blocked = data.error === 'blocked_host'
  return { ok: false, message: blocked ? String(data.message || READ_FAILED) : READ_FAILED, blocked }
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

/** The fields the page did not state that are still empty in the form: what an AI step could be asked for. */
export function stillMissing(form, missing) {
  return (missing || []).filter((name) => AD_FIELDS.includes(name) && isEmpty(form[name]))
}
