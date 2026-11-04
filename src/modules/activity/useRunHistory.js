import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchRuns } from './activityClient.js'

const START = { status: 'idle', runs: [], next: null, retentionDays: 90, error: null, more: 'idle', moreError: null }

/**
 * The run history for the Activity screen. It asks the server when the screen opens, when the user presses Refresh, and when the user asks
 * for more; at no other time. There is no timer. A tab that is hidden when the screen opens asks nothing until it is shown, and then once.
 * Nothing is kept in the browser: the history lives in this component's state and goes with it.
 */
export function useRunHistory({ fetchFn } = {}) {
  const [state, setState] = useState(START)
  const turn = useRef(0)
  const next = useRef(null)
  const loaded = useRef(false)
  const fetcher = useRef(fetchFn)
  fetcher.current = fetchFn

  const load = useCallback(async () => {
    const mine = ++turn.current
    setState((was) => ({ ...was, status: 'loading', error: null, more: 'idle', moreError: null }))
    try {
      const page = await fetchRuns({ fetchFn: fetcher.current })
      if (mine !== turn.current) return
      loaded.current = true
      next.current = page.next ?? null
      setState({ status: 'ready', runs: page.runs, next: next.current, retentionDays: page.retentionDays ?? 90, error: null, more: 'idle', moreError: null })
    } catch (error) {
      if (mine !== turn.current) return
      setState((was) => ({ ...was, status: 'error', error: error.message }))
    }
  }, [])

  const loadMore = useCallback(async () => {
    if (!next.current) return
    const mine = ++turn.current
    setState((was) => ({ ...was, more: 'loading', moreError: null }))
    try {
      const page = await fetchRuns({ before: next.current, fetchFn: fetcher.current })
      if (mine !== turn.current) return
      next.current = page.next ?? null
      setState((was) => {
        const seen = new Set(was.runs.map((run) => run.runId))
        return { ...was, runs: [...was.runs, ...page.runs.filter((run) => !seen.has(run.runId))], next: next.current, more: 'idle' }
      })
    } catch (error) {
      if (mine !== turn.current) return
      setState((was) => ({ ...was, more: 'error', moreError: error.message }))
    }
  }, [])

  useEffect(() => {
    const visible = () => globalThis.document?.visibilityState !== 'hidden'
    let listening = false
    const onShow = () => {
      if (!visible()) return
      globalThis.document.removeEventListener('visibilitychange', onShow)
      listening = false
      if (!loaded.current) load()
    }
    if (visible()) load()
    else {
      globalThis.document.addEventListener('visibilitychange', onShow)
      listening = true
    }
    return () => {
      turn.current += 1 // an answer that arrives after the screen is gone is dropped
      if (listening) globalThis.document.removeEventListener('visibilitychange', onShow)
    }
  }, [load])

  return { ...state, refresh: load, loadMore }
}
