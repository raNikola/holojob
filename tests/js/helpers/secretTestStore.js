import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach } from 'vitest'
import { setSecretsRoot } from '../../../scripts/secret-store.js'

/** A fixed canary: long enough for the store, and not shaped like any real provider key. */
export const CANARY = 'SECRET-CANARY-7f3a9c1d'

/** Points the secret store at a fresh temp directory for every test. Real data/secrets is never touched. */
export function useTempSecretStore() {
  const state = { dir: null }
  beforeEach(() => {
    state.dir = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'secrets-')), 'secrets')
    setSecretsRoot(state.dir)
  })
  afterEach(() => {
    setSecretsRoot()
    fs.rmSync(path.dirname(state.dir), { recursive: true, force: true })
  })
  return state
}
