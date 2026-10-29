import { ensureApiAvailable } from '../../utils/apiAvailability.js'

async function post(url, body) {
  if (!(await ensureApiAvailable())) throw new Error('The migration needs the local API server')
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const payload = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(payload.error || `Request failed (${res.status})`)
  return payload
}

/** Dry run over the browser job list: the plan and the hash that apply needs. Writes nothing. */
export const previewMigration = (jobs) => post('/api/applications/migrate/preview', { jobs })

/** Apply the migration reviewed in `previewMigration`; `previewSha` ties it to that dry run. */
export const runMigration = (jobs, previewSha) => post('/api/applications/migrate', { jobs, confirm: true, previewSha })
