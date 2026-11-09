// How the app words the result of the fact gate. "Passed" means the defined automatic checks found nothing wrong; it is not a
// statement that every sentence is true, and the owner reads the document before sending it. The same limits are listed in
// python/resume_generator/provenance_checker.py (module docstring) and docs/DECISIONS.md.

export const CHECKS_PASSED = 'Passed the automatic checks'
export const CHECKS_FAILED = 'Did not pass the automatic checks'

export const COVERED = 'numbers, years of experience, names of employers, titles, schools, projects and technologies, degrees and certifications'

export const NOT_COVERED = [
  'a technology or skill that was invented but written in lowercase',
  'a true fact reworded into a false one that keeps the same words and numbers',
  'a number reused with another meaning when it also appears elsewhere in your CV',
  'tone and quality',
]

export const CHECK_LIMITS = `The automatic checks cover ${COVERED}. They do not prove every statement is true. Not checked: ${NOT_COVERED.join('; ')}. Read the document before you send it.`
