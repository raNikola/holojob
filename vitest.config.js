import os from 'node:os'
import path from 'node:path'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['tests/js/**/*.test.js'],
    environment: 'node',
    setupFiles: ['tests/js/setup/findingsRoot.js'],
    // No test reaches the real data/secrets or a key from the environment; tests that need a store point it at a temp dir.
    env: {
      CAREER_OS_SECRETS_DIR: path.join(os.tmpdir(), `holojob-vitest-secrets-${process.pid}`),
      OPENAI_API_KEY: '',
      ANTHROPIC_API_KEY: '',
    },
  },
})
