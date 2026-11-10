import SelectField from '../ui/SelectField'

export const SERVICE_TIER_OPTIONS = [
  { value: 'standard', label: 'Standard' },
  { value: 'flex', label: 'Flex (about half the price)' },
]

/** Only OpenAI has more than one price for a model; every other provider hides this. */
export default function AIServiceTierSelector({ settings, onChange }) {
  if (settings.provider !== 'openai') return null
  return (
    <div>
      <SelectField
        id="ai-service-tier"
        label="Processing option"
        value={settings.serviceTier === 'flex' ? 'flex' : 'standard'}
        onChange={(serviceTier) => onChange({ ...settings, serviceTier: serviceTier === 'flex' ? 'flex' : 'standard' })}
        options={SERVICE_TIER_OPTIONS}
      />
      <p className="mt-1 text-xs text-stone-500">
        Flex costs less but can be temporarily unavailable. When it is, the request fails with a clear message and is
        never silently replaced by Standard. Switch to Standard here yourself to continue.
      </p>
    </div>
  )
}
