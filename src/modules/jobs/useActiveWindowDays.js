import { useEffect, useState } from 'react'
import { GATE_SETTINGS_SAVED_EVENT, loadActiveWindowDays } from '../ai/gateClient'

/**
 * The Settings period the Active list keeps an ad the latest search did not return (Settings > AI budget, "Jobs: Active list ...").
 * `null` until the server has answered, or when it cannot: the list then keeps no such ad in Active instead of guessing a number.
 * Read again whenever the owner saves Settings, so a change shows with no reload.
 */
export function useActiveWindowDays() {
  const [days, setDays] = useState(null)
  useEffect(() => {
    let alive = true
    const read = () => loadActiveWindowDays().then((value) => { if (alive) setDays(value) })
    read()
    window.addEventListener(GATE_SETTINGS_SAVED_EVENT, read)
    return () => {
      alive = false
      window.removeEventListener(GATE_SETTINGS_SAVED_EVENT, read)
    }
  }, [])
  return days
}
