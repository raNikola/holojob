import { useCallback, useEffect, useRef, useState } from 'react'
import { applyStatus, emptyRunView, fetchRescrapeStatus, startRescrapeRun } from './rescrapeRun.js'

const POLL_MS = 2500

/**
 * Follows the server's Re-scrape: reads its status when mounted (so a reload reattaches to a live run), polls while it is
 * active, and calls `onFinished(run)` when a run this page was following ends.
 */
export function useRescrapeRun({ enabled, onFinished }) {
  const [view, setView] = useState(emptyRunView)
  const current = useRef(emptyRunView())
  const finished = useRef(onFinished)
  const pollNow = useRef(() => {})

  useEffect(() => {
    finished.current = onFinished
  }, [onFinished])

  useEffect(() => {
    if (!enabled) return undefined
    let stopped = false
    let timer = null

    const poll = async () => {
      clearTimeout(timer)
      let status
      try {
        status = await fetchRescrapeStatus(current.current.next)
      } catch {
        // the server is restarting or away: try again, the run does not depend on this page
        if (!stopped && current.current.active) timer = setTimeout(poll, POLL_MS)
        return
      }
      if (stopped) return
      const wasActive = current.current.active
      const next = applyStatus(current.current, status)
      current.current = next
      setView(next)
      if (next.reread) poll()
      else if (next.active) timer = setTimeout(poll, POLL_MS)
      else if (wasActive) finished.current?.(next.run)
    }

    pollNow.current = poll
    poll()
    return () => {
      stopped = true
      clearTimeout(timer)
      pollNow.current = () => {}
    }
  }, [enabled])

  const start = useCallback(async (request) => {
    let runId
    try {
      ({ runId } = await startRescrapeRun(request))
    } catch (error) {
      pollNow.current() // refused because a run started elsewhere: follow that one
      throw error
    }
    // Follows the new run from its first line, and counts as active so its end is noticed even if it ends before the next poll.
    const next = { ...emptyRunView(), run: { runId, status: 'running' }, active: true }
    current.current = next
    setView(next)
    pollNow.current()
  }, [])

  // Asks the server again now. A scoring run that finishes outside a Re-scrape (Re-score, a judged run) can
  // clear "scoring behind", and nothing else polls while no run is active.
  const refresh = useCallback(() => pollNow.current(), [])

  return { view, start, refresh }
}
