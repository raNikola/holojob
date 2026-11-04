import { ensureApiAvailable } from '../../utils/apiAvailability.js'
import { loadIntelligence } from '../intelligence/intelligenceExport.js'
import { loadJobs } from '../jobs/jobStorage.js'

/** The download name, with the date and time on the owner's clock (the container runs on UTC, so the browser names it). */
export function backupFileName(now = new Date()) {
  const two = (n) => String(n).padStart(2, '0')
  const date = `${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())}`
  return `holojob-backup-${date}_${two(now.getHours())}-${two(now.getMinutes())}.zip`
}

/** Returns the name the file was saved under. */
export async function downloadBackupZip(profile) {
  if (!(await ensureApiAvailable())) {
    throw new Error('Backup requires the local API server (npm run dev or npm run start)')
  }
  const intelligence = loadIntelligence()
  const jobs = loadJobs()
  const res = await fetch('/api/backup/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      profile,
      intelligence,
      jobs: jobs.jobs?.length ? jobs : null,
    }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || err.error || 'Backup export failed')
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  const name = backupFileName()
  anchor.download = name
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
  return name
}

export async function importBackupZip(file) {
  if (!(await ensureApiAvailable())) {
    throw new Error('Backup import requires the local API server')
  }
  const buffer = await file.arrayBuffer()
  const res = await fetch('/api/backup/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/zip' },
    body: buffer,
  })
  const payload = await res.json()
  if (!res.ok) throw new Error(payload.message || payload.error || 'Backup import failed')
  return payload
}
