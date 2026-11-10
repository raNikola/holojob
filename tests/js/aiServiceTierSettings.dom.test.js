// @vitest-environment jsdom
// Settings > AI Provider: the processing option (Standard / Flex) is visible for OpenAI only and is saved through the selection.
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AIServiceTierSelector from '../../src/components/ai/AIServiceTierSelector.jsx'
import { formFromSelection, selectionFromForm } from '../../src/modules/ai/aiSettings.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let root
let container
afterEach(async () => {
  await act(async () => root?.unmount())
  container?.remove()
  vi.unstubAllGlobals()
})

async function render(settings, onChange = () => {}) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => { root.render(createElement(AIServiceTierSelector, { settings, onChange })) })
}

describe('processing option control', () => {
  it('shows Standard and Flex for OpenAI, defaults to Standard, and warns that Flex is never replaced by Standard', async () => {
    await render(formFromSelection({ provider: 'openai', model: 'gpt-6-luna' }))
    const select = container.querySelector('select')
    expect(select.value).toBe('standard')
    expect([...select.options].map((o) => o.textContent)).toEqual(expect.arrayContaining(['Standard', 'Flex (about half the price)']))
    expect(container.textContent).toMatch(/temporarily unavailable/)
    expect(container.textContent).toMatch(/never silently replaced by Standard/)
    expect(container.textContent).not.toMatch(/service_tier|default|sk-/i)
  })

  it('is hidden for providers without tiers', async () => {
    await render(formFromSelection({ provider: 'claude-code', model: 'sonnet' }))
    expect(container.querySelector('select')).toBeNull()
  })

  it('reports Flex when chosen, and the saved selection carries it', async () => {
    const changes = []
    await render(formFromSelection({ provider: 'openai', model: 'gpt-6-luna' }), (next) => changes.push(next))
    const select = container.querySelector('select')
    await act(async () => {
      select.value = 'flex'
      select.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(changes).toHaveLength(1)
    expect(selectionFromForm(changes[0]).serviceTier).toBe('flex')
  })

  it('the form round-trips the stored tier and falls back to Standard', () => {
    expect(selectionFromForm(formFromSelection({ provider: 'openai', model: 'm', serviceTier: 'flex' })).serviceTier).toBe('flex')
    expect(selectionFromForm(formFromSelection({ provider: 'openai', model: 'm' })).serviceTier).toBe('standard')
    expect(selectionFromForm({ ...formFromSelection(null), serviceTier: 'fast' }).serviceTier).toBe('standard')
  })
})
