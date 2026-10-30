import { beforeAll, describe, expect, it } from 'vitest'
import fs from 'node:fs'
import React, { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  DISCOVERY_OPTIONS_KEY, discoveryProviders, loadDiscoveryOptions, saveDiscoveryOptions,
} from '../../src/modules/jobs/discoveryOptions.js'

// The test runner compiles JSX with the classic runtime, which needs React in scope.
let DiscoverySourceOptions
let JOBERTY_HELP
beforeAll(async () => {
  globalThis.React = React
  ;({ default: DiscoverySourceOptions, JOBERTY_HELP } = await import('../../src/components/jobs/DiscoverySourceOptions.jsx'))
})

const memory = (initial = {}) => {
  const items = new Map(Object.entries(initial))
  return { items, getItem: (k) => items.get(k) ?? null, setItem: (k, v) => items.set(k, v) }
}

describe('Joberty option state', () => {
  it('is off by default, and for anything unreadable', () => {
    expect(loadDiscoveryOptions(memory())).toEqual({ includeJoberty: false })
    expect(loadDiscoveryOptions(memory({ [DISCOVERY_OPTIONS_KEY]: 'not json' }))).toEqual({ includeJoberty: false })
    expect(loadDiscoveryOptions(memory({ [DISCOVERY_OPTIONS_KEY]: '{"includeJoberty":"yes"}' }))).toEqual({ includeJoberty: false })
    expect(loadDiscoveryOptions(null)).toEqual({ includeJoberty: false })
  })

  it('is remembered', () => {
    const storage = memory()
    saveDiscoveryOptions({ includeJoberty: true }, storage)
    expect(loadDiscoveryOptions(storage)).toEqual({ includeJoberty: true })
    saveDiscoveryOptions({ includeJoberty: false }, storage)
    expect(loadDiscoveryOptions(storage)).toEqual({ includeJoberty: false })
  })

  it('survives a storage that refuses writes', () => {
    expect(() => saveDiscoveryOptions({ includeJoberty: true }, { setItem() { throw new Error('quota') } })).not.toThrow()
  })
})

describe('request payload', () => {
  it('unchecked, the request is exactly the standard run', () => {
    expect(discoveryProviders({ includeJoberty: false })).toBe('serbia')
    expect(discoveryProviders(undefined)).toBe('serbia')
  })

  it('checked, joberty is added to the standard run', () => {
    expect(discoveryProviders({ includeJoberty: true })).toBe('serbia,joberty')
  })

  it('the Re-scrape button sends what the box says, and nothing else about the request changed', () => {
    const screen = fs.readFileSync('src/components/jobs/JobDiscoveryScreen.jsx', 'utf8')
    expect(screen).toContain('await runDiscovery({ providers: discoveryProviders(discoveryOptions), country: searchCountry(profile, intelligence), intelligence, profile })')
    expect(screen).toContain('<DiscoverySourceOptions')
  })
})

describe('the checkbox', () => {
  const render = (options) => renderToStaticMarkup(createElement(DiscoverySourceOptions, { options, onChange: () => {} }))

  it('has the label and the tooltip, and shows the saved state', () => {
    const off = render({ includeJoberty: false })
    expect(off).toContain('Include Joberty (Serbian IT board)')
    expect(off).toContain(JOBERTY_HELP.replaceAll("'", '&#x27;'))
    expect(off).not.toContain('checked=""')
    expect(render({ includeJoberty: true })).toContain('checked=""')
  })

  it('carries the agreed tooltip text', () => {
    expect(JOBERTY_HELP).toBe("Reads Joberty's public API (Product Management category). Check Joberty's terms before enabling.")
  })
})
