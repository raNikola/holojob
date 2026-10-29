import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Input from '../ui/Input'
import Alert from '../ui/Alert'
import SelectField from '../ui/SelectField'
import { PROVIDER_DEFAULTS, loadAiSettings, maskApiKey, readLegacyAiKey, clearLegacyAiKey } from '../../modules/ai/aiSettings'
import {
  KEYED_AI_PROVIDERS,
  deleteAiSecret,
  fetchSecretsStatus,
  moveLegacyKeyToServer,
  putAiSecret,
} from '../../modules/ai/secretsClient'

/** claude and gemini use fixed endpoints in their providers, so a base URL would do nothing for them. */
const TAKES_BASE_URL = new Set(['openai', 'openrouter'])

function describeRow(entry) {
  if (!entry?.set) return 'not set'
  const where = entry.source === 'env' ? '.env' : 'Settings'
  return `set …${entry.last4} · source: ${where}${entry.baseUrl ? ` · base URL: ${entry.baseUrl}` : ''}`
}

/** The default provider for moving a browser key: the saved one when it takes a key, else none (the owner picks). */
function legacyDefaults(legacy) {
  const provider = KEYED_AI_PROVIDERS.includes(legacy?.provider) ? legacy.provider : ''
  const base = provider ? legacy.baseUrl : ''
  return { provider, baseUrl: base && base !== PROVIDER_DEFAULTS[provider]?.baseUrl ? base : '' }
}

