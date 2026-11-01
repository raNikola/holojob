import { useState } from 'react'
import { Download, Loader2, RotateCcw } from 'lucide-react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { useProfile } from '../../context/ProfileContext'
import { loadIntelligence } from '../../modules/intelligence/intelligenceExport'
import { openOnboarding } from '../../modules/appNavigation'
import {
  RESET_KEEPS, RESET_REMOVES, RESET_WORD, backupFileName, buildProfileBackup, canRunReset, requestProfileReset, setResetNotice,
} from '../../modules/profile/profileReset'

const FIELD = 'w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm dark:border-stone-700 dark:bg-stone-900'

function downloadJson(data, fileName) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export default function ResetProfilePanel() {
  const { profile, resetProfile } = useProfile()
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)

  const close = () => {
    setOpen(false)
    setTyped('')
  }

  const handleDownload = () => {
    const now = new Date()
    downloadJson(buildProfileBackup(profile, loadIntelligence(), now), backupFileName(now))
  }

  const handleReset = async () => {
    if (!canRunReset(typed, running)) return
    setRunning(true)
    setResult(null)
    const outcome = await requestProfileReset(typed)
    setRunning(false)
    if (!outcome.ok) {
      setResult({ ok: false, text: outcome.error })
      return
    }
    const text = outcome.backup ? `Profile reset. The old files are in ${outcome.backup}.` : 'Profile reset. There were no files on the server to back up.'
    setResetNotice(text)
    resetProfile()
    close()
    setResult({ ok: true, text })
    openOnboarding()
  }

  return (
    <Card title="Reset profile" description="Start onboarding again. Jobs, the tracker, settings and keys stay.">
      {result && <Alert variant={result.ok ? 'success' : 'error'}>{result.text}</Alert>}
      {!open ? (
        <Button variant="ghost" onClick={() => { setResult(null); setOpen(true) }} className="text-red-600 hover:text-red-700">
          <RotateCcw className="h-4 w-4" />
          Reset profile
        </Button>
      ) : (
        <div role="alertdialog" aria-labelledby="reset-profile-title" className="space-y-4 rounded-lg border border-red-300 bg-red-50 p-4 dark:border-red-900 dark:bg-red-950/30">
          <h4 id="reset-profile-title" className="text-sm font-semibold text-red-800 dark:text-red-200">Reset your profile?</h4>
          <div className="text-sm text-stone-700 dark:text-stone-300">
            <p className="font-medium">Removed:</p>
            <ul className="list-disc space-y-1 pl-5">{RESET_REMOVES.map((t) => <li key={t}>{t}</li>)}</ul>
          </div>
          <div className="text-sm text-stone-700 dark:text-stone-300">
            <p className="font-medium">Not touched:</p>
            <ul className="list-disc space-y-1 pl-5">{RESET_KEEPS.map((t) => <li key={t}>{t}</li>)}</ul>
          </div>
          <p className="text-sm text-stone-700 dark:text-stone-300">
            Nothing is deleted outright. The server files are moved to a folder named <code>data/profile.bak-</code> and the time, and you
            can also download the profile and intelligence as JSON (the stored CV PDFs are only in the server folder).
          </p>
          <Button variant="secondary" onClick={handleDownload} disabled={running}>
            <Download className="h-4 w-4" />
            Download backup (JSON)
          </Button>
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Type {RESET_WORD} to confirm</span>
            <input
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              disabled={running}
              autoComplete="off"
              spellCheck={false}
              className={FIELD}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button variant="danger" onClick={handleReset} disabled={!canRunReset(typed, running)}>
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
              {running ? 'Resetting…' : 'Reset profile'}
            </Button>
            <Button variant="ghost" onClick={close} disabled={running}>Cancel</Button>
          </div>
        </div>
      )}
    </Card>
  )
}
