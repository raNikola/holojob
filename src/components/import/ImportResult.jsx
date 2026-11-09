import { useState } from 'react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { useProfile } from '../../context/ProfileContext'
import { retryMirrorSync, undoLastImport } from '../../modules/profile/importApply'
import { clearIntelligenceStale, currentProfile, isIntelligenceStale, isSyncPending, realImportDeps, snapshotStore } from '../../modules/profile/importDeps'
import { regenerateIntelligence, saveIntelligence } from '../../modules/intelligence/intelligenceExport'
import { saveIntelligenceToDataDir } from '../../modules/jobs/intelligenceSync'

/**
 * The two things an import can leave open, shown wherever they matter: the profile mirror is behind ("not synced yet", Retry resends the
 * stored profile and never applies the import again) and the intelligence is older than the profile (regenerating stays the owner's action).
 */
export function ProfileChangeNotices({ onChange }) {
  const { commitProfile } = useProfile()
  const [pending, setPending] = useState(isSyncPending)
  const [stale, setStale] = useState(isIntelligenceStale)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const retry = async () => {
    setBusy(true)
    setMessage('')
    const { synced } = await retryMirrorSync({ getProfile: currentProfile, deps: realImportDeps({ commitToScreen: commitProfile }) })
    setPending(!synced)
    if (!synced) setMessage('The server could not be reached. Your profile is saved in this browser; try again later.')
    setBusy(false)
    onChange?.()
  }

  const regenerate = () => {
    setBusy(true)
    setMessage('')
    try {
      const generated = regenerateIntelligence(currentProfile())
      saveIntelligence(generated)
      void saveIntelligenceToDataDir(generated)
      clearIntelligenceStale()
      setStale(false)
    } catch {
      setMessage('The intelligence could not be regenerated. Check the profile and try again.')
    }
    setBusy(false)
    onChange?.()
  }

  if (!pending && !stale) return null
  return (
    <div className="space-y-3">
      {pending && (
        <Alert variant="error" title="Not synced yet">
          <p>Your profile is saved in this browser, but the server's copy is behind. Scoring runs read the server's copy.</p>
          <Button variant="secondary" className="mt-2" onClick={retry} disabled={busy}>Retry sync</Button>
        </Alert>
      )}
      {stale && (
        <Alert variant="info" title="Your profile changed">
          <p>Your candidate intelligence was built from the previous profile. Regenerate it when you are ready; this runs locally and costs nothing.</p>
          <Button variant="secondary" className="mt-2" onClick={regenerate} disabled={busy}>Regenerate intelligence</Button>
        </Alert>
      )}
      {message && <p role="status" className="text-sm text-stone-600 dark:text-stone-400">{message}</p>}
    </div>
  )
}

/** Shown after Apply: what happened, what is still open, Undo while nothing has changed since, and Continue. */
export default function ImportResult({ result, onContinue }) {
  const { commitProfile } = useProfile()
  const [undone, setUndone] = useState(false)
  const [undoMessage, setUndoMessage] = useState('')
  const [, refresh] = useState(0)

  const undo = async () => {
    setUndoMessage('')
    const outcome = await undoLastImport({ getProfile: currentProfile, deps: realImportDeps({ commitToScreen: commitProfile }) })
    if (outcome.ok) setUndone(true)
    else setUndoMessage(outcome.reason === 'changed' ? 'Your profile was edited after the import, so it cannot be undone safely.' : 'The previous profile could not be restored.')
    refresh((n) => n + 1)
  }

  return (
    <div className="space-y-4">
      <Card title={undone ? 'Import undone' : result.duplicate ? 'Nothing to apply' : 'Import applied'}>
        <p className="text-sm text-stone-600 dark:text-stone-400">
          {undone
            ? 'Your profile is back as it was before the import.'
            : result.duplicate
              ? 'This import is already in your profile, so nothing was changed.'
              : 'Your profile was updated and a backup of the previous one was made.'}
        </p>
      </Card>
      <ProfileChangeNotices onChange={() => refresh((n) => n + 1)} />
      {undoMessage && <Alert variant="error">{undoMessage}</Alert>}
      <div className="flex flex-wrap justify-end gap-2">
        {!undone && !result.duplicate && snapshotStore.load() && <Button variant="ghost" onClick={undo}>Undo this import</Button>}
        <Button onClick={onContinue}>Continue</Button>
      </div>
    </div>
  )
}
