import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const HOOK = path.join(ROOT, 'scripts/git-hooks/pre-push')
const INSTALLER = path.join(ROOT, 'scripts/install-git-hooks.sh')
const ZERO = '0'.repeat(40)
const SHA = 'a'.repeat(40)

// An empty PATH: git and podman cannot be found, so no test can start the real checks.
const runHook = (remote, url, input) =>
  spawnSync('/bin/sh', [HOOK, remote, url], { input, encoding: 'utf-8', env: { PATH: '' } })

describe('git hook scripts', () => {
  it.each([HOOK, INSTALLER])('%s is executable and has valid sh syntax', (file) => {
    expect(fs.statSync(file).mode & 0o111).toBe(0o111)
    expect(spawnSync('/bin/sh', ['-n', file], { encoding: 'utf-8' }).status).toBe(0)
  })
})

describe('pre-push', () => {
  const origin = ['origin', 'git@github.com:raNikola/holojob.git']

  it.each([
    ['upstream', 'no-push'],
    ['upstream', 'https://github.com/example/other-project.git'],
    ['https://github.com/example/other-project.git', 'https://github.com/example/other-project.git'],
    ['backup', 'git@github.com:someone/else.git'],
    ['origin', 'https://github.com/example/other-project.git'],
    ['git@github.com:raNikola/holojob.git', 'git@github.com:raNikola/holojob.git'],
  ])('refuses %s %s, even for a tag or a deletion', (remote, url) => {
    for (const line of [`refs/tags/v1 ${SHA} refs/tags/v1 ${ZERO}\n`, `(delete) ${ZERO} refs/heads/old ${SHA}\n`]) {
      const result = runHook(remote, url, line)
      expect(result.status).toBe(1)
      expect(result.stderr).toContain('Refusing push')
    }
  })

  it.each([
    ['a branch deletion', `(delete) ${ZERO} refs/heads/old ${SHA}\n`],
    ['a tag-only push', `refs/tags/v1 ${SHA} refs/tags/v1 ${ZERO}\n`],
    ['nothing to push', ''],
  ])('skips the checks for %s', (_name, input) => {
    expect(runHook(...origin, input).status).toBe(0)
  })

  it.each([
    ['a branch update', `refs/heads/main ${SHA} refs/heads/main ${ZERO}\n`],
    ['a branch pushed together with a tag', `refs/tags/v1 ${SHA} refs/tags/v1 ${ZERO}\nrefs/heads/main ${SHA} refs/heads/main ${ZERO}\n`],
  ])('does not skip the checks for %s (and fails when it cannot run them)', (_name, input) => {
    const result = runHook(...origin, input)
    expect(result.status).toBe(1)
    expect(result.stderr).toContain('--no-verify')
  })
})
