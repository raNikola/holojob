import fs from 'node:fs'
import { describe, expect, it } from 'vitest'
import { validateStep } from '../../src/utils/validators.js'

const read = (file) => fs.readFileSync(`src/components/import/${file}`, 'utf8')
const modules = (file) => [...read(file).matchAll(/from '([^']+)'/g)].map((m) => m[1])

describe('the import wizard saves only in handleSave', () => {
  const wizard = read('ImportWizard.jsx')
  const save = wizard.slice(wizard.indexOf('const handleSave'), wizard.indexOf('if (view ===', wizard.indexOf('const handleSave')))

  it('keeps every write to the profile, the CV library and the CV files in ImportWizard.handleSave', () => {
    expect(wizard.match(/updateProfile/g)).toHaveLength(2) // the hook and its one use below
    expect(save).toMatch(/saveReviewedDraft\(\{ draft, choices, file: pdfFile, upload: uploadCvFile, updateProfile \}\)/)
    expect(wizard).not.toMatch(/cvActions|saveProfile|localStorage|setStep|applyImportDraft|applyResumeExtraction/)
    // The upload function is imported, but only handed over inside handleSave.
    expect(wizard.match(/uploadCvFile/g)).toHaveLength(2)
    expect(wizard.slice(0, wizard.indexOf('const handleSave'))).not.toMatch(/uploadCvFile\(/)
  })

  it('reads a PDF into a draft without a write: extract and parse are all that is handed to readPdfDraft', () => {
    const read1 = wizard.slice(wizard.indexOf('const handleFile'), wizard.indexOf('const reset'))
    expect(read1).toMatch(/readPdfDraft\(file, pdfSource, \{ extract: extractTextFromPdf, parse: parseImportText \}\)/)
    expect(read1).toMatch(/setView\('review'\)/)
    expect(read1).not.toMatch(/updateProfile|uploadCvFile|cvActions/)
  })

  it('no longer sends a PDF through the old upload screen', () => {
    expect(wizard).not.toMatch(/ResumeUpload|import-linkedin|linkedinImport/)
  })

  it('has no way to write in the picker, the paste step, the PDF step or the review screen', () => {
    for (const file of ['SourcePicker.jsx', 'PasteStep.jsx', 'PdfStep.jsx', 'ImportReview.jsx']) {
      const source = read(file)
      expect(source, file).not.toMatch(/useProfile|updateProfile|cvActions|uploadCvFile|localStorage|sessionStorage|fetch\(/)
      expect(modules(file).filter((m) => /context|cvApi|storage|ProfileContext|resumeParser/.test(m)), file).toEqual([])
    }
  })

  it('parses through the one stateless route and touches /api/cvs only through cvApi in handleSave', () => {
    const api = fs.readFileSync('src/modules/profile/importApi.js', 'utf8')
    expect(api).toMatch(/\/api\/profile\/import\/parse/)
    for (const file of ['ImportWizard.jsx', 'SourcePicker.jsx', 'PasteStep.jsx', 'PdfStep.jsx', 'ImportReview.jsx']) {
      expect(read(file), file).not.toMatch(/\/api\/cvs/)
    }
    expect(api).not.toMatch(/\/api\/cvs/)
    expect(fs.readFileSync('src/modules/profile/importFlow.js', 'utf8')).not.toMatch(/fetch\(|\/api\//)
  })

  it('keeps the unsaved draft in memory only', () => {
    for (const file of ['ImportWizard.jsx', 'PasteStep.jsx', 'PdfStep.jsx', 'ImportReview.jsx']) {
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
