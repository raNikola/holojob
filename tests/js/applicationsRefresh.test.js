import { afterEach, describe, expect, it } from 'vitest'
import * as client from '../../src/modules/applications/applicationsClient.js'

let payload
const respond = (url) => ({
  ok: true,
  json: async () => (url.endsWith('/settings') ? { settings: payload.settings } : payload.store),
})

afterEach(() => client.configureClient())

describe('refreshApplications as a background refresh', () => {
  it('shows another tab\'s change, and does not notify when nothing changed', async () => {
    payload = { store: { applications: { a: { id: 'a', events: [] } } }, settings: { trackingEnabled: true } }
    client.configureClient({ ensure: async () => true, fetch: async (url) => respond(url) })
    let notified = 0
    await client.refreshApplications()
    const stop = client.subscribe(() => { notified += 1 })
    const first = client.getApplicationsState()

    await client.refreshApplications()
    expect(notified).toBe(0)
    expect(client.getApplicationsState()).toBe(first)

    payload = { ...payload, store: { applications: { a: { id: 'a', events: [{ id: 'e1' }] } } } }
    await client.refreshApplications()
    expect(notified).toBe(1)
    expect(client.getApplicationsState().store.applications.a.events).toHaveLength(1)
    stop()
  })
})
