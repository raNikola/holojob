// Turn a CV analysis (facts the model read, already checked against the CV by
// the server) into suggestions beside the profile, and apply the ones the user
// ticks. Nothing here writes on its own: buildSuggestions only compares, and
// applySuggestions runs only from the review's Apply button.

import { joinAnswerList, parseAnswerList } from './answerList'
import { patchCvAnalysis, syncDefaultEntry } from './cvLibrary'

export const PROJECTS_QUESTION_ID = 4
export const SUMMARY_QUESTION_ID = 17

const QUESTION_TEXT = {
  4: 'Which projects are you most proud of and why?',
  17: 'Write a short personal career summary in your own words.',
}

export function norm(text) {
  return (text || '')
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .replace(/đ/gi, 'dj')
    .toLowerCase()
    .replace(/[^a-z0-9+#]+/g, ' ')
    .trim()
}

const contains = (haystack, needle) => Boolean(norm(needle)) && ` ${norm(haystack)} `.includes(` ${norm(needle)} `)
const answerOf = (profile, id) => profile.questionnaire?.answers?.find((a) => a.id === id)?.answer || ''

export function formatEducation(e) {
  return `${e.degree} — ${e.school}${e.year ? ` | ${e.year}` : ''}`
}

export function formatCertification(c) {
  return `${c.name}${c.issuer ? ` — ${c.issuer}` : ''}${c.year ? ` | ${c.year}` : ''}`
}

export function formatProject(p) {
  return `${p.name} — ${p.summary}`
}

function formatRole(r) {
  const dates = [r.start, r.end].filter(Boolean).join('–')
  return `${r.title} — ${r.company}${dates ? ` | ${dates}` : ''}`
}

function sameGroups(a = [], b = []) {
  const key = (g) => `${norm(g.label)}:${[...(g.items || [])].map(norm).sort().join(',')}`
  return a.length === b.length && [...a].map(key).sort().join('|') === [...b].map(key).sort().join('|')
}

/** status: new (not in the profile), have (already there), differs (there, but not the same). */
export function buildSuggestions(profile, facts) {
  const pd = profile.resume?.parsedData || {}
  const have = (list, value) => (list || []).some((x) => norm(x) === norm(value))

  const skills = (facts.skills || []).map((value) => ({
    id: `skill:${norm(value)}`, value, status: have(pd.skills, value) ? 'have' : 'new',
  }))

  const q4 = parseAnswerList(answerOf(profile, PROJECTS_QUESTION_ID))
  const projects = (facts.keyProjects || []).map((p) => {
    const value = formatProject(p)
    const present = q4.some((x) => contains(x, p.summary) || norm(x) === norm(value))
    return { id: `project:${norm(value)}`, value, status: present ? 'have' : 'new' }
  })

  const experience = (facts.experience || []).map((role, i) => {
    const detail = (pd.experienceDetail || []).find((d) => norm(d.company) === norm(role.company) && norm(d.title) === norm(role.title))
    const listed = (pd.workExperience || []).some((w) => contains(w, role.company))
    const same = detail && JSON.stringify(detail.bullets) === JSON.stringify(role.bullets)
    return {
      id: `role:${i}`, role, label: formatRole(role), listed,
      status: same ? 'have' : detail ? 'differs' : 'new',
    }
  })

  const groups = (key) => {
    const next = facts[key] || []
    const current = pd[key] || []
    return { next, current, status: !next.length ? 'none' : sameGroups(next, current) ? 'have' : current.length ? 'differs' : 'new' }
  }

  const education = (facts.education || []).map((e, i) => {
    const idx = (pd.education || []).findIndex((x) => contains(x, e.school))
    const existing = idx >= 0 ? pd.education[idx] : null
    const matches = existing && contains(existing, e.degree) && (!e.year || contains(existing, e.year))
    return {
      id: `edu:${i}`, value: formatEducation(e), existing, existingIndex: idx, existingCutOff: looksCutOff(existing),
      status: !existing ? 'new' : matches ? 'have' : 'differs',
    }
  })

  const certifications = (facts.certifications || []).map((c, i) => {
    const idx = (pd.certifications || []).findIndex((x) => contains(x, c.name))
    const existing = idx >= 0 ? pd.certifications[idx] : null
    const matches = existing && (!c.year || contains(existing, c.year))
    return {
      id: `cert:${i}`, value: formatCertification(c), existing, existingIndex: idx,
      status: !existing ? 'new' : matches ? 'have' : 'differs',
    }
  })

  const draft = facts.draftCareerSummary || ''
  const existingSummary = answerOf(profile, SUMMARY_QUESTION_ID)
  const summary = draft
    ? { id: 'summary', draft, existing: existingSummary, status: !existingSummary.trim() ? 'new' : norm(existingSummary) === norm(draft) ? 'have' : 'differs' }
    : null

  return {
    skills, projects, experience, summary, education, certifications,
    competencyGroups: groups('competencyGroups'),
    toolGroups: groups('toolGroups'),
  }
}

/** Ids ticked when the review opens: what is new. Anything that would replace something is left to the user. */
export function defaultSelection(s) {
  const ids = []
  for (const item of [...s.skills, ...s.projects, ...s.experience, ...s.education, ...s.certifications]) {
    if (item.status === 'new') ids.push(item.id)
  }
  if (s.competencyGroups.status === 'new') ids.push('competencyGroups')
  if (s.toolGroups.status === 'new') ids.push('toolGroups')
  if (s.summary?.status === 'new') ids.push('summary')
  return new Set(ids)
}

function setAnswer(profile, id, answer) {
  const answers = [...(profile.questionnaire?.answers || [])]
  const idx = answers.findIndex((a) => a.id === id)
  const entry = { id, question: QUESTION_TEXT[id], answer }
  if (idx >= 0) answers[idx] = entry
  else answers.push(entry)
  answers.sort((a, b) => a.id - b.id)
  return { ...profile, questionnaire: { ...profile.questionnaire, answers } }
}

/** Write the ticked suggestions into the profile. Returns a new profile. */
export function applySuggestions(profile, facts, selected) {
  const s = buildSuggestions(profile, facts)
  const pick = (items) => items.filter((i) => selected.has(i.id))
  const pd = { ...(profile.resume?.parsedData || {}) }

  const skills = pick(s.skills).map((i) => i.value)
  if (skills.length) pd.skills = [...(pd.skills || []), ...skills.filter((v) => !(pd.skills || []).some((x) => norm(x) === norm(v)))]

  const detail = [...(pd.experienceDetail || [])]
  const work = [...(pd.workExperience || [])]
  for (const item of pick(s.experience)) {
    const at = detail.findIndex((d) => norm(d.company) === norm(item.role.company) && norm(d.title) === norm(item.role.title))
    if (at >= 0) detail[at] = item.role
    else detail.push(item.role)
    if (!item.listed) work.push(item.label)
  }
  if (pick(s.experience).length) { pd.experienceDetail = detail; pd.workExperience = work }

  if (selected.has('competencyGroups')) pd.competencyGroups = s.competencyGroups.next
  if (selected.has('toolGroups')) pd.toolGroups = s.toolGroups.next

  for (const [key, items] of [['education', s.education], ['certifications', s.certifications]]) {
    const next = [...(pd[key] || [])]
    for (const item of pick(items)) {
      if (item.existingIndex >= 0 && item.status === 'differs') next[item.existingIndex] = item.value
      else if (!next.some((x) => norm(x) === norm(item.value))) next.push(item.value)
    }
    if (pick(items).length) pd[key] = next
  }

  let next = { ...profile, resume: { ...profile.resume, parsedData: pd } }
  const projects = pick(s.projects).map((i) => i.value)
  if (projects.length) {
    next = setAnswer(next, PROJECTS_QUESTION_ID, joinAnswerList([...parseAnswerList(answerOf(next, PROJECTS_QUESTION_ID)), ...projects]))
  }
  if (selected.has('summary') && s.summary) next = setAnswer(next, SUMMARY_QUESTION_ID, s.summary.draft)
  return next
}

/** The ticked ids that would change something: what is already in the profile is left out. */
export function usableIds(s, selected) {
  const status = new Map([...s.skills, ...s.projects, ...s.experience, ...s.education, ...s.certifications].map((i) => [i.id, i.status]))
  status.set('competencyGroups', s.competencyGroups.status)
  status.set('toolGroups', s.toolGroups.status)
  if (s.summary) status.set('summary', s.summary.status)
  return new Set([...selected].filter((id) => status.has(id) && status.get(id) !== 'have' && status.get(id) !== 'none'))
}

/** An entry that starts with punctuation was cut off somewhere ("B. Sc." read as ".Sc."). */
export const looksCutOff = (text) => /^[^\p{L}\p{N}]/u.test((text || '').trim())

/**
 * Apply the ticked suggestions of one CV to the profile, only when it is the
 * default CV (its data is what the rest of the app reads). Items that were
 * already in the profile are not counted. The entry remembers what it applied,
 * so the review can tell "applied" from "was already there".
 * Returns { profile, count } or null.
 */
export function applyToDefaultCv(profile, id, selected) {
  const entry = profile.cvLibrary?.find((c) => c.id === id)
  if (!entry?.analysis || profile.defaultCvId !== id) return null
  const s = buildSuggestions(profile, entry.analysis.facts)
  const usable = usableIds(s, selected)
  if (usable.size === 0) return { profile, count: 0 }
  const applied = applySuggestions(profile, entry.analysis.facts, usable)
  const withMemory = patchCvAnalysis(
    applied, id, { applied: [...new Set([...(entry.analysis.applied || []), ...usable])], lastApply: { at: new Date().toISOString(), count: usable.size, state: 'pending' } },
  )
  return { profile: syncDefaultEntry(withMemory), count: usable.size }
}
