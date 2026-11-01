// The import draft: what a parser found in one source, held in memory until the user saves it.
//
// A draft is never stored and is not a profile format. It carries the existing profile fields
// (basicProfile, parsedData, languages, links), a confidence per field, and what could not be
// placed. `applyImportDraft` is the only place that turns a reviewed draft into a profile.

import { addCv, ensureCvLibrary, newCvId } from '../../utils/cvLibrary.js'
import { normalizeLanguages } from '../../utils/languages.js'

export const IMPORT_SOURCES = {
  paste: { importSource: 'pasted_text', name: 'Pasted text' },
  resume_pdf: { importSource: 'resume_pdf', name: 'Resume PDF', pdf: true },
  linkedin_pdf: { importSource: 'linkedin_pdf', name: 'LinkedIn PDF', pdf: true },
}

export const BASIC_FIELDS = ['fullName', 'email', 'phone', 'location', 'currentRole', 'experienceYears']

/** `editedKey` is the name ProfileForm passes to markFieldEdited for the same data. */
export const SECTIONS = [
  { id: 'experience', label: 'Experience', editedKey: 'workExperience' },
  { id: 'education', label: 'Education', editedKey: 'education' },
  { id: 'skills', label: 'Skills', editedKey: 'skills' },
  { id: 'languages', label: 'Languages', editedKey: 'languages' },
  { id: 'certifications', label: 'Certifications', editedKey: 'certifications' },
  { id: 'projects', label: 'Projects', editedKey: 'projects' },
  { id: 'links', label: 'Links', editedKey: 'links' },
]

const text = (value) => (typeof value === 'string' ? value.trim() : '')
const norm = (value) => text(value).replace(/\s+/g, ' ').toLowerCase()
const list = (value) => (Array.isArray(value) ? value : [])

function entryKey(entry) {
  return [entry?.company, entry?.title, entry?.start].map(norm).join('|')
}

/** The "Title — Company | start – end | text" line the evidence index reads. */
export function deriveWorkExperience(entries) {
  return list(entries).map((entry) => {
    const head = [entry.title, entry.company].filter(Boolean).join(' — ')
    const period = [entry.start, entry.end].filter(Boolean).join(' – ')
    const description = text(entry.description).replace(/\s+/g, ' ')
    const bullets = [description, ...list(entry.bullets).map(text)].filter(Boolean).map((b) => (/[.!?]$/.test(b) ? b : `${b}.`)).join(' ')
    return [head, period, bullets].filter((part, i) => i < 2 || part).join(' | ')
  })
}

function isEdited(profile, key) {
  return Boolean(profile._editedFields?.[key])
}

/** The items a section holds in a draft: experience entries when there are any, else plain lines. */
export function draftItems(draft, id) {
  const parsed = draft?.parsedData || {}
  if (id === 'experience') return list(parsed.experienceDetail).length ? list(parsed.experienceDetail) : list(parsed.workExperience)
  if (id === 'languages') return list(draft?.languages)
  if (id === 'links') return list(draft?.links)
  return list(parsed[id])
}

/** How many items the profile holds now for a section. */
export function liveCount(profile, id) {
  const parsed = profile.resume?.parsedData || {}
  if (id === 'experience') return Math.max(list(parsed.experienceDetail).length, list(parsed.workExperience).length)
  if (id === 'languages') return normalizeLanguages(profile.basicProfile?.languages).length
  return list(parsed[id]).length
}

/** The summary text the profile holds now (`resume.parsedData.summary`); empty when it has none. */
export function liveSummary(profile) {
  return text(profile.resume?.parsedData?.summary)
}

/** Defaults: fill only what is empty and was not edited by the user; everything else is kept. */
export function defaultChoices(profile, draft) {
  const basics = {}
  for (const field of BASIC_FIELDS) {
    const free = !text(profile.basicProfile?.[field]) && !isEdited(profile, field)
    basics[field] = text(draft?.basicProfile?.[field]) && free ? 'use' : 'keep'
  }
  const sections = {}
  for (const { id, editedKey } of SECTIONS) {
    const empty = liveCount(profile, id) === 0 && !isEdited(profile, editedKey)
    sections[id] = draftItems(draft, id).length && empty ? 'add' : 'keep'
  }
  const summary = text(draft?.summary) && !liveSummary(profile) && !isEdited(profile, 'summary') ? 'use' : 'keep'
  return { basics, sections, summary }
}

/** A field or section the user edited is never replaced: the choice falls back to keeping it. */
export function effectiveBasicChoice(profile, field, choice) {
  return isEdited(profile, field) ? 'keep' : choice === 'use' ? 'use' : 'keep'
}

