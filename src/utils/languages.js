/**
 * Spoken languages on the profile: basicProfile.languages, a list of
 * { language, proficiency } entries.
 *
 * Imports nothing, and is imported with an explicit extension where plain Node
 * has to resolve it (scripts/regenerate-intelligence.js).
 */

/**
 * The profile values. JSON Resume's schema leaves `fluency` as free text
 * ("Fluent", "Beginner"), so these are ours; the Python exporter maps each to
 * a JSON Resume wording (python/resume_generator/profile_languages.py).
 * Keep the two lists in step.
 */
export const LANGUAGE_PROFICIENCIES = ['native', 'fluent', 'advanced', 'intermediate', 'basic']

/**
 * Clean a stored value into a list of entries. A missing or malformed value
 * becomes an empty list, so profiles saved before this field existed still
 * load. An unknown proficiency is left unstated, never guessed.
 *
 * @param {unknown} value
 * @returns {{ language: string, proficiency: string }[]}
 */
export function normalizeLanguages(value) {
  if (!Array.isArray(value)) return []
  return value
    .map((entry) => ({
      language: typeof entry?.language === 'string' ? entry.language.trim() : '',
      proficiency: LANGUAGE_PROFICIENCIES.includes(entry?.proficiency) ? entry.proficiency : '',
    }))
    .filter((entry) => entry.language)
}

/**
 * The strings the fit judge and the CV read: "Serbian (native)". An entry with
 * no proficiency is just the language name.
 *
 * @param {unknown} value
 * @returns {string[]}
 */
export function formatLanguages(value) {
  return normalizeLanguages(value).map((entry) =>
    entry.proficiency ? `${entry.language} (${entry.proficiency})` : entry.language,
  )
}
