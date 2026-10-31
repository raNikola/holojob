import fs from 'node:fs'
import { describe, expect, it } from 'vitest'
import { validateStep } from '../../src/utils/validators.js'

const read = (file) => fs.readFileSync(`src/components/import/${file}`, 'utf8')
const modules = (file) => [...read(file).matchAll(/from '([^']+)'/g)].map((m) => m[1])

describe('the import wizard saves only in handleSave', () => {
  it('keeps every write to the profile, the CV library and the CV files in ImportWizard.handleSave', () => {
    const wizard = read('ImportWizard.jsx')
    expect(wizard.match(/updateProfile\(/g)).toHaveLength(1)
    const save = wizard.slice(wizard.indexOf('const handleSave'), wizard.indexOf('if (view ===', wizard.indexOf('const handleSave')))
    expect(save).toMatch(/updateProfile\(\(prev\) => applyImportDraft\(prev, draft, choices\)\)/)
    expect(wizard).not.toMatch(/cvActions|uploadCvFile|cvApi|localStorage|saveProfile|setStep/)
  })

  it('has no way to write in the picker, the paste step or the review screen', () => {
    for (const file of ['SourcePicker.jsx', 'PasteStep.jsx', 'ImportReview.jsx']) {
      const source = read(file)
      expect(source, file).not.toMatch(/useProfile|updateProfile|cvActions|uploadCvFile|localStorage|sessionStorage|fetch\(/)
      expect(modules(file).filter((m) => /context|cvApi|storage|ProfileContext/.test(m)), file).toEqual([])
    }
  })

  it('parses through the one stateless route and never touches /api/cvs', () => {
    const api = fs.readFileSync('src/modules/profile/importApi.js', 'utf8')
    expect(api).toMatch(/\/api\/profile\/import\/parse/)
    for (const file of ['ImportWizard.jsx', 'SourcePicker.jsx', 'PasteStep.jsx', 'ImportReview.jsx']) {
      expect(read(file), file).not.toMatch(/\/api\/cvs/)
    }
    expect(api).not.toMatch(/\/api\/cvs/)
  })

  it('keeps the unsaved draft in memory only', () => {
    for (const file of ['ImportWizard.jsx', 'PasteStep.jsx', 'ImportReview.jsx']) {
      expect(read(file), file).not.toMatch(/localStorage|sessionStorage|indexedDB/)
    }
  })

  it('holds the Continue button while a draft is being reviewed', () => {
    const wizard = fs.readFileSync('src/components/onboarding/OnboardingWizard.jsx', 'utf8')
    expect(wizard).toMatch(/disabled=\{importBusy && currentStep === 1\}/)
    expect(wizard).toMatch(/<ImportWizard onBusyChange=\{setImportBusy\}/)
  })
})

describe('step 1 no longer demands a PDF', () => {
  const profile = (patch) => ({ resume: { fileName: '', rawText: '' }, basicProfile: { fullName: '' }, ...patch })

  it('asks for a source when there is neither a CV text nor a name', () => {
    const result = validateStep(1, profile())
    expect(result.valid).toBe(false)
    expect(result.errors[0]).toMatch(/Enter manually/)
  })

  it('passes with a CV text, however it was brought in', () => {
    expect(validateStep(1, profile({ resume: { fileName: 'Pasted text 2026-10-31', rawText: 'text' } })).valid).toBe(true)
  })

  it('passes for a profile entered by hand', () => {
    expect(validateStep(1, profile({ basicProfile: { fullName: 'Jane Sample' } })).valid).toBe(true)
  })
})
