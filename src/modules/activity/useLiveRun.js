import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchRun } from './activityClient.js'

export const POLL_MS = 3000
export const BACKOFF_MS = [3000, 6000, 12000, 30000]
const KEEP_EVENTS = 300

const START = { run: null, events: [], receivedAt: null, error: null, retryInMs: null, finished: false }

/**
 * Follows one running run (S7c). It asks `GET /api/runs/<id>?after=N` every 3 s, and only while the tab is visible and the run is active:
 * a hidden tab stops the timer, and showing the tab again asks at once. After an error it waits 3, 6, 12 and then 30 s, and stays at 30.
 * The first answer that says the run is not active is the last one; `onFinished(run)` is called once with it, and nothing is asked again.
 * A run that ends while the tab is hidden is found on return: one immediate request, one `onFinished`, no more. Nothing is stored.
 */
export function useLiveRun({ runId, fetchFn, onFinished }) {
  const [state, setState] = useState(START)
  const finishedCallback = useRef(onFinished)
  const fetcher = useRef(fetchFn)
  const pollNow = useRef(() => {})
  finishedCallback.current = onFinished
  fetcher.current = fetchFn

  useEffect(() => {
    setState(START)
    if (!runId) return undefined
    let stopped = false
    let done = false
    let busy = false
    let timer = null
    let failures = 0
    let cursor = 0
    const visible = () => globalThis.document?.visibilityState !== 'hidden'
    const clear = () => { clearTimeout(timer); timer = null }
    const schedule = (ms) => {
      clear()
      if (!stopped && !done && visible()) timer = setTimeout(poll, ms)
    }
    const finish = (run) => {
      done = true
      clear()
      setState((was) => ({ ...was, finished: true, retryInMs: null, error: null }))
      finishedCallback.current?.(run)
    }

    async function poll() {
      clear()
      if (stopped || done || busy) return
      busy = true
      let data
      try {
        data = await fetchRun(runId, cursor, { fetchFn: fetcher.current })
      } catch (error) {
        busy = false
        if (stopped) return
        if (error.status === 404) {
          finish(null) // the run is gone from the history: nothing left to follow
          return
        }
        failures += 1
        const wait = BACKOFF_MS[Math.min(failures, BACKOFF_MS.length) - 1]
        setState((was) => ({ ...was, error: error.message, retryInMs: wait }))
        schedule(wait)
        return
      }
      busy = false
      if (stopped) return
      failures = 0
      cursor = data.next
      setState((was) => ({
        run: data.run, events: [...was.events, ...data.events].slice(-KEEP_EVENTS), receivedAt: Date.now(), error: null, retryInMs: null, finished: false,
      }))
      if (data.active) schedule(POLL_MS)
      else finish(data.run)
    }

    const onVisibility = () => {
      if (!visible()) clear()
      else if (!done) poll()
    }
    pollNow.current = () => { if (!done) poll() }
    globalThis.document?.addEventListener('visibilitychange', onVisibility)
    if (visible()) poll()
    return () => {
      stopped = true
      clear()
      globalThis.document?.removeEventListener('visibilitychange', onVisibility)
      pollNow.current = () => {}
    }
  }, [runId])

  const refresh = useCallback(() => pollNow.current(), [])
  return { ...state, refresh }
}
