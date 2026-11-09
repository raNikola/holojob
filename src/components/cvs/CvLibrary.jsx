import { useRef, useState } from 'react'
import { Check, Download, Sparkles, FileText, Loader2, Pencil, Star, Trash2, Upload, X } from 'lucide-react'
import Card from '../ui/Card'
import Alert from '../ui/Alert'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import { useProfile } from '../../context/ProfileContext'
import { extractTextFromPdf } from '../../utils/resumeParser'
import { extractProfileFromResume } from '../../utils/profileExtractor'
import { parseImportText } from '../../modules/profile/importApi'
import { cvEntryParsedData } from '../../modules/profile/importFlow'
import { cvDownloadUrl, deleteCvFile, uploadCvFile } from '../../modules/cvs/cvApi'
import { canRemoveCv } from '../../utils/cvLibrary'
import { regenerateAndSync } from '../../modules/cvs/regenerateAfterApply'
import { applyWithBackup } from '../../modules/cvs/applyWithBackup'
import { backupProfileForImport } from '../../modules/jobs/profileSync'
import CvAnalyzeDialog from './CvAnalyzeDialog'
import CvAnalysisReview from './CvAnalysisReview'

function formatDate(value) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString()
}

function LabelEditor({ initial, onSave, onCancel }) {
  const [value, setValue] = useState(initial)
  const save = () => { if (value.trim()) onSave(value.trim()) }
  return (
    <div className="flex items-center gap-1.5">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') onCancel() }}
        maxLength={60}
        autoFocus
        aria-label="CV label"
        className="min-w-0 flex-1 rounded-lg border border-stone-300 px-2 py-1 text-sm dark:border-stone-700 dark:bg-stone-950 dark:text-stone-50"
      />
      <button type="button" onClick={save} aria-label="Save label" className="rounded-lg p-1.5 text-teal-700 hover:bg-stone-100 dark:hover:bg-stone-800"><Check className="h-4 w-4" /></button>
      <button type="button" onClick={onCancel} aria-label="Cancel rename" className="rounded-lg p-1.5 text-stone-500 hover:bg-stone-100 dark:hover:bg-stone-800"><X className="h-4 w-4" /></button>
    </div>
  )
}

function CvCard({ cv, profile, isDefault, canDelete, busy, onSetDefault, onRename, onDelete, onAnalysis, onApplyAnalysis, onRetrySync }) {
  const [editing, setEditing] = useState(false)
  const [dialog, setDialog] = useState(null)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const hasFile = Boolean(cv.filePath)

  return (
    <Card className="!p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          {editing ? (
            <LabelEditor initial={cv.label} onSave={(label) => { onRename(label); setEditing(false) }} onCancel={() => setEditing(false)} />
          ) : (
            <p className="flex flex-wrap items-center gap-2 font-medium text-stone-900 dark:text-stone-100">
              <FileText className="h-4 w-4 shrink-0 text-stone-400" />
              {cv.label}
              {isDefault && <Badge variant="high">Default</Badge>}
            </p>
          )}
          <p className="text-sm text-stone-600 dark:text-stone-400">{cv.fileName || '—'}</p>
          <p className="text-xs text-stone-500">
            Uploaded {formatDate(cv.uploadedAt)}
            {cv.rawText ? ` · ${cv.rawText.length.toLocaleString()} characters` : ''}
          </p>
          {!hasFile && (
            <p className="text-xs text-amber-700 dark:text-amber-400">
              The original PDF was not stored (uploaded before My CVs existed). Its text and parsed data are kept.
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {hasFile && (
            <a
              href={cvDownloadUrl(cv.id, cv.fileName)}
              className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-stone-200 px-3 py-1.5 text-xs font-medium text-stone-700 hover:bg-stone-50 dark:border-stone-700 dark:text-stone-300 dark:hover:bg-stone-800"
            >
              <Download className="h-3.5 w-3.5" /> Download
            </a>
          )}
          {!isDefault && (
            <Button variant="secondary" onClick={onSetDefault} disabled={busy}>
              <Star className="h-4 w-4" /> Set as default
            </Button>
          )}
          {cv.analysis && (
            <Button variant="secondary" onClick={() => setReviewOpen((o) => !o)}>
              {reviewOpen ? 'Hide analysis' : 'Review analysis'}
            </Button>
          )}
          <Button variant="secondary" onClick={() => setDialog({ force: Boolean(cv.analysis) })} disabled={busy || !cv.rawText}>
            <Sparkles className="h-4 w-4" /> {cv.analysis ? 'Re-analyze' : 'Analyze with AI'}
          </Button>
          <Button variant="ghost" onClick={() => setEditing(true)} disabled={busy || editing}>
            <Pencil className="h-4 w-4" /> Rename
          </Button>
          {confirming ? (
            <span className="inline-flex items-center gap-1.5 text-xs">
              <span className="text-stone-600 dark:text-stone-400">Delete this CV?</span>
              <Button variant="secondary" onClick={() => { setConfirming(false); onDelete() }} disabled={busy}>Delete</Button>
              <Button variant="ghost" onClick={() => setConfirming(false)}>Keep</Button>
            </span>
          ) : (
            <Button
              variant="ghost"
              onClick={() => setConfirming(true)}
              disabled={busy || !canDelete}
              title={canDelete ? undefined : 'Set another CV as default first'}
            >
              <Trash2 className="h-4 w-4" /> Delete
            </Button>
          )}
        </div>
      </div>
      {reviewOpen && cv.analysis && (
        <CvAnalysisReview profile={profile} cv={cv} isDefault={isDefault} onApply={onApplyAnalysis} onRetrySync={onRetrySync} />
      )}
      {dialog && (
        <CvAnalyzeDialog
          profile={profile}
          cv={cv}
          force={cv.analysis ? dialog.force : false}
          onClose={() => setDialog(null)}
          onDone={(result) => {
            onAnalysis({
              facts: result.facts,
              rejected: result.rejected,
              fingerprint: result.fingerprint,
              provider: result.provider,
              model: result.model,
              analyzedAt: result.analyzedAt,
              promptVersion: result.promptVersion,
            })
            setDialog(null)
            setReviewOpen(true)
          }}
        />
      )}
    </Card>
  )
}

