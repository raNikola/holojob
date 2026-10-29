import fs from 'node:fs'
import { describe, expect, it } from 'vitest'
import { linkedInRiskConfirmed } from '../../src/modules/outreach/linkedinConsent.js'

describe('the confirmation before the LinkedIn cookie may be entered', () => {
  it('needs the ticked box and the typed phrase together', () => {
    expect(linkedInRiskConfirmed({ accepted: true, typed: 'I understand' })).toBe(true)
    expect(linkedInRiskConfirmed({ accepted: true, typed: '  i UNDERSTAND ' })).toBe(true)
    expect(linkedInRiskConfirmed({ accepted: false, typed: 'I understand' })).toBe(false)
    expect(linkedInRiskConfirmed({ accepted: true, typed: '' })).toBe(false)
    expect(linkedInRiskConfirmed({ accepted: true, typed: 'I understand it' })).toBe(false)
    expect(linkedInRiskConfirmed({ accepted: 'yes', typed: 'I understand' })).toBe(false)
    expect(linkedInRiskConfirmed({})).toBe(false)
  })

  it('gates the cookie field, the Save button and the submit handler in Settings', () => {
    const src = fs.readFileSync('src/components/settings/SecretsPanel.jsx', 'utf8')
    const form = src.slice(src.indexOf('editingLinkedIn !== null'))
    expect(form).toMatch(/label="li_at cookie"[\s\S]*?disabled=\{!linkedInRiskConfirmed\(/)
    expect(form).toMatch(/type="submit" disabled=\{[^}]*!linkedInRiskConfirmed\(/)
    expect(src).toMatch(/const handleSaveLinkedIn = async \(\) => \{\s*if \(!linkedInRiskConfirmed\(/)
  })
})
