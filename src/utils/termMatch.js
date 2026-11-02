// Whole-term matching for skill names. A plain substring test finds "Go" inside
// "Google" and "Git" inside "Digitalni"; \b does not help for names that begin or
// end with a symbol ("C++", "C#", ".NET"). So the neighbours are checked instead:
//   - before the term: no letter, digit or underscore;
//   - after it: no letter, digit or underscore, and no "+" or "#" (so "C" is not
//     found in "C++" or "C#"), and no hyphen-then-letter (so "go-to-market" is
//     not "Go"; "React-based" is the cost of that rule).

const WORD = String.raw`\p{L}\p{N}_`
const cache = new Map()

function patternFor(term) {
  let re = cache.get(term)
  if (!re) {
    const escaped = term.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')
    re = new RegExp(String.raw`(?<![${WORD}])${escaped}(?![${WORD}+#]|-\p{L})`, 'u')
    cache.set(term, re)
  }
  return re
}

/** True when `term` occurs in `text` as a whole term, ignoring case. */
export function containsTerm(text, term) {
  const t = String(term ?? '').trim().toLowerCase()
  if (!t || !text) return false
  return patternFor(t).test(String(text).toLowerCase())
}
