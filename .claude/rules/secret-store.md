---
paths:
  - "scripts/secret-store.js"
  - "scripts/secrets-handler.js"
  - "scripts/run-ai.js"
  - "python/llm/secret_store.py"
  - "python/outreach_scraper/**"
  - "src/modules/settings/**"
---

# Secret store (AI keys)

`scripts/secret-store.js` is the only code that writes `data/secrets/` and the only Node reader; Python reads `ai.json` read-only through
`python/llm/secret_store.py` (directory 700, files 600, atomic writes,
never logged). `data/secrets/ai.json` holds `{ provider: { key, baseUrl, setAt } }` for openai, openrouter, claude and gemini.
Routes: `GET /api/secrets` (set / not set, source, last 4 characters, base URL), `PUT` / `DELETE /api/secrets/ai/<provider>`
(`scripts/secrets-handler.js`); no route returns a key, and errors never quote the request. Settings > Privacy: secrets and keys
sets, replaces and removes a key, and moves the one an older build left in the browser (cleared only after the server confirms
the same last 4 characters).

- `run-ai.js` calls `resolveAiSettings()` once per call. A keyed provider takes its key **and base URL** from the store, then
  `.env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` only); an `apiKey` or `baseUrl` in a request is ignored, so there is no fallback
  to a key from the browser. No key answers "No API key configured" and makes no call. `claude-code`, `mock` and `ollama` need no key.
- A custom base URL (a proxy, openrouter) is entered with the key in Settings; the key is sent only there.
- The stored values and the `.env` keys are masked by exact value in every error, SSE event, gate record and console line
  (`secret-mask.js`); the patterns remain a second layer. Tests point the store at a temp dir (`HOLOJOB_SECRETS_DIR`, set in
  `vitest.config.js`) and never read the real one.
- The LinkedIn cookie is `data/secrets/linkedin.json` (`{ li_at, setAt }`), `PUT` / `DELETE /api/secrets/linkedin`, then `LINKEDIN_LI_AT`
  from `.env`. `POST /api/outreach/discover` ignores any cookie in the body. The scraper gets it only in the child's environment in deep
  mode (`--li-at` no longer exists; search mode strips it), and its text is masked. `data/outreach/linkedin_session.json` is no longer read.
- **Python reads the store too** (`python/llm/secret_store.py`, read-only; not named `secrets.py`, which would shadow the standard library). For the
  selected provider only (`openai`, `openrouter`), the key and pinned base URL come from the store; `.env` (`OPENAI_API_KEY`, ...) applies only when
  the store has no key for that provider. The intended setup is store only, so `.env` keys can be removed. A store file that is not private (group or
  other access, symlink, bad JSON) refuses the call, with no `.env` fallback; a missing key refuses before the gate (logged, ledger row), and no other
  provider is tried. A stored key goes only to its pinned URL or the provider's own address (`*_BASE_URL` does not redirect it). The exact key is masked
  in errors, log lines and ledger rows (`secret_store.mask`). Check without a call: `podman exec holojob python python/llm/secret_store.py status openai`.
