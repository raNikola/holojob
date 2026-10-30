import InfoTip from '../ui/InfoTip'

export const JOBERTY_HELP = "Reads Joberty's public API (Product Management category). Check Joberty's terms before enabling."

/** The opt-in sources of the scrape: one box per source that is in no default group. */
export default function DiscoverySourceOptions({ options, onChange, disabled = false }) {
  return (
    <div className="flex items-center gap-2">
      <label className="flex items-center gap-2 text-sm text-stone-700 dark:text-stone-300">
        <input
          type="checkbox"
          checked={options.includeJoberty}
          disabled={disabled}
          onChange={(e) => onChange({ ...options, includeJoberty: e.target.checked })}
          className="rounded border-stone-300 text-teal-600 focus:ring-teal-500"
        />
        Include Joberty (Serbian IT board)
      </label>
      <InfoTip text={JOBERTY_HELP} label="About Joberty" />
    </div>
  )
}
