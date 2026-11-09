import React, { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeAll, describe, expect, it } from 'vitest'
import { defaultChoices } from '../../src/modules/profile/importDraft.js'
import { buildImportPreview } from '../../src/modules/profile/importPreview.js'

const entry = (title, company, start) => ({ title, company, location: '', start, end: '2022', description: '', bullets: ['x.'] })
const draft = { source: 'paste', rawText: 'r', summary: '', basicProfile: {}, languages: [], links: [], confidence: {},
  parsedData: { skills: [], projects: [], education: [], certifications: [], workExperience: [], competencyGroups: [], experienceDetail: [entry('PM', 'Acme', '2019')] } }
const profile = { basicProfile: { languages: [] }, resume: { parsedData: { experienceDetail: [entry('Old', 'Old Co', '2010')], workExperience: [] } }, repositories: { githubLinks: [] },
  cvLibrary: [{ id: 'cv-old', fileName: 'o.pdf', parsedData: {} }], defaultCvId: 'cv-old', meta: {}, _editedFields: {} }
const IMPACT = {
  profileVersion: { before: 'aaaa', after: 'bbbb', changed: true }, evidence: { before: 3, after: 4, added: 1, removed: 0 },
  matcher: { entriesTotal: 12, matchingNow: 12, stopMatching: 12, alreadyMatchingAfter: 0 }, judge: { changes: false }, findings: { stored: 5, mayMiss: true },
}

describe('the confirm screen (smoke)', () => {
  let ImportConfirm
  let impactLines
  beforeAll(async () => {
    globalThis.React = React
    ;({ default: ImportConfirm, impactLines } = await import('../../src/components/import/ImportConfirm.jsx'))
  })
  const html = (sections, impact) => {
    const choices = { ...defaultChoices(profile, draft), sections: { ...defaultChoices(profile, draft).sections, ...sections } }
    return renderToStaticMarkup(createElement(ImportConfirm, { preview: buildImportPreview(profile, draft, choices), impact, applying: false, error: null, onApply() {}, onBack() {} }))
  }

  it('Merge: says nothing is written yet, names the backup, needs no second confirm, and Apply is enabled', () => {
    const out = html({ experience: 'add' }, { status: 'ready', data: IMPACT })
    expect(out).toMatch(/Nothing has been written yet/)
    expect(out).toMatch(/backup of your current profile first/)
    expect(out).not.toMatch(/type="checkbox"/)
    expect(out).toMatch(/<button[^>]*>Apply import<\/button>/)
    expect(out).not.toMatch(/<button[^>]*disabled=""[^>]*>Apply import/)
    expect(out).toMatch(/It does not become your active CV/)
  })

  it('Replace: shows what is removed, asks for the second confirm, and Apply stays disabled until it is ticked', () => {
    const out = html({ experience: 'replace' }, { status: 'loading' })
    expect(out).toMatch(/1 existing entry will be removed/)
    expect(out).toMatch(/type="checkbox"/)
    expect(out).toMatch(/<button[^>]*disabled=""[^>]*>Apply import<\/button>/)
  })

  it('states the cache impact in counts, and says a failed lookup does not block', () => {
    const out = html({ experience: 'add' }, { status: 'ready', data: IMPACT })
    expect(out).toMatch(/12 cached matcher answers will no longer match/)
    expect(out).toMatch(/Nothing is re-run by the import itself/)
    expect(html({}, { status: 'failed' })).toMatch(/You can still apply/)
  })

  it('an unchanged evidence version says every cached answer stays valid', () => {
    const lines = impactLines({ ...IMPACT, profileVersion: { before: 'a', after: 'a', changed: false }, findings: { stored: 5, mayMiss: false } })
    expect(lines[0]).toMatch(/stays valid/)
    expect(lines.join(' ')).not.toMatch(/job analys/)
  })
})
