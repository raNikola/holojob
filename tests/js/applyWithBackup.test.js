import { describe, expect, it, vi } from 'vitest'
import { applyWithBackup, BACKUP_FAILED } from '../../src/modules/cvs/applyWithBackup.js'

const profile = { basicProfile: { fullName: 'x' } }

describe('applying AI suggestions takes the backup first', () => {
  it('applies after a verified backup, and the backup saw the profile as it was', async () => {
    const order = []
    const backup = vi.fn(async (p) => { order.push(['backup', p]); return true })
    const apply = vi.fn(() => { order.push(['apply']); return { count: 2 } })
    const r = await applyWithBackup({ profile, backup, apply })
    expect(r).toEqual({ ok: true, result: { count: 2 } })
    expect(order.map((o) => o[0])).toEqual(['backup', 'apply'])
    expect(order[0][1]).toBe(profile)
  })

  it.each([
    ['false', async () => false],
    ['not exactly true', async () => 'yes'],
    ['a rejection', async () => { throw new Error('down') }],
    ['a synchronous throw', () => { throw new Error('down') }],
    ['undefined', async () => undefined],
  ])('changes nothing when the backup is %s', async (_n, backup) => {
    const apply = vi.fn()
    const r = await applyWithBackup({ profile, backup, apply })
    expect(r).toEqual({ ok: false, stage: 'backup', message: BACKUP_FAILED })
    expect(apply).not.toHaveBeenCalled()
  })
})
