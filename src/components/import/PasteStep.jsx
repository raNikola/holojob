import { useState } from 'react'
import { ArrowLeft, Loader2 } from 'lucide-react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import Textarea from '../ui/Textarea'
import { MAX_PASTE_BYTES, pasteSize } from '../../modules/profile/importApi'

export default function PasteStep({ onParse, onBack, busy, error }) {
  const [text, setText] = useState('')
  const size = pasteSize(text)
  const tooLarge = size > MAX_PASTE_BYTES

  return (
    <Card title="Paste text" description="Paste your CV, or the About, Experience, Education and Skills sections of your LinkedIn profile. English headings work best.">
      <Textarea
        label="Text"
        rows={14}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={'Jane Sample\nProduct Manager\n\nEXPERIENCE\nProduct Manager, Acme | Jan 2020 - Present\n- Led a team of eight\n\nSKILLS\nRoadmapping, SQL'}
        error={tooLarge ? 'This is over the 200 KB limit.' : undefined}
      />
      <p className="mt-1 text-xs text-stone-500">{Math.round(size / 1024)} KB of 200 KB</p>
      {error && <div className="mt-4"><Alert variant="error" title="Could not read the text">{error}</Alert></div>}
      <div className="mt-4 flex items-center justify-between gap-3">
        <Button variant="ghost" onClick={onBack} disabled={busy}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
        <Button onClick={() => onParse(text)} disabled={busy || !text.trim() || tooLarge}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          Read the text
        </Button>
      </div>
    </Card>
  )
}
