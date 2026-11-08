// Whether a string is shaped like a keyword or a skill, and not like prose.
// The ATS keyword bank holds skills and role names; a sentence or a paragraph of a CV cannot be matched against an ad.
// The same rule is in python/job_scoring/keyword_shape.py; tests/fixtures/keyword-shape.json is run by both.

export const MAX_KEYWORD_WORDS = 6
export const MAX_KEYWORD_CHARS = 48

// A comma, semicolon or colon anywhere, or a full stop / ! / ? that ends a word ("Node.js" and "C++" stay).
const PROSE_PUNCTUATION = /[,;:]|[.!?](\s|$)/
const BULLET_START = /^\s*([-*•●–—]|\d+[.)])\s/

export function isKeywordShaped(value) {
  if (typeof value !== 'string') return false
  const text = value.trim()
  if (!text || text.length > MAX_KEYWORD_CHARS || /[\r\n]/.test(text)) return false
  if (text.split(/\s+/).length > MAX_KEYWORD_WORDS) return false
  return !(PROSE_PUNCTUATION.test(text) || BULLET_START.test(text))
}
