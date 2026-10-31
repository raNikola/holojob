import { useEffect, useState } from 'react'
import { Moon, Sun, ChevronLeft, ChevronRight } from 'lucide-react'
import ProgressBar from './ProgressBar'
import StepLayout from './StepLayout'
import WelcomeStep from './WelcomeStep'
import ImportWizard from '../import/ImportWizard'
import ProfileForm from '../profile/ProfileForm'
import RepositoryForm from '../repositories/RepositoryForm'
import QuestionnaireForm from '../questionnaire/QuestionnaireForm'
import ReviewScreen from '../review/ReviewScreen'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import { useProfile } from '../../context/ProfileContext'
import { QUESTION_COUNT } from '../../data/questions'
import { answeredQuestionIds, orderedQuestions } from '../../modules/profile/questionnaireStatus'
import { validateStep } from '../../utils/validators'
import { profileChangedSince, takeProfileSnapshot } from '../../utils/profileSnapshot'
import { saveProfileToDataDir } from '../../modules/jobs/profileSync'
import { deleteCvFile } from '../../modules/cvs/cvApi'
import { cvFilesToDiscard } from '../../utils/cvLibrary'

const STEP_CONFIG = [
  { title: 'Welcome', description: '' },
  { title: 'Bring in your history', description: 'Import a resume or LinkedIn data, review what was found, then save it.' },
  { title: 'Your profile', description: 'Review and edit autofilled details from your resume.' },
  { title: 'Repositories', description: 'Add GitHub links and local project folder paths.' },
  { title: 'Questionnaire', description: `Optional: answer what you like to improve your matches. Skip any question.` },
  { title: 'Review & export', description: 'Review everything and export your candidate-profile.json.' },
]

const ORDERED_QUESTIONS = orderedQuestions()
const QUESTIONNAIRE_STEP = 4
const TOTAL_STEPS = STEP_CONFIG.length
const EDIT_START_STEP = 1

