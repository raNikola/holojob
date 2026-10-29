import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

/** The short-syntax entries under every `ports:` key of a compose file. */
export function publishedPorts(text) {
  const out = []
  let inPorts = false
  let indent = 0
  for (const line of text.split('\n')) {
    if (!line.trim() || line.trim().startsWith('#')) continue
    const lead = line.length - line.trimStart().length
    if (/^\s*ports:\s*$/.test(line)) { inPorts = true; indent = lead; continue }
    if (inPorts) {
      const item = /^\s*-\s*["']?([^"'#]+?)["']?\s*(#.*)?$/.exec(line)
      if (lead > indent && item) out.push(item[1])
      else if (lead <= indent) inPorts = false
    }
  }
  return out
}

const isLoopback = (spec) => /^(127\.0\.0\.1|\[::1\]):/.test(spec)

describe('docker-compose.yml ports', () => {
  const compose = fs.readFileSync(path.join(ROOT, 'docker-compose.yml'), 'utf-8')

  it('publishes the app on loopback only', () => {
    const ports = publishedPorts(compose)
    expect(ports).toContain('127.0.0.1:3073:5173')
    for (const spec of ports) expect(isLoopback(spec), `${spec} is published on all interfaces`).toBe(true)
  })

  it('the check itself rejects an all-interfaces mapping', () => {
    expect(publishedPorts('services:\n  a:\n    ports:\n      - "3073:5173"\n      - 0.0.0.0:80:80\n    volumes:\n      - x:y\n').map(isLoopback)).toEqual([false, false])
    expect(publishedPorts('    ports:\n      - "127.0.0.1:3073:5173"\n')).toEqual(['127.0.0.1:3073:5173'])
  })
})
