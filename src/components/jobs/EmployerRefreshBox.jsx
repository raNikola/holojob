import { useState } from 'react'
import Alert from '../ui/Alert'
import Button from '../ui/Button'
import Input from '../ui/Input'
import { acceptEmployerText, canRefreshFromEmployer, discardEmployerText, fetchEmployerText } from '../../modules/jobs/employerRefresh'

const MARK = { add: '+ ', del: '- ', same: '  ' }
const TONE = { add: 'text-green-700', del: 'text-red-700 line-through', same: '' }

/** Fetch the ad's text from the employer's own page and compare it with the scraped text. Nothing changes until Accept; the original is kept. */
export default function EmployerRefreshBox({ job, apiAvailable = true }) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [proposal, setProposal] = useState(null)
  if (!canRefreshFromEmployer(job)) return null

  const run = async (work) => {
    setBusy(true)
    setMessage('')
    await work()
    setBusy(false)
  }
  const fetchText = () =>
    run(async () => {
      const result = await fetchEmployerText(job.jobId, url.trim())
      if (result.ok) setProposal(result)
      else setMessage(result.message)
    })
  const accept = () =>
    run(async () => {
      const result = await acceptEmployerText(job.jobId)
      if (result.ok) setProposal(null)
      else setMessage(result.message)
    })
  const discard = () =>
    run(async () => {
      await discardEmployerText(job.jobId)
      setProposal(null)
    })

  return (
    <Alert variant="info">
      <div className="space-y-2">
        <p>Refresh the ad text from the employer&apos;s own page. You see the difference first; the scraped original is kept and no AI is used.</p>
        <Input id={`job-employer-url-${job.jobId}`} label="Employer page address" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://" />
        {!apiAvailable && <p>The server cannot be reached right now.</p>}
        {message && <p role="alert">{message}</p>}
        <Button variant="secondary" disabled={busy || !apiAvailable || !url.trim()} onClick={fetchText}>{busy && !proposal ? 'Fetching…' : 'Fetch and compare'}</Button>
        {proposal && (
          <div className="space-y-2">
            {proposal.against !== 'scraped' && (
              <p>The difference is against the text you {proposal.against === 'employer' ? 'accepted from the employer earlier' : 'pasted earlier'}, not the scraped text.</p>
            )}
            {proposal.replacesText && <p>Accepting replaces that text. It stays recoverable as the previous text (one level).</p>}
            {proposal.identical ? <p>The employer page has the same text as the saved ad.</p> : (
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap text-sm" aria-label="Difference">
                {proposal.diff.map((line, index) => <span key={index} className={`block ${TONE[line.op]}`}>{MARK[line.op]}{line.text}</span>)}
              </pre>
            )}
            {proposal.truncated && <p>Only the first part of the difference is shown. Accepting uses the whole text.</p>}
            <div className="flex gap-2">
              <Button disabled={busy || proposal.identical} onClick={accept}>{busy ? 'Scoring…' : 'Use the employer text and score'}</Button>
              <Button variant="secondary" disabled={busy} onClick={discard}>Discard</Button>
            </div>
          </div>
        )}
      </div>
    </Alert>
  )
}
