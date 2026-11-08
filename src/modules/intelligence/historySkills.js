// Skills from the whole work history, not from the current CV headline or a narrow slice.
//
// Every history entry of every CV in the profile (experienceDetail title + description + bullets, and the plain
// workExperience entries) is scanned for the terms in skillsVocabulary.json and skillsDictionary.js, and the skills the CV
// lists itself (skills, competency and tool groups) are kept. Each result is a short term with a count of the entries that
// state it: proven experience, never an assumption. The text of an entry is read here and never stored.

import { SKILLS_DICTIONARY } from '../../data/skillsDictionary.js'
import vocabulary from '../../data/skillsVocabulary.json'
import domainAdjacency from '../../data/domainAdjacency.json'
import { containsTerm } from '../../utils/termMatch.js'
import { isKeywordShaped } from './keywordShape.js'

export const MAX_HISTORY_SKILLS = 60

const VOCAB_CATEGORY = new Map()
for (const [category, terms] of Object.entries(vocabulary)) {
  if (!Array.isArray(terms)) continue
  for (const term of terms) VOCAB_CATEGORY.set(term, category)
}
const TECH_TERMS = SKILLS_DICTIONARY.filter((t) => !VOCAB_CATEGORY.has(t))

/** productBusiness, delivery or leadership for a vocabulary term; null for anything else. */
export function vocabularyCategory(term) {
  return VOCAB_CATEGORY.get(term) || null
}

function parsedDataOf(profile) {
  const sources = [profile?.resume?.parsedData]
  for (const cv of profile?.cvLibrary || []) sources.push(cv?.parsedData)
  return sources.filter((pd) => pd && typeof pd === 'object')
}

function entryTexts(pd) {
  const texts = []
  for (const entry of pd.experienceDetail || []) {
    if (!entry || typeof entry !== 'object') continue
    texts.push([entry.title, entry.description, ...(Array.isArray(entry.bullets) ? entry.bullets : [])].filter(Boolean).join(' '))
  }
  for (const entry of pd.workExperience || []) {
    if (typeof entry === 'string') texts.push(entry)
    else if (entry && typeof entry === 'object') texts.push([entry.title, entry.description].filter(Boolean).join(' '))
  }
  return texts.map((t) => t.trim()).filter(Boolean)
}

function listedTerms(pd) {
  const groups = [...(pd.competencyGroups || []), ...(pd.toolGroups || [])].flatMap((g) => (Array.isArray(g?.items) ? g.items : []))
  return [...(pd.skills || []), ...groups].filter((s) => typeof s === 'string').map((s) => s.trim()).filter(isKeywordShaped)
}

/**
 * @param {{ profile: object }} ctx the normalized profile (normalizeProfile)
 * @returns {{ term: string, entries: number, listed: boolean }[]} most evidenced first; `entries` is how many history
 *   entries (all CVs, duplicates counted once) state the term, `listed` whether a CV lists it as a skill.
 */
export function deriveHistorySkills(ctx) {
  const sources = parsedDataOf(ctx?.profile)
  const texts = [...new Set(sources.flatMap(entryTexts))]
  const listed = new Map()
  for (const pd of sources) {
    for (const term of listedTerms(pd)) {
      const key = term.toLowerCase()
      if (!listed.has(key)) listed.set(key, term)
    }
  }
  const candidates = new Map(listed)
  for (const term of [...VOCAB_CATEGORY.keys(), ...TECH_TERMS]) {
    if (!candidates.has(term.toLowerCase())) candidates.set(term.toLowerCase(), term)
  }

  const result = []
  for (const [key, term] of candidates) {
    const entries = texts.filter((text) => containsTerm(text, key)).length
    const isListed = listed.has(key)
    if (entries > 0 || isListed) result.push({ term, entries, listed: isListed })
  }
  result.sort((a, b) => b.entries - a.entries || Number(b.listed) - Number(a.listed) || a.term.localeCompare(b.term))
  return result.slice(0, MAX_HISTORY_SKILLS)
}

// --- Which industry each history entry is in, and which capabilities it states -------------------------------------
// Read by python/job_scoring/domain_transfer.py: a bridge from one industry to another needs an entry (role and period) that
// is in the first industry AND states the capability. Only the role title, the period and ids are kept, never the entry text.

export const MAX_HISTORY_ENTRIES = 12

function periodOf(entry) {
  const start = String(entry?.start ?? '').trim()
  const end = String(entry?.end ?? '').trim()
  const period = start && end ? `${start}–${end}` : start || end
  return period.length <= 24 ? period : ''
}

function idsFound(text, table) {
  return Object.entries(table)
    .filter(([, item]) => item.markers.some((marker) => containsTerm(text, marker)))
    .map(([id]) => id)
}

/**
 * @param {{ profile: object }} ctx
 * @returns {{ role: string, period: string, domains: string[], capabilities: string[] }[]} the entries that sit in a known
 *   industry or state a known capability, newest first as the CV lists them; duplicates across CVs are kept once.
 */
export function deriveHistoryEntries(ctx) {
  const seen = new Set()
  const result = []
  for (const pd of parsedDataOf(ctx?.profile)) {
    for (const entry of pd.experienceDetail || []) {
      if (!entry || typeof entry !== 'object') continue
      const text = [entry.title, entry.company, entry.description, ...(Array.isArray(entry.bullets) ? entry.bullets : [])]
        .filter(Boolean).join(' ').trim()
      const role = isKeywordShaped(entry.title) ? entry.title.trim() : ''
      const period = periodOf(entry)
      const key = `${role}|${period}|${text.length}`
      if (!text || seen.has(key)) continue
      seen.add(key)
      const domains = idsFound(text, domainAdjacency.domains)
      const capabilities = idsFound(text, domainAdjacency.capabilities)
      if (domains.length || capabilities.length) result.push({ role, period, domains, capabilities })
    }
  }
  return result.slice(0, MAX_HISTORY_ENTRIES)
}
