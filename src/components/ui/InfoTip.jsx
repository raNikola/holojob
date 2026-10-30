import { useEffect, useId, useRef, useState } from 'react'
import { Info } from 'lucide-react'

/**
 * An info icon with a tooltip. Opens on hover, keyboard focus and tap; closes on Escape, blur and
 * mouse leave. It sits above the icon so it never covers the field under the label.
 */
const TONES = {
  amber: 'bg-amber-100 text-amber-700 hover:bg-amber-200 dark:bg-amber-900/40 dark:text-amber-300',
  neutral: 'bg-stone-200 text-stone-600 hover:bg-stone-300 dark:bg-stone-700 dark:text-stone-300',
}

/**
 * `glyph` replaces the info icon with a round badge of that character, in the `tone` colour (amber or neutral).
 * `icon` + `onActivate` make it an action button whose tooltip names the action; `align="right"` opens the
 * tooltip towards the left, for a button at the right edge of a box.
 */
export default function InfoTip({ text, label = 'More about this filter', glyph = null, tone = 'neutral', icon: Icon = Info, onActivate = null, align = 'left' }) {
  const id = useId()
  const root = useRef(null)
  const [hover, setHover] = useState(false)
  const [focus, setFocus] = useState(false)
  const [tapped, setTapped] = useState(false)
  const open = hover || focus || tapped

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') { setHover(false); setFocus(false); setTapped(false) }
    }
    const onOutside = (e) => { if (!root.current?.contains(e.target)) setTapped(false) }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onOutside)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onOutside)
    }
  }, [open])

  return (
    <span ref={root} className="relative inline-flex" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <button
        type="button"
        aria-label={label}
        aria-describedby={id}
        onClick={() => (onActivate ? (onActivate(), setTapped(false), setHover(false)) : setTapped((v) => !v))}
        onFocus={() => setFocus(true)}
        onBlur={() => setFocus(false)}
        className={glyph
          ? `inline-flex h-4 w-4 items-center justify-center rounded-full text-[11px] font-bold leading-none focus:outline-none focus:ring-2 focus:ring-teal-500/40 ${TONES[tone] || TONES.neutral}`
          : 'rounded-full text-stone-400 hover:text-stone-600 focus:outline-none focus:ring-2 focus:ring-teal-500/40 dark:hover:text-stone-300'}
      >
        {glyph ? <span aria-hidden="true">{glyph}</span> : <Icon className="h-3.5 w-3.5" aria-hidden="true" />}
      </button>
      <span
        id={id}
        role="tooltip"
        className={`absolute bottom-full ${align === 'right' ? 'right-0' : 'left-0'} z-30 mb-1 w-64 max-w-[80vw] rounded-lg border border-stone-200 bg-white p-2 text-xs font-normal leading-snug text-stone-700 shadow-lg dark:border-stone-700 dark:bg-stone-900 dark:text-stone-200 ${open ? '' : 'hidden'}`}
      >
        {text}
      </span>
    </span>
  )
}
