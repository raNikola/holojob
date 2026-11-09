import { useState } from 'react'
import { Maximize2 } from 'lucide-react'
import Alert from '../ui/Alert'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import SettingsLink from '../settings/SettingsLink'
import { useApplications } from '../../hooks/useApplications'
import { useProfile } from '../../context/ProfileContext'
import { drawerTracking } from '../../modules/applications/trackingSummary'
import { describeError, markApplied, newApplicationDefaults } from '../../modules/applications/trackerController'
import { MISSING_JOB_HINT } from '../../modules/jobs/jobRoute'

const NOT_RECORDED = 'Not recorded'

function Field({ label, value, placeholder }) {
  return (
    <div>
      <dt className="text-xs text-stone-500">{label}</dt>
      <dd className={value ? 'text-stone-900 dark:text-stone-100' : 'text-stone-500 dark:text-stone-400'}>{value || placeholder}</dd>
    </div>
  )
}

function OpenFullDetails({ onOpen, canOpen }) {
  return (
    <span title={canOpen ? undefined : MISSING_JOB_HINT}>
      <Button variant="secondary" onClick={onOpen} disabled={!canOpen}><Maximize2 className="mr-1 inline h-4 w-4" />Open full details</Button>
    </span>
  )
}

/** One click records the application through the same call as the full form; the owner corrects date, CV and channel on Job Details. */
function MarkApplied({ job, cache, voidedOnly }) {
  const { profile } = useProfile()
  const [form, setForm] = useState(() => newApplicationDefaults(job, profile))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      await markApplied(job, cache, form)
      setForm(newApplicationDefaults(job, profile))
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-stone-600 dark:text-stone-400">
        No application recorded for this job.{voidedOnly ? ' An earlier entry was voided and stays in the history.' : ''}
      </p>
      {error && (
        <Alert variant="error">
          {describeError(error)}
          {error.extra?.conflictingId && ' Open full details to see it, or to record a separate attempt through another channel.'}
        </Alert>
      )}
      <Button variant="secondary" onClick={() => submit()} disabled={busy}>Mark Applied</Button>
    </div>
  )
}

/** The quick view's read-only tracking block. Every edit stays on the full Job Details page. */
export default function ApplicationTrackingSummary({ job, onOpenFull, canOpenFull }) {
  const cache = useApplications()
  const view = drawerTracking(job, cache)
  let body
  if (view.kind === 'loading') body = <p className="text-sm text-stone-600 dark:text-stone-400">Loading the application tracker…</p>
  else if (view.kind === 'error') body = <Alert variant="error">The application tracker could not be loaded: {view.message}</Alert>
  else if (view.kind === 'migrate-first') {
    body = (
      <Alert variant="info">
        This job still has tracking saved in the old format. Run the migration first (<SettingsLink section="application-migration">Settings → Application tracking migration</SettingsLink>).
      </Alert>
    )
  } else if (view.kind === 'none') body = <MarkApplied job={job} cache={cache} voidedOnly={view.voidedOnly} />
  else {
    const s = view.summary
    body = (
      <div className="space-y-3">
        <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
          <Field label="Applied on" value={s.appliedOn} placeholder={NOT_RECORDED} />
          <Field label="Next follow-up" value={s.followUp} placeholder="Not scheduled" />
          <Field label="CV used" value={s.cv} placeholder={NOT_RECORDED} />
          <Field label="Recruiter" value={s.recruiter} placeholder={NOT_RECORDED} />
          <Field label="History" value={`${s.eventCount} ${s.eventCount === 1 ? 'event' : 'events'}`} />
          <Field label="Notes" value={String(s.noteCount)} />
        </dl>
        <OpenFullDetails onOpen={onOpenFull} canOpen={canOpenFull} />
      </div>
    )
  }

  return (
    <div className="space-y-3 border-t border-stone-200 pt-4 dark:border-stone-800">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-stone-800 dark:text-stone-200">Application tracking</h3>
        {view.kind === 'summary' && <Badge>{view.summary.stage}</Badge>}
      </div>
      {body}
    </div>
  )
}
