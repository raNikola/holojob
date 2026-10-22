/**
 * The country part of a location: "Niš, Serbia" gives "Serbia". Empty for a
 * location with no comma, since "Niš" alone does not say.
 *
 * @param {string | null | undefined} location
 * @returns {string}
 */
export function countryOfLocation(location) {
  const parts = String(location || '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
  return parts.length > 1 ? parts[parts.length - 1] : ''
}

/**
 * The country to search jobs in, taken from the candidate and nowhere else:
 * the intelligence file's own country first, then the last part of the
 * profile location ("Niš, Serbia" gives "Serbia"). Empty when neither says,
 * and the caller then passes no country: discovery reports that it has none
 * instead of searching a market nobody chose.
 *
 * @param {{ basicProfile?: { location?: string } } | null | undefined} profile
 * @param {{ searchStrategy?: { country?: string }, jobFitPreferences?: { country?: string } } | null | undefined} intelligence
 * @returns {string}
 */
export function searchCountry(profile, intelligence) {
  const fromIntelligence = intelligence?.searchStrategy?.country || intelligence?.jobFitPreferences?.country
  if (fromIntelligence) return fromIntelligence

  return countryOfLocation(profile?.basicProfile?.location)
}
