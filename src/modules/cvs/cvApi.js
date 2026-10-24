import { ensureApiAvailable } from '../../utils/apiAvailability'

/** Store the PDF on the server. Returns its id, or null when the API is not reachable. */
export async function uploadCvFile(file) {
  if (!(await ensureApiAvailable())) return null
  const res = await fetch('/api/cvs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/pdf' },
    body: file,
  })
  const payload = await res.json().catch(() => ({}))
  if (!res.ok || !payload.ok) throw new Error(payload.error || 'Could not save the CV file.')
  return payload.id
}

export async function deleteCvFile(id) {
  if (!id) return
  if (!(await ensureApiAvailable())) throw new Error('The local API is not reachable, so the file was not deleted.')
  const res = await fetch(`/api/cvs/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Could not delete the CV file.')
}

export function cvDownloadUrl(id, fileName) {
  return `/api/cvs/${id}/file?name=${encodeURIComponent(fileName || 'cv.pdf')}`
}
