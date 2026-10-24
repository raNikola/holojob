// A list answer (skills, projects, themes) is stored as one string. Entries are
// ended by a newline, not a comma: a project sentence contains commas, and
// splitting on them cut the sentence into pieces that no longer matched their
// chip, so each click on it added another copy. A string with no newline is an
// answer saved before this and is read as comma-separated. The newline ends the
// last entry too, so a single entry that holds commas is still told apart.

export const ANSWER_SEPARATOR = '\n'

function unique(items) {
  const seen = new Set()
  return items.filter((item) => {
    const key = item.toLowerCase()
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function parseAnswerList(answer) {
  if (!answer || typeof answer !== 'string') return []
  const sep = answer.includes(ANSWER_SEPARATOR) ? ANSWER_SEPARATOR : ','
  return unique(answer.split(sep).map((s) => s.trim()).filter(Boolean))
}

export function joinAnswerList(values) {
  return unique((values || []).map((s) => (s || '').trim()).filter(Boolean)).map((s) => s + ANSWER_SEPARATOR).join('')
}

// "3,000" cut at its comma leaves "000 websites": a piece that starts with a
// digit and sits inside a known entry is the tail of that entry, not an answer.
function isSplitNumberTail(piece, known) {
  return /^\d/.test(piece) && known.some((entry) => entry.includes(piece) && entry !== piece)
}

/**
 * Read an answer saved with commas between entries when some entries are
 * sentences that hold commas. `knownEntries` (the résumé's project sentences)
 * are lifted out whole; what is left is split on commas. Repeats are dropped.
 * Returns the entries in the order they first appear.
 */
export function repairCommaAnswer(answer, knownEntries = []) {
  if (!answer || typeof answer !== 'string') return []
  if (answer.includes(ANSWER_SEPARATOR)) return parseAnswerList(answer)
  const known = [...knownEntries].filter(Boolean).sort((a, b) => b.length - a.length)
  const marked = known.reduce((text, entry, i) => text.split(entry).join(`,\uE000${i}\uE000,`), answer)
  const entries = marked.split(',').map((s) => s.trim()).filter(Boolean).filter((piece) => !isSplitNumberTail(piece, known)).map((piece) => {
    const m = /^\uE000(\d+)\uE000$/.exec(piece)
    return m ? known[Number(m[1])] : piece
  })
  return unique(entries)
}
