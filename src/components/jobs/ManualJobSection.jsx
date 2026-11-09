import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ExternalLink, Pencil, Trash2 } from 'lucide-react'
import Alert from '../ui/Alert'
import Button from '../ui/Button'
import Textarea from '../ui/Textarea'
import AddJobDialog from './AddJobDialog'
import { NO_DESCRIPTION, deleteConfirmMessage, deleteManualJob, scoreStoredJob } from '../../modules/jobs/manualScoring'
import { patchJob } from '../../modules/jobs/jobsStore'
import { normalizeJobUrl } from '../../modules/jobs/manualJob'
import { OPEN_TRACKER_EVENT } from '../../modules/appNavigation'

/**
 * The extra links and the owner's notes of a hand-entered job. Both stay in this browser's job record: no AI
 * context, request or file carries them. Notes save when the field loses focus.
 */
export default function ManualJobSection({ job, onJobUpdated, apiAvailable = true }) {
  const links = (job.extraLinks || []).filter((link) => normalizeJobUrl(link.url))
  const [notes, setNotes] = useState(job.notes || '')
  useEffect(() => { setNotes(job.notes || '') }, [job.notes])
  const [scoring, setScoring] = useState(false)
  const [scoreMessage, setScoreMessage] = useState('')
  const [pasted, setPasted] = useState('')
  const [editing, setEditing] = useState(false)
  const [editMessage, setEditMessage] = useState('')
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteRefusal, setDeleteRefusal] = useState(null)

  const sourceUrl = normalizeJobUrl(job.sourceUrl) ? job.sourceUrl : ''
  if (!job.manualEntry && !links.length && !job.notes && !sourceUrl) return null

  const saveNotes = () => {
    if (notes !== (job.notes || '')) onJobUpdated?.({ ...job, notes })
  }

  const unscored = job.manualEntry && typeof job.matchScore !== 'number'
  const noText = job.manualEntry && !String(job.description ?? '').trim()
  const scoreNow = async () => {
    setScoring(true)
    setScoreMessage('')
    // The pasted ad text is saved on the job first; scoring needs it.
    if (noText && pasted.trim()) patchJob(job.jobId, { description: pasted.trim() })
    const result = await scoreStoredJob(job.jobId)
    if (!result.ok) setScoreMessage(result.message)
    setScoring(false)
  }

  const confirmDelete = async () => {
    setDeleting(true)
    const result = await deleteManualJob(job.jobId)
    setDeleting(false)
    setConfirmingDelete(false)
    // On success the job leaves the stored list and this view unmounts with it.
    if (!result.ok) setDeleteRefusal(result)
  }

  return (
    <div className="space-y-3">
      {job.manualEntry && (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" onClick={() => { setEditMessage(''); setEditing(true) }}><Pencil className="mr-1 inline h-4 w-4" />Edit</Button>
          <Button variant="secondary" onClick={() => { setDeleteRefusal(null); setConfirmingDelete(true) }}><Trash2 className="mr-1 inline h-4 w-4" />Delete job</Button>
          {editMessage && <p role="status" className="text-sm text-stone-700 dark:text-stone-300">{editMessage}</p>}
        </div>
      )}
      {job.manualEntry && confirmingDelete && (
        <Alert variant="info">
          <div className="space-y-2" role="alertdialog" aria-label="Confirm delete">
            <p>{deleteConfirmMessage(job)}</p>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={deleting} onClick={confirmDelete}>{deleting ? 'Deleting…' : 'Delete this job'}</Button>
              <Button variant="secondary" disabled={deleting} onClick={() => setConfirmingDelete(false)}>Cancel</Button>
            </div>
          </div>
        </Alert>
      )}
      {deleteRefusal && (
        <Alert variant="error">
          <div className="space-y-2" role="alert">
            <p>{deleteRefusal.message}</p>
            {deleteRefusal.reason === 'has_application' && (
              <div className="space-y-1">
                <p>To stop tracking it, void the application on this job&apos;s page; the job itself stays.</p>
                <Button variant="secondary" onClick={() => window.dispatchEvent(new CustomEvent(OPEN_TRACKER_EVENT))}>Open in Tracker</Button>
              </div>
            )}
          </div>
        </Alert>
      )}
      {editing && createPortal(
        <AddJobDialog
          job={job}
          apiAvailable={apiAvailable}
          onClose={() => setEditing(false)}
          onSaved={(_saved, _open, result) => { setEditing(false); setEditMessage(result.message || '') }}
        />,
        document.body,
      )}
      {unscored && (
        <Alert variant="info">
          <div className="space-y-2">
            {noText ? <p>{NO_DESCRIPTION}</p> : <p>This job is not scored yet. Scoring runs on this server with the local rules only; no AI is used.</p>}
            {noText && (
              <Textarea id={`job-ad-text-${job.jobId}`} label="Ad text" rows={6} value={pasted} onChange={(event) => setPasted(event.target.value)} placeholder="Paste the text of the ad" />
            )}
            {!apiAvailable && <p>The server cannot be reached right now.</p>}
            {scoreMessage && <p role="alert">{scoreMessage}</p>}
            <Button variant="secondary" disabled={scoring || (noText && !pasted.trim())} onClick={scoreNow}>{scoring ? 'Scoring…' : noText ? 'Save text and score' : scoreMessage ? 'Try again' : 'Score now'}</Button>
          </div>
        </Alert>
      )}
      {(sourceUrl || job.sourceChoice) && (
        <p className="text-sm text-stone-700 dark:text-stone-300">
          <span className="text-xs text-stone-500">Source: </span>
          {sourceUrl && (
            <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-teal-600">
              {sourceUrl} <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
          {!sourceUrl && job.sourceChoice}
        </p>
      )}
      {links.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-stone-500">Extra links</h4>
          <ul className="space-y-1 text-sm">
            {links.map((link) => (
              <li key={link.url}>
                <a href={link.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-teal-600">
                  {link.label || link.url} <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
      <Textarea
        id={`job-notes-${job.jobId}`}
        label="Notes (only for you, never sent to AI)"
        rows={3}
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
        onBlur={saveNotes}
      />
    </div>
  )
}
