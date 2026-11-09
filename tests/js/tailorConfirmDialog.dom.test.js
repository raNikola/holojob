// @vitest-environment jsdom
// The tailoring confirm dialog: shows the previewed text, and only its own button sends.
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const previewTailor = vi.fn()
vi.mock('../../src/modules/jobs/pipelineRunner', () => ({ previewTailor: (...a) => previewTailor(...a) }))

const { default: TailorConfirmDialog } = await import('../../src/components/jobs/TailorConfirmDialog.jsx')

const JOB = { jobId: 'j1', title: 'Lead PM', company: 'Hiring Co', prompt: 'REDACTED PROMPT TEXT', characters: 20, refused: null }
const OK = { ok: true, provider: 'claude-code', available: true, jobs: [{ ...JOB, gate: { allowed: true, reason: null, class: 'paid' } }] }

let host
let root
afterEach(async () => {
  await act(async () => root?.unmount())
  host?.remove()
  previewTailor.mockReset()
})

async function open(preview, handlers = {}) {
  previewTailor.mockResolvedValue(preview)
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  const props = { opts: { jobId: 'j1' }, onClose: vi.fn(), onConfirm: vi.fn(), onRuleBased: vi.fn(), ...handlers }
  await act(async () => { root.render(createElement(TailorConfirmDialog, props)) })
  await act(async () => { await Promise.resolve() })
  return props
}

describe('TailorConfirmDialog', () => {
  it('shows exactly the previewed text and sends nothing by itself', async () => {
    const props = await open(OK)
    expect(host.querySelector('[data-testid="tailor-sent-text"]').textContent).toBe('REDACTED PROMPT TEXT')
    expect(props.onConfirm).not.toHaveBeenCalled()
    expect(props.onRuleBased).not.toHaveBeenCalled()
  })

  it('its send button is the only thing that confirms', async () => {
    const props = await open(OK)
    await act(async () => { host.querySelector('[data-testid="tailor-send"]').click() })
    expect(props.onConfirm).toHaveBeenCalledTimes(1)
    expect(props.onRuleBased).not.toHaveBeenCalled()
  })

  it('the rule-based button sends nothing and does not confirm', async () => {
    const props = await open(OK)
    await act(async () => { host.querySelector('[data-testid="tailor-rule-based"]').click() })
    expect(props.onRuleBased).toHaveBeenCalledTimes(1)
    expect(props.onConfirm).not.toHaveBeenCalled()
  })

  it.each([
    ['the gate refuses', { ...OK, jobs: [{ ...JOB, gate: { allowed: false, reason: 'AI budget is 0', class: 'paid' } }] }, 'AI budget is 0'],
    ['redaction refuses', { ...OK, jobs: [{ ...JOB, prompt: null, characters: 0, gate: null, refused: 'personal details could not be removed' }] }, 'personal details could not be removed'],
    ['Claude Code is missing', { ...OK, available: false, availability: 'claude CLI not installed' }, 'claude CLI not installed'],
  ])('cannot be confirmed when %s, and says why', async (_name, preview, reason) => {
    const props = await open(preview)
    expect(host.querySelector('[data-testid="tailor-send"]').disabled).toBe(true)
    expect(host.textContent).toContain(reason)
    await act(async () => { host.querySelector('[data-testid="tailor-send"]').click() })
    expect(props.onConfirm).not.toHaveBeenCalled()
  })

  it('shows the error and offers no send when the preview fails', async () => {
    previewTailor.mockRejectedValue(new Error('Could not prepare the preview.'))
    host = document.createElement('div'); document.body.append(host); root = createRoot(host)
    await act(async () => { root.render(createElement(TailorConfirmDialog, { opts: {}, onClose() {}, onConfirm() {}, onRuleBased() {} })) })
    await act(async () => { await Promise.resolve() })
    expect(host.textContent).toContain('Could not prepare the preview.')
    expect(host.querySelector('[data-testid="tailor-send"]')).toBeNull()
  })
})
