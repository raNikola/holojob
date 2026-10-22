export default function Badge({ children, variant = 'default' }) {
  const variants = {
    default: 'bg-stone-100 text-stone-700 dark:bg-stone-800 dark:text-stone-300',
    high: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
    medium: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
    warn: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
    low: 'bg-stone-100 text-stone-500 dark:bg-stone-800 dark:text-stone-400',
  }
  return <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${variants[variant]}`}>{children}</span>
}