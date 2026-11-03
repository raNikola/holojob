import os from 'node:os'
import path from 'node:path'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  // Components are .jsx without a React import; render them with the automatic runtime.
  esbuild: { jsx: 'automatic' },
  test: {
    include: ['tests/js/**/*.test.js'],
    environment: 'node',
    setupFiles: ['tests/js/setup/findingsRoot.js'],
    // No test reaches the real data/secrets or a key from the environment; tests that need a store point it at a temp dir.
    env: {
      CAREER_OS_SECRETS_DIR: path.join(os.tmpdir(), `holojob-vitest-secrets-${process.pid}`),
      // No test writes saved AI answers to the real data/interviews, data/resumes or data/analytics.
      CAREER_OS_AI_OUTPUT_DIR: path.join(os.tmpdir(), `holojob-vitest-ai-output-${process.pid}`),
      // No test takes the real run lock or writes the real run log.
      CAREER_OS_PIPELINE_LOCK: path.join(os.tmpdir(), `holojob-vitest-pipeline-${process.pid}.lock`),
      CAREER_OS_ANALYTICS_DIR: path.join(os.tmpdir(), `holojob-vitest-analytics-${process.pid}`),
      OPENAI_API_KEY: '',
      ANTHROPIC_API_KEY: '',
    },
  },
})
