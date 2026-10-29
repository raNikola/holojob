import { BaseProvider } from './baseProvider.js'

const isNode = typeof globalThis.process !== 'undefined' && Boolean(globalThis.process?.versions?.node)

/**
 * Local Claude Code CLI provider — uses your Claude Pro/Max subscription login,
 * no API key. Runs server-side only (dev API spawns the CLI); the browser
 * reaches it through the /api/ai endpoints like every other provider.
 */
export class ClaudeCodeProvider extends BaseProvider {
  constructor() {
    super('claude-code')
  }

  async complete({ messages, model, timeout = 240000 }) {
    if (!isNode) {
      throw new Error('Claude Code runs server-side; use the dev API (/api/ai/*)')
    }
    const { execFile } = await import(/* @vite-ignore */ 'node:child_process')
    const prompt = messages.map((m) => (m.role === 'system' ? `[Instructions]\n${m.content}` : m.content)).join('\n\n')
    const args = ['-p', '--output-format', 'json', '--tools', '']
    if (model) args.push('--model', model)

    const stdout = await new Promise((resolve, reject) => {
      const child = execFile('claude', args, { timeout, maxBuffer: 10 * 1024 * 1024 }, (err, out) => {
        if (err && !out) reject(new Error(`Claude Code failed: ${err.message}`))
        else resolve(out)
      })
      child.stdin.write(prompt)
      child.stdin.end()
    })

    let data
    try {
      data = JSON.parse(stdout)
    } catch {
      throw new Error(`Unparseable Claude Code output: ${stdout.slice(0, 200)}`)
    }
    if (data.is_error) {
      throw new Error(data.result || 'Claude Code error (run `claude` and /login once)')
    }
    return {
      text: data.result || '',
      usage: {
        inputTokens: data.usage?.input_tokens || 0,
        outputTokens: data.usage?.output_tokens || 0,
      },
    }
  }

  /**
   * Install and login file only. A test prompt would be a paid model call
   * outside the AI budget gate, so none is sent.
   */
  async healthCheck() {
    if (!isNode) return { online: false, reason: 'Checked server-side' }
    const { spawnSync } = await import(/* @vite-ignore */ 'node:child_process')
    const fs = await import(/* @vite-ignore */ 'node:fs')
    const os = await import(/* @vite-ignore */ 'node:os')
    const path = await import(/* @vite-ignore */ 'node:path')
    const probe = spawnSync('claude', ['--version'], { timeout: 10000 })
    if (probe.error || probe.status !== 0) return { online: false, reason: 'claude CLI not installed' }
    if (!fs.existsSync(path.join(os.homedir(), '.claude', '.credentials.json'))) {
      return { online: false, reason: 'Not logged in — run `claude /login` once' }
    }
    return { online: true }
  }

  async listModels() {
    return ['sonnet', 'opus', 'haiku']
  }
}
