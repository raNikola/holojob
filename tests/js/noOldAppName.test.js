import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// The app is called Holojob everywhere. This scans the repository files for any spelling of the name it had before.
// The pattern is built from parts, so this file does not match itself, and nothing here reads data/ or .env.

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const OLD_NAME = new RegExp(['career', '[ _.-]?', 'os|', 'career', 'os'].join(''), 'i')

const SKIP_DIRS = new Set(['.git', 'node_modules', 'dist', 'data', 'graphify-out', 'claude-config', '.venv', '__pycache__', '.pytest_cache', 'worktrees', 'coverage'])
const TEXT_EXT = new Set(['.md', '.js', '.jsx', '.ts', '.py', '.json', '.html', '.css', '.yml', '.yaml', '.sh', '.txt', '.toml', '.ini', '.cfg'])
const TEXT_NAMES = new Set(['Dockerfile', '.gitignore', '.dockerignore', '.env.example', 'LICENSE'])
const SKIP_FILE = /^(\.env|settings\.local\.json|settings\.json\.(bak|graphify).*)$/

// TEMPORARY, removed in the second rename stage once the folder itself is renamed: the folder path in docs and scripts.
const OLD_FOLDER = ['/srv/', 'career', '-os'].join('')
// TEMPORARY, deleted with the cutover: the runbook has to name the old folder, container and host.
const ALLOWED_FILES = new Set(['docs/CUTOVER_RUNBOOK.md'])

function* walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isSymbolicLink()) continue
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) yield* walk(full)
    } else if (!SKIP_FILE.test(entry.name) && (TEXT_EXT.has(path.extname(entry.name)) || TEXT_NAMES.has(entry.name))) {
      yield full
    }
  }
}

describe('the old app name', () => {
  it('is in no file name', () => {
    const hits = [...walk(ROOT)].map((f) => path.relative(ROOT, f)).filter((rel) => OLD_NAME.test(rel))
    expect(hits).toEqual([])
  })

  it('is in no file content (file and line numbers only)', () => {
    const hits = []
    for (const file of walk(ROOT)) {
      const rel = path.relative(ROOT, file)
      if (ALLOWED_FILES.has(rel)) continue
      fs.readFileSync(file, 'utf-8').split('\n').forEach((line, i) => {
        if (OLD_NAME.test(line.split(OLD_FOLDER).join(''))) hits.push(`${rel}:${i + 1}`)
      })
    }
    expect(hits, 'old app name left in these places').toEqual([])
  })
})
