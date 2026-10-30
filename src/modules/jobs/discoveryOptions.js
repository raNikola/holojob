/**
 * Opt-in discovery sources for the "Re-scrape jobs" button. The standard run is the `serbia` group;
 * a source that is in no group is added to the request only while its box is ticked.
 */
export const DISCOVERY_OPTIONS_KEY = 'job-dashboard-discovery-options'
export const STANDARD_PROVIDERS = 'serbia'

export const DEFAULT_DISCOVERY_OPTIONS = { includeJoberty: false }

export function loadDiscoveryOptions(storage = globalThis.localStorage) {
  try {
    const saved = JSON.parse(storage.getItem(DISCOVERY_OPTIONS_KEY))
    return { includeJoberty: saved?.includeJoberty === true }
  } catch {
    return { ...DEFAULT_DISCOVERY_OPTIONS }
  }
}

export function saveDiscoveryOptions(options, storage = globalThis.localStorage) {
  try {
    storage.setItem(DISCOVERY_OPTIONS_KEY, JSON.stringify({ includeJoberty: options.includeJoberty === true }))
  } catch {
    // The choice then lasts until the page closes.
  }
}

/** The `providers` value of the discovery request. Unticked, it is exactly the standard run. */
export function discoveryProviders(options) {
  return options?.includeJoberty === true ? `${STANDARD_PROVIDERS},joberty` : STANDARD_PROVIDERS
}
