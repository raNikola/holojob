import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import InfoTip from '../ui/InfoTip'
import { fetchSources, migrateLegacyDiscoveryOptions, saveSources } from '../../modules/sources/sourcesClient'
import {
  BOARD_HELP, BOARD_SUBTEXT, CONSENT_LABEL, boardLabel, canSave, changesFrom, consentSummary, draftFrom, turningOn,
} from '../../modules/sources/jobBoards'

const CHIP = 'inline-flex flex-col items-start rounded-xl border px-3 py-2 text-left text-sm'
const CHIP_ON = 'border-teal-300 bg-teal-50 text-teal-900 dark:border-teal-700 dark:bg-teal-950/40 dark:text-teal-100'
const CHIP_OFF = 'border-stone-200 bg-white text-stone-700 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-300'

/** The chips and the consent line; no fetching, so it renders the same in tests. */
export function JobBoardChips({ boards, draft, consent, onToggle, onConsent, disabled = false }) {
  const pending = turningOn(draft, boards)
  return (
    <div className="space-y-3">
      <ul className="flex flex-wrap gap-2">
        {boards.map((board) => {
          const on = board.optIn ? draft[board.name] === true : board.inStandardRun
          const sub = board.optIn
            ? BOARD_SUBTEXT[board.name] || 'Opt-in'
            : board.inStandardRun ? 'In the standard run' : 'Not in the standard run'
          return (
            <li key={board.name} className="flex items-start gap-1">
              <button
                type="button"
                role="switch"
                aria-checked={on}
                disabled={disabled || !board.optIn}
                onClick={() => onToggle(board.name, !on)}
                title={board.optIn ? undefined : 'Follows the provider group until board switching ships'}
                className={`${CHIP} ${on ? CHIP_ON : CHIP_OFF} ${board.optIn ? 'hover:border-teal-400' : 'cursor-default opacity-80'}`}
              >
                <span className="font-medium">{boardLabel(board.name)}</span>
                <span className="text-xs text-stone-500 dark:text-stone-400">{sub}</span>
              </button>
              {BOARD_HELP[board.name] && <InfoTip text={BOARD_HELP[board.name]} label={`About ${boardLabel(board.name)}`} />}
            </li>
          )
        })}
      </ul>
      {pending.map((name) => (
        <label key={name} className="flex items-center gap-2 text-sm text-stone-700 dark:text-stone-300">
          <input
            type="checkbox"
            checked={consent[name] === true}
            disabled={disabled}
            onChange={(e) => onConsent(name, e.target.checked)}
            className="rounded border-stone-300 text-teal-600 focus:ring-teal-500"
          />
          {boardLabel(name)}: {CONSENT_LABEL}
        </label>
      ))}
      {boards.filter((b) => b.optIn && consentSummary(b)).map((b) => (
        <p key={b.name} className="text-xs text-stone-500 dark:text-stone-400">{boardLabel(b.name)}: {consentSummary(b)}</p>
      ))}
    </div>
  )
}

export default function JobBoardsPanel() {
  const [boards, setBoards] = useState(null)
  const [draft, setDraft] = useState({})
  const [consent, setConsent] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [message, setMessage] = useState(null)

  const apply = useCallback((data) => {
    setBoards(data.boards || [])
    setDraft(draftFrom(data.boards))
    setConsent({})
    setError(data.error || null)
  }, [])

  const refresh = useCallback(async () => {
    const result = await fetchSources()
    if (result.ok) apply(result.data)
    else setError(result.data?.error || 'Pipeline API offline: sources cannot be read or changed.')
  }, [apply])

  useEffect(() => {
    let cancelled = false
    migrateLegacyDiscoveryOptions().then((moved) => {
      if (!cancelled && moved.migrated) setMessage('Joberty was switched on from the old Jobs-screen checkbox; the move is recorded as consent.')
      if (!cancelled) refresh()
    })
    return () => { cancelled = true }
  }, [refresh])

  const handleSave = async () => {
    const changes = changesFrom(draft, boards, consent)
    if (!changes) return
    setBusy(true)
    setMessage(null)
    const result = await saveSources(changes)
    setBusy(false)
    if (result.ok) {
      apply(result.data)
      setMessage('Sources saved. The next discovery run uses them.')
    } else {
      setError(result.data?.needsConsent ? `Tick "${CONSENT_LABEL}" first.` : result.data?.errors?.join('; ') || result.data?.error || 'Not saved.')
    }
  }

  return (
    <Card title="Job boards" description="Where discovery looks. Opt-in boards run only while switched on here; the others follow the standard run.">
      {boards === null && !error && <p className="text-sm text-stone-500"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" />Loading…</p>}
      {boards && (
        <JobBoardChips
          boards={boards}
          draft={draft}
          consent={consent}
          disabled={busy}
          onToggle={(name, on) => {
            setDraft((d) => ({ ...d, [name]: on }))
            if (!on) setConsent((c) => ({ ...c, [name]: false }))
          }}
          onConsent={(name, ok) => setConsent((c) => ({ ...c, [name]: ok }))}
        />
      )}
      <div className="mt-4 flex items-center gap-3">
        <Button onClick={handleSave} disabled={busy || !boards || !canSave(draft, boards, consent)}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          Save sources
        </Button>
        {message && <p className="text-xs text-teal-700 dark:text-teal-300">{message}</p>}
      </div>
      {error && <div className="mt-3"><Alert variant="error">{error}</Alert></div>}
    </Card>
  )
}
