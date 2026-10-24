/**
 * Job ads arrive as light markdown (LinkedIn, Greenhouse) or as HTML. This turns one
 * into blocks the drawer can render as elements: paragraphs, headings, lists and
 * bold runs. It does not cover markdown in general, only that pattern, and it never
 * produces HTML, so nothing in an ad can inject markup.
 *
 * block:  { type: 'p' | 'h' | 'ul' | 'ol', ... }  with inline runs [{ text, bold }]
 */

const ENTITIES = { '&lt;': '<', '&gt;': '>', '&amp;': '&', '&#39;': "'", '&quot;': '"', '&nbsp;': ' ' }

/** Plain text with line structure kept: tags that end a line become newlines, the rest go. */
export function toPlainLines(raw) {
  // Entities first: Greenhouse sends its HTML escaped (&lt;p&gt;), which must become tags before they are read.
  return String(raw || '')
    .replace(/&(lt|gt|amp|quot|nbsp|#39);/g, (m) => ENTITIES[m])
    .replace(/<\s*br\s*\/?>/gi, '\n')
    .replace(/<\s*li[^>]*>/gi, '\n* ')
    .replace(/<\/\s*(p|div|h[1-6]|ul|ol|li)\s*>/gi, '\n\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\r\n?/g, '\n')
    .replace(/[ \t]+/g, ' ')
    .replace(/ ?\n ?/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/** **bold** runs; a marker left unmatched (a cut-off ad) is dropped rather than shown. */
export function inlineRuns(text) {
  const runs = []
  const parts = String(text).split('**')
  const pairs = parts.length - (parts.length % 2 === 0 ? 1 : 0)
  parts.forEach((part, i) => {
    if (!part) return
    const bold = i % 2 === 1 && i < pairs
    runs.push({ text: part, bold })
  })
  return runs
}

const BULLET = /^\s*(?:[*\-•–]\s+)(.+)$/
const NUMBERED = /^\s*\d+[.)]\s+(.+)$/
const MD_HEADING = /^\s*#{1,6}\s+(.+)$/
const BOLD_ONLY = /^\s*\*\*([^*]+)\*\*:?\s*$/

export function parseDescription(raw) {
  const lines = toPlainLines(raw).split('\n')
  const blocks = []
  let paragraph = []

  const flush = () => {
    if (paragraph.length) blocks.push({ type: 'p', runs: inlineRuns(paragraph.join(' ')) })
    paragraph = []
  }
  const pushItem = (type, text) => {
    flush()
    const last = blocks[blocks.length - 1]
    if (last && last.type === type) last.items.push(inlineRuns(text))
    else blocks.push({ type, items: [inlineRuns(text)] })
  }

  lines.forEach((line, i) => {
    const text = line.trim()
    if (!text) { flush(); return }
    let m
    if ((m = BULLET.exec(line)) && !text.startsWith('**')) return pushItem('ul', m[1])
    if ((m = NUMBERED.exec(line))) return pushItem('ol', m[1])
    if ((m = MD_HEADING.exec(line))) {
      flush()
      return blocks.push({ type: 'h', runs: inlineRuns(m[1].replace(/\*\*/g, '')) })
    }
    // A line that is only bold is a heading when it stands alone; in the middle
    // of a sentence ("looking for a new / **Product Manager** / to join") it is not.
    const alone = !(lines[i - 1] || '').trim() && !(lines[i + 1] || '').trim()
    if ((m = BOLD_ONLY.exec(line)) && alone) {
      flush()
      return blocks.push({ type: 'h', runs: inlineRuns(m[1]) })
    }
    const previous = paragraph[paragraph.length - 1]
    if (previous && /:\s*$/.test(previous)) flush()   // "What you'll do:" then its lines
    paragraph.push(text)
  })
  flush()
  return blocks
}

/** The first `limit` characters of the ad, ended at a word, for the collapsed view. */
export function truncateDescription(raw, limit) {
  const plain = toPlainLines(raw)
  if (plain.length <= limit) return { text: plain, truncated: false }
  const cut = plain.slice(0, limit)
  return { text: `${cut.slice(0, Math.max(cut.lastIndexOf(' '), limit - 20))}…`, truncated: true }
}
