import { useEffect, useMemo, useSyncExternalStore } from 'react'
import { createServerListLoader, extraKey, queryKey } from './serverList.js'

/**
 * The server's list for the Jobs screen: `{ status, rows, total, nextOffset, counts, meta, error, notice, loadingMore, refreshing, more, reload, ids, clearNotice }`.
 * `request` is `{ stored, mode, filters, classes, recent, sort, today }`; the loader asks again when the query or the browser's own rows change, and only then.
 * `enabled: false` (no API, demo data) never asks. `loader` is for the tests.
 */
export function useServerList({ enabled, request, loader: given }) {
  const loader = useMemo(() => given ?? createServerListLoader(), [given])
  const state = useSyncExternalStore(loader.subscribe, loader.getState, loader.getState)
  const queryId = request ? queryKey(request) : null
  const extraId = request ? extraKey(request) : null
  useEffect(() => {
    if (enabled && request) loader.setRequest(request)
    // the request is read when its query or its browser rows changed, which is what the two keys say
  }, [enabled, loader, queryId, extraId]) // eslint-disable-line react-hooks/exhaustive-deps
  return { ...state, more: loader.more, reload: loader.reload, ids: loader.ids, clearNotice: loader.clearNotice }
}
