import { useCallback, useSyncExternalStore } from 'react'

/** Whether a media query matches now, following changes. Where there is no `matchMedia`, `fallback`. */
export function useMediaQuery(query, fallback = false) {
  const subscribe = useCallback((onChange) => {
    const list = globalThis.matchMedia?.(query)
    list?.addEventListener?.('change', onChange)
    return () => list?.removeEventListener?.('change', onChange)
  }, [query])
  const read = () => globalThis.matchMedia?.(query)?.matches ?? fallback
  return useSyncExternalStore(subscribe, read, read) // the app never hydrates server markup, so the two reads can be the same
}