/** The summary is one value, chosen like a basic field: filled, or kept as it is; an edited summary is never replaced. */
export function effectiveSummaryChoice(profile, choice) {
  return isEdited(profile, 'summary') ? 'keep' : choice === 'use' ? 'use' : 'keep'
}

export function effectiveSectionChoice(profile, id, choice) {
  const { editedKey } = SECTIONS.find((s) => s.id === id)
  if (choice === 'replace') return isEdited(profile, editedKey) ? 'keep' : 'replace'
  return choice === 'add' ? 'add' : 'keep'
}

function mergeList(live, incoming, choice, keyOf = norm) {
  if (choice === 'replace') return incoming
  if (choice !== 'add') return live
  const seen = new Set(live.map(keyOf))
  return [...live, ...incoming.filter((item) => {
    const key = keyOf(item)
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })]
}

const GITHUB = /^(?:https?:\/\/)?(?:www\.)?github\.com\//i

function githubUrl(link) {
  return /^https?:\/\//i.test(link) ? link : `https://${link}`
}

const bare = (url) => norm(url).replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/$/, '')

const cleanLines = (value) => list(value).map(text).filter(Boolean)

/** Experience entries as saved: trimmed, empty bullets gone, and entries with nothing to say dropped. */
function cleanEntries(value) {
  return list(value)
    .map((e) => ({
      title: text(e?.title), company: text(e?.company), location: text(e?.location), start: text(e?.start), end: text(e?.end),
      description: text(e?.description), bullets: cleanLines(e?.bullets),
    }))
    .filter((e) => e.title || e.company || e.start || e.description || e.bullets.length)
}

function entryParsedData(draft) {
  const parsed = draft.parsedData || {}
  const entries = cleanEntries(parsed.experienceDetail)
  return {
    summary: text(draft.summary),
    skills: cleanLines(parsed.skills),
    projects: cleanLines(parsed.projects),
    education: cleanLines(parsed.education),
    certifications: cleanLines(parsed.certifications),
    links: cleanLines(draft.links),
    workExperience: entries.length ? deriveWorkExperience(entries) : cleanLines(parsed.workExperience),
    experienceDetail: entries,
    competencyGroups: list(parsed.competencyGroups),
  }
}

/** True when saving would make the new My CVs entry the active CV: the profile has no CV yet. */
export function willBeActive(profile) {
  return !ensureCvLibrary(profile).defaultCvId
}

/**
 * The profile after saving a reviewed draft: the chosen fields and sections merged in, and a
 * "My CVs" entry for the source. The entry is not made the active CV, with one exception: a
 * profile with no CV at all gets it as its first, and so as its active, CV.
 */
export function applyImportDraft(profile, draft, choices, { now = new Date(), makeId = newCvId, file = null } = {}) {
  const incoming = entryParsedData(draft)
  const basicProfile = { ...profile.basicProfile }
  const confidence = { ...profile._confidence }
  const parsedData = { ...(profile.resume?.parsedData || {}) }
  const repositories = { ...profile.repositories, githubLinks: [...list(profile.repositories?.githubLinks)] }

  const note = (key, applied) => {
    const level = draft.confidence?.[key]
    if (!applied) return
    if (level) confidence[key] = level
    else delete confidence[key]
  }

  for (const field of BASIC_FIELDS) {
    const value = text(draft.basicProfile?.[field])
    if (value && effectiveBasicChoice(profile, field, choices?.basics?.[field]) === 'use') {
      basicProfile[field] = value
      note(field, true)
    }
  }

  if (incoming.summary && effectiveSummaryChoice(profile, choices?.summary) === 'use') {
    parsedData.summary = incoming.summary
    note('summary', true)
  }

  for (const { id, editedKey } of SECTIONS) {
    const choice = effectiveSectionChoice(profile, id, choices?.sections?.[id])
    if (choice === 'keep' || !draftItems(draft, id).length) continue
    if (id === 'languages') {
      basicProfile.languages = mergeList(normalizeLanguages(basicProfile.languages), normalizeLanguages(draft.languages), choice, (l) => norm(l.language))
    } else if (id === 'experience') {
      parsedData.experienceDetail = mergeList(list(parsedData.experienceDetail), incoming.experienceDetail, choice, entryKey)
      parsedData.workExperience = parsedData.experienceDetail.length && incoming.experienceDetail.length
        ? deriveWorkExperience(parsedData.experienceDetail)
        : mergeList(list(parsedData.workExperience), incoming.workExperience, choice)
    } else {
      parsedData[id] = mergeList(list(parsedData[id]), incoming[id], choice)
      if (id === 'skills') {
        const groupKey = (g) => `${norm(g.label)}|${list(g.items).map(norm).join(',')}`
        parsedData.competencyGroups = mergeList(list(parsedData.competencyGroups), incoming.competencyGroups, choice, groupKey)
      }
      if (id === 'links') {
        const known = new Set(repositories.githubLinks.map(bare))
        for (const link of incoming.links.filter((l) => GITHUB.test(l))) {
          if (!known.has(bare(link))) repositories.githubLinks.push(githubUrl(link))
        }
      }
    }
    if (id !== 'languages') note(editedKey, true)
  }

  const source = IMPORT_SOURCES[draft.source] || { importSource: 'imported', name: 'Imported text' }
  const day = now.toISOString().slice(0, 10)
  // A PDF source keeps its own file name; `file` carries the stored copy's id and path when the upload worked.
  const named = source.pdf && text(draft.fileName)
  const entry = {
    id: file?.id || makeId(),
    ...(named ? {} : { label: `${source.name} ${day}` }),
    fileName: named || `${source.name} ${day}`,
    filePath: file?.filePath || null,
    uploadedAt: now.toISOString(),
    rawText: draft.rawText || '',
    importSource: source.importSource,
    parsedData: incoming,
  }

  const merged = { ...profile, basicProfile, repositories, _confidence: confidence, resume: { ...profile.resume, parsedData } }
  const next = addCv(merged, entry, { makeDefault: false })
  // addCv makes the entry active when the profile had no CV; keep the merged fields in that case too.
  return next.defaultCvId === entry.id ? { ...next, resume: { ...next.resume, parsedData } } : next
}

