import { useEffect, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import Alert from '../ui/Alert'
import Button from '../ui/Button'
import Textarea from '../ui/Textarea'
import { NO_DESCRIPTION, scoreStoredJob } from '../../modules/jobs/manualScoring'
import { patchJob } from '../../modules/jobs/jobsStore'
import { normalizeJobUrl } from '../../modules/jobs/manualJob'

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

  return (
    <div className="space-y-3">
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
