import { Briefcase, ClipboardPaste, FileUp, PencilLine } from 'lucide-react'
import Card from '../ui/Card'

const SOURCES = [
  { id: 'file', icon: FileUp, title: 'Upload a file', text: 'A resume as a PDF or Word file, a text or Markdown file, or a JSON Resume file. Other file types are coming.' },
  { id: 'linkedin', icon: Briefcase, title: 'LinkedIn', text: 'The PDF you get from "Save to PDF" on your profile.' },
  { id: 'paste', icon: ClipboardPaste, title: 'Paste text', text: 'Paste your CV or the sections of your LinkedIn profile.' },
  { id: 'manual', icon: PencilLine, title: 'Enter manually', text: 'Skip the import and fill in your profile by hand.' },
]

export default function SourcePicker({ onPick }) {
  return (
    <Card title="Bring in your history" description="Pick where it comes from. You review everything before anything is saved.">
      <div className="grid gap-3 sm:grid-cols-2">
        {SOURCES.map(({ id, icon: Icon, title, text }) => (
          <button
            key={id}
            type="button"
            onClick={() => onPick(id)}
            className="flex gap-3 rounded-xl border border-stone-200 p-4 text-left transition-colors hover:border-teal-500 hover:bg-teal-50/40 focus:outline-none focus:ring-2 focus:ring-teal-500/40 dark:border-stone-700 dark:hover:bg-teal-900/10"
          >
            <Icon className="mt-0.5 h-5 w-5 shrink-0 text-teal-600 dark:text-teal-400" />
            <span>
              <span className="block text-sm font-medium text-stone-900 dark:text-stone-50">{title}</span>
              <span className="mt-0.5 block text-xs text-stone-500 dark:text-stone-400">{text}</span>
            </span>
          </button>
        ))}
      </div>
      <p className="mt-4 text-xs text-stone-500 dark:text-stone-400">
        Reading a file or text happens on this server. Nothing is sent to an AI provider.
      </p>
    </Card>
  )
}
