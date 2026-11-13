import { Plus, Trash2, Link2, FolderOpen, RefreshCw, Loader2 } from 'lucide-react'
import Card from '../ui/Card'
import OperationConsole from '../ui/OperationConsole'
import { useRepoScan } from '../../hooks/useRepoScan'
import { useProfile } from '../../context/ProfileContext'
import { isValidUrl } from '../../utils/validators'
import { saveProfileToDataDir } from '../../modules/jobs/profileSync'

function DynamicList({ icon: Icon, label, description, items, onChange, placeholder, validateUrl }) {
  const update = (index, value) => {
    const next = [...items]
    next[index] = value
    onChange(next)
  }
  const add = () => onChange([...items, ''])
  const remove = (index) => onChange(items.filter((_, i) => i !== index))

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-5 w-5 text-teal-600 dark:text-teal-400" />
        <div>
          <h4 className="text-sm font-semibold text-stone-800 dark:text-stone-200">{label}</h4>
          <p className="text-xs text-stone-500 dark:text-stone-400">{description}</p>
        </div>
      </div>
      <div className="space-y-2">
        {items.length === 0 && (
          <p className="text-sm text-stone-400 italic">No entries yet. Click add to include one.</p>
        )}
        {items.map((item, i) => {
          const invalid = validateUrl && item && !isValidUrl(item)
          return (
            <div key={i} className="flex gap-2">
              <input
                value={item}
                onChange={(e) => update(i, e.target.value)}
                placeholder={placeholder}
                className={`flex-1 rounded-lg border px-3 py-2 text-sm dark:bg-stone-950 dark:text-stone-50 ${invalid ? 'border-red-400' : 'border-stone-300 dark:border-stone-700'}`}
              />
              <button type="button" onClick={() => remove(i)} className="rounded-lg p-2 text-stone-400 hover:text-red-500">
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          )
        })}
        <button type="button" onClick={add} className="inline-flex items-center gap-1 text-sm text-teal-600 hover:text-teal-700 dark:text-teal-400">
          <Plus className="h-4 w-4" /> Add
        </button>
      </div>
    </div>
  )
}

export default function RepositoryForm() {
  const { profile, updateProfile } = useProfile()
  const repos = profile.repositories
  const { projectIntel, scanning, scanMsg, scanLog, scan, canScan } = useRepoScan(profile)
  const scannedAt = projectIntel?.meta?.scannedAt
  const repoCount = projectIntel?.projects?.length

  const setRepos = (field, value) => {
    // Keep empty rows while editing — blanks are filtered at consumption time.
    updateProfile((prev) => {
      const next = { ...prev, repositories: { ...prev.repositories, [field]: value } }
      // Sync to disk so Python tools always read fresh repo lists.
      // Fire-and-forget; no need to await.
      saveProfileToDataDir(next)
      return next
    })
  }

  return (
    <div className="space-y-6">
      <Card title="GitHub & local repositories" description="Add your GitHub profile links and local project folder paths. Both are optional.">
        <div className="space-y-8">
          <DynamicList
            icon={Link2}
            label="GitHub links"
            description="Public GitHub profile or repository URLs"
            items={repos.githubLinks.length ? repos.githubLinks : ['']}
            onChange={(v) => setRepos('githubLinks', v)}
            placeholder="https://github.com/username"
            validateUrl
          />
          <DynamicList
            icon={FolderOpen}
            label="Local repo paths"
            description="Absolute or relative paths to projects on your machine"
            items={repos.localRepoPaths.length ? repos.localRepoPaths : ['']}
            onChange={(v) => setRepos('localRepoPaths', v)}
            placeholder="/Users/you/projects/my-app"
          />
        </div>
      </Card>
      <Card title="Scan repositories" description="Claude Code mines your repos for skills, metrics and project summaries, which pre-fill the questionnaire.">
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={scan}
            disabled={!canScan || scanning}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-teal-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-700 disabled:opacity-60"
          >
            {scanning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            {projectIntel ? 'Re-scan repos' : 'Scan GitHub repos'}
          </button>
          <p className="text-xs text-stone-600 dark:text-stone-400">
            {scanMsg || (!canScan
              ? 'Add a GitHub link or a local path above to enable scanning.'
              : projectIntel && (scannedAt || repoCount != null)
                ? `Last scan: ${[scannedAt && new Date(scannedAt).toLocaleDateString(), repoCount != null && `${repoCount} repo(s)`].filter(Boolean).join(' · ')}`
                : '')}
          </p>
        </div>
        <OperationConsole lines={scanLog.lines} active={scanLog.active} title={scanning ? 'Scanning repos…' : 'Scan log'} className="mt-2 w-full" />
      </Card>
    </div>
  )
}