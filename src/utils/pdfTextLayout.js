// Turns pdf.js text items into plain text that keeps the page's line structure.
// Pure functions: no pdf.js import, so they can be tested with fake items.

const BULLET_ONLY = /^[•●▪◦‣∙·*-]$/
const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' }

// Single pass, so "&amp;lt;" becomes "&lt;" and is never decoded twice.
export function decodeEntities(text) {
  return text.replace(/&(?:#(\d{1,6})|#x([0-9a-f]{1,5})|([a-z]+));/gi, (match, dec, hex, name) => {
    if (dec || hex) {
      const code = dec ? parseInt(dec, 10) : parseInt(hex, 16)
      return code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : match
    }
    return Object.hasOwn(ENTITIES, name.toLowerCase()) ? ENTITIES[name.toLowerCase()] : match
  })
}

// Removes the stray space a line wrap leaves around the hyphen of a compound.
// A hyphen with spaces on both sides (a dash) and "and" / "or" / "to" after a
// hyphen ("front- and back-end") are left alone.
export function fixHyphenSpacing(line) {
  return line
    .replace(/([\p{L}\d]) -(?=\p{Ll})/gu, '$1-')
    .replace(/([\p{L}\d])- (?=\p{Ll})(?!(?:and|or|to)\b)/gu, '$1-')
}

function itemInfo(item) {
  const t = item.transform || []
  const height = item.height || Math.abs(t[3]) || Math.abs(t[0]) || 10
  const x = t[4] ?? 0
  const width = item.width ?? 0
  return { str: item.str, x, y: t[5] ?? 0, width, height }
}

function groupLines(items) {
  const infos = items.filter((i) => typeof i.str === 'string' && i.str !== '').map(itemInfo)
  infos.sort((a, b) => b.y - a.y)
  const lines = []
  for (const info of infos) {
    const last = lines[lines.length - 1]
    const tolerance = Math.max(2, info.height * 0.5)
    if (last && Math.abs(last.y - info.y) <= tolerance) {
      last.items.push(info)
    } else {
      lines.push({ y: info.y, height: info.height, items: [info] })
    }
  }
  return lines
}

function joinLine(lineItems) {
  const sorted = [...lineItems].sort((a, b) => a.x - b.x)
  let out = ''
  let prev = null
  for (const item of sorted) {
    if (prev) {
      const gap = item.x - (prev.x + prev.width)
      const threshold = Math.max(prev.height, item.height) * 0.15
      const glued = /\s$/.test(out) || /^\s/.test(item.str)
      if (!glued && (gap > threshold || BULLET_ONLY.test(prev.str.trim()))) out += ' '
    }
    out += item.str
    prev = item
  }
  return fixHyphenSpacing(out.replace(/[ \t ]+/g, ' ').trim())
}

export function pageItemsToText(items) {
  const lines = groupLines(items || [])
  const out = []
  let prev = null
  for (const line of lines) {
    const text = joinLine(line.items)
    if (!text) continue
    if (prev && prev.y - line.y > Math.max(prev.height, line.height) * 1.8) out.push('')
    out.push(text)
    prev = line
  }
  return out.join('\n')
}

export function pagesToText(pages) {
  const text = pages.map(pageItemsToText).filter(Boolean).join('\n\n')
  return decodeEntities(text).trim()
}
