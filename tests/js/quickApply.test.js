import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../src/modules/applications/applicationsClient.js', () => ({
  getApplicationsState: () => ({ status: 'ready', store: { applications: {} }, settings: null }),
  createApplication: vi.fn(),
  ClientError: class ClientError extends Error {
    constructor(status, message, extra = {}) { super(message); this.status = status; this.extra = extra }
  },
}))

import * as client from '../../src/modules/applications/applicationsClient.js'
import { quickApplyForm, submitQuickApply } from '../../src/modules/applications/quickApply.js'
import { overlayTracking } from '../../src/modules/applications/trackingView.js'
import { updateJobRecord, updateJobStatus } from '../../src/modules/jobs/jobStorage.js'

const job = { jobId: 'a1b2c3d4e5f60718', title: 'PM', company: 'Acme', status: 'new' }
const cache = { status: 'ready', store: { applications: {} }, settings: null }

beforeEach(() => vi.clearAllMocks())

describe('the Applied button writes an application only after a confirmed save', () => {
  it('shows nothing as applied before, or after a failed save, and calls onSaved only on success', async () => {
    const onSaved = vi.fn()
    client.createApplication.mockRejectedValueOnce(new client.ClientError(409, 'Already tracked'))
    await expect(submitQuickApply(job, cache, quickApplyForm(job, null), { onSaved })).rejects.toThrow('Already tracked')
    expect(onSaved).not.toHaveBeenCalled()
    expect(overlayTracking([job], cache.store, undefined)[0].status).toBe('new')

    client.createApplication.mockResolvedValueOnce({ application: { id: 'app-0123456789abcdef' } })
    await submitQuickApply(job, cache, quickApplyForm(job, null), { onSaved })
    expect(onSaved).toHaveBeenCalledOnce()
    expect(client.createApplication).toHaveBeenCalledTimes(2)
  })

  it('the form starts from the shared defaults and the request carries the job id', async () => {
    client.createApplication.mockResolvedValueOnce({ application: {} })
    const form = quickApplyForm(job, null)
    expect(form.channel).toBe('company_site')
    await submitQuickApply(job, cache, form)
    expect(client.createApplication.mock.calls[0][0]).toMatchObject({ jobId: job.jobId, requestId: form.requestId })
  })

  it('a status change never writes applied_manually; a composed row cannot save it either', () => {
    const jobs = [{ ...job }]
    expect(updateJobStatus(jobs, job.jobId, 'applied_manually')).toBe(jobs)
    expect(updateJobRecord(jobs, job.jobId, { status: 'applied_manually', title: 'PM 2' })[0]).toMatchObject({ status: 'new', title: 'PM 2' })
  })

  it('a row with an active application shows Applied, derived from the store', () => {
    const app = {
      id: 'app-0123456789abcdef', createdAt: '2026-11-09T00:00:00.000Z', origin: 'manual',
      posting: { jobId: job.jobId, title: 'PM', company: 'Acme' },
      attempt: { channel: 'company_site', applicationUrl: '', appliedDate: '2026-11-09', cv: { kind: 'unknown' } },
      events: [{ id: 'e1', seq: 1, type: 'applied', at: '2026-11-09T00:00:00.000Z', date: '2026-11-09', source: 'user', data: {} }],
    }
    const rows = overlayTracking([job, { jobId: 'other', status: 'saved' }], { applications: { [app.id]: app } })
    expect(rows[0].status).toBe('applied_manually')
    expect(rows[1].status).toBe('saved')
  })
})
