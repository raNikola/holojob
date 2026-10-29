import { useMemo, useState } from 'react'
import Alert from '../ui/Alert'
import { moveApplication } from '../../modules/applications/applicationsClient'
import { boardFootnote, buildBoard, dropDecision, moveChoices } from '../../modules/applications/boardModel'
import { useApplications } from '../../hooks/useApplications'
import SettingsLink from '../settings/SettingsLink'

const today = () => new Date().toISOString().slice(0, 10)

function Card({ card, settings, busy, error, onOpen, onMove, onDragStart, onDragEnd }) {
  return (
    <li
      draggable={!busy}
      aria-busy={busy || undefined}
      onDragStart={(e) => onDragStart(e, card)}
      onDragEnd={onDragEnd}
      className={`rounded-lg border border-stone-200 bg-white p-3 text-sm shadow-sm dark:border-stone-700 dark:bg-stone-900 ${busy ? 'opacity-60' : 'cursor-grab'}`}
    >
      <button type="button" onClick={() => onOpen(card)} className="block w-full text-left">
        <span className="block font-medium text-stone-900 dark:text-stone-100">{card.company || '—'}</span>
        <span className="block text-stone-600 dark:text-stone-400">{card.title || '—'}</span>
      </button>
      <p className={`mt-1 text-xs ${card.stale ? 'text-amber-700 dark:text-amber-300' : 'text-stone-500'}`}>
        {card.days === null ? 'Days in stage unknown (no date recorded)' : `${card.days} day${card.days === 1 ? '' : 's'} in stage`}
        {card.stale && ' · stale'}
      </p>
      <select
        aria-label={`Move ${card.company || 'application'} to`}
        value=""
        disabled={busy}
        onChange={(e) => e.target.value && onMove(card, e.target.value)}
        className="mt-2 w-full rounded-md border border-stone-300 px-2 py-1.5 text-xs dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50"
      >
        <option value="">{busy ? 'Moving…' : 'Move to…'}</option>
        {moveChoices(settings, card.column).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {error && <p role="alert" className="mt-1 text-xs text-red-700 dark:text-red-300">{error}</p>}
    </li>
  )
}

/** The Kanban board: columns from the stage registry, cards from the application store. */
export default function ApplicationBoard({ onOpenJob }) {
  const applications = useApplications()
  const [busy, setBusy] = useState({})
  const [errors, setErrors] = useState({})
  const [notice, setNotice] = useState(null)
  const [dragging, setDragging] = useState(null)
  const [overColumn, setOverColumn] = useState(null)

  const board = useMemo(
    () => (applications.status === 'ready' ? buildBoard(applications.store, applications.settings, today()) : null),
    [applications.status, applications.store, applications.settings],
  )

  if (applications.status === 'error') return <Alert variant="error" title="The application tracker could not be loaded">{applications.error}</Alert>
  if (!board) return <p className="text-sm text-stone-500">Loading the application tracker…</p>
  if (applications.settings.trackingEnabled === false) {
    return <Alert variant="info" title="Application tracking is off">Switch it on in <SettingsLink section="application-tracking">Settings → Applications</SettingsLink>. Nothing was deleted.</Alert>
  }

  const handleMove = async (card, toStage) => {
    setBusy((b) => ({ ...b, [card.appId]: true }))
    setErrors((e) => ({ ...e, [card.appId]: null }))
    try {
      await moveApplication(card.appId, { toStage })
    } catch (e) {
      // the cache is untouched on failure, so the card stays where it was
      setErrors((prev) => ({ ...prev, [card.appId]: e.message }))
    } finally {
      setBusy((b) => ({ ...b, [card.appId]: false }))
    }
  }

  const trackingOn = applications.settings.trackingEnabled !== false
  const decide = (column) => dragging && dropDecision(applications.settings, dragging, column.key, { busy: Boolean(busy[dragging.appId]), trackingEnabled: trackingOn })

  const handleDragStart = (e, card) => {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', card.appId)
    setDragging(card)
  }

  const endDrag = () => {
    setDragging(null)
    setOverColumn(null)
  }

  const handleDrop = (e, column) => {
    e.preventDefault()
    const decision = decide(column)
    const card = dragging
    endDrag()
    if (decision?.action === 'move') handleMove(card, decision.toStage)
  }

  const handleOpen = (card) => {
    const opened = card.jobId ? onOpenJob(card.jobId) : false
    setNotice(opened ? null : `"${card.company || card.title}" is no longer in the Jobs list, so its details cannot be opened yet.`)
  }

  const footnote = boardFootnote(board)
  return (
    <div className="space-y-3">
      {board.total === 0 && <p className="text-sm text-stone-600 dark:text-stone-400">No applications in the tracker yet. Open a job and use Mark applied.</p>}
      {notice && <Alert variant="info">{notice}</Alert>}
      <div className="flex gap-3 overflow-x-auto pb-2">
        {board.columns.map((column) => (
          <section
            key={column.key}
            aria-label={column.label}
            onDragOver={(e) => {
              if (decide(column)?.action !== 'move') return
              e.preventDefault()
              e.dataTransfer.dropEffect = 'move'
              if (overColumn !== column.key) setOverColumn(column.key)
            }}
            onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget) && overColumn === column.key) setOverColumn(null) }}
            onDrop={(e) => handleDrop(e, column)}
            className={`min-w-[16rem] flex-1 rounded-xl border p-3 ${overColumn === column.key
              ? 'border-teal-500 bg-teal-50 ring-2 ring-teal-300 dark:border-teal-500 dark:bg-teal-950/30 dark:ring-teal-700'
              : 'border-stone-200 bg-stone-50 dark:border-stone-800 dark:bg-stone-950/40'}`}
          >
            <h3 className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-stone-600 dark:text-stone-400">
              {column.label}
              <span className="rounded-full bg-stone-200 px-2 py-0.5 text-stone-700 dark:bg-stone-800 dark:text-stone-300">{column.cards.length}</span>
            </h3>
            <ul className="space-y-2">
              {column.cards.map((card) => (
                <Card key={card.appId} card={card} settings={applications.settings} busy={Boolean(busy[card.appId])} error={errors[card.appId]} onOpen={handleOpen} onMove={handleMove} onDragStart={handleDragStart} onDragEnd={endDrag} />
              ))}
            </ul>
          </section>
        ))}
      </div>
      {footnote && <p className="text-xs text-stone-500">{footnote}</p>}
    </div>
  )
}
