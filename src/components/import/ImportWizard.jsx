import { useEffect, useState } from 'react'
import SourcePicker from './SourcePicker'
import PasteStep from './PasteStep'
import PdfStep from './PdfStep'
import ImportReview from './ImportReview'
import ImportConfirm from './ImportConfirm'
import ImportResult from './ImportResult'
import { useProfile } from '../../context/ProfileContext'
import { defaultChoices } from '../../modules/profile/importDraft'
import { fetchImportImpact, parseImportText, parsePastedText } from '../../modules/profile/importApi'
import { readPdfDraft } from '../../modules/profile/importFlow'
import { applyReviewedImport } from '../../modules/profile/importApply'
import { buildImportPreview } from '../../modules/profile/importPreview'
import { currentProfile, realImportDeps } from '../../modules/profile/importDeps'
import { extractTextFromPdf } from '../../utils/resumeParser'

const APPLY_FAILURES = {
  backup: 'The backup of your current profile could not be made, so nothing was changed. Check that the server is running and try again.',
  snapshot: 'A copy for Undo could not be stored in this browser, so nothing was changed.',
  write: 'Your browser could not store the profile (its storage may be full), so nothing was changed.',
}

// Step 1 of the profile wizard: pick a source, read it, review the draft, confirm, apply. Nothing reaches the
// profile, the CV library or the CV files before handleApply, which goes through applyReviewedImport (backup first, one write,
// mirror retry that never re-applies); the draft, and a PDF's File, live in this component's state only and are lost on a refresh.
export default function ImportWizard({ onBusyChange, onManual, onSaved }) {
  const { profile, commitProfile } = useProfile()
  const [view, setView] = useState('pick')
  const [pdfSource, setPdfSource] = useState('resume_pdf')
  const [pdfFile, setPdfFile] = useState(null)
  const [draft, setDraft] = useState(null)
  const [choices, setChoices] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [preview, setPreview] = useState(null)
  const [impact, setImpact] = useState({ status: 'loading' })
  const [applyError, setApplyError] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    onBusyChange?.(view === 'review' || view === 'confirm')
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
    setPreview(null)
    setResult(null)
    setApplyError(null)
    setView('pick')
  }

  // Review -> confirm: work out the diff (pure) and ask the server what the cache impact would be (read-only). Nothing is written.
  const handleReviewed = () => {
    const now = currentProfile()
    const next = buildImportPreview(now, draft, choices)
    setPreview(next)
    setApplyError(null)
    setImpact({ status: 'loading' })
    setView('confirm')
    fetchImportImpact(now, next.planned).then((data) => setImpact(data ? { status: 'ready', data } : { status: 'failed' }))
  }

  const handleApply = async () => {
    if (busy) return
    setBusy(true)
    setApplyError(null)
    try {
      const applied = await applyReviewedImport({ profile: currentProfile(), draft, choices, file: pdfFile, deps: realImportDeps({ commitToScreen: commitProfile }) })
      if (!applied.ok) {
        setApplyError(APPLY_FAILURES[applied.stage] || APPLY_FAILURES.write)
        return
      }
      setResult(applied)
      setView('result')
    } finally {
      setBusy(false)
    }
  }

  const finish = () => {
    reset()
    onSaved?.()
  }

  if (view === 'result' && result) return <ImportResult result={result} onContinue={finish} />
  if (view === 'confirm' && preview) {
    return <ImportConfirm preview={preview} impact={impact} applying={busy} error={applyError} onApply={handleApply} onBack={() => setView('review')} />
  }
  if (view === 'review' && draft && choices) {
    return (
      <ImportReview
        draft={draft}
        profile={profile}
        choices={choices}
        onDraftChange={setDraft}
        onChoicesChange={setChoices}
        onSave={handleReviewed}
        onDiscard={reset}
        saving={busy}
      />
    )
  }
  if (view === 'paste') return <PasteStep onParse={handleParse} onBack={() => { setError(null); setView('pick') }} busy={busy} error={error} />
  if (view === 'pdf') return <PdfStep source={pdfSource} onFile={handleFile} onBack={() => { setError(null); setView('pick') }} busy={busy} error={error} />
  return <SourcePicker onPick={pick} />
}
