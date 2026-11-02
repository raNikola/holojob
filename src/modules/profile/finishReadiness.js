import { profileFieldErrors, isNonEmpty } from '../../utils/validators.js'

const PROFILE_STEP = 2
const IMPORT_STEP = 1

// What Finish needs before onboarding can complete: the Profile-step required
// fields, then a résumé or parsed skills. No questionnaire answer is needed.
// When something is missing, `step` is where to send the user.
export function checkFinishReadiness(profile) {
  const fieldErrors = profileFieldErrors(profile?.basicProfile)
  if (Object.keys(fieldErrors).length) {
    return { ready: false, step: PROFILE_STEP, fieldErrors, errors: Object.values(fieldErrors) }
  }
  const resume = profile?.resume || {}
  const hasResume = isNonEmpty(resume.rawText) || (resume.parsedData?.skills?.length > 0)
  if (!hasResume) {
    return { ready: false, step: IMPORT_STEP, fieldErrors: {}, errors: ['A résumé or at least one skill is needed before you can finish. Upload or paste your history on this step, or choose Enter manually and add skills under Parsed resume data on the Profile step.'] }
  }
  return { ready: true, step: null, fieldErrors: {}, errors: [] }
}
