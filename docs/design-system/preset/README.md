# Preset snapshot

Reference only. Not wired into the app; nothing imports these files. Superseded preset `b7CScIWmG` was removed from here on 2026-11-04 and is not a live reference ([decision](../../DECISIONS.md#design-system-preset-changed-to-b1a1czcrs-2026-11-04)).

## Provenance

| Item | Value |
|---|---|
| Preset | `b1a1cZcRs` |
| Retrieved | 2026-11-04 |
| Source URL | `https://ui.shadcn.com/init?preset=b1a1cZcRs` |
| CLI | `shadcn@4.23.0` (`@latest` on that day) |
| Environment | `node:20-bookworm`, Node 20.20.2, npm 10.8.2, with only an empty scratch folder mounted (`--security-opt label=disable`) |
| Generating command | `npx shadcn@4.23.0 init -t vite -p b1a1cZcRs -n ds-new -y --no-monorepo` |
| Components | `npx shadcn@4.23.0 add -y` with the 37 names in `registry-base-mira/` other than `button`, which `init` writes |
| Also run, scratch only | `pnpm dlx shadcn@latest apply --preset b1a1cZcRs -y` (pnpm 12.16.1) over a project with the old preset: same tokens, but the old font import, `--font-serif` line and dependency stayed |

## Files

| File | What it is |
|---|---|
| `init.b1a1cZcRs.json` | Answer of the source URL, reformatted with `python3 -m json.tool` |
| `components.generated.json` | `components.json` written by the CLI, unedited |
| `index.generated.css` | `src/index.css` written by the CLI, unedited: every token, font and base rule |
| `registry-base-mira/` | Component source as the CLI wrote it, unedited, TypeScript: 38 components, `use-mobile.ts`, `utils.ts`, `theme-provider.tsx` |
| `shadcn-tailwind.4.23.0.css` | `dist/tailwind.css` of the `shadcn` package, imported by `index.generated.css` |
| `locked-versions.json` | Direct dependencies as locked in the scaffold |
| `MANIFEST.sha256` | Checksums of the files above. Check: `sha256sum -c MANIFEST.sha256`, from this folder |
| `contrast_check.py` | Measures contrast from `index.generated.css` and the provisional proposals. Prerequisite G3 reruns it against the final palette. Standard library only. Not part of the manifest, since it is not from the CLI |
| `contrast-report.md` | Its output (`--write`) |

## Reconstructing it without the website

The tokens and fonts come from `index.generated.css`, the settings from `components.generated.json`, and the components from `registry-base-mira/`, converted to `.jsx` as the app's `components.json` says (`tsx: false`). The packages come from npm at the versions in `locked-versions.json`.

The app's real `components.json` differs on purpose (`tsx: false`, `aliases.ui`), and `theme-provider.tsx` is kept only as a record: the app does not use it. See [../README.md](../README.md).
