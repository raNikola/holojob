// The Jobs list as the server pages it: what the screen holds in memory (docs/redesign/JOBS_LIST_SERVER_PLAN.md, P3).
//
// A loader, like `useAllAds`'s: plain state, `subscribe`, no React, so it is tested alone. The screen gives it the query (mode, filters, classes, recent, sort)
// and the browser's stored rows; it asks the server for the first page, pulls the next one on `more()`, and holds the pages in MEMORY ONLY. Nothing is written to
// browser storage and no ad that is only a server row is ever put into the browser's list.
//
// Rules it keeps:
//  - The page size is the server's (Settings `jobsPageSize`); this file has no number.
//  - A page carries the revision of the list it came from. If the data moved since, the server says so (`changed`), and the loader starts again from the first
//    page and says so in `notice`: a list is never cut or spliced from two states.
//  - A change of query starts a new list (the rows of the old query are dropped at once). A change only in the browser's own rows (the owner set a status, or
//    worked on an ad) reloads in place: the rows stay on screen and are replaced by the same number of rows from the new state.
//  - A refusal (a request that is too large, a failure) never empties or shortens the list silently: the rows already loaded stay, `error` says what happened.
//  - A late answer to an old request is ignored.
import { selectExtraRows } from './extraRows.js'
import { buildListBody, fetchListPage } from './jobListClient.js'
import { pickFilters } from './listFilters.js'

const IDLE = {
  status: 'idle', // idle | loading | ready | error
  rows: [], total: 0, limit: null, nextOffset: null, revision: null, counts: null, meta: null, extra: null,
  loadingMore: false, refreshing: false, error: null, notice: null,
}

/** What makes two requests the same list: the query, not the browser's own rows. */
export const queryKey = (request) => JSON.stringify([request.mode, pickFilters(request.filters), [...(request.classes ?? [])].sort(), Boolean(request.recent), request.sort?.key ?? null, request.sort?.dir ?? null])

/** What makes the browser's own rows the same: what would be sent for them. */
export const extraKey = (request) => JSON.stringify(selectExtraRows(request.stored ?? [], { withText: Boolean(String(request.filters?.searchText ?? '').trim()) }))

export function createServerListLoader({ fetchFn } = {}) {
  let state = IDLE
  let request = null
  let key = null
  let extra = null
  let latest = 0
  const listeners = new Set()
  const set = (next) => {
    state = next
    listeners.forEach((listener) => listener())
  }
  const ask = (offset, revision) => fetchListPage(buildListBody({ ...request, offset, revision }), fetchFn ?? globalThis.fetch)

  const failure = (answer, mine) => {
    if (mine !== latest) return
    set({ ...state, status: state.rows.length ? 'ready' : 'error', loadingMore: false, refreshing: false, error: { message: answer.message, tooLarge: Boolean(answer.tooLarge), rowCount: answer.rowCount ?? null } })
  }

  /** The first page (and, when `through` is given, the pages after it until that many rows are held): a new list, or the same one made again. */
  async function load({ through = 0, keep = false } = {}) {
    const mine = ++latest
    set(keep ? { ...state, refreshing: true, error: null } : { ...IDLE, status: 'loading', notice: state.notice })
    let rows = []
    let first = null
    let revision = null
    let offset = 0
    for (;;) {
      const answer = await ask(offset, revision)
      if (mine !== latest) return
      if (!answer.ok) return failure(answer, mine)
      if (answer.changed) { // the list moved under a multi-page read: start again from the first page
        first = null
        rows = []
        revision = null
        offset = 0
        continue
      }
      first ??= answer.page
      revision = first.revision
      rows = rows.concat(answer.page.rows)
      offset = answer.page.nextOffset ?? null
      if (offset === null || rows.length >= through) {
        set({
          status: 'ready', rows, total: first.total, limit: first.limit, nextOffset: offset, revision, counts: first.counts, meta: first.meta ?? null, extra: first.extra ?? null,
          loadingMore: false, refreshing: false, error: null, notice: state.notice,
        })
        return
      }
    }
  }

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },

    /** Gives the loader the query and the browser's rows. Starts a new list for a new query, reloads in place for new rows of the owner's, and does nothing otherwise. */
    setRequest(next) {
      const nextKey = queryKey(next)
      const nextExtra = extraKey(next)
      const sameQuery = key === nextKey
      const sameExtra = extra === nextExtra
      request = next
      key = nextKey
      extra = nextExtra
      if (sameQuery && sameExtra) return Promise.resolve()
      if (sameQuery && state.status === 'ready') return load({ through: state.rows.length, keep: true })
      return load()
    },

    /** The next page, from where the held rows end. If the list moved meanwhile it starts again from the first page and says so. */
    async more() {
      if (state.status !== 'ready' || state.loadingMore || state.nextOffset === null || !request) return
      const mine = ++latest
      set({ ...state, loadingMore: true, error: null })
      const answer = await ask(state.nextOffset, state.revision)
      if (mine !== latest) return
      if (!answer.ok) return failure(answer, mine)
      if (answer.changed) {
        set({ ...state, notice: 'The list changed while you were looking at it, so it was loaded again from the start.' })
        return load()
      }
      const rows = state.rows.concat(answer.page.rows)
      set({ ...state, rows, total: answer.page.total, nextOffset: answer.page.nextOffset, loadingMore: false, error: null })
    },

    /** The same list made again where it stands: the rows stay on screen and the same number is loaded again (after something that changed the server's data). */
    refresh() {
      if (!request) return Promise.resolve()
      return state.status === 'ready' ? load({ through: state.rows.length, keep: true }) : load()
    },

    /** Loads the list again from the first page, as it is now. */
    reload() {
      if (!request) return Promise.resolve()
      return load()
    },

    /** Every matching ad (for select-all across pages): `{ ids, selectableIds }`, or `{ error }`. */
    async ids() {
      if (!request) return { error: 'No list is loaded.' }
      const answer = await fetchListPage(buildListBody({ ...request, ids: true }), fetchFn ?? globalThis.fetch)
      if (!answer.ok) return { error: answer.message }
      return answer.changed ? { error: 'The list changed. Load it again, then select.' } : { ids: answer.page.ids, selectableIds: answer.page.selectableIds }
    },

    clearNotice() {
      if (state.notice) set({ ...state, notice: null })
    },
  }
}
