import { useState } from 'react'
import { Brain, Loader2, Pencil, Upload } from 'lucide-react'
import Card from '../ui/Card'
import { formatLanguages } from '../../utils/languages'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { useProfile } from '../../context/ProfileContext'
import { validateProfileForIntelligence } from '../../modules/intelligence/intelligenceValidators'
import { regenerateIntelligence, saveIntelligence } from '../../modules/intelligence/intelligenceExport'
import { saveIntelligenceToDataDir } from '../../modules/jobs/intelligenceSync'
import { clearIntelligenceStale } from '../../modules/profile/importDeps'
import { ProfileChangeNotices } from '../import/ImportResult'
import { VIEWS } from '../../modules/appNavigation'
import { QUESTIONS } from '../../data/questions'
import { describeAnswer } from '../../modules/profile/answerDisplay'
import CompleteProfileCard from './CompleteProfileCard'
import { answeredQuestionIds } from '../../modules/profile/questionnaireStatus'

// Wizard steps, as numbered in OnboardingWizard.
const RESUME_STEP = 1
const PROFILE_STEP = 2
const REPOS_STEP = 3
const QUESTIONNAIRE_STEP = 4

function Field({ label, value }) {
  if (!value || (Array.isArray(value) && value.length === 0)) return null
  return (
    <div className="py-2">
      <dt className="text-xs font-medium uppercase tracking-wide text-stone-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-stone-800 dark:text-stone-200">
        {Array.isArray(value) ? value.join(', ') : value}
      </dd>
    </div>
  )
}

export default function ProfileHome({ onNavigate }) {
  const { profile, startProfileEdit, dismissCompleteProfile } = useProfile()
  const { basicProfile: bp, resume, repositories, questionnaire } = profile
  const pd = resume.parsedData
  const [regenerating, setRegenerating] = useState(false)
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)

  const answeredCount = answeredQuestionIds(profile).length
  const validation = validateProfileForIntelligence(profile)

  const editStep = (step) => {
    startProfileEdit(step)
    onNavigate(VIEWS.PROFILE_EDIT)
  }

  const sectionEdit = (step, label) => (
    <Button variant="ghost" onClick={() => editStep(step)} aria-label={`Edit ${label}`}>
      <Pencil className="h-4 w-4" />
      Edit
    </Button>
  )

  const handleRegenerate = async () => {
    setError(null)
    setStatus(null)
    if (!validation.valid) {
      setError(validation.errors.join(' '))
      return
    }
    setRegenerating(true)
    try {
      const generated = regenerateIntelligence(profile)
      saveIntelligence(generated)
      void saveIntelligenceToDataDir(generated)
      clearIntelligenceStale()
      setStatus('Intelligence regenerated successfully.')
    } catch (e) {
      setError(e.message || 'Failed to regenerate intelligence.')
    } finally {
      setRegenerating(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
        <Button onClick={() => editStep(PROFILE_STEP)}>
          <Pencil className="h-4 w-4" />
          Edit Profile
        </Button>
        <Button variant="secondary" onClick={() => editStep(RESUME_STEP)}>
          <Upload className="h-4 w-4" />
          Re-upload Resume
        </Button>
        <Button variant="secondary" onClick={handleRegenerate} disabled={regenerating}>
          {regenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Brain className="h-4 w-4" />}
          Regenerate Intelligence
        </Button>
      </div>

      <ProfileChangeNotices />

      <CompleteProfileCard profile={profile} onAnswer={() => editStep(QUESTIONNAIRE_STEP)} onDismiss={dismissCompleteProfile} />

      {status && <p className="text-xs text-teal-700 dark:text-teal-300">{status}</p>}
      {error && <Alert variant="error" title="Error">{error}</Alert>}

      <Card title="Basic profile" action={sectionEdit(PROFILE_STEP, 'basic profile')}>
        <dl className="divide-y divide-stone-100 dark:divide-stone-800">
          <Field label="Full name" value={bp.fullName} />
          <Field label="Email" value={bp.email} />
          <Field label="Phone" value={bp.phone} />
          <Field label="Current role" value={bp.currentRole} />
          <Field label="Target roles" value={bp.targetRoles} />
          <Field label="Preferred locations" value={bp.preferredLocations} />
          <Field label="Languages" value={formatLanguages(bp.languages)} />
        </dl>
      </Card>

      <Card title="Resume" action={sectionEdit(RESUME_STEP, 'resume')}>
        <dl className="divide-y divide-stone-100 dark:divide-stone-800">
          <Field label="File" value={resume.fileName} />
          <Field label="Skills" value={pd.skills} />
        </dl>
      </Card>

      <Card title="Repositories" action={sectionEdit(REPOS_STEP, 'repositories')}>
        <dl className="divide-y divide-stone-100 dark:divide-stone-800">
          <Field label="GitHub links" value={repositories.githubLinks} />
          <Field label="Local repo paths" value={repositories.localRepoPaths} />
        </dl>
      </Card>

      <Card title="Questionnaire" action={sectionEdit(QUESTIONNAIRE_STEP, 'questionnaire')}>
        <p className="mb-3 text-sm text-stone-600 dark:text-stone-400">
          {answeredCount} of {QUESTIONS.length} questions answered
        </p>
        <div className="space-y-5">
          {(questionnaire.answers || []).map((a) => describeAnswer(a, profile)).filter(Boolean).map((d) => (
            <div key={d.id} className="border-b border-stone-100 pb-4 last:border-0 last:pb-0 dark:border-stone-800">
              <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">
                {d.label}
                {d.derived && <span className="ml-2 font-normal normal-case text-amber-700 dark:text-amber-300">pre-filled, not confirmed</span>}
              </p>
              {d.kind === 'chips' && (
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {d.items.map((item) => (
                    <li key={item} className="rounded-full bg-stone-100 px-2.5 py-1 text-xs text-stone-800 dark:bg-stone-800 dark:text-stone-200">{item}</li>
                  ))}
                </ul>
              )}
              {d.kind === 'bullets' && (
                <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm text-stone-800 marker:text-stone-400 dark:text-stone-200">
                  {d.items.map((item) => <li key={item}>{item}</li>)}
                </ul>
              )}
              {d.kind === 'prose' && (
                <p className="mt-2 max-w-prose whitespace-pre-line text-sm leading-relaxed text-stone-800 dark:text-stone-200">{d.text}</p>
              )}
              {d.kind === 'text' && (
                <p className="mt-1.5 text-sm text-stone-800 dark:text-stone-200">{d.text}</p>
              )}
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
