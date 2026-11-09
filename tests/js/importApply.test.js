import { describe, expect, it, vi } from 'vitest'
import { applyImportDraft, defaultChoices, draftKey, resolveChoices } from '../../src/modules/profile/importDraft.js'
import { applyReviewedImport, retryMirrorSync, sameProfile, undoLastImport } from '../../src/modules/profile/importApply.js'

const NOW = new Date('2026-11-09T10:00:00Z')
let counter
const options = () => ({ now: NOW, makeId: () => `cv-test-${(counter += 1)}` })

const entry = (title, company, start, bullets) => ({ title, company, location: '', start, end: '2022', description: '', bullets })
const draft = (extra = {}) => ({
  source: 'paste',
  fileName: '',
  rawText: 'RAW TEXT OF THE CV',
  summary: 'Product leader.',
  basicProfile: { fullName: 'Test Person', email: 'test@example.invalid', phone: '', location: 'Somewhere', currentRole: 'Product Manager', experienceYears: '8' },
  languages: [{ language: 'English', proficiency: 'fluent' }],
  links: ['https://example.invalid/in/test'],
  parsedData: {
    skills: ['Roadmapping', 'SQL'],
    projects: ['Payments revamp'],
    education: ['BSc Economics'],
    certifications: ['CSPO'],
    experienceDetail: [entry('Product Manager', 'Acme', '2019', ['Led the roadmap.']), entry('Analyst', 'Beta', '2016', ['Built reports.'])],
    workExperience: [],
    competencyGroups: [],
  },
  confidence: {},
  ...extra,
})

const emptyProfile = () => ({ basicProfile: { languages: [] }, resume: { parsedData: {} }, repositories: { githubLinks: [] }, cvLibrary: [], defaultCvId: null, meta: {}, _editedFields: {} })
const richProfile = () => ({
  basicProfile: { fullName: 'Hand Typed', languages: [{ language: 'German', proficiency: 'basic' }] },
  resume: { fileName: 'old.pdf', uploadedAt: '2026-01-01T00:00:00Z', rawText: 'old', importSource: 'resume_pdf', parsedData: { skills: ['Excel'], experienceDetail: [entry('Old role', 'Old Co', '2010', ['Did old things.'])], workExperience: ['Old role — Old Co | 2010 – 2022 | Did old things.'], education: [], certifications: [], projects: [], links: [] } },
  repositories: { githubLinks: [] },
  cvLibrary: [{ id: 'cv-old', label: 'old', fileName: 'old.pdf', uploadedAt: '2026-01-01T00:00:00Z', rawText: 'old', importSource: 'resume_pdf', filePath: null, parsedData: {} }],
  defaultCvId: 'cv-old',
  meta: { updatedAt: '2026-01-01T00:00:00Z' },
  _editedFields: {},
})

const choicesFor = (profile, d, sections = {}) => {
  const c = defaultChoices(profile, d)
  return { ...c, sections: { ...c.sections, ...sections } }
}

/** In-memory effects with a record of what happened, in order. */
function makeDeps(initial, over = {}) {
  const state = { profile: initial, backups: [], mirror: null, pending: false, stale: false, snap: null, calls: [], uploads: [] }
  const deps = {
    backup: vi.fn(async (p) => { state.calls.push('backup'); state.backups.push(JSON.parse(JSON.stringify(p))); return true }),
    snapshot: {
      saveBefore: vi.fn((p) => { state.calls.push('snapshot'); state.snap = { before: JSON.parse(JSON.stringify(p)), after: null } }),
      saveAfter: vi.fn((p) => { state.snap.after = JSON.parse(JSON.stringify(p)) }),
      load: () => (state.snap?.before && state.snap?.after ? state.snap : null),
      clear: () => { state.snap = null },
    },
    upload: vi.fn(async () => 'file-1'),
    discardUpload: vi.fn(async (id) => { state.uploads.push(id) }),
    commit: vi.fn((p) => { state.calls.push('commit'); state.profile = { ...p, meta: { ...p.meta, updatedAt: 'stamped' } }; return state.profile }),
    syncMirror: vi.fn(async (p) => { state.calls.push('sync'); state.mirror = JSON.parse(JSON.stringify(p)); return true }),
    setSyncPending: vi.fn((v) => { state.pending = v }),
    markIntelligenceStale: vi.fn(() => { state.stale = true }),
    ...over,
  }
  return { state, deps }
}

const run = (state, deps, d, sections, file = null) => applyReviewedImport({
  profile: state.profile, draft: d, choices: choicesFor(state.profile, d, sections), file, deps, options: options(),
})

/** What one clean apply produces, for comparison. */
function cleanApply(initial, d, sections) {
  counter = 0
  return applyImportDraft(initial, d, resolveChoices(initial, d, choicesFor(initial, d, sections)), options())
}