export default function SecretsPanel() {
  const [status, setStatus] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [editing, setEditing] = useState(null) // { provider, key, baseUrl }
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)
  const [legacy, setLegacy] = useState(() => readLegacyAiKey())
  const [moveTo, setMoveTo] = useState(() => legacyDefaults(readLegacyAiKey()))

  const refresh = useCallback(async () => {
    const result = await fetchSecretsStatus()
    if (result.ok) {
      setStatus(result.data.ai)
      setLoadError(result.data.unreadable ? 'The secret store file cannot be read. Nothing was changed.' : null)
    } else {
      setLoadError(result.error)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const startEdit = (provider) => {
    setMessage(null)
    setError(null)
    setEditing({ provider, key: '', baseUrl: status?.[provider]?.baseUrl || '' })
  }

  const handleSave = async () => {
    setBusy(true)
    setError(null)
    const result = await putAiSecret(editing.provider, { key: editing.key, baseUrl: editing.baseUrl.trim() })
    setBusy(false)
    if (!result.ok) {
      setError(result.error)
      return
    }
    setEditing(null) // the typed key is dropped with the form state
    setMessage(`${editing.provider}: key saved on the server.`)
    refresh()
  }

  const handleRemove = async (provider) => {
    if (!window.confirm(`Remove the stored ${provider} key from the server?`)) return
    setBusy(true)
    const result = await deleteAiSecret(provider)
    setBusy(false)
    if (!result.ok) setError(result.error)
    else setMessage(`${provider}: stored key removed.`)
    refresh()
  }

  const handleMove = async () => {
    // Another browser profile may hold an older key than the one now on the server (after a rotation).
    const onServer = status?.[moveTo.provider]
    if (onServer?.source === 'store') {
      const here = legacy.apiKey.trim().slice(-4)
      if (onServer.last4 === here) {
        setError(`The server already holds this key (…${here}). Use "Remove from this browser without moving".`)
        return
      }
      if (!window.confirm(`The server already holds a ${moveTo.provider} key ending …${onServer.last4}. This browser's key ends …${here}. Replace the server's key with this browser's?`)) return
    }
    setBusy(true)
    setError(null)
    setMessage(null)
    const result = await moveLegacyKeyToServer({ provider: moveTo.provider, baseUrl: moveTo.baseUrl.trim() })
    setBusy(false)
    if (!result.ok) {
      setError(result.error)
      if (result.onServer) setLegacy(readLegacyAiKey())
    } else {
      setLegacy(null)
      setMessage('Moved. The key is on the server and removed from this browser. Rotate it at the provider now (see the checklist in docs/redesign/BROWSER_STORAGE_POLICY.md, section 4).')
    }
    refresh()
  }

  const handleDiscard = () => {
    if (!window.confirm('Remove the key from this browser without moving it to the server?')) return
    if (clearLegacyAiKey()) {
      setLegacy(null)
      setMessage('The key was removed from this browser.')
    } else {
      setError('The key could not be removed from this browser.')
    }
  }

  return (
    <Card
      title="Privacy: secrets and keys"
      description="AI provider keys live on the server only (data/secrets/). This screen shows whether a key is set and its last 4 characters; it can never show the key."
    >
      <div className="space-y-4">
        {message && <Alert variant="success">{message}</Alert>}
        {error && <Alert variant="error" title="Not done">{error}</Alert>}
        {loadError && <Alert variant="error" title="Secret store">{loadError}</Alert>}

        {legacy && (
          <Alert variant="info" title="A key is stored in this browser">
            <p className="mb-3">
              An older version saved the key ({maskApiKey(legacy.apiKey)}) here, in plain text. Move it to the server;
              it is removed from this browser only after the server confirms it.
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <SelectField
                label="This key is for"
                value={moveTo.provider}
                onChange={(provider) => setMoveTo({ ...moveTo, provider })}
                options={KEYED_AI_PROVIDERS}
              />
              {TAKES_BASE_URL.has(moveTo.provider) && <Input
                label="Base URL (only if not the provider's own)"
                value={moveTo.baseUrl}
                onChange={(e) => setMoveTo({ ...moveTo, baseUrl: e.target.value })}
                placeholder={PROVIDER_DEFAULTS[moveTo.provider]?.baseUrl || ''}
                autoComplete="off"
              />}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button onClick={handleMove} disabled={busy || !moveTo.provider}>
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                Move to server
              </Button>
              <Button variant="ghost" onClick={handleDiscard} disabled={busy}>Remove from this browser without moving</Button>
            </div>
          </Alert>
        )}

        {!status && !loadError && (
          <p className="flex items-center gap-2 text-sm text-stone-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</p>
        )}

        {status && (
          <ul className="divide-y divide-stone-200 dark:divide-stone-800">
            {KEYED_AI_PROVIDERS.map((provider) => {
              const entry = status[provider]
              return (
                <li key={provider} className="flex flex-wrap items-center justify-between gap-2 py-3">
                  <div>
                    <p className="text-sm font-medium text-stone-800 dark:text-stone-100">{provider}</p>
                    <p className="text-xs text-stone-500">{describeRow(entry)}</p>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="secondary" onClick={() => startEdit(provider)} disabled={busy}>
                      {entry?.set ? 'Replace' : 'Set key'}
                    </Button>
                    {entry?.source === 'store' && (
                      <Button variant="ghost" onClick={() => handleRemove(provider)} disabled={busy}>Remove</Button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}

        {editing && (
          <form
            className="space-y-3 rounded-lg border border-stone-200 p-4 dark:border-stone-800"
            autoComplete="off"
            onSubmit={(e) => { e.preventDefault(); handleSave() }}
          >
            <p className="text-sm font-medium text-stone-800 dark:text-stone-100">{editing.provider}</p>
            <Input
              label="API key"
              type="password"
              value={editing.key}
              onChange={(e) => setEditing({ ...editing, key: e.target.value })}
              autoComplete="off"
              spellCheck={false}
            />
            {TAKES_BASE_URL.has(editing.provider) && (
              <Input
                label="Base URL (optional; the key is sent only there)"
                value={editing.baseUrl}
                onChange={(e) => setEditing({ ...editing, baseUrl: e.target.value })}
                placeholder={PROVIDER_DEFAULTS[editing.provider]?.baseUrl || ''}
                autoComplete="off"
              />
            )}
            <div className="flex gap-2">
              <Button type="submit" disabled={busy || !editing.key}>Save on server</Button>
              <Button type="button" variant="ghost" onClick={() => setEditing(null)} disabled={busy}>Cancel</Button>
            </div>
          </form>
        )}

        <p className="text-xs text-stone-500">
          The active provider is chosen in AI Provider ({loadAiSettings().provider}). A key from <code>.env</code> is used only
          when no key is stored here.
        </p>
      </div>
    </Card>
  )
}
