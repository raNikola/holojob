import { useState } from 'react'
import { Loader2, ShieldCheck } from 'lucide-react'
import Button from '../ui/Button'
import { acceptCoverLetter } from '../../modules/ai/coverLetterAccept'
import { CHECKS_PASSED, CHECK_LIMITS } from '../../modules/jobs/factCheckNote'

/**
 * The AI cover letter is a draft on the server. Nothing can attach it to an application until the server has checked it
 * against the profile; this button asks for that check and, on a pass, offers the document.
 */
export default function CoverLetterAccept({ jobId }) {
  const [state, setState] = useState({ status: 'draft' })

  const accept = async () => {
    setState({ status: 'checking' })
    const result = await acceptCoverLetter(jobId)
    setState(result.ok ? { status: 'accepted' } : { status: 'refused', message: result.message, issues: result.issues })
  }

  if (state.status === 'accepted') {
    return (
      <div className="space-y-1">
        <a
          data-testid="cover-letter-download"
          href={`/api/resumes/${jobId}/ai_cover_letter.md`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-teal-600"
        >
          <ShieldCheck className="h-3.5 w-3.5" />{CHECKS_PASSED}. Download ai_cover_letter.md
        </a>
        <p data-testid="cover-letter-limits" className="text-xs text-stone-500">{CHECK_LIMITS}</p>
      </div>
    )
  }
  return (
    <div className="space-y-1">
      <p className="text-xs text-stone-500">This is a draft. It becomes a document only after it passes the server's automatic checks. Passing is not a guarantee that every statement is true.</p>
      <Button variant="secondary" className="!text-xs" onClick={accept} disabled={state.status === 'checking'} data-testid="cover-letter-accept">
        {state.status === 'checking' ? <Loader2 className="h-3 w-3 animate-spin" /> : <ShieldCheck className="h-3 w-3" />}
        Run the automatic checks and save as document
      </Button>
      {state.status === 'refused' && (
        <div role="alert" data-testid="cover-letter-refused" className="text-xs text-red-600 dark:text-red-400">
          <p>{state.message}</p>
          <ul className="list-disc pl-4">{state.issues.slice(0, 8).map((i) => <li key={i}>{i}</li>)}</ul>
        </div>
      )}
    </div>
  )
}