describe('applyReviewedImport: order and failure', () => {
  it('backs up, snapshots, writes once, then syncs; the result is the pure apply', async () => {
    counter = 0
    const { state, deps } = makeDeps(richProfile())
    const res = await run(state, deps, draft())
    expect(state.calls).toEqual(['backup', 'snapshot', 'commit', 'sync'])
    expect(res).toMatchObject({ ok: true, applied: true, synced: true })
    expect(state.backups).toHaveLength(1)
    expect(state.backups[0]).toEqual(richProfile())
    expect(state.stale).toBe(true)
    expect(state.pending).toBe(false)
    expect(sameProfile(state.profile, cleanApply(richProfile(), draft()))).toBe(true)
  })

  it('a failed or throwing backup aborts: nothing written, nothing synced, no snapshot', async () => {
    for (const backup of [async () => false, async () => { throw new Error('down') }]) {
      const { state, deps } = makeDeps(richProfile(), { backup })
      const res = await run(state, deps, draft())
      expect(res).toEqual({ ok: false, applied: false, stage: 'backup' })
      expect(deps.commit).not.toHaveBeenCalled()
      expect(deps.syncMirror).not.toHaveBeenCalled()
      expect(deps.snapshot.saveBefore).not.toHaveBeenCalled()
      expect(deps.upload).not.toHaveBeenCalled()
      expect(state.profile).toEqual(richProfile())
    }
  })

  it('a snapshot that cannot be stored aborts before any write', async () => {
    const { state, deps } = makeDeps(richProfile())
    deps.snapshot.saveBefore = vi.fn(() => { throw new Error('quota') })
    expect(await run(state, deps, draft())).toEqual({ ok: false, applied: false, stage: 'snapshot' })
    expect(deps.commit).not.toHaveBeenCalled()
  })

  it('a failed browser write leaves the profile as it was, removes a stored upload, and does not sync', async () => {
    const { state, deps } = makeDeps(richProfile(), { commit: vi.fn(() => { throw new Error('QuotaExceededError') }) })
    const res = await run(state, deps, draft({ source: 'resume_pdf', fileName: 'cv.pdf' }), {}, { name: 'cv.pdf' })
    expect(res).toEqual({ ok: false, applied: false, stage: 'write' })
    expect(state.profile).toEqual(richProfile())
    expect(state.uploads).toEqual(['file-1'])
    expect(deps.syncMirror).not.toHaveBeenCalled()
    expect(state.stale).toBe(false)
  })

  it('error details never leave the module: results carry fixed fields only', async () => {
    const { state, deps } = makeDeps(richProfile(), { backup: async () => { throw new Error('CANARY-PROFILE-TEXT') } })
    expect(JSON.stringify(await run(state, deps, draft()))).not.toContain('CANARY')
  })
})

describe('mirror sync failure and retry (owner condition 1)', () => {
  it('shows "not synced yet", and the retry resends the stored profile without applying again; the profile equals one clean apply', async () => {
    counter = 0
    const { state, deps } = makeDeps(richProfile(), { syncMirror: vi.fn(async () => false) })
    const res = await run(state, deps, draft())
    expect(res).toMatchObject({ ok: true, applied: true, synced: false })
    expect(state.pending).toBe(true)
    const applied = state.profile
    const commits = deps.commit.mock.calls.length

    deps.syncMirror = vi.fn(async (p) => { state.mirror = p; return true })
    const retry = await retryMirrorSync({ getProfile: () => state.profile, deps })
    expect(retry).toEqual({ synced: true })
    expect(state.pending).toBe(false)
    expect(deps.commit.mock.calls.length).toBe(commits) // nothing was written or applied again
    expect(deps.backup).toHaveBeenCalledTimes(1)
    expect(state.profile).toBe(applied)
    expect(state.mirror).toBe(applied)
    expect(sameProfile(state.profile, cleanApply(richProfile(), draft()))).toBe(true)
    expect(state.profile.cvLibrary.filter((c) => c.importDraftKey)).toHaveLength(1)
  })

  it('a sync that throws is the same as one that fails', async () => {
    const { state, deps } = makeDeps(richProfile(), { syncMirror: vi.fn(async () => { throw new Error('ECONNRESET') }) })
    expect(await run(state, deps, draft())).toMatchObject({ ok: true, applied: true, synced: false })
    expect(state.pending).toBe(true)
  })
})

