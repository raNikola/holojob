import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, Lock } from 'lucide-react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { changeStages, changeSwitches } from '../../modules/applications/applicationsClient'
import { activeStages, retiredStages } from '../../modules/applications/stageRegistry'
import { buildBoard } from '../../modules/applications/boardModel'
import { useApplications } from '../../hooks/useApplications'

const INPUT = 'min-w-0 flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50'

function FixedRow({ label }) {
  return (
    <li className="flex items-center gap-2 rounded-lg bg-stone-50 px-3 py-2 text-sm text-stone-600 dark:bg-stone-900 dark:text-stone-400">
      <Lock className="h-3.5 w-3.5" aria-hidden />
      <span className="flex-1">{label}</span>
      <span className="text-xs">fixed</span>
    </li>
  )
}

/** Settings > Applications: the tracking switch and the board columns (TRACKER_PLAN 1.6, 1.7). */
export default function ApplicationSettingsPanel() {
  const applications = useApplications()
  const [drafts, setDrafts] = useState({})
  const [newLabel, setNewLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [offerRestore, setOfferRestore] = useState(null)

  const { settings } = applications
  // counted from the cached store, so a move made on the board is already in it
  const counts = useMemo(() => {
    if (applications.status !== 'ready') return null
    const board = buildBoard(applications.store, settings, new Date().toISOString().slice(0, 10))
    return Object.fromEntries(board.columns.map((c) => [c.key, c.cards.length]))
  }, [applications.status, applications.store, settings])
  if (applications.status === 'error') {
    return <Card title="Applications"><Alert variant="error">The application tracker could not be loaded: {applications.error}</Alert></Card>
  }
  if (!settings) return <Card title="Applications"><p className="text-sm text-stone-500">Loading…</p></Card>

  const enabled = settings.trackingEnabled
  const active = activeStages(settings)
  const retired = retiredStages(settings)

  const run = async (call) => {
    setBusy(true)
    setError(null)
    setOfferRestore(null)
    try {
      await call()
      return true
    } catch (e) {
      setError(e.message)
      if (e.extra?.retiredKey) setOfferRestore(e.extra.retiredKey)
      return false
    } finally {
      setBusy(false)
    }
  }

  const rename = async (stage) => {
    const label = drafts[stage.key]
    if (label === undefined || label.trim() === stage.label) return
    if (await run(() => changeStages({ op: 'rename', key: stage.key, label }))) {
      setDrafts(({ [stage.key]: _done, ...rest }) => rest)
    }
  }

  const add = async () => {
    if (await run(() => changeStages({ op: 'add', label: newLabel }))) setNewLabel('')
  }

  return (
    <Card title="Applications">
      <div className="space-y-5">
        <label className="flex items-start gap-2 text-sm text-stone-700 dark:text-stone-300">
          <input
            type="checkbox"
            checked={enabled}
            disabled={busy}
            onChange={(e) => run(() => changeSwitches({ trackingEnabled: e.target.checked }))}
            className="mt-0.5 rounded border-stone-300 text-teal-600 focus:ring-teal-500"
          />
          <span>
            Application tracking
            <span className="block text-xs text-stone-500">Off hides the board and refuses new changes. Nothing is deleted; switching it on again shows everything as it was.</span>
          </span>
        </label>

        {error && <Alert variant="error">{error}</Alert>}
        {offerRestore && (
          <Button variant="secondary" disabled={busy} onClick={() => run(() => changeStages({ op: 'unretire', key: offerRestore }))}>
            Restore the retired column instead
          </Button>
        )}

        <div>
          <h3 className="mb-2 text-sm font-medium text-stone-800 dark:text-stone-200">Board columns</h3>
          {!enabled && <p className="mb-2 text-xs text-stone-500">Switch tracking on to change the columns.</p>}
          <ul className="space-y-2">
            <FixedRow label="Applied" />
            {active.map((stage, i) => {
              const count = counts?.[stage.key] ?? 0
              const draft = drafts[stage.key] ?? stage.label
              return (
                <li key={stage.key} className="flex flex-wrap items-center gap-2 rounded-lg border border-stone-200 px-3 py-2 dark:border-stone-700">
                  <input
                    aria-label={`Name of the ${stage.label} column`}
                    className={INPUT}
                    value={draft}
                    disabled={busy || !enabled}
                    onChange={(e) => setDrafts((d) => ({ ...d, [stage.key]: e.target.value }))}
                    onKeyDown={(e) => e.key === 'Enter' && rename(stage)}
                  />
                  <Button variant="secondary" className="!min-h-0 !px-3 !py-1.5" disabled={busy || !enabled || draft.trim() === stage.label} onClick={() => rename(stage)}>Rename</Button>
                  <Button variant="ghost" className="!min-h-0 !px-2 !py-1.5" aria-label={`Move ${stage.label} up`} disabled={busy || !enabled || i === 0} onClick={() => run(() => changeStages({ op: 'move', key: stage.key, dir: 'up' }))}><ArrowUp className="h-4 w-4" /></Button>
                  <Button variant="ghost" className="!min-h-0 !px-2 !py-1.5" aria-label={`Move ${stage.label} down`} disabled={busy || !enabled || i === active.length - 1} onClick={() => run(() => changeStages({ op: 'move', key: stage.key, dir: 'down' }))}><ArrowDown className="h-4 w-4" /></Button>
                  <span className="w-24 text-right text-xs text-stone-500">{count} open</span>
                  <Button variant="ghost" className="!min-h-0 !px-3 !py-1.5" disabled={busy || !enabled} onClick={() => run(() => changeStages({ op: 'retire', key: stage.key }))}>Remove</Button>
                </li>
              )
            })}
            <FixedRow label="Rejected" />
            <FixedRow label="Ghosted" />
          </ul>
          <p className="mt-2 text-xs text-stone-500">
            Remove hides a column; it never deletes data. Applications already in it must be moved out first, and the
            history keeps its name. A removed column can be restored below.
          </p>
          <div className="mt-3 flex gap-2">
            <input
              aria-label="New column name"
              className={INPUT}
              placeholder="New column name"
              value={newLabel}
              disabled={busy || !enabled}
              onChange={(e) => setNewLabel(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && newLabel.trim() && add()}
            />
            <Button variant="secondary" disabled={busy || !enabled || !newLabel.trim()} onClick={add}>Add column</Button>
          </div>
        </div>

        {retired.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-medium text-stone-800 dark:text-stone-200">Removed columns</h3>
            <ul className="space-y-1">
              {retired.map((stage) => (
                <li key={stage.key} className="flex items-center gap-2 text-sm text-stone-600 dark:text-stone-400">
                  <span className="flex-1">{stage.label}</span>
                  <Button variant="ghost" className="!min-h-0 !px-3 !py-1.5" disabled={busy || !enabled} onClick={() => run(() => changeStages({ op: 'unretire', key: stage.key }))}>Restore</Button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  )
}
