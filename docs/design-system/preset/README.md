# Preset snapshot

Reference only, retrieved 2026-11-04. Not wired into the app; nothing imports these files.

| File | What it is |
|---|---|
| `init.b7CScIWmG.json` | Answer of `GET https://ui.shadcn.com/init?preset=b7CScIWmG`, reformatted with `python3 -m json.tool` |
| `components.generated.json` | `components.json` written by the CLI, unedited |
| `index.generated.css` | `src/index.css` written by the CLI, unedited |

Generated with `npx shadcn@4.23.0 init -t vite -p b7CScIWmG -n ds-vite -y --no-monorepo` in `node:20-bookworm` (Node 20.20.2), in an empty scratch folder. A `-t react-router` run gave the same tokens; only the CSS path and the alias prefix differ.

The app's real `components.json` will differ on purpose (`tsx: false`, `aliases.ui`). See [../README.md](../README.md).
