// The two number settings of Settings > Sources: description retries per ad (`descriptionRetry.maxTotal`) and the repost window in days
// (`repostWindowDays`). The server is the master and holds the bounds (source_settings.py); this file only checks what the owner typed so a
// bad value is not sent, and builds the request from what changed. The defaults and limits shown come from the server's answer, never from here.

const whole = (text) => (/^\d+$/.test(String(text).trim()) ? Number(String(text).trim()) : null)

/** The draft the fields start from, from the server's answer (`GET /api/sources`). Strings, as typed. */
export function numbersDraftFrom(data) {
  return {
    maxTotal: String(data?.descriptionRetry?.maxTotal ?? ''),
    repostWindowDays: String(data?.repostWindowDays ?? ''),
  }
}

/** `{ payload, errors }`: only the fields that differ from the saved ones go in the payload; `payload` is null with nothing changed or any error. */
export function numbersChanges(draft, data) {
  const limits = data?.limits
  const errors = {}
  const payload = {}
  const retry = whole(draft.maxTotal)
  if (retry === null || retry > (limits?.retryMax ?? 0)) errors.maxTotal = `A whole number from 0 to ${limits?.retryMax ?? '?'}`
  else if (retry !== data?.descriptionRetry?.maxTotal) payload.descriptionRetry = { maxTotal: retry }
  const days = whole(draft.repostWindowDays)
  if (days === null || days < 1 || days > (limits?.repostWindowMax ?? 0)) errors.repostWindowDays = `A whole number from 1 to ${limits?.repostWindowMax ?? '?'}`
  else if (days !== data?.repostWindowDays) payload.repostWindowDays = days
  return { payload: Object.keys(errors).length || !Object.keys(payload).length ? null : payload, errors }
}
