import { useEffect, useState } from 'react'
import SourcePicker from './SourcePicker'
import PasteStep from './PasteStep'
import PdfStep from './PdfStep'
import ImportReview from './ImportReview'
import { useProfile } from '../../context/ProfileContext'
import { defaultChoices } from '../../modules/profile/importDraft'
import { parseImportText, parsePastedText } from '../../modules/profile/importApi'
import { readPdfDraft, saveReviewedDraft } from '../../modules/profile/importFlow'
import { extractTextFromPdf } from '../../utils/resumeParser'
import { uploadCvFile } from '../../modules/cvs/cvApi'

// Step 1 of the profile wizard: pick a source, read it, review the draft, save. Nothing reaches the
// profile, the CV library or the CV files before handleSave; the draft, and a PDF's File, live in this
// component's state only and are lost on a refresh.
export default function ImportWizard({ onBusyChange, onManual, onSaved }) {
  const { profile, updateProfile } = useProfile()
  const [view, setView] = useState('pick')
  const [pdfSource, setPdfSource] = useState('resume_pdf')
  const [pdfFile, setPdfFile] = useState(null)
  const [draft, setDraft] = useState(null)
  const [choices, setChoices] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    onBusyChange?.(view === 'review')
    return () => onBusyChange?.(false)
  }, [view, onBusyChange])

  const pick = (id) => {
    setError(null)
    if (id === 'manual') { onManual?.(); return }
    if (id === 'paste') { setView('paste'); return }
    setPdfSource(id === 'linkedin' ? 'linkedin_pdf' : 'resume_pdf')
    setView('pdf')
  }

  const handleParse = async (text) => {
    setBusy(true)
    setError(null)
    try {
      const parsed = await parsePastedText(text)
      setDraft(parsed)
      setChoices(defaultChoices(profile, parsed))
      setView('review')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The text could not be read.')
    } finally {
      setBusy(false)
    }
  }

  const handleFile = async (file) => {
    setBusy(true)
    setError(null)
    try {
      const parsed = await readPdfDraft(file, pdfSource, { extract: extractTextFromPdf, parse: parseImportText })
      setDraft(parsed)
      setPdfFile(file)
      setChoices(defaultChoices(profile, parsed))
      setView('review')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The PDF could not be read.')
    } finally {
      setBusy(false)
    }
  }

  const reset = () => {
    setPdfFile(null)
    setDraft(null)
    setChoices(null)
    setView('pick')
  }

  const handleSave = async () => {
    if (busy) return
    setBusy(true)
    try {
      await saveReviewedDraft({ draft, choices, file: pdfFile, upload: uploadCvFile, updateProfile })
    } finally {
      setBusy(false)
    }
    reset()
    onSaved?.()
  }

  if (view === 'review' && draft && choices) {
    return (
      <ImportReview
        draft={draft}
        profile={profile}
        choices={choices}
        onDraftChange={setDraft}
        onChoicesChange={setChoices}
        onSave={handleSave}
        onDiscard={reset}
        saving={busy}
      />
    )
  }
  if (view === 'paste') return <PasteStep onParse={handleParse} onBack={() => { setError(null); setView('pick') }} busy={busy} error={error} />
  if (view === 'pdf') return <PdfStep source={pdfSource} onFile={handleFile} onBack={() => { setError(null); setView('pick') }} busy={busy} error={error} />
  return <SourcePicker onPick={pick} />
}
