---
paths:
  - "python/llm/**"
  - "scripts/ai-*.js"
  - "scripts/run-ai.js"
  - "src/data/aiPricing.json"
  - "src/modules/ai/**"
  - "src/modules/settings/**"
  - "python/resume_generator/llm_tailor.py"
  - "python/project_intelligence/**"
  - "python/job_import/**"
---

# AI budget gate and AI provider selection

## AI budget gate

Every real model call goes through `python/llm/ai_gate.py` before it is made (Python:
`llm_client.complete_json`, `claude_code._run`; Node: `scripts/ai-gate.js` from
`run-ai.js`). A new call site uses one of those, never a provider directly. Budget,
limits and the automation switch are in `data/ai/settings.json` (missing = budget 0,
automation off); the append-only ledger is `data/ai/usage-ledger.jsonl`; prices and
free / local / paid classes are in `src/data/aiPricing.json` (unknown = paid). Usage:
`GET /api/ai/usage`.

Settings screen > AI budget edits these through `PUT /api/ai/settings` and
`PUT /api/ai/pricing` (`scripts/ai-settings-handler.js`; validation and the atomic write
are in `ai_gate.py`). Raising what the gate allows (higher limit, removed call cap,
automation on, a looser price) needs `"confirm": true`, else 409 with the list. Price
edits are overrides in `data/ai/pricing-overrides.json`, merged over `aiPricing.json`;
free or priced needs a source note. No route writes or deletes ledger rows.

**Claude Code on a flat subscription** (`claudeCodeSubscription` in `data/ai/settings.json`, default off, owner decision 2026-10-29): when
enabled, a call by provider `claude-code` for an allowlisted feature (default only `jobAnalysis`) gets class `subscription`: cost 0, not
counted against the budget, written to the ledger, and limited by `maxCallsDaily` (default 5, in the settings timezone). Every other
`claude-code` feature (tailoring, job import, project scan, ...) and every other provider keep their class and stay refused at budget 0.
Turning it on, raising the cap or adding a feature needs `confirm: true`. A findings hit never reaches the gate, so it does not count.
The prompts still leave the machine for Anthropic (redacted). Rule: `python/llm/ai_gate.py` (`_call_row`, `_decide`).

## AI provider selection

One file, `data/config/ai-settings.json` (git-ignored, not in backups), holds the provider, model, temperature, max tokens, the ollama
base URL and the nine feature toggles; never a key. `python/llm/ai_selection.py` validates (unknown keys rejected, bounded numbers, fixed
provider list) and writes it atomically. `GET` / `PUT /api/ai/selection` (`ai-settings-handler.js`) go through the gate CLI
(`ai_gate.py selection-get` / `selection-put`), so the Node server and `llm_client.active_provider()` read the same file. Selecting a paid or
unknown-class provider (a change of provider, model or base URL) needs `"confirm": true`, else 409.

- **There is no default.** Nothing selected, an unreadable file, or a provider that side cannot run (`claude`, `gemini`, `mock` in Python;
  `deepseek`, `groq` in Node) refuses the call, logs it and writes a ledger refusal. No env key, `HOLOJOB_LLM_PROVIDER` or CLI fallback picks one.
  `run-ai.js` does not read a provider, model or limit from the request.
- Not covered: the features hard-wired to the Claude Code CLI (`llm_tailor.py`, job import, project scan) still call it directly through the gate.
- The browser holds no AI setting; an older `job-dashboard-ai-settings` is moved once from Settings > AI Provider (read back from the server before it is removed).