describe('repeated Apply (owner condition 3)', () => {
  it('Merge: a second Apply of the same draft changes nothing and makes no backup or write', async () => {
    counter = 0
    const { state, deps } = makeDeps(richProfile())
    await run(state, deps, draft())
    const once = state.profile
    const calls = [...state.calls]
    const second = await run(state, deps, draft())
    expect(second).toMatchObject({ ok: true, applied: false, duplicate: true })
    expect(state.calls).toEqual(calls)
    expect(state.profile).toBe(once)
    expect(state.profile.cvLibrary.filter((c) => c.importDraftKey)).toHaveLength(1)
  })

  it('Replace: the second Apply equals one clean Replace', async () => {
    counter = 0
    const sections = { experience: 'replace', skills: 'replace', education: 'add' }
    const { state, deps } = makeDeps(richProfile())
    await run(state, deps, draft(), sections)
    const second = await run(state, deps, draft(), sections)
    expect(second.duplicate).toBe(true)
    const clean = cleanApply(richProfile(), draft(), sections)
    expect(sameProfile(state.profile, clean)).toBe(true)
    expect(state.profile.resume.parsedData.experienceDetail.map((e) => e.company)).toEqual(['Acme', 'Beta'])
  })

  it.each([
    ['Merge', {}],
    ['Replace', { experience: 'replace', skills: 'replace', education: 'replace', projects: 'replace' }],
  ])('the pure apply is idempotent on its own: %s applied twice equals applied once (rich and empty profile)', (_n, sections) => {
    for (const make of [richProfile, emptyProfile]) {
      counter = 0
      const d = draft()
      const choices = (p) => resolveChoices(p, d, choicesFor(p, d, sections))
      const once = applyImportDraft(make(), d, choices(make()), options())
      const twice = applyImportDraft(once, d, choices(once), options())
      expect(sameProfile(twice, once)).toBe(true)
    }
  })

  it('apply interrupted during sync, then the owner clicks Apply again and retries: still one clean apply', async () => {
    counter = 0
    const { state, deps } = makeDeps(richProfile(), { syncMirror: vi.fn(async () => { throw new Error('killed') }) })
    await run(state, deps, draft(), { experience: 'replace' })
    const afterInterrupt = state.profile
    deps.syncMirror = vi.fn(async (p) => { state.mirror = p; return true })
    expect((await run(state, deps, draft(), { experience: 'replace' })).duplicate).toBe(true) // second Apply: no-op
    expect(await retryMirrorSync({ getProfile: () => state.profile, deps })).toEqual({ synced: true })
    expect(state.profile).toBe(afterInterrupt)
    expect(state.mirror).toBe(afterInterrupt)
    expect(sameProfile(state.profile, cleanApply(richProfile(), draft(), { experience: 'replace' }))).toBe(true)
    expect(deps.backup).toHaveBeenCalledTimes(1)
  })

  it('an edited draft is a different draft: it applies, with its own key and one more My CVs entry', async () => {
    counter = 0
    const { state, deps } = makeDeps(richProfile())
    await run(state, deps, draft())
    const edited = draft({ summary: 'Edited summary.' })
    expect(draftKey(edited)).not.toBe(draftKey(draft()))
    expect((await run(state, deps, edited)).applied).toBe(true)
    expect(state.profile.cvLibrary.filter((c) => c.importDraftKey)).toHaveLength(2)
  })
})

describe('what the import does to the profile', () => {
  it('never makes the imported CV active when the profile already has one; the first CV of an empty profile is active', () => {
    counter = 0
    const rich = richProfile()
    const next = applyImportDraft(rich, draft(), resolveChoices(rich, draft(), defaultChoices(rich, draft())), options())
    expect(next.defaultCvId).toBe('cv-old')
    const fresh = emptyProfile()
    const first = applyImportDraft(fresh, draft(), resolveChoices(fresh, draft(), defaultChoices(fresh, draft())), options())
    expect(first.defaultCvId).toBe(first.cvLibrary[0].id)
  })

  it('profile.resume stays a copy of the default My CVs entry after an apply', () => {
    for (const make of [richProfile, emptyProfile]) {
      counter = 0
      const p = make()
      const next = applyImportDraft(p, draft(), resolveChoices(p, draft(), defaultChoices(p, draft())), options())
      const def = next.cvLibrary.find((c) => c.id === next.defaultCvId)
      for (const field of ['fileName', 'uploadedAt', 'rawText', 'importSource']) expect(next.resume[field]).toEqual(def[field])
      if (make === richProfile) expect(def.parsedData).toEqual(next.cvLibrary.find((c) => c.id === 'cv-old').parsedData)
    }
  })

  it('an edited field is kept even when Replace is chosen', () => {
    counter = 0
    const p = { ...richProfile(), _editedFields: { workExperience: true } }
    const d = draft()
    const next = applyImportDraft(p, d, resolveChoices(p, d, { ...defaultChoices(p, d), sections: { ...defaultChoices(p, d).sections, experience: 'replace' } }), options())
    expect(next.resume.parsedData.experienceDetail.map((e) => e.company)).toEqual(['Old Co'])
  })
})

describe('Undo', () => {
  it('restores the pre-import profile while nothing changed since, and refuses after a later edit', async () => {
    counter = 0
    const { state, deps } = makeDeps(richProfile())
    await run(state, deps, draft())
    const edited = { ...state.profile, basicProfile: { ...state.profile.basicProfile, fullName: 'Edited later' } }
    expect(await undoLastImport({ getProfile: () => edited, deps })).toEqual({ ok: false, reason: 'changed' })
    const undone = await undoLastImport({ getProfile: () => state.profile, deps })
    expect(undone).toMatchObject({ ok: true })
    expect(sameProfile(state.profile, richProfile())).toBe(true)
    expect(await undoLastImport({ getProfile: () => state.profile, deps })).toEqual({ ok: false, reason: 'none' })
  })
})
