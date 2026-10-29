import { describe, expect, it } from 'vitest'
import {
  DEFAULT_SETTINGS_CATEGORY, SETTINGS_CATEGORIES, SETTINGS_SECTIONS, findSection, isCategoryId, searchSettings, sectionsOf,
} from '../../src/modules/settings/settingsRegistry.js'

const categoryOf = (query) => searchSettings(query).map((s) => s.category)

describe('settings registry', () => {
  it('has the eight owner-decided categories in nav order', () => {
    expect(SETTINGS_CATEGORIES.map((c) => c.title)).toEqual([
      'Job search', 'Sources', 'Applications', 'AI & costs', 'Privacy & security', 'Data & backups', 'General', 'Danger zone',
    ])
    expect(isCategoryId(DEFAULT_SETTINGS_CATEGORY)).toBe(true)
  })

  it('has unique category and section ids, and every section names an existing category', () => {
    const categoryIds = SETTINGS_CATEGORIES.map((c) => c.id)
    const sectionIds = SETTINGS_SECTIONS.map((s) => s.id)
    expect(new Set(categoryIds).size).toBe(categoryIds.length)
    expect(new Set(sectionIds).size).toBe(sectionIds.length)
    for (const s of SETTINGS_SECTIONS) expect(categoryIds, s.id).toContain(s.category)
    for (const s of SETTINGS_SECTIONS) expect(s.keywords.length, s.id).toBeGreaterThan(0)
  })

  it('an empty category carries a one-line note, a filled one does not', () => {
    for (const c of SETTINGS_CATEGORIES) {
      const empty = sectionsOf(c.id).length === 0
      expect(Boolean(c.empty), c.id).toBe(empty)
    }
  })

  it('search finds the sections the owner looks for', () => {
    expect(categoryOf('budget')).toContain('ai-costs')
    expect(categoryOf('backup')).toContain('data-backups')
    expect(categoryOf('weights')).toContain('job-search')
    expect(categoryOf('automation')).toContain('ai-costs')
    expect(categoryOf('notifications')).toContain('applications')
    expect(searchSettings('')).toEqual([])
    expect(searchSettings('zzzz-nothing')).toEqual([])
  })

  it('looks a section up by id, and marks what can spend, send data out or delete', () => {
    expect(findSection('ai-budget').category).toBe('ai-costs')
    expect(findSection('nope')).toBeNull()
    expect(findSection('ai-budget').risky).toBe('spend')
    expect(findSection('clear-local-data').risky).toBe('delete')
  })

})
