import { useCallback, useEffect, useRef } from 'react'
import { X } from 'lucide-react'

export const TOAST_AUTO_HIDE_MS = 15000

const tone = {
  info: 'border-stone-200 bg-white text-stone-800 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-200',
  success: 'border-teal-200 bg-teal-50 text-teal-900 dark:border-teal-900 dark:bg-teal-950 dark:text-teal-100',
  warn: 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100',
  error: 'border-red-300 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100',
}

/** Bottom-right stack, outside the page flow. Renders nothing when it has no toasts. */
export function ToastStack({ children }) {
  const items = [children].flat(Infinity).filter(Boolean)
  if (!items.length) return null
  return (
    <div className="pointer-events-none fixed bottom-20 right-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2 md:bottom-4" data-testid="toast-stack">
      {items}
    </div>
  )
}

/**
 * One toast. `autoHideMs` (omit for persistent) counts down only while the pointer and the keyboard focus are both away: hovering or
 * focusing it pauses the timer, leaving resumes with the time that was left. Escape on the toast dismisses it. `onDismiss` omitted
 * means the toast has no X (a notice that cannot be closed).
 */
export function Toast({ children, kind = 'info', autoHideMs = null, onDismiss = null, className = '' }) {
  const left = useRef(autoHideMs)
  const startedAt = useRef(0)
  const timer = useRef(null)
  const dismissRef = useRef(onDismiss)
  const hovered = useRef(false)
  const focused = useRef(false)
  useEffect(() => { dismissRef.current = onDismiss })

  const stop = useCallback(() => {
    if (timer.current === null) return
    clearTimeout(timer.current)
    timer.current = null
    left.current = Math.max(0, left.current - (Date.now() - startedAt.current))
  }, [])
  const start = useCallback(() => {
    if (autoHideMs === null || timer.current !== null || hovered.current || focused.current) return
    startedAt.current = Date.now()
    timer.current = setTimeout(() => { timer.current = null; dismissRef.current?.() }, left.current)
  }, [autoHideMs])

  useEffect(() => {
    start()
    return () => { if (timer.current !== null) clearTimeout(timer.current); timer.current = null }
  }, [start])

  return (
    <div
      role={kind === 'error' ? 'alert' : 'status'}
      className={`pointer-events-auto flex items-start gap-2 rounded-lg border p-3 text-sm shadow-lg ${tone[kind] || tone.info} ${className}`}
      onMouseEnter={() => { hovered.current = true; stop() }}
      onMouseLeave={() => { hovered.current = false; start() }}
      onFocus={() => { focused.current = true; stop() }}
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) { focused.current = false; start() } }}
      onKeyDown={(event) => { if (event.key === 'Escape' && onDismiss) { event.stopPropagation(); onDismiss() } }}
    >
      <div className="min-w-0 flex-1">{children}</div>
      {onDismiss && (
        <button type="button" aria-label="Dismiss" onClick={onDismiss} className="shrink-0 rounded p-1 text-current opacity-70 hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-teal-500/40">
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}
