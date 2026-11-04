import { useRef, useState } from 'react'
import Button from '../ui/Button'
import { cancelRun } from '../../modules/activity/activityClient.js'
import { CANCEL_CONFIRM_TEXT, CANCEL_REQUESTED_TEXT, classifyCancel } from '../../modules/activity/liveView.js'

/**
 * Cancel a running Re-scrape: ask first, then POST /api/rescrape/cancel once. "Cancel requested" is only that: the run stops at its next
 * safe point, and nothing here says it has stopped. `requested` is the server's own flag (the request file exists); then the parent says so
 * and this shows nothing. `onAnswer({kind, message})` tells the parent what the server said (requested, settled, refused).
 */
export default function CancelRun({ runId, requested = false, fetchFn, onAnswer }) {
  const [step, setStep] = useState('idle') // idle | confirming | sending | requested | error
  const [problem, setProblem] = useState(null)
  const sending = useRef(false)

  async function send() {
    if (sending.current) return // a second click while the first is on its way sends nothing
    sending.current = true
    setStep('sending')
    try {
      const answer = classifyCancel(await cancelRun(runId, { fetchFn }))
      setStep(answer.kind === 'requested' ? 'requested' : 'idle')
      onAnswer?.(answer)
    } catch (error) {
      setProblem(error.message)
      setStep('error')
    } finally {
      sending.current = false
    }
  }

  if (requested) return null
  if (step === 'requested') return <p role="status" className="text-sm">{CANCEL_REQUESTED_TEXT}</p>
  if (step === 'confirming' || step === 'sending') {
    return (
      <div className="space-y-2" role="group" aria-label="Confirm cancel">
        <p className="text-sm">{CANCEL_CONFIRM_TEXT}</p>
        <div className="flex gap-2">
          <Button variant="danger" onClick={send} disabled={step === 'sending'}>{step === 'sending' ? 'Sending…' : 'Yes, cancel the run'}</Button>
          <Button variant="secondary" onClick={() => setStep('idle')} disabled={step === 'sending'}>Keep running</Button>
        </div>
      </div>
    )
  }
  return (
    <div className="space-y-2">
      {step === 'error' && <p role="alert" className="text-sm text-red-700 dark:text-red-300">The cancel request could not be sent ({problem}). Nothing changed. Try again.</p>}
      <Button variant="secondary" onClick={() => setStep('confirming')}>Cancel run</Button>
    </div>
  )
}