export default function OnboardingWizard({ mode = 'onboarding', onComplete }) {
  const isEdit = mode === 'edit'
  const { currentStep, setStep, profile, restoreProfile } = useProfile()
  // The profile as it was when this edit began, for Cancel. Nothing is kept in onboarding.
  const [snapshot] = useState(() => (mode === 'edit' ? takeProfileSnapshot(profile) : null))
  const [errors, setErrors] = useState([])
  // Counts failed Continue presses, so the form shows field errors and focus moves to the first one.
  const [failed, setFailed] = useState({ key: null, count: 0 })
  const [importBusy, setImportBusy] = useState(false)
  const [questionnaireIndex, setQuestionnaireIndex] = useState(0)
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))

  const minStep = isEdit ? EDIT_START_STEP : 0
  const stepKey = `${currentStep}:${questionnaireIndex}`
  const showFieldErrors = failed.key === stepKey

  const fail = (errs) => {
    setErrors(errs)
    setFailed((f) => ({ key: stepKey, count: f.count + 1 }))
  }
  const clearFailed = () => setFailed((f) => ({ ...f, key: null }))

  // After a failed Continue, focus the first field the form marked invalid.
  useEffect(() => {
    if (!failed.key) return
    const first = document.querySelector('[aria-invalid="true"], [data-invalid="true"]')
    if (first) {
      first.focus()
      first.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
    }
  }, [failed.count]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (isEdit && currentStep < EDIT_START_STEP) {
      setStep(EDIT_START_STEP)
    }
  }, [isEdit, currentStep, setStep])

  const toggleDark = () => {
    document.documentElement.classList.toggle('dark')
    setDark(!dark)
  }

  const scrollToTop = () => window.scrollTo({ top: 0, behavior: 'smooth' })

  const goNext = () => {
    if (currentStep === QUESTIONNAIRE_STEP) {
      if (questionnaireIndex < QUESTION_COUNT - 1) {
        setErrors([])
        clearFailed()
        setQuestionnaireIndex(questionnaireIndex + 1)
        scrollToTop()
        return
      }
      setErrors([])
      clearFailed()
      setStep(currentStep + 1)
      scrollToTop()
      return
    }

    const { valid, errors: errs } = validateStep(currentStep, profile)
    if (!valid) { fail(errs); return }
    setErrors([])
    clearFailed()
    if (currentStep < TOTAL_STEPS - 1) setStep(currentStep + 1)
  }

  const goBack = () => {
    if (currentStep === QUESTIONNAIRE_STEP && questionnaireIndex > 0) {
      setErrors([])
      clearFailed()
      setQuestionnaireIndex(questionnaireIndex - 1)
      scrollToTop()
      return
    }

    setErrors([])
    clearFailed()
    if (currentStep > minStep) {
      if (currentStep === QUESTIONNAIRE_STEP) setQuestionnaireIndex(0)
      setStep(currentStep - 1)
    }
  }

  const cancelEdit = () => {
    if (snapshot) {
      const changed = profileChangedSince(snapshot, profile)
      // A CV uploaded in this session has its PDF stored already; the restore
      // drops its entry, so the file would be left behind with no owner.
      const orphans = cvFilesToDiscard(snapshot, profile)
      restoreProfile(snapshot)
      for (const id of orphans) deleteCvFile(id).catch(() => {})
      // Some steps mirror the profile to disk as they go; put that copy back too.
      if (changed) void saveProfileToDataDir(snapshot)
    }
    onComplete?.()
  }

  const jumpToStep = (step) => {
    setErrors([])
    clearFailed()
    setStep(step)
    scrollToTop()
  }

  const jumpToQuestion = (index) => {
    setErrors([])
    clearFailed()
    setQuestionnaireIndex(index)
    scrollToTop()
  }

  const renderStep = () => {
    switch (currentStep) {
      case 0: return <WelcomeStep onNext={goNext} onDemoComplete={onComplete} />
      case 1: return <ImportWizard onBusyChange={setImportBusy} onManual={() => jumpToStep(2)} onSaved={() => jumpToStep(2)} />
      case 2: return <ProfileForm showErrors={showFieldErrors} />
      case 3: return <RepositoryForm />
      case 4: return <QuestionnaireForm
        questionIndex={questionnaireIndex}
        onJumpToQuestion={isEdit ? jumpToQuestion : undefined}
      />
      case 5: return (
        <ReviewScreen
          mode={mode}
          onEditStep={(step) => { setStep(step); scrollToTop() }}
          onComplete={onComplete}
        />
      )
      default: return null
    }
  }

  const config = STEP_CONFIG[currentStep]
  // An unanswered question is skipped, not blocked.
  const skipsQuestion = currentStep === QUESTIONNAIRE_STEP
    && !answeredQuestionIds(profile).includes(ORDERED_QUESTIONS[questionnaireIndex]?.id)
  const showNavFooter = currentStep < TOTAL_STEPS - 1
    && (isEdit ? currentStep >= EDIT_START_STEP : currentStep > 0)

  const questionnaireDescription =
    currentStep === QUESTIONNAIRE_STEP
      ? `Question ${questionnaireIndex + 1} of ${QUESTION_COUNT} — ${ORDERED_QUESTIONS[questionnaireIndex]?.text.slice(0, 60)}…`
      : config.description

  const headerTitle = isEdit ? 'Edit Profile' : 'Profile Setup'

  return (
    <div className={isEdit ? '' : 'min-h-screen'}>
      {!isEdit && (
        <header className="border-b border-stone-200 bg-white/80 backdrop-blur dark:border-stone-800 dark:bg-stone-950/80">
          <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-4 sm:px-6">
            <span className="font-display text-sm font-semibold text-stone-800 dark:text-stone-200">{headerTitle}</span>
            <button type="button" onClick={toggleDark} className="rounded-lg p-2 text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800" aria-label="Toggle dark mode">
              {dark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </button>
          </div>
        </header>
      )}

      <main className={isEdit ? '' : 'mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-12'}>
        {(isEdit || currentStep > minStep) && <ProgressBar currentStep={currentStep} editMode={isEdit} onStepClick={isEdit ? jumpToStep : undefined} />}

        {currentStep > minStep || (isEdit && currentStep >= EDIT_START_STEP) ? (
          <StepLayout title={config.title} description={questionnaireDescription}>
            {errors.length > 0 && (
              <div className="mb-4">
                <Alert variant="error" title="Please fix the following">
                  <ul className="list-inside list-disc text-sm">
                    {errors.map((e) => <li key={e}>{e}</li>)}
                  </ul>
                </Alert>
              </div>
            )}
            {renderStep()}
          </StepLayout>
        ) : renderStep()}

        {showNavFooter && (
          <div className="sticky bottom-0 mt-8 flex items-center justify-between gap-4 border-t border-stone-200 bg-[var(--color-surface)] py-4 dark:border-stone-800">
            <Button variant="secondary" onClick={goBack} disabled={currentStep <= minStep}>
              <ChevronLeft className="h-4 w-4" /> Back
            </Button>
            <div className="flex items-center gap-2">
              {isEdit && (
                <>
                  <Button variant="ghost" onClick={cancelEdit}>
                    Cancel
                  </Button>
                  <Button variant="secondary" onClick={() => onComplete?.()}>
                    Done
                  </Button>
                </>
              )}
              <Button onClick={goNext} disabled={importBusy && currentStep === 1}>
                {skipsQuestion ? 'Skip' : 'Continue'} <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
