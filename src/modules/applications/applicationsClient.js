/**
 * The browser's read cache of the application store (docs/redesign/TRACKER_PLAN.md 3.2). The
 * server is the master: every write replaces the cached application with the server's answer,
 * and a failed write leaves the cache as it was. One cache feeds every view.
 */

import { ensureApiAvailable } from '../../utils/apiAvailability.js'

export class ClientError extends Error {
  constructor(status, message, extra = {}) {
    super(message)
    this.status = status
    this.extra = extra
  }
}

const IDLE = { status: 'idle', store: null, settings: null, error: null }
let state = IDLE
const listeners = new Set()
let inflight = null
// Tests point the client at a temp-root server.
let transport = { fetch: (...args) => globalThis.fetch(...args), base: '', ensure: ensureApiAvailable }

export function configureClient(overrides) {
  transport = overrides ? { ...transport, ...overrides } : { fetch: (...args) => globalThis.fetch(...args), base: '', ensure: ensureApiAvailable }
  state = IDLE
  inflight = null
}

export const getApplicationsState = () => state
export function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function publish(next) {
  state = next
  for (const listener of listeners) listener()
}

async function request(method, url, body) {
  if (!(await transport.ensure())) throw new ClientError(0, 'The application tracker needs the local API server')
  const res = await transport.fetch(`${transport.base}${url}`, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const payload = await res.json().catch(() => ({}))
  if (!res.ok) {
    const { error, ...extra } = payload
    throw new ClientError(res.status, error || `Request failed (${res.status})`, extra)
  }
  return payload
}

/** Load the store and the stage settings. Safe to call often: concurrent calls share one load. */
export function refreshApplications() {
  if (inflight) return inflight
  if (state.status !== 'ready') publish({ ...state, status: 'loading', error: null })
  inflight = (async () => {
    try {
      const [store, settings] = await Promise.all([request('GET', '/api/applications'), request('GET', '/api/applications/settings')])
      publish({ status: 'ready', store, settings: settings.settings, error: null })
    } catch (e) {
      publish({ ...state, status: 'error', error: e.message })
    } finally {
      inflight = null
    }
    return state
  })()
  return inflight
}

function replaceApplication(application) {
  if (!state.store) return
  publish({
    ...state,
    store: { ...state.store, applications: { ...state.store.applications, [application.id]: application } },
  })
}

export async function createApplication(body) {
  const result = await request('POST', '/api/applications', body)
  replaceApplication(result.application)
  return result
}

export async function addEvent(appId, event) {
  const result = await request('POST', `/api/applications/${appId}/events`, event)
  replaceApplication(result.application)
  return result
}

export async function moveApplication(appId, body) {
  const result = await request('POST', `/api/applications/${appId}/move`, body)
  replaceApplication(result.application)
  return result
}
