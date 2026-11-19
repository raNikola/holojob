/** A tab strip that wraps instead of scrolling sideways. `compact` is the slimmer variant for the page header. */
export default function Tabs({ tabs, active, onChange, className = '', compact = false }) {
  const size = compact ? 'px-3 py-1.5' : 'px-4 py-2'
  return (
    <div role="tablist" className={`flex flex-wrap gap-1 rounded-xl border border-stone-200 bg-stone-50 p-1 dark:border-stone-800 dark:bg-stone-900 ${className}`}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
          className={`whitespace-nowrap rounded-lg ${size} text-sm font-medium transition-all ${
            active === tab.id
              ? 'bg-white text-teal-700 shadow-sm dark:bg-stone-800 dark:text-teal-300'
              : 'text-stone-600 hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-200'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
