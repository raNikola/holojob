import { useState } from 'react'
import Alert from '../ui/Alert'
import Button from '../ui/Button'
import Textarea from '../ui/Textarea'
import { MIN_PASTE_CHARS, canPasteDescription, pasteDescription } from '../../modules/jobs/pasteDescription'

/** Paste the ad text for a discovered ad whose description is empty or thin. The text stays on this server; no AI is used. */
export default function PasteDescriptionBox({ job, apiAvailable = true }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  if (!canPasteDescription(job)) return null

  const save = async () => {
    setBusy(true)
    setMessage('')
    const result = await pasteDescription(job.jobId, text)
    if (result.ok) setText('')
    else setMessage(result.message)
    setBusy(false)
  }

  return (
    <Alert variant="info">
      <div className="space-y-2">
        <p>The ad text is missing or very short. Paste the full ad to score it. The text is kept on this server only and no AI is used.</p>
        <Textarea id={`job-paste-${job.jobId}`} label="Ad text" rows={6} value={text} onChange={(event) => setText(event.target.value)} placeholder="Paste the text of the ad" />
        {!apiAvailable && <p>The server cannot be reached right now.</p>}
        {message && <p role="alert">{message}</p>}
        <Button variant="secondary" disabled={busy || !apiAvailable || text.trim().length < MIN_PASTE_CHARS} onClick={save}>{busy ? 'Scoring…' : 'Save text and score'}</Button>
      </div>
    </Alert>
  )
}
