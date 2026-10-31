import { useEffect, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import Button from '../ui/Button'
import ResumeUpload from '../resume/ResumeUpload'
import SourcePicker from './SourcePicker'
import PasteStep from './PasteStep'
import ImportReview from './ImportReview'
import { useProfile } from '../../context/ProfileContext'
import { applyImportDraft, defaultChoices } from '../../modules/profile/importDraft'
import { parsePastedText } from '../../modules/profile/importApi'

// Step 1 of the profile wizard: pick a source, read it, review the draft, save. Nothing reaches the
// profile before handleSave; the draft lives in this component's state and is lost on a refresh.
export default function ImportWizard({ onBusyChange, onManual, onSaved }) {
  const { profile, updateProfile } = useProfile()
  const [view, setView] = useState('pick')
  const [oldMode, setOldMode] = useState('resume')
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
    setOldMode(id === 'linkedin' ? 'linkedin' : 'resume')
    setView('old')
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

  const reset = () => {
    setDraft(null)
    setChoices(null)
    setView('pick')
  }

  const handleSave = () => {
    updateProfile((prev) => applyImportDraft(prev, draft, choices))
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
      />
    )
  }
  if (view === 'paste') return <PasteStep onParse={handleParse} onBack={() => { setError(null); setView('pick') }} busy={busy} error={error} />
  if (view === 'old') {
    return (
      <div className="space-y-4">
        <Button variant="ghost" onClick={() => setView('pick')}><ArrowLeft className="h-4 w-4" /> Other ways to import</Button>
        <ResumeUpload initialMode={oldMode} />
      </div>
    )
  }
  return <SourcePicker onPick={pick} />
}
