import { useEffect, useState } from 'react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import Textarea from '../ui/Textarea'
import { loadGateUsage, saveGateSettings } from '../../modules/ai/gateClient'

// The discovery title filter's phrase lists (Settings `roleFilter`, package 3). The server validates and holds the defaults; this panel
// only shows and saves them, one phrase per line. A change applies from the next discovery run.
const LISTS = [
  { key: 'exclude', label: 'Exclude (dropped: a title holding one of these never reaches scoring)' },
  { key: 'include', label: 'Target (a title holding one of these is a target role; at least one phrase)' },
  { key: 'near', label: 'Near (neighbouring roles: kept, and scoring judges them)' },
  { key: 'positionWhitelist', label: "Board position counted as target (a board's own hand-assigned position)" },
]

const toText = (list) => (list || []).join('\n')
const toList = (text) => String(text).split('\n').map((line) => line.trim()).filter(Boolean)

export default function TitleFilterPanel() {
  const [form, setForm] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let live = true
    loadGateUsage()
      .then((body) => {
        if (!live) return
        const lists = body.settings?.roleFilter || {}
        setForm(Object.fromEntries(LISTS.map(({ key }) => [key, toText(lists[key])])))
      })
      .catch((err) => live && setLoadError(err.message))
    return () => { live = false }
  }, [])

  const save = async () => {
    setBusy(true)
    setResult(null)
    try {
      const roleFilter = Object.fromEntries(LISTS.map(({ key }) => [key, toList(form[key])]))
      const answer = await saveGateSettings({ roleFilter })
      setResult(answer)
      if (answer?.ok && answer.settings?.roleFilter) {
        setForm(Object.fromEntries(LISTS.map(({ key }) => [key, toText(answer.settings.roleFilter[key])])))
      }
    } catch (err) {
      setResult({ errors: [err.message] })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="Title filter">
      <p className="mb-3 text-sm text-stone-600 dark:text-stone-400">
        Which ad titles discovery keeps. One phrase per line; matching ignores case and Serbian diacritics, on whole words. A change applies
        from the next discovery run.
      </p>
      {loadError && <Alert variant="error" title="Could not read the title filter">{loadError}</Alert>}
      {form && (
        <div className="flex flex-col gap-3">
          {LISTS.map(({ key, label }) => (
            <Textarea
              key={key}
              id={`title-filter-${key}`}
              label={label}
              rows={5}
              value={form[key]}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
            />
          ))}
          <div>
            <Button onClick={save} disabled={busy}>Save title filter</Button>
          </div>
          {result?.errors && <Alert variant="error" title="Not saved">{result.errors.join('; ')}</Alert>}
          {result?.ok && <Alert variant="success">Saved.</Alert>}
        </div>
      )}
    </Card>
  )
}