export default function CvLibrary() {
  const { profile, cvActions } = useProfile()
  const [uploading, setUploading] = useState(false)
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const fileInput = useRef(null)

  const library = profile.cvLibrary || []

  const upload = async (file) => {
    setError(null)
    setNotice(null)
    setUploading(true)
    try {
      const rawText = await extractTextFromPdf(file)
      const { parsedData, usedFallback } = await cvEntryParsedData(rawText, { parse: parseImportText, fallback: (text) => extractProfileFromResume(text).parsedData })
      const id = await uploadCvFile(file)
      if (!id) throw new Error('The local API is not reachable, so the PDF could not be saved.')
      cvActions.addCv({
        id,
        fileName: file.name,
        uploadedAt: new Date().toISOString(),
        filePath: `profile/cvs/${id}.pdf`,
        rawText,
        parsedData,
        importSource: 'resume_pdf',
      })
      setNotice(`Added ${file.name}. It is not the default; use "Set as default" to make it the CV the app reads.${usedFallback ? ' The server reader could not be used, so the older in-browser reader filled its data; check it.' : ''}`)
    } catch (e) {
      setError(e.message || 'Failed to read this PDF.')
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const recordApply = (cv, count, result) => cvActions.patchCvAnalysis(cv.id, {
    lastApply: { at: new Date().toISOString(), count, state: result.ok ? 'synced' : 'failed', error: result.error || null },
  })

  // Write the ticked suggestions, then regenerate intelligence from the result so
  // scoring sees them, the same as the Regenerate Intelligence button.
  const applyAnalysis = async (cv, selected) => {
    setError(null)
    // The server keeps a verified backup of the profile first, as the import does; without it nothing is changed.
    const taken = await applyWithBackup({
      profile,
      backup: backupProfileForImport,
      apply: () => cvActions.applyCvAnalysis(cv.id, selected),
    })
    if (!taken.ok) { setError(taken.message); return }
    const applied = taken.result
    if (!applied || applied.count === 0) return
    recordApply(cv, applied.count, await regenerateAndSync(applied.profile))
  }

  const retrySync = async (cv) => {
    recordApply(cv, cv.analysis?.lastApply?.count || 0, await regenerateAndSync(profile))
  }

  const remove = async (cv) => {
    setError(null)
    setNotice(null)
    setBusyId(cv.id)
    try {
      if (cv.filePath) await deleteCvFile(cv.id)
      cvActions.removeCv(cv.id)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-stone-600 dark:text-stone-400">
          The CVs you uploaded. The default one is what the app reads for your skills, projects and experience.
          Resumes made for one job are under Resumes.
        </p>
        <label className={`inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-lg bg-teal-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-teal-700 ${uploading ? 'pointer-events-none opacity-60' : ''}`}>
          {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          Upload new CV
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf,.pdf"
            className="hidden"
            disabled={uploading}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f) }}
          />
        </label>
      </div>

      {error && <Alert variant="error" title="My CVs">{error}</Alert>}
      {notice && <Alert variant="success" title="CV added">{notice}</Alert>}

      {library.length === 0 ? (
        <Card>
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <FileText className="h-10 w-10 text-stone-400" />
            <p className="font-medium text-stone-900 dark:text-stone-100">No CV uploaded yet</p>
            <p className="text-sm text-stone-600 dark:text-stone-400">Upload a PDF to keep it here. The first one becomes your default.</p>
          </div>
        </Card>
      ) : (
        library.map((cv) => (
          <CvCard
            key={cv.id}
            cv={cv}
            profile={profile}
            isDefault={cv.id === profile.defaultCvId}
            canDelete={canRemoveCv(profile, cv.id)}
            busy={busyId === cv.id}
            onSetDefault={() => { setNotice(null); cvActions.setDefaultCv(cv.id) }}
            onRename={(label) => cvActions.renameCv(cv.id, label)}
            onDelete={() => remove(cv)}
            onAnalysis={(analysis) => cvActions.setCvAnalysis(cv.id, analysis)}
            onApplyAnalysis={(selected) => applyAnalysis(cv, selected)}
            onRetrySync={() => retrySync(cv)}
          />
        ))
      )}
    </div>
  )
}
