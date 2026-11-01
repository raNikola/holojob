import { useState } from 'react'
import { ArrowLeft, Loader2, Upload } from 'lucide-react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Alert from '../ui/Alert'

const COPY = {
  resume_pdf: {
    title: 'Upload a resume PDF',
    description: 'PDF only, up to 10 MB. English headings work best. The file is read on this server; nothing is saved until you have reviewed it.',
    drop: 'Drag & drop your resume PDF here',
  },
  linkedin_pdf: {
    title: 'Upload your LinkedIn PDF',
    description: 'On your LinkedIn profile choose "Save to PDF", then drop the file here. PDF only, up to 10 MB. Nothing is saved until you have reviewed it.',
    drop: 'Drag & drop your LinkedIn profile PDF here',
  },
}

export default function PdfStep({ source, onFile, onBack, busy, error }) {
  const [dragOver, setDragOver] = useState(false)
  const copy = COPY[source] || COPY.resume_pdf

  const pick = (file) => { if (file && !busy) onFile(file) }

  return (
    <Card title={copy.title} description={copy.description}>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); pick(e.dataTransfer.files?.[0]) }}
        className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 transition-colors ${dragOver ? 'border-teal-500 bg-teal-50/50 dark:bg-teal-900/10' : 'border-stone-300 dark:border-stone-700'}`}
      >
        {busy ? <Loader2 className="h-10 w-10 animate-spin text-teal-600" /> : <Upload className="h-10 w-10 text-stone-400" />}
        <p className="mt-4 text-sm font-medium text-stone-700 dark:text-stone-300">{busy ? 'Reading the PDF...' : copy.drop}</p>
        <p className="mt-1 text-xs text-stone-500">or</p>
        <label className="mt-3 cursor-pointer">
          <span className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700">Browse files</span>
          <input type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} disabled={busy} />
        </label>
      </div>
      {error && <div className="mt-4"><Alert variant="error" title="Could not read the PDF">{error}</Alert></div>}
      <div className="mt-4">
        <Button variant="ghost" onClick={onBack} disabled={busy}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
      </div>
    </Card>
  )
}
