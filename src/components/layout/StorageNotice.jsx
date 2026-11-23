import { useState } from 'react'
import { AlertTriangle, Info } from 'lucide-react'
import SettingsLink from '../settings/SettingsLink'
import { Toast, ToastStack } from '../ui/Toast'
import { useStorageHealth } from '../../hooks/useStorageHealth'
import { ERROR_NOTICE, LEAN_NOTICE, MINIMAL_NOTICE, MISSING_NOTICE, NEAR_NOTICE, NO_SOURCE_TEXT_NOTICE } from '../../modules/jobs/storageNoticeText.js'

export const DISMISSED_KEY = 'holojob.storageNotice.dismissed'

const readDismissed = () => {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(DISMISSED_KEY) || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch { return [] }
}
const writeDismissed = (keys) => {
  try { window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(keys)) } catch { /* the dismissal then lasts for this visit only */ }
}

/**
 * How the browser holds the job list, when it is not simply "all of it" (S8a), as bottom-right toasts. The error and the missing-texts
 * notices cannot be closed. The others stay until dismissed, and the dismissal is remembered in this browser (localStorage, by notice).
 */
export default function StorageNotice() {
  const health = useStorageHealth()
  const [dismissed, setDismissed] = useState(readDismissed)
  const notes = []
  if (health.level === 'error') notes.push({ key: 'error', kind: 'error', text: ERROR_NOTICE, backup: true })
  else if (health.level === 'minimal') notes.push({ key: 'minimal', kind: 'warn', text: MINIMAL_NOTICE(health.droppedText) })
  else if (health.level === 'lean') notes.push({ key: 'lean', kind: 'warn', text: LEAN_NOTICE })
  else if (health.level === 'near') notes.push({ key: 'near', kind: 'info', text: NEAR_NOTICE(health.percent) })
  if (health.textsMissing > 0) notes.push({ key: 'missing', kind: 'warn', text: MISSING_NOTICE(health.textsMissing), permanent: true })
  if (health.textsNoSourceText > 0) notes.push({ key: 'no-source-text', kind: 'info', text: NO_SOURCE_TEXT_NOTICE(health.textsNoSourceText) })
  const shown = notes.filter((note) => note.permanent || note.key === 'error' || !dismissed.includes(note.key))
  const dismiss = (key) => {
    const next = [...new Set([...dismissed, key])]
    setDismissed(next)
    writeDismissed(next)
  }
  return (
    <ToastStack>
      {shown.map((note) => {
        const Icon = note.kind === 'info' ? Info : AlertTriangle
        const closable = !note.permanent && note.key !== 'error'
        return (
          <Toast key={note.key} kind={note.kind} onDismiss={closable ? () => dismiss(note.key) : null}>
            <div className="flex gap-2" data-testid="storage-notice">
              <Icon className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p>{note.text}</p>
                {note.backup && <p className="mt-1">Take a backup in <SettingsLink section="backup-restore">Settings &gt; Data &amp; backups</SettingsLink>, then free space.</p>}
              </div>
            </div>
          </Toast>
        )
      })}
    </ToastStack>
  )
}
