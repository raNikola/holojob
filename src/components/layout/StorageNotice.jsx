import { useState } from 'react'
import { AlertTriangle, Info } from 'lucide-react'
import SettingsLink from '../settings/SettingsLink'
import { useStorageHealth } from '../../hooks/useStorageHealth'
import { ERROR_NOTICE, LEAN_NOTICE, MINIMAL_NOTICE, MISSING_NOTICE, NEAR_NOTICE } from '../../modules/jobs/storageNoticeText.js'

const tone = {
  info: 'border-stone-200 bg-stone-50 text-stone-800 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-200',
  warn: 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-100',
  error: 'border-red-300 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950/50 dark:text-red-100',
}

/**
 * How the browser holds the job list, when it is not simply "all of it" (S8a). The error cannot be dismissed. The other notices can, until
 * the shape changes; nothing is stored about the dismissal.
 */
export default function StorageNotice() {
  const health = useStorageHealth()
  const [dismissed, setDismissed] = useState(null)
  const notes = []
  if (health.level === 'error') notes.push({ key: 'error', tone: 'error', text: ERROR_NOTICE, backup: true })
  else if (health.level === 'minimal') notes.push({ key: 'minimal', tone: 'warn', text: MINIMAL_NOTICE(health.droppedText) })
  else if (health.level === 'lean') notes.push({ key: 'lean', tone: 'warn', text: LEAN_NOTICE })
  else if (health.level === 'near') notes.push({ key: 'near', tone: 'info', text: NEAR_NOTICE(health.percent) })
  if (health.textsMissing > 0) notes.push({ key: 'missing', tone: 'warn', text: MISSING_NOTICE(health.textsMissing), permanent: true })
  const shown = notes.filter((note) => note.permanent || note.key === 'error' || dismissed !== note.key)
  if (!shown.length) return null
  return (
    <div className="space-y-2 px-4 pt-3" data-testid="storage-notice">
      {shown.map((note) => {
        const Icon = note.tone === 'info' ? Info : AlertTriangle
        return (
          <div key={note.key} role={note.tone === 'error' ? 'alert' : 'status'} className={`flex gap-3 rounded-lg border p-3 text-sm ${tone[note.tone]}`}>
            <Icon className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p>{note.text}</p>
              {note.backup && <p className="mt-1">Take a backup in <SettingsLink section="backup-restore">Settings &gt; Data &amp; backups</SettingsLink>, then free space.</p>}
              {!note.permanent && note.key !== 'error' && (
                <button type="button" className="mt-1 underline underline-offset-2" onClick={() => setDismissed(note.key)}>Dismiss</button>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
