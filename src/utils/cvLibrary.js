// The CV library: every CV the candidate uploaded, beside profile.resume.
//
// profile.resume stays the one active résumé that the rest of the app reads
// (parsedData, rawText, fileName). profile.cvLibrary lists the uploaded CVs and
// profile.defaultCvId says which of them profile.resume currently is. The
// default entry is a mirror: its parsedData is edited in the profile form, so
// the live copy is profile.resume, and it is written back into the entry before
// another CV takes over.

const RESUME_FIELDS = ['fileName', 'uploadedAt', 'rawText', 'parsedData', 'importSource']

function stableId(resume) {
  // Derived from the résumé itself so a profile migrated twice before it is
  // saved gets the same id both times.
  let h = 0
  const seed = `${resume.fileName}|${resume.uploadedAt}|${(resume.rawText || '').length}`
  for (let i = 0; i < seed.length; i += 1) h = (Math.imul(31, h) + seed.charCodeAt(i)) | 0
  return `cv-${(h >>> 0).toString(16)}`
}

export function labelFromFileName(fileName) {
  return (fileName || 'CV').replace(/\.pdf$/i, '').trim() || 'CV'
}

export function newCvId() {
  return `cv-${Math.random().toString(16).slice(2, 10)}${Date.now().toString(16)}`
}

/**
 * First run: a profile with a résumé but no library gets that résumé as its one
 * entry, marked default. Its file was never stored (filePath null). Idempotent.
 */
export function ensureCvLibrary(profile) {
  if (Array.isArray(profile.cvLibrary)) return profile
  const resume = profile.resume
  if (!resume?.fileName) return { ...profile, cvLibrary: [], defaultCvId: null }
  const id = stableId(resume)
  const entry = {
    id,
    label: labelFromFileName(resume.fileName),
    filePath: null,
    ...Object.fromEntries(RESUME_FIELDS.map((k) => [k, resume[k]])),
    importSource: resume.importSource || 'resume_pdf',
  }
  return { ...profile, cvLibrary: [entry], defaultCvId: id }
}

/** Write the live résumé back into the default entry (it holds the form's edits). */
export function syncDefaultEntry(profile) {
  const lib = profile.cvLibrary || []
  if (!profile.defaultCvId || !lib.some((c) => c.id === profile.defaultCvId)) return profile
  const live = Object.fromEntries(RESUME_FIELDS.map((k) => [k, profile.resume?.[k]]))
  return { ...profile, cvLibrary: lib.map((c) => (c.id === profile.defaultCvId ? { ...c, ...live } : c)) }
}

function promote(profile, entry) {
  const outgoing = syncDefaultEntry(profile)
  const target = outgoing.cvLibrary.find((c) => c.id === entry.id)
  return {
    ...outgoing,
    defaultCvId: target.id,
    resume: { ...outgoing.resume, ...Object.fromEntries(RESUME_FIELDS.map((k) => [k, target[k]])) },
  }
}

/**
 * Add an uploaded CV. A new entry is not the default unless `makeDefault` is set
 * or the library has no default yet; making it default copies it into
 * profile.resume exactly as a normal upload does.
 */
export function addCv(profile, entry, { makeDefault = false } = {}) {
  const base = ensureCvLibrary(profile)
  const synced = syncDefaultEntry(base)
  const full = { filePath: null, importSource: 'resume_pdf', label: labelFromFileName(entry.fileName), ...entry }
  const next = { ...synced, cvLibrary: [...synced.cvLibrary, full] }
  return makeDefault || !next.defaultCvId ? promote(next, full) : next
}

export function setDefaultCv(profile, id) {
  const base = syncDefaultEntry(ensureCvLibrary(profile))
  const entry = base.cvLibrary.find((c) => c.id === id)
  if (!entry || base.defaultCvId === id) return profile
  return promote(base, entry)
}

export function renameCv(profile, id, label) {
  const trimmed = (label || '').trim()
  if (!trimmed) return profile
  return { ...profile, cvLibrary: (profile.cvLibrary || []).map((c) => (c.id === id ? { ...c, label: trimmed } : c)) }
}

/** The default CV cannot be removed: the app always keeps an active résumé. */
export function canRemoveCv(profile, id) {
  return (profile.cvLibrary || []).some((c) => c.id === id) && profile.defaultCvId !== id
}

export function removeCv(profile, id) {
  if (!canRemoveCv(profile, id)) return profile
  return { ...profile, cvLibrary: profile.cvLibrary.filter((c) => c.id !== id) }
}

/**
 * Ids of stored PDFs that only the discarded state references: entries in
 * `current` that are not in `snapshot`. Anything the snapshot already had stays,
 * whatever happened to it during the session (renamed, made default).
 */
export function cvFilesToDiscard(snapshot, current) {
  const kept = new Set((snapshot?.cvLibrary || []).map((c) => c.id))
  return (current?.cvLibrary || []).filter((c) => c.filePath && !kept.has(c.id)).map((c) => c.id)
}

/** Keep the last analysis of a CV on its entry; it is data about the file, not the profile. */
export function setCvAnalysis(profile, id, analysis) {
  return { ...profile, cvLibrary: (profile.cvLibrary || []).map((c) => (c.id === id ? { ...c, analysis } : c)) }
}

/** Merge fields into an entry's analysis (what was applied, the result of the last apply). */
export function patchCvAnalysis(profile, id, patch) {
  return {
    ...profile,
    cvLibrary: (profile.cvLibrary || []).map((c) => (c.id === id && c.analysis ? { ...c, analysis: { ...c.analysis, ...patch } } : c)),
  }
}