/** A copy of the draft with one basic field changed by the user; the parser's confidence for it no longer applies. */
export function withBasic(draft, field, value) {
  const { [field]: _dropped, ...confidence } = draft.confidence || {}
  return { ...draft, basicProfile: { ...draft.basicProfile, [field]: value }, confidence }
}

/**
 * How the parser read one education line: `{ degree, school, year }`, or null when the line was edited since
 * (the reading belongs to the text it was made from), or was not read. Display only: it is not saved,
 * the education lines are.
 */
export function educationReading(draft, line) {
  const found = list(draft?.parsedData?.educationDetail).find((d) => d && d.text === line)
  if (!found || !(found.degree || found.school || found.year)) return null
  return { degree: text(found.degree), school: text(found.school), year: text(found.year) }
}

/** A copy of the draft with the summary changed by the user; the parser's confidence for it no longer applies. */
export function withSummary(draft, value) {
  const { summary: _dropped, ...confidence } = draft.confidence || {}
  return { ...draft, summary: value, confidence }
}

/** A copy of the draft with one section's items replaced by the user's edit. */
export function withSection(draft, id, items) {
  const { editedKey } = SECTIONS.find((s) => s.id === id)
  const { [editedKey]: _dropped, ...confidence } = draft.confidence || {}
  const parsedData = { ...draft.parsedData }
  const next = { ...draft, parsedData, confidence }
  if (id === 'languages') next.languages = items
  else if (id === 'links') next.links = items
  else if (id === 'experience') {
    const entries = items.filter((item) => item && typeof item === 'object')
    if (entries.length || !items.length) {
      parsedData.experienceDetail = entries
      parsedData.workExperience = deriveWorkExperience(entries)
    } else {
      parsedData.experienceDetail = []
      parsedData.workExperience = items
    }
  } else parsedData[id] = items
  return next
}

const entryConfidenceKey = (index) => `experienceDetail.${index}`

/** A copy of the draft with one experience entry changed; only that entry's parser confidence is dropped. */
export function withEntry(draft, index, entry) {
  const { [entryConfidenceKey(index)]: _dropped, ...confidence } = draft.confidence || {}
  const entries = list(draft.parsedData?.experienceDetail).map((e, i) => (i === index ? entry : e))
  return { ...draft, confidence, parsedData: { ...draft.parsedData, experienceDetail: entries, workExperience: deriveWorkExperience(cleanEntries(entries)) } }
}

export function addEntry(draft) {
  const entries = [...list(draft.parsedData?.experienceDetail), { title: '', company: '', location: '', start: '', end: '', description: '', bullets: [] }]
  return { ...draft, parsedData: { ...draft.parsedData, experienceDetail: entries } }
}

/** Removes one entry and moves the later entries' confidence up with them. */
export function removeEntry(draft, index) {
  const entries = list(draft.parsedData?.experienceDetail).filter((_, i) => i !== index)
  const confidence = {}
  for (const [key, level] of Object.entries(draft.confidence || {})) {
    const match = /^experienceDetail\.(\d+)$/.exec(key)
    if (!match) confidence[key] = level
    else if (Number(match[1]) < index) confidence[key] = level
    else if (Number(match[1]) > index) confidence[entryConfidenceKey(Number(match[1]) - 1)] = level
  }
  return { ...draft, confidence, parsedData: { ...draft.parsedData, experienceDetail: entries, workExperience: deriveWorkExperience(cleanEntries(entries)) } }
}
