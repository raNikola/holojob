import { useEffect, useState } from 'react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Input from '../ui/Input'
import AIProviderSelector from './AIProviderSelector'
import AIModelSelector from './AIModelSelector'
import AIFeatureToggles from './AIFeatureToggles'
import AIHealthStatus from './AIHealthStatus'
import AIUsageDashboard from './AIUsageDashboard'
import AIBudgetPanel from './AIBudgetPanel'
import { loadAiSettings, saveAiSettings } from '../../modules/ai/aiSettings'
import { fetchSecretsStatus } from '../../modules/ai/secretsClient'
import { KEYLESS_PROVIDERS } from '../../modules/ai/aiProviderRegistry'
import { clearAiCache } from '../../modules/ai/aiResponseCache'
import { clearAiUsage } from '../../modules/ai/aiUsageTracker'

export default function AISettingsPanel() {
  const [settings, setSettings] = useState(() => loadAiSettings())
  const [saved, setSaved] = useState(false)
  const [keyEntry, setKeyEntry] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetchSecretsStatus().then((result) => {
      if (!cancelled) setKeyEntry(result.ok ? result.data.ai?.[settings.provider] ?? null : null)
    })
    return () => { cancelled = true }
  }, [settings.provider])

  const handleSave = () => {
    saveAiSettings(settings)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="space-y-6">
      <AIBudgetPanel />

      <Card title="AI Provider">
        <div className="space-y-4">
          <AIProviderSelector settings={settings} onChange={setSettings} />
          <AIModelSelector settings={settings} onChange={setSettings} />
          {!KEYLESS_PROVIDERS.has(settings.provider) && (
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
          <Button onClick={handleSave}>Save AI settings</Button>
          {saved && <p className="text-xs text-teal-700 dark:text-teal-300">Settings saved.</p>}
        </div>
      </Card>

      <Card title="Provider health">
        <AIHealthStatus />
      </Card>

      <Card title="Feature toggles">
        <AIFeatureToggles settings={settings} onChange={setSettings} />
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
