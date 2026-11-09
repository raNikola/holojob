import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import ApplicationRecordsList from '../../src/components/applications/ApplicationRecordsList.jsx'
import { allApplicationRecords, trackerStats } from '../../src/modules/applications/trackingView.js'

const ev = (seq, type, extra = {}) => ({ id: `e${seq}`, seq, type, at: '2026-11-01T10:00:00.000Z', date: '2026-11-01', source: 'user', data: {}, ...extra })
const app = (id, created, { jobId = 'a1b2c3d4e5f60718', events = [ev(1, 'applied')], posting = {} } = {}) => ({
  id, createdAt: created, origin: 'manual',
  posting: { jobId, title: `Role ${id}`, company: 'Acme', description: 'ad text', capturedFrom: 'scored_jobs', capturedAfterApply: false, ...posting },
  attempt: { channel: 'company_site', applicationUrl: '', appliedDate: '2026-11-01', cv: { kind: 'unknown' } },
  events,
})
const store = {
  applications: {
    'app-0000000000000001': app('app-0000000000000001', '2026-11-01T10:00:00.000Z'),
    'app-0000000000000002': app('app-0000000000000002', '2026-11-02T10:00:00.000Z', { events: [ev(1, 'applied'), ev(2, 'application_voided')] }),
    'mig-0000000000000003': { ...app('mig-0000000000000003', '2026-11-03T10:00:00.000Z', { jobId: null, posting: { description: '', capturedFrom: 'browser', capturedAfterApply: true } }), origin: 'migration' },
  },
}

describe('all application records', () => {
  it('lists every record, newest first, voided and ad-less included, and says how honest each snapshot is', () => {
    const rows = allApplicationRecords(store)
    expect(rows.map((r) => r.id)).toEqual(['mig-0000000000000003', 'app-0000000000000002', 'app-0000000000000001'])
    expect(rows.map((r) => r.voided)).toEqual([false, true, false])
    expect(rows[0].snapshot).toEqual({ capturedFrom: 'browser', capturedAfterApply: true, descriptionMissing: true })
    expect(rows[2].snapshot.descriptionMissing).toBe(false)
  })

  it('does not change the counts: a voided application is listed here and counted nowhere', () => {
    expect(trackerStats(store).crmApplied).toBe(2)
  })

  it('renders the voided state and the snapshot wording, and handles an empty store', () => {
    const html = renderToStaticMarkup(createElement(ApplicationRecordsList, { store, onOpenJob() {} }))
    expect(html).toContain('Voided')
    expect(html).toContain('taken after applying')
    expect(html).toContain('no ad text')
    expect(renderToStaticMarkup(createElement(ApplicationRecordsList, { store: { applications: {} }, onOpenJob() {} }))).toContain('No applications recorded yet')
  })
})
