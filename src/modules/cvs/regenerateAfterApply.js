import { validateProfileForIntelligence } from '../intelligence/intelligenceValidators'
import { regenerateIntelligence, saveIntelligence } from '../intelligence/intelligenceExport'
import { saveIntelligenceToDataDir } from '../jobs/intelligenceSync'

/**
 * What the "Regenerate Intelligence" button does (validate, regenerate, keep in the
 * browser, sync to disk), reporting each way it can fail instead of ignoring it.
 * Local and rule-based: no model is called.
 * Returns { ok, error? }; ok means regenerated and synced.
 */
export async function regenerateAndSync(profile) {
  const validation = validateProfileForIntelligence(profile)
  if (!validation.valid) return { ok: false, error: validation.errors.join(' ') }
  let generated
  try {
    generated = regenerateIntelligence(profile)
    saveIntelligence(generated)
  } catch (e) {
    return { ok: false, error: e.message || 'Failed to regenerate intelligence.' }
  }
  const synced = await saveIntelligenceToDataDir(generated)
  if (!synced.ok) return { ok: false, error: `Regenerated in the browser, but not synced to disk: ${synced.reason}` }
  return { ok: true }
}
