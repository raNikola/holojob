import { describe, expect, it } from 'vitest'
import { STATUS } from '../../src/modules/jobs/engineShadow'

describe('engine statuses (engine 0.3.0)', () => {
  it('knows every status the engine reports', () => {
    for (const status of ['MET', 'PARTIAL', 'CONTRADICTED', 'NOT_EVIDENCED', 'UNKNOWN']) expect(STATUS[status]).toBeTruthy()
  })

  it('shows only a contradiction as a red cross, and a row stored by 0.2.x as MISSING like a silence', () => {
    expect(STATUS.CONTRADICTED.mark).toBe('✗')
    expect(STATUS.NOT_EVIDENCED.mark).not.toBe('✗')
    expect(STATUS.MISSING).toEqual(STATUS.NOT_EVIDENCED)
  })
})
