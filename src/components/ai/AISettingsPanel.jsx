import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Input from '../ui/Input'
import Alert from '../ui/Alert'
import AIProviderSelector from './AIProviderSelector'
import AIModelSelector from './AIModelSelector'
import AIServiceTierSelector from './AIServiceTierSelector'
import AIFeatureToggles from './AIFeatureToggles'
import AIHealthStatus from './AIHealthStatus'
import AIUsageDashboard from './AIUsageDashboard'
import AIBudgetPanel from './AIBudgetPanel'
import {
  formFromSelection, migrateAiSettingsToServer, readLegacyAiSettings, selectionFromForm,
} from '../../modules/ai/aiSettings'
import { fetchAiSelection, putAiSelection } from '../../modules/ai/aiSelectionClient'
import { fetchSecretsStatus } from '../../modules/ai/secretsClient'
import { KEYLESS_PROVIDERS } from '../../modules/ai/aiProviderRegistry'
import { clearAiCache } from '../../modules/ai/aiResponseCache'
import { clearAiUsage } from '../../modules/ai/aiUsageTracker'

export default function AISettingsPanel() {
  const [settings, setSettings] = useState(() => formFromSelection(null))
  const [server, setServer] = useState(null) // { selection, providers, nodeProviders, class, error } from GET /api/ai/selection
  const [loadError, setLoadError] = useState(null)
  const [result, setResult] = useState(null) // { ok } | { needsConfirm, increases } | { errors }
  const [busy, setBusy] = useState(false)
  const [keyEntry, setKeyEntry] = useState(null)
  const [legacy, setLegacy] = useState(() => readLegacyAiSettings())
  const [migration, setMigration] = useState(null) // { message?, error?, needsConfirm?, conflict? }

  const refresh = useCallback(async () => {
    const loaded = await fetchAiSelection()
    if (!loaded.ok) {
      setLoadError(loaded.error)
      return
    }
    setLoadError(null)
    setServer(loaded.data)
    setSettings(formFromSelection(loaded.data.selection))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  useEffect(() => {
    let cancelled = false
    fetchSecretsStatus().then((r) => {
      if (!cancelled) setKeyEntry(r.ok ? r.data.ai?.[settings.provider] ?? null : null)
    })
    return () => { cancelled = true }
  }, [settings.provider])

  const save = async (confirm) => {
    setBusy(true)
    const saved = await putAiSelection(selectionFromForm(settings), { confirm })
    setBusy(false)
    setResult(saved)
    if (saved.ok) refresh()
  }

  const migrate = async (options = {}) => {
    setBusy(true)
    const done = await migrateAiSettingsToServer(options)
    setBusy(false)
    if (done.ok) {
      setLegacy(readLegacyAiSettings())
      setMigration({ message: done.keyRemains
        ? 'Moved. The settings are on the server and removed from this browser. An API key is still in this browser: move it in Privacy: secrets and keys.'
        : 'Moved. The settings are on the server and removed from this browser.' })
      refresh()
    } else if (done.needsConfirm || done.conflict) {
      setMigration(done)
    } else {
      setMigration({ error: done.error })
      if (done.onServer) setLegacy(readLegacyAiSettings())
    }
  }

  const selection = server?.selection
  const providers = server?.providers || []
  const nodeProviders = server?.nodeProviders || []

  return (
    <div className="space-y-6">
      <AIBudgetPanel />

      <Card title="AI Provider" description="The provider and its settings are stored on the server, in one file that the browser features and the Python pipeline both read. Nothing is stored in this browser.">
        <div className="space-y-4">
          {loadError && <Alert variant="error" title="AI settings">{loadError}</Alert>}
          {server?.error && <Alert variant="error" title="AI settings file">{server.error}. Calls are refused until it is fixed or saved again here.</Alert>}
          {!server && !loadError && (
            <p className="flex items-center gap-2 text-sm text-stone-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</p>
          )}

          {legacy && (
            <Alert variant="info" title="AI settings are stored in this browser">
              <p className="mb-3">
                An older version saved the provider{legacy.provider ? ` (${legacy.provider}${legacy.model ? `, ${legacy.model}` : ''})` : ''}, model,
                temperature, token limit and feature toggles here. Move them to the server; they are removed from this browser only after
                the server confirms them. No key is moved by this button.
              </p>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => migrate()} disabled={busy}>
                  {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                  Move AI settings to server
                </Button>
              </div>
            </Alert>
          )}
          {migration?.message && <Alert variant="success">{migration.message}</Alert>}
          {migration?.error && <Alert variant="error" title="Not moved">{migration.error}</Alert>}
          {migration?.needsConfirm && (
            <Alert variant="error" title="Confirm: this selects a provider that can spend money">
              <ul className="list-disc pl-5">{migration.increases.map((line) => <li key={line}>{line}</li>)}</ul>
              <Button className="mt-3" onClick={() => migrate({ confirm: true })} disabled={busy}>Confirm and move</Button>
            </Alert>
          )}
          {migration?.conflict && (
            <Alert variant="error" title="The server already has different AI settings">
              <p>Server: {migration.server.provider} / {migration.server.model}. This browser: {migration.browser.provider} / {migration.browser.model}.</p>
              <Button className="mt-3" onClick={() => migrate({ overwrite: true })} disabled={busy}>Replace the server&apos;s with this browser&apos;s</Button>
            </Alert>
          )}

          {server && !selection && !server.error && (
            <Alert variant="info" title="No provider selected">
              Every AI call, in the browser and in the Python pipeline, is refused until you pick a provider and save.
            </Alert>
          )}

          <AIProviderSelector settings={settings} onChange={setSettings} providers={providers} nodeProviders={nodeProviders} />
          <AIModelSelector settings={settings} onChange={setSettings} />
          <AIServiceTierSelector settings={settings} onChange={setSettings} />
          {settings.provider && !KEYLESS_PROVIDERS.has(settings.provider) && (
            <p className="text-sm text-stone-600 dark:text-stone-400">
              API key: {keyEntry?.set ? `set on the server (…${keyEntry.last4})` : 'not set'}. It is entered and replaced in
              Privacy: secrets and keys, below.
            </p>
          )}
          {settings.provider === 'claude-code' && (
            <p className="text-xs text-stone-500">
              Uses your local Claude Code CLI with your Claude Pro/Max login — no API key.
              Run <code>claude</code> in a terminal and <code>/login</code> once if health shows offline.
            </p>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-stone-700 dark:text-stone-300">Temperature</label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={settings.temperature}
                onChange={(e) => setSettings({ ...settings, temperature: parseFloat(e.target.value) })}
                className="w-full"
              />
              <span className="text-xs text-stone-500">{settings.temperature}</span>
            </div>
            <Input
              label="Max tokens"
              type="number"
              value={settings.maxTokens}
              onChange={(e) => setSettings({ ...settings, maxTokens: parseInt(e.target.value, 10) || 2000 })}
            />
          </div>
          <Button onClick={() => save(false)} disabled={busy || !settings.provider || !settings.model}>Save AI settings</Button>
          {result?.ok && <p className="text-xs text-teal-700 dark:text-teal-300">Settings saved.</p>}
          {result?.errors && <Alert variant="error" title="Not saved">{result.errors.join('; ')}</Alert>}
          {result?.needsConfirm && (
            <Alert variant="error" title="Confirm: this selects a provider that can spend money">
              <ul className="list-disc pl-5">{result.increases.map((line) => <li key={line}>{line}</li>)}</ul>
              <Button className="mt-3" onClick={() => save(true)} disabled={busy}>Confirm and save</Button>
            </Alert>
          )}
        </div>
      </Card>

      <Card title="Provider health">
        <AIHealthStatus />
      </Card>

      <Card title="Feature toggles">
        <AIFeatureToggles settings={settings} onChange={setSettings} />
        <p className="mt-2 text-xs text-stone-500">Toggles are saved with the button above.</p>
      </Card>

      <Card title="Usage & cost (this browser)">
        <AIUsageDashboard />
        <div className="mt-3 flex gap-2">
          <Button variant="secondary" onClick={() => clearAiCache()}>Clear cache</Button>
          <Button variant="ghost" onClick={() => clearAiUsage()}>Clear browser usage log</Button>
        </div>
      </Card>
    </div>
  )
}
