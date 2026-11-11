import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, expect, it } from 'vitest'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const HOOK = path.join(ROOT, 'scripts/git-hooks/pre-push')
const COMMIT_MSG = path.join(ROOT, 'scripts/git-hooks/commit-msg')
const INSTALLER = path.join(ROOT, 'scripts/install-git-hooks.sh')
const ZERO = '0'.repeat(40)
const SHA = 'a'.repeat(40)

// An empty PATH: git and podman cannot be found, so no test can start the real checks.
const runHook = (remote, url, input) =>
  spawnSync('/bin/sh', [HOOK, remote, url], { input, encoding: 'utf-8', env: { PATH: '' } })

describe('git hook scripts', () => {
  it.each([HOOK, COMMIT_MSG, INSTALLER])('%s is executable and has valid sh syntax', (file) => {
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

describe('attribution lines', () => {
  const dirs = []
  const tempDir = () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hooks-'))
    dirs.push(dir)
    return dir
  }
  afterEach(() => dirs.splice(0).forEach((d) => fs.rmSync(d, { recursive: true, force: true })))

  const ATTRIBUTION = [
    'Co-Authored-By: Someone <someone@example.test>',
    'co-authored-by: someone <someone@example.test>',
    'Claude-Session: abc123',
    'Generated with Claude Code',
    '🤖 Generated with Claude Code',
  ]

  const runCommitMsg = (message) => {
    const file = path.join(tempDir(), 'MSG')
    fs.writeFileSync(file, message)
    return spawnSync('/bin/sh', [COMMIT_MSG, file], { encoding: 'utf-8' })
  }

  it.each(ATTRIBUTION)('commit-msg refuses a message with: %s', (line) => {
    const result = runCommitMsg(`A subject\n\nA body.\n\n${line}\n`)
    expect(result.status).toBe(1)
    expect(result.stderr).toContain('only author')
  })

  it('commit-msg accepts an ordinary message and ignores git comment lines', () => {
    expect(runCommitMsg('A subject\n\nAuthored by the owner.\n').status).toBe(0)
    expect(runCommitMsg('A subject\n# Co-Authored-By: a comment git strips\n').status).toBe(0)
  })

  // A real temporary repository; PATH holds git and grep but no podman, so a commit that passes stops at "podman not found".
  function repository() {
    const dir = tempDir()
    const bin = tempDir()
    for (const tool of ['git', 'grep', 'mktemp', 'rm', 'cat']) {
      const found = spawnSync('/bin/sh', ['-c', `command -v ${tool}`], { encoding: 'utf-8' }).stdout.trim()
      if (found) fs.symlinkSync(found, path.join(bin, tool))
    }
    const env = {
      PATH: bin, HOME: dir, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1', GIT_AUTHOR_NAME: 'Owner', GIT_AUTHOR_EMAIL: 'owner@example.test',
      GIT_COMMITTER_NAME: 'Owner', GIT_COMMITTER_EMAIL: 'owner@example.test',
    }
    const git = (...args) => spawnSync('git', args, { cwd: dir, env: { ...process.env, ...env, PATH: process.env.PATH }, encoding: 'utf-8' }).stdout.trim()
    git('init', '-q')
    const commit = (message) => { git('commit', '-q', '--allow-empty', '-m', message); return git('rev-parse', 'HEAD') }
    const push = (sha) => spawnSync('/bin/sh', [HOOK, 'origin', 'git@github.com:raNikola/holojob.git'], {
      cwd: dir, env, input: `refs/heads/b ${sha} refs/heads/b ${ZERO}\n`, encoding: 'utf-8',
    })
    return { git, commit, push }
  }

  it.each(ATTRIBUTION)('pre-push refuses a new commit with: %s', (line) => {
    const { commit, push } = repository()
    const result = push(commit(`Subject\n\n${line}`))
    expect(result.status).toBe(1)
    expect(result.stderr).toContain('attribution line')
  })

  it('pre-push reads every new commit, not only the tip', () => {
    const { commit, push } = repository()
    commit('Older\n\nClaude-Session: abc')
    const result = push(commit('Clean tip'))
    expect(result.status).toBe(1)
    expect(result.stderr).toContain('attribution line')
  })

  it('pre-push passes a clean commit on to the checks', () => {
    const { commit, push } = repository()
    const result = push(commit('Clean subject'))
    expect(result.stderr).not.toContain('attribution line')
    expect(result.stderr).toContain('podman not found')
  })

  it('pre-push leaves history the remote already has alone', () => {
    const { git, commit, push } = repository()
    const old = commit('Old\n\nCo-Authored-By: Someone <someone@example.test>')
    git('update-ref', 'refs/remotes/origin/main', old)
    const result = push(commit('New and clean'))
    expect(result.stderr).not.toContain('attribution line')
    expect(result.stderr).toContain('podman not found')
  })
})
