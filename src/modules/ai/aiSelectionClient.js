/**
 * Browser side of the AI provider selection (scripts/ai-settings-handler.js, python/llm/ai_selection.py).
 * The server file is the only copy; the browser keeps none. No key ever passes through here.
 */

async function parse(res) {
  const body = await res.json().catch(() => ({}))
  return { status: res.status, body }
}

/** { ok, data: { selection | null, providers: [{ name, class }], nodeProviders, class?, error? } } | { ok: false, error } */
export async function fetchAiSelection(fetchImpl = globalThis.fetch) {
  let res
  try {
    res = await fetchImpl('/api/ai/selection')
  } catch {
    return { ok: false, error: 'The server could not be reached' }
  }
  const { status, body } = await parse(res)
  if (!res.ok) return { ok: false, error: (typeof body.error === 'string' && body.error) || `Server answered ${status}` }
  return { ok: true, data: body }
}

/**
 * Resolves { ok, data } | { ok: false, needsConfirm, increases } | { ok: false, errors } | { ok: false, error }.
 * Pass confirm: true only after the owner agreed to a paid or unknown-class provider.
 */
export async function putAiSelection(settings, { confirm = false } = {}, fetchImpl = globalThis.fetch) {
  let res
  try {
    res = await fetchImpl('/api/ai/selection', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings, confirm }),
    })
  } catch {
    return { ok: false, error: 'The server could not be reached' }
  }
  const { status, body } = await parse(res)
  if (status === 409) return { ok: false, needsConfirm: true, increases: body.increases || [] }
  if (!res.ok) return { ok: false, errors: body.errors || [body.error || `Save failed (${status})`] }
  return { ok: true, data: body }
}
