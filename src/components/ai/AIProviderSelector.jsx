import SelectField from '../ui/SelectField'
import Input from '../ui/Input'
import { PROVIDER_DEFAULTS } from '../../modules/ai/aiSettings'

/** `providers`: [{ name, class }] from the server; `nodeProviders`: the names the browser AI features can run. */
export default function AIProviderSelector({ settings, onChange, providers = [], nodeProviders = [] }) {
  const handleProviderChange = (provider) => {
    const defaults = PROVIDER_DEFAULTS[provider] || {}
    onChange({
      ...settings,
      provider,
      model: defaults.model || settings.model,
      baseUrl: defaults.baseUrl ?? settings.baseUrl,
    })
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <SelectField
        label="Provider"
        value={settings.provider}
        onChange={handleProviderChange}
        options={providers.map((p) => p.name)}
      />
      <p className="text-xs text-stone-500 sm:col-span-2">
        Class: {providers.find((p) => p.name === settings.provider)?.class ?? 'unknown'} (free and local calls cost nothing;
        paid and unknown ones count against the AI budget).
        {settings.provider && !nodeProviders.includes(settings.provider) && ' The browser AI features cannot run this provider; only the Python pipeline can.'}
        {['claude', 'gemini', 'mock'].includes(settings.provider) && ' The Python pipeline cannot run this provider; only the browser features can.'}
      </p>
      {settings.provider === 'ollama' && (
        <Input
          label="Base URL"
          value={settings.baseUrl}
          onChange={(e) => onChange({ ...settings, baseUrl: e.target.value })}
        />
      )}
    </div>
  )
}
