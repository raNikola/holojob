const key = (s) => s.replace(/\s+/g, ' ').trim().toLowerCase()

/** Drop repeated " - " parts inside one segment: "Remote - Remote" -> "Remote". */
function dedupeParts(segment) {
  const seen = new Set()
  const parts = segment.split(/\s+-\s+/).filter((p) => {
    const k = key(p)
    if (!k || seen.has(k)) return false
    seen.add(k)
    return true
  })
  return parts.join(' - ')
}

/**
 * Display form of a job's location: segments split on "," or ";" that repeat (ignoring case and spacing) are
 * shown once, in their first spelling. Presentation only: sorting, filtering and Job Details use the raw string.
 */
export function displayLocation(raw) {
  if (typeof raw !== 'string') return ''
  const seen = new Set()
  const out = []
  for (const piece of raw.split(/[,;]/)) {
    const segment = dedupeParts(piece.trim())
    const k = key(segment)
    if (!k || seen.has(k)) continue
    seen.add(k)
    out.push(segment)
  }
  return out.join(', ')
}
