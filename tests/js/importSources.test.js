import fs from 'node:fs'
import { describe, expect, it } from 'vitest'
import sourcesFile from '../../src/data/importSources.json'
import { DRAFT_VERSION, IMPORT_SOURCES } from '../../src/modules/profile/importDraft.js'
import { IMPORT_SOURCES as ROUTE_SOURCES } from '../../scripts/run-profile-import.js'

describe('the import source list is one file', () => {
  it('the browser module reads it whole', () => {
    expect(IMPORT_SOURCES).toBe(sourcesFile.sources)
    expect(DRAFT_VERSION).toBe(sourcesFile.draftVersion)
  })

  it('the route accepts exactly the text-input sources', () => {
    const textSources = Object.entries(sourcesFile.sources).filter(([, s]) => s.input === 'text').map(([id]) => id)
    expect(ROUTE_SOURCES).toEqual(textSources)
  })

  it('every source names its My CVs label and import source', () => {
    for (const [id, source] of Object.entries(sourcesFile.sources)) {
      expect(id).toMatch(/^[a-z_]+$/)
      expect(source.importSource).toMatch(/^[a-z_]+$/)
      expect(source.name.length).toBeGreaterThan(2)
      expect(['text', 'bytes']).toContain(source.input)
    }
  })

  it('no module keeps its own copy of the list', () => {
    for (const file of ['scripts/run-profile-import.js', 'src/modules/profile/importDraft.js', 'python/profile_import/text_parser.py']) {
      expect(fs.readFileSync(file, 'utf-8')).not.toMatch(/\[\s*'paste'\s*,\s*'resume_pdf'|\(\s*"paste"\s*,\s*"resume_pdf"/)
    }
  })
})
