import { buildAiContext, buildAiRedactionHints } from './aiContextBuilder.js'

const NOT_FRESH = { fresh: false, at: null, model: null }

/**
 * Asks the server whether a call to `featureId` with the job's current inputs would be answered from a stored finding
 * (POST /api/ai/findings/check: no AI call, no budget, no key). Any failure answers "not fresh", so the button stays usable.
 */
export async function fetchFindingStatus(featureId, { job } = {}) {
  try {
    const context = { ...buildAiContext({ featureId, job }), redactionHints: buildAiRedactionHints({ job }) }
    const res = await fetch('/api/ai/findings/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feature: featureId, context }),
    })
    if (!res.ok) return NOT_FRESH
    const data = await res.json()
    return data?.fresh === true ? { fresh: true, at: data.at ?? null, model: data.model ?? null } : NOT_FRESH
  } catch {
    return NOT_FRESH
  }
}

/**
 * State of the analysis button. It is disabled while a call runs, and when the stored finding is still valid and its
 * result is on screen. With a valid finding but nothing on screen the button stays enabled: a click is answered from
 * the stored finding and costs nothing. Regenerate is a separate control and is not decided here.
 */
export function analysisButtonState({ status, hasAnalysis, loading }) {
  if (loading) return { disabled: true, title: '' }
  if (status?.fresh && hasAnalysis) {
    const date = status.at ? new Date(status.at).toLocaleDateString() : 'an earlier date'
    return { disabled: true, title: `Already analysed on ${date} with ${status.model || 'the selected model'}; nothing has changed` }
  }
  return { disabled: false, title: '' }
}

export const REGENERATE_CONFIRM = 'Nothing has changed since the last analysis. Regenerating makes a new AI call that counts against your limit. Continue?'

/**
 * What a click on Regenerate does. Ignored while a call runs (`loading` or `inFlight`, the latter set synchronously so two
 * quick clicks cannot both start one). With a valid finding on the server it asks first; otherwise it just runs.
 * { disabled } for the button, { action: 'ignore' | 'confirm' | 'run' } for the click.
 */
export function regenerateDecision({ status, loading, inFlight = false }) {
  if (loading || inFlight) return { disabled: true, action: 'ignore' }
  return { disabled: false, action: status?.fresh ? 'confirm' : 'run' }
}
