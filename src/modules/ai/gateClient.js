/** Browser side of the AI budget gate routes (scripts/ai-settings-handler.js, GET /api/ai/usage). */

async function parse(res) {
  const body = await res.json().catch(() => ({}))
  return { status: res.status, body }
}

export async function loadGateUsage() {
  const res = await fetch('/api/ai/usage')
  const { body } = await parse(res)
  if (!res.ok) throw new Error(body.error || `Could not read AI usage (${res.status})`)
  return body
}

async function put(path, payload) {
  const res = await fetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const { status, body } = await parse(res)
  if (status === 409) return { ok: false, needsConfirm: true, increases: body.increases || [] }
  if (!res.ok) return { ok: false, errors: body.errors || [body.error || `Save failed (${status})`] }
  return body
}

/** Resolves { ok } | { needsConfirm, increases } | { errors }. Pass confirm: true only after the owner agreed. */
export const saveGateSettings = (settings, confirm = false) => put('/api/ai/settings', { settings, confirm })
export const saveGatePricing = (entries, confirm = false) => put('/api/ai/pricing', { entries, confirm })

/** The form's text fields as the settings object the server validates ('' for a call limit means none). */
export function settingsFromForm(form) {
  const num = (v) => (v === '' || v == null ? NaN : Number(v))
  const count = (v) => (String(v).trim() === '' ? null : num(v))
  return {
    currency: String(form.currency).trim().toUpperCase(),
    dailyLimit: num(form.dailyLimit),
    monthlyLimit: num(form.monthlyLimit),
    maxCallsDaily: count(form.maxCallsDaily),
    maxCallsMonthly: count(form.maxCallsMonthly),
    estimatedOutputTokens: num(form.estimatedOutputTokens),
    timezone: String(form.timezone).trim(),
    automation: { enabled: Boolean(form.automationEnabled) },
    claudeCodeSubscription: {
      enabled: Boolean(form.subscriptionEnabled),
      maxCallsDaily: num(form.subscriptionMaxCallsDaily),
      features: form.subscriptionFeatures,
    },
  }
}

export function formFromSettings(s) {
  const text = (v) => (v == null ? '' : String(v))
  return {
    currency: s.currency, dailyLimit: text(s.dailyLimit), monthlyLimit: text(s.monthlyLimit),
    maxCallsDaily: text(s.maxCallsDaily), maxCallsMonthly: text(s.maxCallsMonthly),
    estimatedOutputTokens: text(s.estimatedOutputTokens), timezone: s.timezone,
    automationEnabled: Boolean(s.automation?.enabled),
    subscriptionEnabled: Boolean(s.claudeCodeSubscription?.enabled),
    subscriptionMaxCallsDaily: text(s.claudeCodeSubscription?.maxCallsDaily),
    subscriptionFeatures: s.claudeCodeSubscription?.features || ['jobAnalysis'],
  }
}
