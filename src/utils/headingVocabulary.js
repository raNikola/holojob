import vocabulary from '../data/sectionHeadings.json'

// Reads the heading and label vocabulary in src/data/sectionHeadings.json. A new
// language is a new block in that file; nothing here names a language. The
// Python import parser reads the same file (python/profile_import/vocabulary.py).

const CYRILLIC = vocabulary.transliteration.cyrillicToLatin
const EXTRA = vocabulary.transliteration.extra
const LANGUAGES = Object.values(vocabulary.languages)

/** Lower case, Cyrillic to Latin, diacritics removed: "ВЕШТИНЕ", "Veštine" and "vestine" all become "vestine". */
export function foldText(text) {
  let out = ''
  for (const ch of String(text ?? '').toLowerCase()) out += CYRILLIC[ch] ?? EXTRA[ch] ?? ch
  return out.normalize('NFD').replace(/\p{M}/gu, '')
}

const CONJUNCTIONS = new Set(LANGUAGES.flatMap((l) => l.conjunctions.map(foldText)))

/** The comparison form of a heading or label: folded, brackets and punctuation gone, "&" / "i" / "and" alike. */
export function normalizePhrase(text) {
  const words = foldText(text)
    .replace(/\([^)]*\)/g, ' ')
    .replace(/&/g, ' and ')
    .replace(/[^a-z\- ]/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => (CONJUNCTIONS.has(w) ? 'and' : w))
  return words.join(' ')
}

function indexOf(listOf) {
  const index = new Map()
  for (const lang of LANGUAGES) {
    for (const [key, phrases] of listOf(lang)) for (const phrase of phrases) index.set(normalizePhrase(phrase), key)
  }
  return index
}

const SECTION_OF = indexOf((l) => Object.entries(l.sections))
const UNPLACED = indexOf((l) => [['unplaced', l.unplacedSections]])
const LABEL_OF = indexOf((l) => Object.entries(l.fieldLabels))
const LEVEL_OF = indexOf((l) => Object.entries(l.languageLevels))
const HEADING_MAX_CHARS = 60

/**
 * The section a line opens, or null. `key` is a vocabulary section ("experience",
 * "personal", ...) or "unplaced" for a heading the app does not keep (hobbies, ...).
 * The whole line, or the part before a colon, must be the heading; brackets are
 * ignored, so "Experience (2019-2024)" and "Education:" both count.
 */
export function headingOf(line) {
  const trimmed = String(line ?? '').trim()
  if (!trimmed || trimmed.length > HEADING_MAX_CHARS) return null
  const head = trimmed.split(':')[0]
  for (const candidate of head === trimmed ? [trimmed] : [head, trimmed]) {
    const phrase = normalizePhrase(candidate)
    if (!phrase) continue
    if (SECTION_OF.has(phrase)) return { key: SECTION_OF.get(phrase) }
    if (UNPLACED.has(phrase)) return { key: 'unplaced' }
  }
  return null
}

/** { field, value } for a "Label: value" line whose label the vocabulary knows ("Ime i prezime: X"), else null. */
export function labeledField(line) {
  const match = String(line ?? '').trim().match(/^([^:]{2,40}):\s*(.*)$/)
  if (!match) return null
  const field = LABEL_OF.get(normalizePhrase(match[1]))
  return field ? { field, value: match[2].trim() } : null
}

/** The proficiency ("native" ... "basic") a level word names in any language, or "". */
export function languageLevel(word) {
  return LEVEL_OF.get(normalizePhrase(word)) ?? ''
}

export const SECTION_KEYS = [...new Set(LANGUAGES.flatMap((l) => Object.keys(l.sections)))]
