import RequiredMark from './RequiredMark'

export default function SelectField({ label, labelExtra, id, required, error, value, onChange, options = [], placeholder = 'Select...' }) {
  return (
    <div>
      {label && (
        <div className="mb-1.5 flex items-center gap-1">
          <label htmlFor={id} className="text-sm font-medium text-stone-700 dark:text-stone-300">{label}{required && <RequiredMark />}</label>
          {labelExtra}
        </div>
      )}
      <select
        id={id}
        aria-required={required || undefined}
        aria-invalid={error ? true : undefined}
        aria-describedby={error && id ? `${id}-error` : undefined}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full rounded-lg border px-3 py-2.5 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500/30 dark:bg-stone-950 dark:text-stone-50 ${error ? 'border-red-400' : 'border-stone-300 dark:border-stone-700'}`}
      >
        <option value="">{placeholder}</option>
        {options.map((opt) => {
          const { value: optValue, label: optLabel } = typeof opt === 'string' ? { value: opt, label: opt } : opt
          return <option key={optValue} value={optValue}>{optLabel}</option>
        })}
      </select>
      {error && <p id={id ? `${id}-error` : undefined} className="mt-1 text-xs text-red-500">{error}</p>}
    </div>
  )
}
