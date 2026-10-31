export function isNonEmpty(value) {
  return typeof value === 'string' && value.trim().length > 0
}

export function isValidEmail(email) {
  if (!isNonEmpty(email)) return false
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())
}

export function isValidPhone(phone) {
  if (!isNonEmpty(phone)) return true
  const cleaned = phone.replace(/[\s().-]/g, '')
  return /^(\+91)?[6-9]\d{9}$/.test(cleaned) || /^\+?\d{10,15}$/.test(cleaned)
}

export function isValidUrl(url) {
  if (!isNonEmpty(url)) return false
  try {
    const parsed = new URL(url.trim())
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch { return false }
}

// The basic-profile fields the profile step requires. The form reads this list
// for its asterisks, so the marks and the validation cannot drift apart.
export const REQUIRED_PROFILE_FIELDS = ['fullName', 'email', 'currentRole', 'experienceYears', 'targetRoles']

// Per-field messages for the profile step, keyed by field. Phone is optional but must be well formed.
export function profileFieldErrors(basicProfile) {
  const { fullName, email, phone, currentRole, experienceYears, targetRoles } = basicProfile || {}
  const errors = {}
  if (!isNonEmpty(fullName)) errors.fullName = 'Full name is required.'
  if (!isValidEmail(email)) errors.email = 'A valid email address is required.'
  if (isNonEmpty(phone) && !isValidPhone(phone)) errors.phone = 'Phone number format is invalid.'
  if (!isNonEmpty(currentRole)) errors.currentRole = 'Current role is required.'
  if (experienceYears === undefined || experienceYears === null || String(experienceYears).trim() === '') {
    errors.experienceYears = 'Years of experience is required.'
  }
  if (!targetRoles?.length) errors.targetRoles = 'At least one target role is required.'
  return errors
}

export function validateStep(stepIndex, profile) {
  const errors = []
  switch (stepIndex) {
    case 0: break
    case 1:
      if (!isNonEmpty(profile.resume?.rawText) && !isNonEmpty(profile.basicProfile?.fullName)) {
        errors.push('Bring in your history first: upload a file, paste text, or choose "Enter manually".')
      }
      break
    case 2: {
      errors.push(...Object.values(profileFieldErrors(profile.basicProfile)))
      break
    }
    case 3:
      for (const link of profile.repositories?.githubLinks || []) {
        if (!isValidUrl(link)) errors.push('Invalid GitHub URL: ' + link)
      }
      break
    // The questionnaire is optional: an unanswered question is unknown, never an error.
    case 4: break
    case 5: break
  }
  return { valid: errors.length === 0, errors }
}
